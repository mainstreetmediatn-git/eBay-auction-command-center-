from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

from .ebay import EbayConfig
from .hybrid_ebay import HybridEbayConnector
from .repositories import SaleScannerRepository
from .runtime import SaleScannerAgent


def _repo() -> SaleScannerRepository:
    dsn = os.getenv("DATABASE_URL", "").strip()
    if not dsn:
        raise SystemExit("DATABASE_URL is required")
    return SaleScannerRepository.connect(dsn)


def _connector() -> HybridEbayConnector:
    return HybridEbayConnector(EbayConfig.from_env())


def init_db(args) -> int:
    repo = _repo()
    try:
        schema = Path(args.schema).read_text(encoding="utf-8")
        with repo.connection.transaction():
            with repo.connection.cursor() as cur:
                cur.execute(schema)
    finally:
        repo.close()
    print("database initialized")
    return 0


def add_search(args) -> int:
    repo = _repo()
    try:
        with repo.connection.transaction():
            with repo.connection.cursor() as cur:
                cur.execute(
                    """INSERT INTO saved_searches (connector_id,query,poll_interval_seconds,max_price,category_id)
                       VALUES ('ebay',%s,%s,%s,%s) RETURNING search_id::text""",
                    (args.query, args.interval, args.max_price, args.category_id),
                )
                row = cur.fetchone()
                search_id = row["search_id"] if isinstance(row, dict) else row[0]
    finally:
        repo.close()
    print(search_id)
    return 0


def _jsonable(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value


def scan(args) -> int:
    """Run an immediate hybrid eBay API + TinyFish browser search."""
    connector = _connector()
    filters = []
    if args.auctions:
        filters.append("buyingOptions:{AUCTION}")
    if args.max_price is not None:
        filters.append(f"price:[..{args.max_price}]")
        filters.append("priceCurrency:USD")
    result = connector.search(
        args.query,
        limit=args.limit,
        filter_expression=",".join(filters) if filters else None,
        sort="endingSoonest" if args.ending_soonest else args.sort,
        fieldgroups="EXTENDED",
        browser_enrich=not args.api_only,
    )

    if args.json:
        payload = {
            "query": args.query,
            "total": result.total,
            "warnings": result.warnings,
            "listings": [_jsonable(asdict(item)) for item in result.listings],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    source = "eBay API + TinyFish" if not args.api_only else "eBay API"
    print(f"\n{source.upper()} RESULTS — {args.query}  ({len(result.listings)} shown / {result.total or '?'} found)\n")
    for warning in result.warnings:
        print(f"warning: {warning}")
    if result.warnings:
        print()
    for index, item in enumerate(result.listings, start=1):
        seller = item.seller_id or "seller unavailable"
        feedback = ""
        if item.seller_feedback_percentage is not None:
            feedback = f" · {item.seller_feedback_percentage}% positive"
        elif item.raw_payload.get("tinyfish_seller_feedback"):
            feedback = f" · {item.raw_payload['tinyfish_seller_feedback']}"
        bids = f" · {item.bid_count} bid{'s' if item.bid_count != 1 else ''}" if item.listing_type == "AUCTION" else ""
        ending = f" · ends {item.end_time_iso}" if item.end_time_iso else ""
        time_left = item.raw_payload.get("tinyfish_time_remaining")
        if time_left:
            ending += f" · {time_left} left"
        condition = item.condition or "Condition unavailable"
        print(f"{index:>2}. {item.title}")
        if item.subtitle:
            print(f"    {item.subtitle}")
        print(f"    {condition}")
        print(f"    {item.price_display or ('$' + str(item.current_price))}{bids}{ending}")
        print(f"    {item.shipping_display or ''}{(' · ' + item.delivery_display) if item.delivery_display else ''}")
        print(f"    {seller}{feedback}{' · Top Rated' if item.seller_top_rated else ''}")
        if item.thumbnail_url:
            print(f"    image: {item.thumbnail_url}")
        print(f"    {item.listing_url}\n")
    return 0


def run_agent(args) -> int:
    repo = _repo()
    connector = _connector()
    agent = SaleScannerAgent(repo, connector, min_expected_profit=Decimal(str(args.min_profit)))
    try:
        while True:
            result = agent.run_once(search_limit=args.search_limit, dispatch_limit=args.dispatch_limit)
            print(f"evaluated={result['evaluated']} dispatched={result['dispatched']}")
            if args.once:
                break
            time.sleep(args.sleep)
    except KeyboardInterrupt:
        pass
    finally:
        repo.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="sale-scanner")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init-db")
    p.add_argument("--schema", default="sql/schema.sql")
    p.set_defaults(func=init_db)

    p = sub.add_parser("add-search")
    p.add_argument("query")
    p.add_argument("--max-price", type=Decimal)
    p.add_argument("--category-id")
    p.add_argument("--interval", type=int, default=300)
    p.set_defaults(func=add_search)

    p = sub.add_parser("scan", help="search eBay now and print visible listing results")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=25)
    p.add_argument("--max-price", type=Decimal)
    p.add_argument("--auctions", action="store_true")
    p.add_argument("--ending-soonest", action="store_true", default=False)
    p.add_argument("--sort", choices=["price", "newlyListed", "endingSoonest"], default=None)
    p.add_argument("--api-only", action="store_true", help="disable TinyFish browser enrichment")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=scan)

    p = sub.add_parser("run")
    p.add_argument("--once", action="store_true")
    p.add_argument("--sleep", type=int, default=30)
    p.add_argument("--min-profit", type=Decimal, default=Decimal("50"))
    p.add_argument("--search-limit", type=int, default=25)
    p.add_argument("--dispatch-limit", type=int, default=50)
    p.set_defaults(func=run_agent)

    args = parser.parse_args()
    if getattr(args, "interval", 300) < 30:
        parser.error("--interval must be >= 30 seconds")
    if getattr(args, "sleep", 30) < 5:
        parser.error("--sleep must be >= 5 seconds")
    if getattr(args, "limit", 25) < 1 or getattr(args, "limit", 25) > 200:
        parser.error("--limit must be between 1 and 200")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
