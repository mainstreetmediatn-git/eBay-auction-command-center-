# eBay Auction Command Center — Sale Scanner Agent

[![CI](https://github.com/mainstreetmediatn-git/eBay-auction-command-center-/actions/workflows/ci.yml/badge.svg)](https://github.com/mainstreetmediatn-git/eBay-auction-command-center-/actions/workflows/ci.yml)

Explainable resale-arbitrage agent for eBay ingestion, comparable-price valuation, financial ceilings, auction decisions, saved-search polling, and durable deal alerts.

## Included
- eBay Browse API connector with OAuth, retry/backoff, normalization, and rate-limit handling
- Saved-search poller with listing-change fingerprints and restart-safe persistence
- Deterministic comp engine with IQR outlier rejection and weighted evidence
- Bootstrap eBay asking-price comp provider when a completed-sales data source is not configured
- Valuation bands: fast-sale, conservative, expected, optimistic
- Safe / normal / aggressive maximum purchase ceilings
- Auction state evaluator: BUY_ZONE, BID, MONITOR, PASS, CLOSED
- PostgreSQL persistence and multi-worker-safe claiming with `FOR UPDATE ... SKIP LOCKED`
- Durable dispatch ledger so qualified alerts are not sent twice
- Console alerts plus optional HTTP webhook alerts
- Runnable `sale-scanner` CLI
- Pytest + GitHub Actions CI

> Note: eBay Browse does not provide completed/sold history. The bundled comp provider uses current fixed-price asking prices as a conservative bootstrap source. For serious purchasing decisions, connect a true sold-comps source before treating valuations as authoritative.

## Install
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[db,dev]'
```

## Configure
```bash
export DATABASE_URL='postgresql://user:pass@localhost:5432/sale_scanner'
export EBAY_CLIENT_ID='your-app-id'
export EBAY_CLIENT_SECRET='your-cert-id'
export EBAY_MARKETPLACE_ID='EBAY_US'
export EBAY_ENVIRONMENT='production'

# Optional: Slack/Discord/custom receiver that accepts JSON POST requests
export DEAL_WEBHOOK_URL='https://example.com/your-webhook'
```

No credentials are committed to this repository.

## Initialize the database
```bash
sale-scanner init-db
```

## Add searches
```bash
sale-scanner add-search 'gaming laptop RTX 4070' --max-price 650 --interval 300
sale-scanner add-search 'Ryzen 9 CPU motherboard combo' --max-price 300 --interval 300
```

## Run the agent
Run one cycle:
```bash
sale-scanner run --once --min-profit 50
```

Run continuously:
```bash
sale-scanner run --sleep 30 --min-profit 50
```

The agent polls due saved searches, ingests new or changed listings, evaluates their economics, persists decisions, and dispatches qualifying BUY_ZONE/BID opportunities. Alert dispatch is persisted so restarts do not cause duplicate sends.

## Test
```bash
pytest
```
