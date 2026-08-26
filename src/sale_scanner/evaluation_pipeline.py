from __future__ import annotations
from dataclasses import asdict
from decimal import Decimal
from typing import Protocol, Sequence
from .auction import evaluate_auction
from .comp_engine import evaluate_comps
from .financial import evaluate_listing_economics
from .models import AuctionSnapshot, Comp, FinancialInputs
from .search_models import ListingChange, SavedSearch


class CompProvider(Protocol):
    def get_comps(self, listing, search: SavedSearch) -> Sequence[Comp]: ...


class ListingEvaluationPipeline:
    def __init__(self, repository, comp_provider: CompProvider, *, outbound_shipping=Decimal("15"), marketplace_fee_pct=Decimal("0.13"), processing_fee_flat=Decimal("0.30"), return_reserve=Decimal("10"), min_profit=Decimal("50")):
        self.repository = repository
        self.comp_provider = comp_provider
        self.outbound_shipping = Decimal(outbound_shipping)
        self.marketplace_fee_pct = Decimal(marketplace_fee_pct)
        self.processing_fee_flat = Decimal(processing_fee_flat)
        self.return_reserve = Decimal(return_reserve)
        self.min_profit = Decimal(min_profit)

    def __call__(self, search: SavedSearch, change: ListingChange, listing) -> None:
        comps = list(self.comp_provider.get_comps(listing, search))
        comp_result = evaluate_comps(comps, (listing.condition or "GOOD").upper())
        self.repository.save_comp_result(listing.listing_id, comp_result)
        if comp_result.bands is None:
            self.repository.append_fixed_price_decision(listing.listing_id, "PASS", 0.0, Decimal("0"), {"reason": "no_valid_comps", "change": asdict(change)})
            return
        fin = FinancialInputs(
            purchase_price=listing.current_price,
            inbound_shipping=listing.shipping_cost,
            sales_tax=Decimal("0"),
            immediate_repair_cost=Decimal("0"),
            conservative_resale_price=comp_result.bands.conservative,
            outbound_shipping=self.outbound_shipping,
            resale_marketplace_fee_pct=self.marketplace_fee_pct,
            payment_processing_fee_flat=self.processing_fee_flat,
            return_risk_reserve=self.return_reserve,
            min_acceptable_profit=self.min_profit,
        )
        economics = evaluate_listing_economics(fin, comp_result.confidence_score, listing.seller_feedback_score or 0)
        if listing.listing_type == "AUCTION" and listing.end_time_iso:
            auction = evaluate_auction(
                AuctionSnapshot(listing.listing_id, listing.current_price, listing.shipping_cost, Decimal("0"), listing.end_time_iso, listing.bid_count),
                comp_result.bands,
                outbound_shipping=self.outbound_shipping,
                resale_marketplace_fee_pct=self.marketplace_fee_pct,
                payment_processing_fee_flat=self.processing_fee_flat,
                return_risk_reserve=self.return_reserve,
                immediate_repair_cost=Decimal("0"),
                min_acceptable_profit=self.min_profit,
                confidence_score=comp_result.confidence_score,
            )
            self.repository.append_decision(auction, confidence_score=comp_result.confidence_score, expected_net_profit=economics.expected_net_profit)
        else:
            self.repository.append_fixed_price_decision(
                listing.listing_id,
                economics.decision,
                comp_result.confidence_score,
                economics.expected_net_profit,
                {"change": asdict(change), "economics": asdict(economics), "bands": asdict(comp_result.bands)},
            )
