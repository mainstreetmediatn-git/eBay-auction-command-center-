from decimal import Decimal
from statistics import median
from typing import List
from .models import Comp, CompDecision, CompResult, ValuationBands

CONDITION_MULTIPLIERS = {
    "NEW": Decimal("1.00"),
    "EXCELLENT": Decimal("0.95"),
    "GOOD": Decimal("0.88"),
    "FAIR": Decimal("0.75"),
    "PARTS": Decimal("0.45"),
}

def iqr_bounds(values: List[Decimal]) -> tuple[Decimal, Decimal]:
    if len(values) < 4:
        return min(values), max(values)
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    lower_half = ordered[:midpoint]
    upper_half = ordered[-midpoint:]
    q1 = Decimal(str(median(lower_half)))
    q3 = Decimal(str(median(upper_half)))
    iqr = q3 - q1
    return q1 - Decimal("1.5") * iqr, q3 + Decimal("1.5") * iqr

def recency_weight(days_old: int) -> Decimal:
    if days_old <= 7:
        return Decimal("1.00")
    if days_old <= 30:
        return Decimal("0.90")
    if days_old <= 90:
        return Decimal("0.75")
    if days_old <= 180:
        return Decimal("0.55")
    return Decimal("0.35")

def calculate_valuation_bands(weighted_price: Decimal, target_mult: Decimal) -> ValuationBands:
    base_expected = weighted_price * target_mult
    base_conservative = base_expected * Decimal("0.95")
    return ValuationBands(
        fast_sale=(base_conservative * Decimal("0.90")).quantize(Decimal("0.01")),
        conservative=base_conservative.quantize(Decimal("0.01")),
        expected=base_expected.quantize(Decimal("0.01")),
        optimistic=(base_expected * Decimal("1.10")).quantize(Decimal("0.01")),
    )

def evaluate_comps(comps: List[Comp], target_condition: str, min_similarity: float = 0.72) -> CompResult:
    evidence: List[CompDecision] = []
    candidates: List[Comp] = []
    for comp in comps:
        if not comp.exact_model_match and comp.title_similarity < min_similarity:
            evidence.append(CompDecision(comp.listing_id, False, "insufficient_product_similarity", comp.total_sale_price))
            continue
        candidates.append(comp)
    if not candidates:
        return CompResult(len(comps), 0, len(comps), Decimal("0"), Decimal("0"), Decimal("0"), 0.0, evidence, None)
    prices = [c.total_sale_price for c in candidates]
    lower, upper = iqr_bounds(prices)
    accepted: List[Comp] = []
    for comp in candidates:
        if comp.total_sale_price < lower or comp.total_sale_price > upper:
            evidence.append(CompDecision(comp.listing_id, False, "statistical_outlier", comp.total_sale_price))
            continue
        accepted.append(comp)
    if not accepted:
        accepted = candidates
    weighted_sum = Decimal("0")
    total_weight = Decimal("0")
    target_mult = CONDITION_MULTIPLIERS.get(target_condition, Decimal("0.80"))
    for comp in accepted:
        weight = recency_weight(comp.sold_days_ago)
        if comp.exact_model_match:
            weight *= Decimal("1.20")
        if comp.condition_grade == target_condition:
            weight *= Decimal("1.15")
        weighted_sum += comp.total_sale_price * weight
        total_weight += weight
        evidence.append(CompDecision(comp.listing_id, True, "accepted_valid_comp", comp.total_sale_price, weight))
    median_price = Decimal(str(median([c.total_sale_price for c in accepted])))
    weighted_price = weighted_sum / total_weight if total_weight else median_price
    bands = calculate_valuation_bands(weighted_price, target_mult)
    volume_factor = min(len(accepted) / 12, 1.0)
    avg_similarity = sum(c.title_similarity for c in accepted) / len(accepted)
    exact_matches = sum(1 for c in accepted if c.exact_model_match)
    exact_match_factor = min(exact_matches / 5, 1.0)
    confidence = min(max(volume_factor * 0.40 + avg_similarity * 0.35 + exact_match_factor * 0.25, 0), 1)
    return CompResult(
        raw_count=len(comps),
        accepted_count=len(accepted),
        rejected_count=len(comps) - len(accepted),
        median_price=median_price.quantize(Decimal("0.01")),
        weighted_price=weighted_price.quantize(Decimal("0.01")),
        conservative_resale=bands.conservative,
        confidence_score=round(confidence, 4),
        evidence=evidence,
        bands=bands,
    )
