from dataclasses import dataclass, field, asdict
from decimal import Decimal
from typing import List, Optional, Dict, Any

@dataclass
class FinancialInputs:
    purchase_price: Decimal
    inbound_shipping: Decimal
    sales_tax: Decimal
    immediate_repair_cost: Decimal
    conservative_resale_price: Decimal
    outbound_shipping: Decimal
    resale_marketplace_fee_pct: Decimal
    payment_processing_fee_flat: Decimal
    return_risk_reserve: Decimal
    min_acceptable_profit: Decimal

@dataclass
class EvaluationResult:
    decision: str
    score: int
    acquisition_cost: Decimal
    expected_net_resale: Decimal
    expected_net_profit: Decimal
    reasons: List[str]
    warnings: List[str]

@dataclass
class Comp:
    listing_id: str
    sold_price: Decimal
    shipping: Decimal
    sold_days_ago: int
    condition_grade: str
    title_similarity: float
    exact_model_match: bool = False

    @property
    def total_sale_price(self) -> Decimal:
        return self.sold_price + self.shipping

@dataclass
class CompDecision:
    listing_id: str
    accepted: bool
    reason: str
    total_sale_price: Decimal
    weight: Decimal = Decimal("0")

@dataclass
class ValuationBands:
    fast_sale: Decimal
    conservative: Decimal
    expected: Decimal
    optimistic: Decimal

@dataclass
class CompResult:
    raw_count: int
    accepted_count: int
    rejected_count: int
    median_price: Decimal
    weighted_price: Decimal
    conservative_resale: Decimal
    confidence_score: float
    evidence: List[CompDecision]
    bands: Optional[ValuationBands] = None

@dataclass
class AuctionSnapshot:
    listing_id: str
    current_price: Decimal
    shipping_cost: Decimal
    sales_tax: Decimal
    end_time_iso: str
    bid_count: int = 0

@dataclass
class AuctionEvaluation:
    listing_id: str
    state: str
    seconds_remaining: int
    current_total_cost: Decimal
    safe_ceiling: Decimal
    normal_ceiling: Decimal
    aggressive_ceiling: Decimal
    next_alert_seconds: Optional[int]
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        for key in ("current_total_cost", "safe_ceiling", "normal_ceiling", "aggressive_ceiling"):
            d[key] = str(d[key])
        return d
