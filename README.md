# eBay Auction Command Center — Sale Scanner Core

[![CI](https://github.com/mainstreetmediatn-git/eBay-auction-command-center-/actions/workflows/ci.yml/badge.svg)](https://github.com/mainstreetmediatn-git/eBay-auction-command-center-/actions/workflows/ci.yml)

Explainable resale-arbitrage engine for marketplace ingestion, comparable-sale valuation, financial ceilings, auction state decisions, and auditable persistence.

## Included
- eBay Browse API connector with OAuth, retry/backoff, normalization, and rate-limit handling
- Deterministic comp engine with IQR outlier rejection and weighted evidence
- Valuation bands: fast-sale, conservative, expected, optimistic
- Safe / normal / aggressive maximum purchase ceilings
- Auction state evaluator: BUY_ZONE, BID, MONITOR, PASS, CLOSED
- Countdown alert offsets: 24h, 1h, 15m, 5m
- PostgreSQL persistence schema and transactional repository
- Multi-worker-safe auction claiming via `FOR UPDATE ... SKIP LOCKED`
- Pytest unit coverage for core valuation, eBay normalization, and repository behavior

## Install / test
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest
```

For PostgreSQL support:
```bash
pip install -e '.[db,dev]'
```

## eBay configuration
```bash
export EBAY_CLIENT_ID='your-app-id'
export EBAY_CLIENT_SECRET='your-cert-id'
export EBAY_MARKETPLACE_ID='EBAY_US'
export EBAY_ENVIRONMENT='production'
```

No credentials are committed to this repository.
