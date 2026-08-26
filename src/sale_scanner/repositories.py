from __future__ import annotations
from decimal import Decimal
from datetime import datetime
from typing import Any, Callable, Mapping, Optional
import json
from .connectors import NormalizedListing
from .models import AuctionEvaluation, CompResult
from .search_models import SavedSearch

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None
    dict_row = None

class RepositoryError(RuntimeError): pass

def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal): return str(value)
    if isinstance(value, datetime): return value.isoformat()
    if hasattr(value, "__dict__"): return value.__dict__
    raise TypeError(f"not JSON serializable: {type(value)!r}")

def _json(value: Any) -> str: return json.dumps(value, default=_json_default, separators=(",", ":"))

class SaleScannerRepository:
    def __init__(self, connection: Any): self.connection = connection
    @classmethod
    def connect(cls, dsn: str) -> "SaleScannerRepository":
        if psycopg is None: raise RepositoryError("psycopg is not installed; install sale-scanner-core[db]")
        return cls(psycopg.connect(dsn, row_factory=dict_row))
    def close(self) -> None: self.connection.close()

    def ingest_listing(self, listing: NormalizedListing, *, product_id=None, asset_id=None, sales_tax=Decimal("0")) -> None:
        with self.connection.transaction():
            with self.connection.cursor() as cur:
                cur.execute("""INSERT INTO listings (listing_id,asset_id,product_id,connector_id,listing_type,title,listing_url,currency,condition_grade,seller_id,seller_feedback_score,seller_feedback_percentage,seller_location,current_price,shipping_cost,sales_tax,bid_count,category_metadata,raw_payload,last_updated_at)
                VALUES (%(listing_id)s,%(asset_id)s,%(product_id)s,%(connector_id)s,%(listing_type)s,%(title)s,%(listing_url)s,%(currency)s,%(condition_grade)s,%(seller_id)s,%(seller_feedback_score)s,%(seller_feedback_percentage)s,%(seller_location)s,%(current_price)s,%(shipping_cost)s,%(sales_tax)s,%(bid_count)s,%(category_metadata)s::jsonb,%(raw_payload)s::jsonb,NOW())
                ON CONFLICT (listing_id) DO UPDATE SET current_price=EXCLUDED.current_price,shipping_cost=EXCLUDED.shipping_cost,sales_tax=EXCLUDED.sales_tax,bid_count=EXCLUDED.bid_count,raw_payload=EXCLUDED.raw_payload,last_updated_at=NOW()""", {
                    "listing_id":listing.listing_id,"asset_id":asset_id,"product_id":product_id,"connector_id":listing.connector_id,"listing_type":listing.listing_type,"title":listing.title,"listing_url":listing.listing_url,"currency":listing.currency,"condition_grade":listing.condition,"seller_id":listing.seller_id,"seller_feedback_score":listing.seller_feedback_score,"seller_feedback_percentage":listing.seller_feedback_percentage,"seller_location":listing.seller_location,"current_price":listing.current_price,"shipping_cost":listing.shipping_cost,"sales_tax":sales_tax,"bid_count":listing.bid_count,"category_metadata":_json({"category_ids":listing.category_ids,"buying_options":listing.buying_options,"thumbnail_url":listing.thumbnail_url}),"raw_payload":_json(listing.raw_payload)})
                cur.execute("INSERT INTO listing_snapshots (listing_id,price,shipping_cost,bid_count,raw_payload) VALUES (%s,%s,%s,%s,%s::jsonb)",(listing.listing_id,listing.current_price,listing.shipping_cost,listing.bid_count,_json(listing.raw_payload)))
                if listing.listing_type == "AUCTION" and listing.end_time_iso:
                    cur.execute("""INSERT INTO auction_events (auction_id,end_time,state,next_alert_at,last_known_price,last_evaluated_at) VALUES (%s,%s,'MONITOR',NOW(),%s,NOW()) ON CONFLICT (auction_id) DO UPDATE SET end_time=EXCLUDED.end_time,last_known_price=EXCLUDED.last_known_price""",(listing.listing_id,listing.end_time_iso,listing.current_price))

    def append_decision(self, evaluation: AuctionEvaluation, *, confidence_score: float, expected_net_profit=None) -> None:
        with self.connection.transaction():
            with self.connection.cursor() as cur:
                cur.execute("INSERT INTO decisions (listing_id,decision_state,confidence_score,safe_ceiling,normal_ceiling,aggressive_ceiling,expected_net_profit,evidence_ledger) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb)",(evaluation.listing_id,evaluation.state,confidence_score,evaluation.safe_ceiling,evaluation.normal_ceiling,evaluation.aggressive_ceiling,expected_net_profit,_json(evaluation.to_dict())))
                cur.execute("UPDATE auction_events SET state=%s,last_evaluated_at=NOW() WHERE auction_id=%s",(evaluation.state,evaluation.listing_id))

    def append_fixed_price_decision(self, listing_id, state, confidence_score, expected_net_profit, evidence) -> None:
        with self.connection.transaction():
            with self.connection.cursor() as cur:
                cur.execute("INSERT INTO decisions (listing_id,decision_state,confidence_score,expected_net_profit,evidence_ledger) VALUES (%s,%s,%s,%s,%s::jsonb)",(listing_id,state,confidence_score,expected_net_profit,_json(evidence)))

    def save_comp_result(self, listing_id: str, result: CompResult) -> None:
        b=result.bands
        with self.connection.transaction():
            with self.connection.cursor() as cur:
                cur.execute("""INSERT INTO comp_sets (listing_id,raw_comps_count,rejected_comps_count,used_comps_count,median_comp_price,weighted_comp_price,fast_sale_estimate,conservative_resale_estimate,expected_resale_estimate,optimistic_resale_estimate,confidence_score,comp_evidence_payload)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""",(listing_id,result.raw_count,result.rejected_count,result.accepted_count,result.median_price,result.weighted_price,b.fast_sale if b else None,b.conservative if b else None,b.expected if b else None,b.optimistic if b else None,result.confidence_score,_json(result.evidence)))

    def claim_due_auctions(self, *, limit=50):
        with self.connection.transaction():
            with self.connection.cursor() as cur:
                cur.execute("""SELECT ae.auction_id,ae.end_time,ae.state,ae.alert_offsets,ae.next_alert_at,ae.last_known_price,l.current_price,l.shipping_cost,l.sales_tax,l.bid_count,l.raw_payload FROM auction_events ae JOIN listings l ON l.listing_id=ae.auction_id WHERE ae.state NOT IN ('CLOSED','PASS') AND ae.end_time>NOW() AND (ae.next_alert_at IS NULL OR ae.next_alert_at<=NOW()) ORDER BY ae.end_time ASC FOR UPDATE OF ae SKIP LOCKED LIMIT %s""",(limit,))
                return [dict(r) if not isinstance(r,dict) else r for r in cur.fetchall()]

    def claim_due_saved_searches(self, *, limit=25):
        with self.connection.transaction():
            with self.connection.cursor() as cur:
                cur.execute("""SELECT search_id::text,connector_id,query,enabled,poll_interval_seconds,max_price,category_id,filters FROM saved_searches WHERE enabled=TRUE AND next_poll_at<=NOW() ORDER BY next_poll_at FOR UPDATE SKIP LOCKED LIMIT %s""",(limit,))
                return [SavedSearch(**(dict(r) if not isinstance(r,dict) else r)) for r in cur.fetchall()]

    def get_search_listing_fingerprint(self, search_id, listing_id):
        with self.connection.cursor() as cur:
            cur.execute("SELECT fingerprint FROM saved_search_listings WHERE search_id=%s AND listing_id=%s",(search_id,listing_id)); row=cur.fetchone()
            return (row.get("fingerprint") if isinstance(row,dict) else row[0]) if row else None

    def record_search_listing_fingerprint(self, search_id, listing_id, fingerprint):
        with self.connection.transaction():
            with self.connection.cursor() as cur:
                cur.execute("""INSERT INTO saved_search_listings (search_id,listing_id,fingerprint) VALUES (%s,%s,%s) ON CONFLICT (search_id,listing_id) DO UPDATE SET fingerprint=EXCLUDED.fingerprint,last_seen_at=NOW()""",(search_id,listing_id,fingerprint))

    def mark_saved_search_polled(self, search_id, *, success, error=None):
        with self.connection.transaction():
            with self.connection.cursor() as cur:
                cur.execute("""UPDATE saved_searches SET last_polled_at=NOW(),next_poll_at=NOW()+(poll_interval_seconds*INTERVAL '1 second'),last_error=%s,updated_at=NOW() WHERE search_id=%s""",(None if success else error,search_id))

class AuctionWorker:
    def __init__(self, repository, evaluator): self.repository,self.evaluator=repository,evaluator
    def run_once(self, *, limit=50):
        processed=0
        for row in self.repository.claim_due_auctions(limit=limit):
            evaluation,confidence,expected_profit=self.evaluator(row)
            self.repository.append_decision(evaluation,confidence_score=confidence,expected_net_profit=expected_profit); processed+=1
        return processed
