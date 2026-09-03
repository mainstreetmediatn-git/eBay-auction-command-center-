from decimal import Decimal

from sale_scanner.connectors import NormalizedListing, SearchResult
from sale_scanner.runtime import ActiveEbayCompProvider, _comp_query, _normalize_title


def listing(listing_id, title, price):
    return NormalizedListing(
        listing_id=listing_id,
        connector_id="ebay",
        platform="eBay",
        listing_type="BUY_IT_NOW",
        title=title,
        listing_url="https://example.test/item",
        current_price=Decimal(price),
        shipping_cost=Decimal("0"),
        currency="USD",
        condition="GOOD",
        condition_id=None,
        seller_id=None,
        seller_feedback_score=100,
        seller_feedback_percentage=Decimal("99.0"),
        seller_location=None,
        bid_count=0,
        end_time_iso=None,
        thumbnail_url=None,
        category_ids=[],
        buying_options=["FIXED_PRICE"],
        raw_payload={},
    )


class FakeConnector:
    def __init__(self, listings):
        self.listings = listings
        self.calls = []

    def search(self, query, **kwargs):
        self.calls.append((query, kwargs))
        return SearchResult(listings=self.listings, total=len(self.listings), next_url=None, warnings=[])


def test_comp_provider_excludes_source_and_bad_similarity():
    source = listing("ebay_1", "Dell OptiPlex 9020 i5 8GB Desktop", "40")
    connector = FakeConnector([
        source,
        listing("ebay_2", "Dell OptiPlex 9020 i5 16GB Desktop", "95"),
        listing("ebay_3", "Vintage Ceramic Flower Vase", "1000"),
    ])
    provider = ActiveEbayCompProvider(connector)
    comps = provider.get_comps(source, object())
    assert [c.listing_id for c in comps] == ["ebay_2"]
    assert connector.calls[0][1]["filter_expression"] == "buyingOptions:{FIXED_PRICE}"


def test_title_helpers_are_stable():
    assert _normalize_title("Dell OptiPlex-9020 / i5") == "dell optiplex 9020 i5"
    assert _comp_query("NEW Dell OptiPlex 9020 with i5 Free Shipping") == "Dell OptiPlex 9020 i5"
