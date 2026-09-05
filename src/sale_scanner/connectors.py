from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional

@dataclass
class NormalizedListing:
    listing_id: str
    connector_id: str
    platform: str
    listing_type: str
    title: str
    listing_url: str
    current_price: Decimal
    shipping_cost: Decimal = Decimal("0")
    currency: str = "USD"
    condition: Optional[str] = None
    condition_id: Optional[str] = None
    seller_id: Optional[str] = None
    seller_feedback_score: Optional[int] = None
    seller_feedback_percentage: Optional[Decimal] = None
    seller_location: Optional[str] = None
    bid_count: int = 0
    end_time_iso: Optional[str] = None
    thumbnail_url: Optional[str] = None
    category_ids: List[str] = field(default_factory=list)
    buying_options: List[str] = field(default_factory=list)
    # Rich marketplace presentation fields. These intentionally preserve the
    # information a shopper sees in marketplace search results instead of
    # flattening the listing down to valuation-only attributes.
    subtitle: Optional[str] = None
    original_price: Optional[Decimal] = None
    price_display: Optional[str] = None
    shipping_display: Optional[str] = None
    delivery_display: Optional[str] = None
    image_urls: List[str] = field(default_factory=list)
    item_location_country: Optional[str] = None
    seller_top_rated: Optional[bool] = None
    seller_store_name: Optional[str] = None
    priority_listing: Optional[bool] = None
    best_offer_enabled: bool = False
    raw_payload: Dict[str, Any] = field(default_factory=dict)

@dataclass
class SearchResult:
    listings: List[NormalizedListing]
    total: Optional[int] = None
    next_url: Optional[str] = None
    warnings: List[Dict[str, Any]] = field(default_factory=list)

class MarketplaceConnector(ABC):
    connector_id: str
    platform: str

    @abstractmethod
    def search(self, query: str, *, limit: int = 50, **kwargs: Any) -> SearchResult:
        raise NotImplementedError
