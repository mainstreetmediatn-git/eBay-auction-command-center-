from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable, Optional
from .models import AuctionSnapshot, AuctionEvaluation, ValuationBands
from .financial import max_purchase_price

DEFAULT_ALERT_OFFSETS = (86400, 3600, 900, 300)

def _seconds_remaining(end_time_iso: str, now: Optional[datetime] = None) -> int:
    now = now or datetime.now(timezone.utc)
    end = datetime.fromisoformat(end_time_iso.replace("Z", "+00:00"))
    return max(0, int((end - now).total_seconds()))

def next_alert_offset(seconds_remaining: int, offsets: Iterable[int] = DEFAULT_ALERT_OFFSETS) -> Optional[int]:
    future = sorted([o for o in offsets if o < seconds_remaining], reverse=True)
    return future[0] if future else None

def evaluate_auction(
    snapshot: AuctionSnapshot,
    bands: ValuationBands,
    *,
    outbound_shipping: Decimal,
    resale_marketplace_fee_pct: Decimal,
    payment_processing_fee_flat: Decimal,
    return_risk_reserve: Decimal,
    immediate_repair_cost: Decimal,
    min_acceptable_profit: Decimal,
    confidence_score: float,
    now: Optional[datetime] = None,
) -> AuctionEvaluation:
    args = (
        outbound_shipping,
        resale_marketplace_fee_pct,
        payment_processing_fee_flat,
        return_risk_reserve,
        snapshot.shipping_cost,
        snapshot.sales_tax,
        immediate_repair_cost,
        min_acceptable_profit,
    )
    safe = max_purchase_price(bands.conservative, *args)
    normal = max_purchase_price(bands.expected, *args)
    aggressive = max_purchase_price(bands.optimistic, *args)
    seconds = _seconds_remaining(snapshot.end_time_iso, now)
    total = snapshot.current_price + snapshot.shipping_cost + snapshot.sales_tax
    reasons = [
        f"confidence={confidence_score:.4f}",
        f"current_bid={snapshot.current_price}",
        f"safe_ceiling={safe}",
        f"normal_ceiling={normal}",
        f"aggressive_ceiling={aggressive}",
        f"seconds_remaining={seconds}",
    ]
    if seconds == 0:
        state = "CLOSED"
    elif snapshot.current_price > aggressive:
        state = "PASS"
        reasons.append("price_above_aggressive_ceiling")
    elif snapshot.current_price <= safe:
        state = "BUY_ZONE"
        reasons.append("price_at_or_below_safe_ceiling")
    elif confidence_score >= 0.85 and snapshot.current_price <= normal:
        state = "BID"
        reasons.append("high_confidence_price_within_normal_ceiling")
    else:
        state = "MONITOR"
        reasons.append("margin_exists_but_not_inside_default_safe_zone")
    return AuctionEvaluation(
        listing_id=snapshot.listing_id,
        state=state,
        seconds_remaining=seconds,
        current_total_cost=total.quantize(Decimal("0.01")),
        safe_ceiling=safe,
        normal_ceiling=normal,
        aggressive_ceiling=aggressive,
        next_alert_seconds=next_alert_offset(seconds),
        reasons=reasons,
    )
