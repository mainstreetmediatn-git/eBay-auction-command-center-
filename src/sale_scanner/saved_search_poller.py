from __future__ import annotations
import hashlib
import json
from decimal import Decimal
from typing import Callable, Mapping
from .connectors import MarketplaceConnector, NormalizedListing
from .search_models import ListingChange, SavedSearch


def listing_fingerprint(listing: NormalizedListing) -> str:
    payload = {
        "listing_id": listing.listing_id,
        "current_price": str(listing.current_price),
        "shipping_cost": str(listing.shipping_cost),
        "bid_count": listing.bid_count,
        "end_time_iso": listing.end_time_iso,
        "condition": listing.condition,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class SavedSearchPoller:
    def __init__(
        self,
        repository,
        connectors: Mapping[str, MarketplaceConnector],
        evaluation_callback: Callable[[SavedSearch, ListingChange, NormalizedListing], None],
    ):
        self.repository = repository
        self.connectors = connectors
        self.evaluation_callback = evaluation_callback

    def run_once(self, *, limit: int = 25) -> int:
        processed = 0
        for search in self.repository.claim_due_saved_searches(limit=limit):
            connector = self.connectors.get(search.connector_id)
            if connector is None:
                self.repository.mark_saved_search_polled(search.search_id, success=False, error=f"unknown connector: {search.connector_id}")
                continue
            try:
                kwargs = dict(search.filters)
                if search.category_id:
                    kwargs["category_ids"] = [search.category_id]
                result = connector.search(search.query, limit=50, **kwargs)
                for listing in result.listings:
                    if search.max_price is not None and listing.current_price > Decimal(search.max_price):
                        continue
                    fingerprint = listing_fingerprint(listing)
                    previous = self.repository.get_search_listing_fingerprint(search.search_id, listing.listing_id)
                    change_type = "NEW" if previous is None else "CHANGED" if previous != fingerprint else "UNCHANGED"
                    self.repository.ingest_listing(listing)
                    self.repository.record_search_listing_fingerprint(search.search_id, listing.listing_id, fingerprint)
                    if change_type != "UNCHANGED":
                        self.evaluation_callback(
                            search,
                            ListingChange(search.search_id, listing.listing_id, change_type, previous, fingerprint),
                            listing,
                        )
                        processed += 1
                self.repository.mark_saved_search_polled(search.search_id, success=True)
            except Exception as exc:
                self.repository.mark_saved_search_polled(search.search_id, success=False, error=str(exc))
        return processed
