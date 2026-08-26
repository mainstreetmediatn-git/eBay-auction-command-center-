from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, Optional

@dataclass(frozen=True)
class SavedSearch:
    search_id: str
    connector_id: str
    query: str
    enabled: bool = True
    poll_interval_seconds: int = 300
    max_price: Optional[Decimal] = None
    category_id: Optional[str] = None
    filters: Dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class ListingChange:
    search_id: str
    listing_id: str
    change_type: str
    previous_fingerprint: Optional[str]
    current_fingerprint: str
