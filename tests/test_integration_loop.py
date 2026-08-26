from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sale_scanner.connectors import NormalizedListing, SearchResult
from sale_scanner.dispatcher import DispatchCandidate, QualifiedDealDispatcher
from sale_scanner.evaluation_pipeline import ListingEvaluationPipeline
from sale_scanner.models import Comp
from sale_scanner.saved_search_poller import SavedSearchPoller
from sale_scanner.search_models import SavedSearch


class Connector:
    connector_id = "ebay"
    platform = "eBay"

    def __init__(self, listing):
        self.listing = listing

    def search(self, query, *, limit=50, **kwargs):
        return SearchResult([self.listing], total=1)


class CompProvider:
    def get_comps(self, listing, search):
        return [
            Comp("c1", Decimal("250"), Decimal("10"), 5, "GOOD", 0.98, True),
            Comp("c2", Decimal("255"), Decimal("10"), 10, "GOOD", 0.97, True),
            Comp("c3", Decimal("260"), Decimal("8"), 20, "GOOD", 0.96, True),
            Comp("c4", Decimal("248"), Decimal("12"), 30, "GOOD", 0.95, True),
        ]


class Repo:
    def __init__(self, search):
        self.search = search
        self.fingerprints = {}
        self.comp_results = []
        self.decisions = []
        self.dispatch_status = {}

    def claim_due_saved_searches(self, limit=25):
        return [self.search]

    def mark_saved_search_polled(self, search_id, *, success, error=None):
        assert success is True

    def get_search_listing_fingerprint(self, search_id, listing_id):
        return self.fingerprints.get((search_id, listing_id))

    def record_search_listing_fingerprint(self, search_id, listing_id, fingerprint):
        self.fingerprints[(search_id, listing_id)] = fingerprint

    def ingest_listing(self, listing):
        self.listing = listing

    def save_comp_result(self, listing_id, result):
        self.comp_results.append((listing_id, result))

    def append_decision(self, evaluation, *, confidence_score, expected_net_profit=None):
        self.decisions.append((evaluation, confidence_score, expected_net_profit))

    def append_fixed_price_decision(self, *args, **kwargs):
        raise AssertionError("auction fixture should use auction path")

    def claim_dispatch_candidates(self, channel_id, *, states, min_expected_profit, lease_seconds, limit):
        result = []
        for index, (ev, confidence, profit) in enumerate(self.decisions, start=1):
            decision_id = f"d{index}"
            key = (decision_id, channel_id)
            if self.dispatch_status.get(key) == "SENT":
                continue
            if ev.state not in states or (profit or Decimal("0")) < min_expected_profit:
                continue
            self.dispatch_status[key] = "PROCESSING"
            result.append(DispatchCandidate(
                decision_id=decision_id,
                listing_id=ev.listing_id,
                decision_state=ev.state,
                confidence_score=confidence,
                expected_net_profit=profit,
                listing_url=self.listing.listing_url,
                title=self.listing.title,
                current_price=self.listing.current_price,
                safe_ceiling=ev.safe_ceiling,
                normal_ceiling=ev.normal_ceiling,
                aggressive_ceiling=ev.aggressive_ceiling,
                evidence_ledger=ev.to_dict(),
            ))
        return result[:limit]

    def mark_dispatch_sent(self, decision_id, channel_id):
        self.dispatch_status[(decision_id, channel_id)] = "SENT"

    def mark_dispatch_failed(self, decision_id, channel_id, error):
        self.dispatch_status[(decision_id, channel_id)] = "FAILED"


class Channel:
    channel_id = "alerts"

    def __init__(self):
        self.sent = []

    def send(self, candidate):
        self.sent.append(candidate.decision_id)


def test_saved_search_to_dispatch_is_restart_deduplicated():
    search = SavedSearch("s1", "ebay", "test gpu")
    listing = NormalizedListing(
        listing_id="ebay_l1",
        connector_id="ebay",
        platform="eBay",
        listing_type="AUCTION",
        title="Test GPU",
        listing_url="https://example.test/l1",
        current_price=Decimal("80"),
        shipping_cost=Decimal("10"),
        condition="GOOD",
        seller_feedback_score=500,
        end_time_iso=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    )
    repo = Repo(search)
    pipeline = ListingEvaluationPipeline(repo, CompProvider(), min_profit=Decimal("40"))
    poller = SavedSearchPoller(repo, {"ebay": Connector(listing)}, pipeline)

    assert poller.run_once() == 1
    assert len(repo.comp_results) == 1
    assert len(repo.decisions) == 1
    assert repo.decisions[0][0].state in {"BUY_ZONE", "BID"}

    channel = Channel()
    dispatcher = QualifiedDealDispatcher(repo, [channel], min_expected_profit=Decimal("40"))
    assert dispatcher.run_once() == 1
    assert channel.sent == ["d1"]

    # Simulated process restart: new dispatcher, same durable repository state.
    restarted = QualifiedDealDispatcher(repo, [channel], min_expected_profit=Decimal("40"))
    assert restarted.run_once() == 0
    assert channel.sent == ["d1"]

    # Unchanged listing fingerprint does not create a second decision.
    assert poller.run_once() == 0
    assert len(repo.decisions) == 1
