from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping, Protocol, Sequence


@dataclass(frozen=True)
class DispatchCandidate:
    decision_id: str
    listing_id: str
    decision_state: str
    confidence_score: float
    expected_net_profit: Decimal | None
    listing_url: str | None
    title: str
    current_price: Decimal
    safe_ceiling: Decimal | None = None
    normal_ceiling: Decimal | None = None
    aggressive_ceiling: Decimal | None = None
    evidence_ledger: Mapping[str, Any] | None = None


class DispatchChannel(Protocol):
    channel_id: str

    def send(self, candidate: DispatchCandidate) -> None: ...


class QualifiedDealDispatcher:
    """Dispatch qualified decisions exactly once per channel.

    The repository owns persistence, leasing, and deduplication. A successful
    send is permanently marked SENT. Failed or abandoned PROCESSING leases can
    be reclaimed on a later run, which makes process restarts safe.
    """

    def __init__(
        self,
        repository,
        channels: Sequence[DispatchChannel],
        *,
        qualifying_states: Sequence[str] = ("BUY_ZONE", "BID"),
        min_expected_profit: Decimal = Decimal("0"),
        lease_seconds: int = 120,
    ):
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        self.repository = repository
        self.channels = tuple(channels)
        self.qualifying_states = tuple(qualifying_states)
        self.min_expected_profit = Decimal(min_expected_profit)
        self.lease_seconds = lease_seconds

    def run_once(self, *, limit_per_channel: int = 50) -> int:
        sent = 0
        for channel in self.channels:
            candidates = self.repository.claim_dispatch_candidates(
                channel.channel_id,
                states=self.qualifying_states,
                min_expected_profit=self.min_expected_profit,
                lease_seconds=self.lease_seconds,
                limit=limit_per_channel,
            )
            for candidate in candidates:
                try:
                    channel.send(candidate)
                except Exception as exc:
                    self.repository.mark_dispatch_failed(
                        candidate.decision_id,
                        channel.channel_id,
                        str(exc),
                    )
                    continue
                self.repository.mark_dispatch_sent(candidate.decision_id, channel.channel_id)
                sent += 1
        return sent
