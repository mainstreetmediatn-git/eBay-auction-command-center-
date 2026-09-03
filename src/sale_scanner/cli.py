from __future__ import annotations

import argparse
import os
import time
from decimal import Decimal
from pathlib import Path

from .ebay import EbayConfig, EbayConnector
from .repositories import SaleScannerRepository
from .runtime import SaleScannerAgent


def _repo() -> SaleScannerRepository:
    dsn = os.getenv("DATABASE_URL", "").strip()
    if not dsn:
        raise SystemExit("DATABASE_URL is required")
    return SaleScannerRepository.connect(dsn)


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


def run_agent(args) -> int:
    repo = _repo()
    connector = EbayConnector(EbayConfig.from_env())
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
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
