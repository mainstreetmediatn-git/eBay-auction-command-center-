from __future__ import annotations
from decimal import Decimal
from datetime import datetime
from typing import Any, Callable, Mapping, Optional
import json
from .connectors import NormalizedListing
from .models import AuctionEvaluation

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None
    dict_row = None

class RepositoryError(RuntimeError):
    pass

def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "__dict__"):
        return value.__dict__
    raise TypeError(f"not JSON serializable: {type(value)!r}")

def _json(value: Any) -> str:
    return json.dumps(value, default=_json_default, separators=(",", ":"))

class SaleScannerRepository:
    def __init__(self, connection: Any):
        self.connection = connection

    @classmethod
    def connect(cls, dsn: str) -> "SaleScannerRepository":
        if psycopg is None:
            raise RepositoryError("psycopg is not installed; install sale-scanner-core[db]")
        return cls(psycopg.connect(dsn, row_factory=dict_row))

    def close(self) -> None:
        self.connection.close()

    def ingest_listing(self, listing: NormalizedListing, *, product_id: Optional[str] = None, asset_id: Optional[str] = None, sales_tax: Decimal = Decimal("0")) -> None:
        with self.connection.transaction():
            with self.connection.cursor() as cur:
                cur.execute(
                    """INSERT INTO listings (
                        listing_id,asset_id,product_id,connector_id,listing_type,title,listing_url,currency,
                        condition_grade,seller_id,seller_feedback_score,seller_feedback_percentage,seller_location,
                        current_price,shipping_cost,sales_tax,bid_count,category_metadata,raw_payload,last_updated_at
                    ) VALUES (
                        %(listing_id)s,%(asset_id)s,%(product_id)s,%(connector_id)s,%(listing_type)s,%(title)s,%(listing_url)s,%(currency)s,
                        %(condition_grade)s,%(seller_id)s,%(seller_feedback_score)s,%(seller_feedback_percentage)s,%(seller_location)s,
                        %(current_price)s,%(shipping_cost)s,%(sales_tax)s,%(bid_count)s,%(category_metadata)s::jsonb,%(raw_payload)s::jsonb,NOW()
                    ) ON CONFLICT (listing_id) DO UPDATE SET
                        current_price=EXCLUDED.current_price,
                        shipping_cost=EXCLUDED.shipping_cost,
                        sales_tax=EXCLUDED.sales_tax,
                        bid_count=EXCLUDED.bid_count,
                        raw_payload=EXCLUDED.raw_payload,
                        last_updated_at=NOW()""",
                    {
                        "listing_id": listing.listing_id,
                        "asset_id": asset_id,
                        "product_id": product_id,
                        "connector_id": listing.connector_id,
                        "listing_type": listing.listing_type,
                        "title": listing.title,
                        "listing_url": listing.listing_url,
                        "currency": listing.currency,
                        "condition_grade": listing.condition,
                        "seller_id": listing.seller_id,
                        "seller_feedback_score": listing.seller_feedback_score,
                        "seller_feedback_percentage": listing.seller_feedback_percentage,
                        "seller_location": listing.seller_location,
                        "current_price": listing.current_price,
                        "shipping_cost": listing.shipping_cost,
                        "sales_tax": sales_tax,
                        "bid_count": listing.bid_count,
                        "category_metadata": _json({"category_ids": listing.category_ids, "buying_options": listing.buying_options, "thumbnail_url": listing.thumbnail_url}),
                        "raw_payload": _json(listing.raw_payload),
                    },
                )
                cur.execute(
                    "INSERT INTO listing_snapshots (listing_id,price,shipping_cost,bid_count,raw_payload) VALUES (%s,%s,%s,%s,%s::jsonb)",
                    (listing.listing_id, listing.current_price, listing.shipping_cost, listing.bid_count, _json(listing.raw_payload)),
                )
                if listing.listing_type == "AUCTION" and listing.end_time_iso:
                    cur.execute(
                        """INSERT INTO auction_events (auction_id,end_time,state,next_alert_at,last_known_price,last_evaluated_at)
                        VALUES (%s,%s,'MONITOR',NOW(),%s,NOW())
                        ON CONFLICT (auction_id) DO UPDATE SET end_time=EXCLUDED.end_time,last_known_price=EXCLUDED.last_known_price""",
                        (listing.listing_id, listing.end_time_iso, listing.current_price),
                    )

    def append_decision(self, evaluation: AuctionEvaluation, *, confidence_score: float, expected_net_profit: Optional[Decimal] = None) -> None:
        with self.connection.transaction():
            with self.connection.cursor() as cur:
                cur.execute(
                    """INSERT INTO decisions (listing_id,decision_state,confidence_score,safe_ceiling,normal_ceiling,aggressive_ceiling,expected_net_profit,evidence_ledger)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""",
                    (evaluation.listing_id, evaluation.state, confidence_score, evaluation.safe_ceiling, evaluation.normal_ceiling, evaluation.aggressive_ceiling, expected_net_profit, _json(evaluation.to_dict())),
                )
                cur.execute(
                    "UPDATE auction_events SET state=%s,last_evaluated_at=NOW() WHERE auction_id=%s",
                    (evaluation.state, evaluation.listing_id),
                )

    def claim_due_auctions(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self.connection.transaction():
            with self.connection.cursor() as cur:
                cur.execute(
                    """SELECT ae.auction_id,ae.end_time,ae.state,ae.alert_offsets,ae.next_alert_at,ae.last_known_price,
                              l.current_price,l.shipping_cost,l.sales_tax,l.bid_count,l.raw_payload
                       FROM auction_events ae
                       JOIN listings l ON l.listing_id=ae.auction_id
                       WHERE ae.state NOT IN ('CLOSED','PASS')
                         AND ae.end_time>NOW()
                         AND (ae.next_alert_at IS NULL OR ae.next_alert_at<=NOW())
                       ORDER BY ae.end_time ASC
                       FOR UPDATE OF ae SKIP LOCKED
                       LIMIT %s""",
                    (limit,),
                )
                return [dict(row) if not isinstance(row, dict) else row for row in cur.fetchall()]

class AuctionWorker:
    def __init__(self, repository: SaleScannerRepository, evaluator: Callable[[Mapping[str, Any]], tuple[AuctionEvaluation, float, Optional[Decimal]]]):
        self.repository = repository
        self.evaluator = evaluator

    def run_once(self, *, limit: int = 50) -> int:
        processed = 0
        for row in self.repository.claim_due_auctions(limit=limit):
            evaluation, confidence, expected_profit = self.evaluator(row)
            self.repository.append_decision(evaluation, confidence_score=confidence, expected_net_profit=expected_profit)
            processed += 1
        return processed
