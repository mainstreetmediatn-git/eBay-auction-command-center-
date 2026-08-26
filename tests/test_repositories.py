from contextlib import contextmanager
from decimal import Decimal
from sale_scanner.connectors import NormalizedListing
from sale_scanner.repositories import SaleScannerRepository, AuctionWorker
from sale_scanner.models import AuctionEvaluation


class FakeCursor:
    def __init__(self, rows=None):
        self.calls = []
        self.rows = rows or []

    def execute(self, sql, params=None):
        self.calls.append((" ".join(sql.split()), params))

    def fetchall(self):
        return self.rows

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeConnection:
    def __init__(self, rows=None):
        self.cursor_obj = FakeCursor(rows)
        self.transactions = 0

    @contextmanager
    def transaction(self):
        self.transactions += 1
        yield

    def cursor(self):
        return self.cursor_obj

    def close(self):
        pass


def test_ingest_listing_upserts_and_appends_snapshot_and_auction_event():
    conn = FakeConnection()
    repo = SaleScannerRepository(conn)
    listing = NormalizedListing(
        listing_id="ebay_1",
        connector_id="ebay",
        platform="eBay",
        listing_type="AUCTION",
        title="GPU",
        listing_url="https://example.test/1",
        current_price=Decimal("100"),
        shipping_cost=Decimal("12"),
        bid_count=3,
        end_time_iso="2026-08-25T00:00:00Z",
        raw_payload={"itemId": "1"},
    )
    repo.ingest_listing(listing)
    sql = [call[0] for call in conn.cursor_obj.calls]
    assert len(sql) == 3
    assert "ON CONFLICT (listing_id) DO UPDATE" in sql[0]
    assert "INSERT INTO listing_snapshots" in sql[1]
    assert "INSERT INTO auction_events" in sql[2]


def test_claim_due_auctions_uses_skip_locked():
    conn = FakeConnection([{"auction_id": "ebay_1"}])
    repo = SaleScannerRepository(conn)
    result = repo.claim_due_auctions()
    assert result == [{"auction_id": "ebay_1"}]
    assert "SKIP LOCKED" in conn.cursor_obj.calls[0][0]


def test_worker_appends_evaluation():
    class Repo:
        def __init__(self):
            self.saved = []

        def claim_due_auctions(self, limit=50):
            return [{"auction_id": "ebay_1"}]

        def append_decision(self, evaluation, **kwargs):
            self.saved.append((evaluation, kwargs))

    repo = Repo()
    evaluation = AuctionEvaluation(
        listing_id="ebay_1",
        state="BUY_ZONE",
        seconds_remaining=300,
        current_total_cost=Decimal("100"),
        safe_ceiling=Decimal("120"),
        normal_ceiling=Decimal("130"),
        aggressive_ceiling=Decimal("140"),
        next_alert_seconds=None,
        reasons=["test"],
    )
    worker = AuctionWorker(repo, lambda row: (evaluation, 0.9, Decimal("55")))
    assert worker.run_once() == 1
    assert repo.saved[0][0].state == "BUY_ZONE"
