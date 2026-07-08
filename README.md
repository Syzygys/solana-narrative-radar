# Solana Narrative Radar

[![Refresh Solana Narrative Radar](https://github.com/Syzygys/solana-narrative-radar/actions/workflows/radar.yml/badge.svg)](https://github.com/Syzygys/solana-narrative-radar/actions/workflows/radar.yml)

**An open-source, explainable narrative detector for the Solana ecosystem — refreshed fortnightly.**

Latest sample output: [`reports/radar-2026-07-03.md`](reports/radar-2026-07-03.md)

## What it does

Every fortnight the radar:

1. **Collects signals** from three independent, public, read-only sources:
   - **GitHub** — newly created + recently active Solana repos (developer momentum)
   - **DefiLlama** — Solana protocol TVL movers, ±15%+ over 7 days (capital momentum)
   - **RSS** — ecosystem blogs/news (editorial signal; optional, degrades gracefully)
2. **Detects narratives** by bucketing signals into a transparent keyword taxonomy
   (AI agents, DePIN, payments, DeFi, consumer/gaming, ZK, RWA, dev tooling, launch infra).
3. **Scores** each narrative with two anti-noise rules:
   - *cross-source confirmation*: a narrative confirmed by both code AND capital outranks one seen in a single source;
   - *generic-signal splitting*: a repo whose description name-drops every trend has its weight split across all buckets it touches, so catch-all spam can't dominate.
4. **Outputs** a markdown report: top narratives, **raw evidence for each** (auditability first — you can always see *why* a narrative fired), and 3–5 concrete build ideas per narrative.

## Why it's novel

Most "trend" tools output vibes. This one outputs **verifiable evidence chains**: every ranked narrative links to the exact repos, TVL moves, and articles that produced its score. Explainability is the product — founders, investors, and other AI agents can audit the ranking instead of trusting it.

## How Solana is used

The radar consumes Solana-native data as its core input: ecosystem repository activity (Anchor, Firedancer, web3.js, and hundreds of long-tail repos) and per-protocol Solana TVL flows via DefiLlama. Its output is Solana-specific build intelligence.

## Run it

```bash
pip install -r requirements.txt
# optional but recommended (higher GitHub rate limits):
export GITHUB_TOKEN=<token>
python src/radar.py --days 14 --out reports/
```

Output: `reports/radar-<date>.md`. Schedule it fortnightly with cron / Task Scheduler / GitHub Actions:

```
0 9 1,15 * *  cd /path/to/repo && python src/radar.py
```

This repository now includes a GitHub Actions workflow that refreshes reports on the
1st and 15th of each month, with manual `workflow_dispatch` support for ad hoc runs.

## Design principles

- **Every source is optional**: a dead endpoint logs a skip and never kills the run.
- **No keys required**: all sources are public; `GITHUB_TOKEN` only raises rate limits.
- **Read-only**: the radar observes; it never transacts, trades, or posts.

## Roadmap

- X/Discord signal collectors (pending API access)
- On-chain program-deployment velocity via public RPC
- LLM-assisted idea generation hook (current templates are deliberately deterministic/auditable)

## License

MIT
