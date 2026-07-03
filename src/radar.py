#!/usr/bin/env python3
"""Solana Narrative Radar — detect emerging narratives, output build ideas.

Pipeline (all public, read-only data):
  1. GitHub    — new & recently-active Solana repos (developer momentum)
  2. DefiLlama — Solana protocol TVL movers (on-chain capital momentum)
  3. RSS       — ecosystem blogs/news (social/editorial signal), optional

Signals are bucketed into a narrative taxonomy, scored by cross-source
confirmation and recency, and rendered as a fortnightly markdown report:
each narrative comes with its raw evidence (explainability first) and
3-5 concrete build ideas.

Usage:
  python src/radar.py --days 14 --out reports/
  GITHUB_TOKEN=... improves GitHub rate limits (optional but recommended).
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

import requests

UA = {"User-Agent": "solana-narrative-radar/0.1"}
TIMEOUT = 20

# --------------------------------------------------------------- taxonomy
# keyword -> narrative bucket. Deliberately transparent: every match is
# reported as evidence, so a human (or agent) can audit why a narrative fired.
TAXONOMY: dict[str, list[str]] = {
    "AI agents on-chain": [
        "agent", "ai-agent", "llm", "mcp", "autonomous", "copilot", "gpt",
    ],
    "DePIN / physical infra": [
        "depin", "iot", "sensor", "wireless", "mapping", "compute network",
    ],
    "Payments & stablecoins": [
        "payment", "stablecoin", "usdc", "remittance", "checkout", "pyusd",
        "payfi", "invoice",
    ],
    "DeFi: perps / lending / LST": [
        "perp", "lending", "borrow", "liquid staking", "lst", "restaking",
        "yield", "amm", "clmm", "vault",
    ],
    "Consumer & gaming": [
        "game", "gaming", "consumer", "social", "mobile", "unity", "nft",
    ],
    "Privacy & ZK": [
        "zk", "zero-knowledge", "privacy", "confidential", "proof",
    ],
    "Tokenization / RWA": [
        "rwa", "tokeniz", "real-world", "treasury", "securit", "equity",
    ],
    "Dev tooling & infra": [
        "sdk", "indexer", "rpc", "anchor", "framework", "cli", "devtool",
        "test", "svm", "rollup", "validator",
    ],
    "Launchpads & memecoins": [
        "memecoin", "launchpad", "pump", "bonding curve", "fair launch",
    ],
}

IDEA_TEMPLATES = [
    ("tooling", "A CLI/SDK that lets developers integrate {topic} in minutes, "
                "using {example} as the reference integration."),
    ("analytics", "A public dashboard tracking {topic} adoption on Solana "
                  "(programs deployed, active wallets, TVL), starting from the "
                  "data points this radar already collects."),
    ("agent", "An autonomous agent that monitors {topic} activity and executes "
              "a narrow, safe task (alerting, indexing, report generation) — "
              "not trading."),
    ("consumer", "A consumer-grade front end that hides the crypto plumbing of "
                 "{topic} behind a familiar web2 UX."),
    ("education", "An interactive 'state of {topic}' explainer refreshed by "
                  "this radar every fortnight, monetizable as a newsletter."),
]


def _get(url: str, **kw) -> requests.Response:
    headers = dict(UA)
    headers.update(kw.pop("headers", {}))
    return requests.get(url, headers=headers, timeout=TIMEOUT, **kw)


# --------------------------------------------------------------- collectors
def collect_github(days: int, log=print) -> list[dict]:
    """New + recently-pushed Solana repos: developer momentum signal."""
    token = os.environ.get("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    signals: list[dict] = []
    queries = [
        (f"solana created:>{since}", "new repo"),
        (f"solana pushed:>{since} stars:>20", "active repo"),
    ]
    for q, kind in queries:
        try:
            r = _get("https://api.github.com/search/repositories",
                     params={"q": q, "sort": "stars", "order": "desc",
                             "per_page": 30},
                     headers=headers)
            r.raise_for_status()
            for it in r.json().get("items", []):
                signals.append({
                    "source": "github",
                    "kind": kind,
                    "name": it["full_name"],
                    "text": " ".join(filter(None, [
                        it.get("name", ""), it.get("description", "") or "",
                        " ".join(it.get("topics", [])),
                    ])),
                    "weight": min(3.0, 1.0 + (it.get("stargazers_count", 0) / 100)),
                    "url": it.get("html_url", ""),
                })
        except Exception as e:  # noqa: BLE001 — a dead source must not kill the run
            log(f"[github] query failed ({type(e).__name__}), skipping: {q}")
    log(f"[github] {len(signals)} repo signals")
    return signals


def collect_defillama(log=print) -> list[dict]:
    """Solana protocol TVL movers: capital momentum signal."""
    signals: list[dict] = []
    try:
        r = _get("https://api.llama.fi/protocols")
        r.raise_for_status()
        for p in r.json():
            if "Solana" not in (p.get("chains") or []):
                continue
            tvl = p.get("tvl") or 0
            ch7 = p.get("change_7d")
            if tvl < 1_000_000 or ch7 is None:
                continue
            if abs(ch7) < 15:  # only significant movers
                continue
            signals.append({
                "source": "defillama",
                "kind": f"TVL {ch7:+.0f}% 7d",
                "name": p.get("name", "?"),
                "text": " ".join(filter(None, [
                    p.get("name", ""), p.get("category", "") or "",
                    p.get("symbol", "") or "",
                ])),
                "weight": min(3.0, 1.0 + abs(ch7) / 50),
                "url": f"https://defillama.com/protocol/{p.get('slug', '')}",
            })
    except Exception as e:  # noqa: BLE001
        log(f"[defillama] failed ({type(e).__name__}), skipping")
    log(f"[defillama] {len(signals)} TVL-mover signals")
    return signals


DEFAULT_FEEDS = [
    "https://solanacompass.com/rss",
    "https://blog.helius.dev/rss/",
]


def collect_rss(days: int, feeds: list[str] | None = None, log=print) -> list[dict]:
    """Ecosystem blogs: editorial/social signal. Every feed is optional."""
    signals: list[dict] = []
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    for feed in feeds or DEFAULT_FEEDS:
        try:
            r = _get(feed)
            r.raise_for_status()
            root = ET.fromstring(r.content)
            for item in root.iter("item"):
                title = (item.findtext("title") or "").strip()
                desc = re.sub(r"<[^>]+>", " ", item.findtext("description") or "")
                pub = item.findtext("pubDate") or ""
                try:
                    when = dt.datetime.strptime(pub[:25].strip(), "%a, %d %b %Y %H:%M:%S")
                    if when.replace(tzinfo=dt.timezone.utc) < cutoff:
                        continue
                except ValueError:
                    pass  # keep undated items, low weight anyway
                signals.append({
                    "source": "rss", "kind": "article", "name": title,
                    "text": f"{title} {desc[:300]}", "weight": 1.0,
                    "url": item.findtext("link") or feed,
                })
        except Exception as e:  # noqa: BLE001
            log(f"[rss] {feed} failed ({type(e).__name__}), skipping")
    log(f"[rss] {len(signals)} article signals")
    return signals


# --------------------------------------------------------------- analysis
SHORT_NAMES = {
    "AI agents on-chain": "on-chain AI agents",
    "DePIN / physical infra": "DePIN",
    "Payments & stablecoins": "stablecoin payments",
    "DeFi: perps / lending / LST": "Solana DeFi (perps/LST)",
    "Consumer & gaming": "consumer gaming",
    "Privacy & ZK": "ZK privacy",
    "Tokenization / RWA": "RWA tokenization",
    "Dev tooling & infra": "Solana dev tooling",
    "Launchpads & memecoins": "token launch infra",
}


def detect_narratives(signals: list[dict]) -> list[dict]:
    """Bucket signals into taxonomy; score by cross-source confirmation.

    A signal matching many buckets is generic (e.g. a repo description that
    name-drops every trend), so its weight is split across the buckets it
    touches — this keeps spammy catch-all repos from dominating evidence.
    """
    matched: list[tuple[dict, list[str]]] = []
    for s in signals:
        text = s["text"].lower()
        hits = [n for n, kws in TAXONOMY.items() if any(k in text for k in kws)]
        if hits:
            matched.append((s, hits))

    buckets: dict[str, list[dict]] = defaultdict(list)
    for s, hits in matched:
        eff = s["weight"] / len(hits)
        for narrative in hits:
            buckets[narrative].append({**s, "eff_weight": eff})

    out = []
    for narrative, evid in buckets.items():
        sources = {e["source"] for e in evid}
        score = sum(e["eff_weight"] for e in evid) * (1 + 0.5 * (len(sources) - 1))
        out.append({
            "narrative": narrative,
            "score": round(score, 1),
            "sources": sorted(sources),
            "evidence": sorted(evid, key=lambda e: -e["eff_weight"])[:6],
        })
    return sorted(out, key=lambda n: -n["score"])


def generate_ideas(narrative: dict, n: int = 4) -> list[str]:
    topic = SHORT_NAMES.get(narrative["narrative"], narrative["narrative"])
    example = narrative["evidence"][0]["name"] if narrative["evidence"] else "the top signal"
    return [f"**[{kind}]** {tpl.format(topic=topic, example=example)}"
            for kind, tpl in IDEA_TEMPLATES[:n]]


# --------------------------------------------------------------- report
def render(narratives: list[dict], days: int, counts: dict[str, int]) -> str:
    today = dt.date.today()
    lines = [
        f"# Solana Narrative Radar — {today} (last {days} days)",
        "",
        f"Signals collected: GitHub {counts.get('github', 0)} · "
        f"DefiLlama {counts.get('defillama', 0)} · RSS {counts.get('rss', 0)}. "
        "Scores reward cross-source confirmation; every narrative lists its raw "
        "evidence so the ranking is auditable.",
        "",
    ]
    for i, n in enumerate(narratives[:5], 1):
        lines += [f"## {i}. {n['narrative']}  (score {n['score']}, "
                  f"sources: {', '.join(n['sources'])})", ""]
        lines += ["**Evidence:**"]
        lines += [f"- `{e['source']}` [{e['name']}]({e['url']}) — {e['kind']}"
                  for e in n["evidence"]]
        lines += ["", "**Build ideas:**"]
        lines += [f"{j}. {idea}" for j, idea in enumerate(generate_ideas(n), 1)]
        lines += [""]
    if not narratives:
        lines.append("_No narratives crossed the signal threshold this fortnight._")
    lines += ["---",
              "_Generated by [solana-narrative-radar]"
              "(https://github.com/Syzygys/solana-narrative-radar) — "
              "an open-source, explainable narrative detector._"]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=14, help="lookback window")
    ap.add_argument("--out", default="reports", help="output directory")
    args = ap.parse_args()

    signals = (collect_github(args.days)
               + collect_defillama()
               + collect_rss(args.days))
    counts: dict[str, int] = defaultdict(int)
    for s in signals:
        counts[s["source"]] += 1
    narratives = detect_narratives(signals)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"radar-{dt.date.today()}.md"
    out_file.write_text(render(narratives, args.days, counts), encoding="utf-8")
    print(f"report -> {out_file}")
    for n in narratives[:5]:
        print(f"  {n['score']:>6}  {n['narrative']}  ({'+'.join(n['sources'])})")


if __name__ == "__main__":
    main()
