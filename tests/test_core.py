from datetime import datetime, timedelta, timezone
from decimal import Decimal
from sale_scanner.models import Comp, AuctionSnapshot
from sale_scanner.comp_engine import evaluate_comps
from sale_scanner.auction import evaluate_auction


def sample_comps():
    return [
        Comp("c1", Decimal("220"), Decimal("10"), 4, "GOOD", 0.95, True),
        Comp("c2", Decimal("225"), Decimal("12"), 10, "GOOD", 0.93, True),
        Comp("c3", Decimal("235"), Decimal("8"), 20, "GOOD", 0.91, True),
        Comp("c4", Decimal("999"), Decimal("0"), 2, "GOOD", 0.90, True),
        Comp("bad", Decimal("120"), Decimal("10"), 5, "GOOD", 0.30, False),
    ]


def test_comp_engine_has_bands():
    result = evaluate_comps(sample_comps(), "GOOD")
    assert result.bands is not None
    assert result.bands.fast_sale < result.bands.conservative < result.bands.optimistic
    assert result.accepted_count >= 3


def test_auction_state():
    comps = evaluate_comps(sample_comps(), "GOOD")
    end = datetime.now(timezone.utc) + timedelta(minutes=10)
    snap = AuctionSnapshot("ebay_test", Decimal("80"), Decimal("10"), Decimal("0"), end.isoformat())
    ev = evaluate_auction(
        snap,
        comps.bands,
        outbound_shipping=Decimal("15"),
        resale_marketplace_fee_pct=Decimal("0.13"),
        payment_processing_fee_flat=Decimal("0.30"),
        return_risk_reserve=Decimal("10"),
        immediate_repair_cost=Decimal("0"),
        min_acceptable_profit=Decimal("50"),
        confidence_score=comps.confidence_score,
    )
    assert ev.state in {"BUY_ZONE", "BID", "MONITOR", "PASS"}
