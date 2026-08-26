from decimal import Decimal
from sale_scanner.dispatcher import DispatchCandidate, QualifiedDealDispatcher


class FakeRepo:
    def __init__(self, candidates):
        self.candidates = list(candidates)
        self.sent = []
        self.failed = []
        self.claim_calls = []

    def claim_dispatch_candidates(self, channel_id, **kwargs):
        self.claim_calls.append((channel_id, kwargs))
        result = list(self.candidates)
        self.candidates = []
        return result

    def mark_dispatch_sent(self, decision_id, channel_id):
        self.sent.append((decision_id, channel_id))

    def mark_dispatch_failed(self, decision_id, channel_id, error):
        self.failed.append((decision_id, channel_id, error))


class Channel:
    channel_id = "test"

    def __init__(self, fail=False):
        self.fail = fail
        self.delivered = []

    def send(self, candidate):
        if self.fail:
            raise RuntimeError("boom")
        self.delivered.append(candidate.decision_id)


def candidate():
    return DispatchCandidate(
        decision_id="d1",
        listing_id="l1",
        decision_state="BUY_ZONE",
        confidence_score=0.92,
        expected_net_profit=Decimal("85"),
        listing_url="https://example.test/l1",
        title="Example GPU",
        current_price=Decimal("100"),
    )


def test_success_marks_sent_once():
    repo = FakeRepo([candidate()])
    channel = Channel()
    dispatcher = QualifiedDealDispatcher(repo, [channel], min_expected_profit=Decimal("50"))
    assert dispatcher.run_once() == 1
    assert repo.sent == [("d1", "test")]
    assert channel.delivered == ["d1"]
    assert dispatcher.run_once() == 0
    assert channel.delivered == ["d1"]


def test_failure_is_recorded_for_retry():
    repo = FakeRepo([candidate()])
    dispatcher = QualifiedDealDispatcher(repo, [Channel(fail=True)])
    assert dispatcher.run_once() == 0
    assert repo.sent == []
    assert repo.failed[0][0:2] == ("d1", "test")
    assert "boom" in repo.failed[0][2]


def test_claim_passes_qualification_and_lease_controls():
    repo = FakeRepo([])
    dispatcher = QualifiedDealDispatcher(
        repo,
        [Channel()],
        qualifying_states=("BUY_ZONE",),
        min_expected_profit=Decimal("75"),
        lease_seconds=90,
    )
    dispatcher.run_once(limit_per_channel=7)
    _, kwargs = repo.claim_calls[0]
    assert kwargs["states"] == ("BUY_ZONE",)
    assert kwargs["min_expected_profit"] == Decimal("75")
    assert kwargs["lease_seconds"] == 90
    assert kwargs["limit"] == 7
