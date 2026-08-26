from decimal import Decimal
from .models import FinancialInputs, EvaluationResult

def evaluate_listing_economics(fin: FinancialInputs, confidence_score: float, seller_feedback_count: int) -> EvaluationResult:
    acquisition_cost = fin.purchase_price + fin.inbound_shipping + fin.sales_tax + fin.immediate_repair_cost
    marketplace_fees = fin.conservative_resale_price * fin.resale_marketplace_fee_pct + fin.payment_processing_fee_flat
    expected_net_resale = fin.conservative_resale_price - fin.outbound_shipping - marketplace_fees - fin.return_risk_reserve
    expected_net_profit = expected_net_resale - acquisition_cost
    reasons = [
        f"conservative_resale={fin.conservative_resale_price}",
        f"acquisition_cost={acquisition_cost}",
        f"expected_net_profit={expected_net_profit}",
        f"minimum_profit={fin.min_acceptable_profit}",
    ]
    warnings = []
    if seller_feedback_count < 20:
        warnings.append("seller_feedback_count_below_20")
    if expected_net_profit < fin.min_acceptable_profit:
        decision = "PASS"
        score = int(confidence_score * 40)
        reasons.append("margin_below_minimum_threshold")
    elif fin.immediate_repair_cost > 0:
        decision = "REPAIR_FLIP"
        score = int(confidence_score * 90)
        reasons.append("repair_reserve_factored_successfully")
    else:
        decision = "BID"
        score = int(confidence_score * 95)
        reasons.append("clean_margin_meets_criteria")
    return EvaluationResult(decision, score, acquisition_cost, expected_net_resale, expected_net_profit, reasons, warnings)

def max_purchase_price(
    resale_price: Decimal,
    outbound_shipping: Decimal,
    resale_marketplace_fee_pct: Decimal,
    payment_processing_fee_flat: Decimal,
    return_risk_reserve: Decimal,
    inbound_shipping: Decimal,
    sales_tax: Decimal,
    immediate_repair_cost: Decimal,
    min_acceptable_profit: Decimal,
) -> Decimal:
    resale_fees = resale_price * resale_marketplace_fee_pct + payment_processing_fee_flat
    max_acquisition = resale_price - outbound_shipping - resale_fees - return_risk_reserve - min_acceptable_profit
    ceiling = max_acquisition - inbound_shipping - sales_tax - immediate_repair_cost
    return max(Decimal("0"), ceiling).quantize(Decimal("0.01"))
