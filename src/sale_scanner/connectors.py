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
