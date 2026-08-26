from decimal import Decimal
from sale_scanner.ebay import EbayConfig, EbayConnector


def connector() -> EbayConnector:
    return EbayConnector(EbayConfig(client_id="test-id", client_secret="test-secret"))


def test_normalizes_auction_item_summary():
    item = {
        "itemId": "v1|195847382011|0",
        "legacyItemId": "195847382011",
        "title": "Dell OptiPlex 7060 SFF i7 16GB - No SSD",
        "itemWebUrl": "https://www.ebay.com/itm/195847382011",
        "buyingOptions": ["AUCTION"],
        "currentBidPrice": {"value": "72.50", "currency": "USD"},
        "shippingOptions": [{"shippingCost": {"value": "14.99", "currency": "USD"}}],
        "condition": "Used",
        "conditionId": "3000",
        "bidCount": 4,
        "itemEndDate": "2026-08-24T20:45:00.000Z",
        "seller": {"username": "seller123", "feedbackScore": 451, "feedbackPercentage": "99.8"},
    }
    result = connector().normalize_item_summary(item)
    assert result.listing_id == "ebay_195847382011"
    assert result.current_price == Decimal("72.50")
    assert result.bid_count == 4


def test_normalizes_fixed_price_and_uses_lowest_shipping():
    item = {
        "itemId": "v1|123|0",
        "title": "Ryzen 7 2700 CPU",
        "itemWebUrl": "https://www.ebay.com/itm/123",
        "buyingOptions": ["FIXED_PRICE", "BEST_OFFER"],
        "price": {"value": "64.00", "currency": "USD"},
        "shippingOptions": [
            {"shippingCost": {"value": "12.00", "currency": "USD"}},
            {"shippingCost": {"value": "8.50", "currency": "USD"}},
        ],
    }
    result = connector().normalize_item_summary(item)
    assert result.listing_id == "ebay_v1|123|0"
    assert result.listing_type == "BUY_IT_NOW"
    assert result.shipping_cost == Decimal("8.50")


def test_search_normalizes_mock_api_response(monkeypatch):
    c = connector()
    monkeypatch.setattr(
        c,
        "_request_json",
        lambda method, url: {
            "total": 1,
            "next": "https://api.ebay.com/next",
            "itemSummaries": [
                {
                    "itemId": "v1|999|0",
                    "title": "Test GPU",
                    "buyingOptions": ["AUCTION"],
                    "currentBidPrice": {"value": "100", "currency": "USD"},
                    "bidCount": 2,
                    "itemEndDate": "2026-08-25T00:00:00.000Z",
                }
            ],
        },
    )
    result = c.search("test gpu", limit=25, sort="endingSoonest")
    assert result.total == 1
    assert result.listings[0].listing_type == "AUCTION"
    assert result.listings[0].current_price == Decimal("100.00")
