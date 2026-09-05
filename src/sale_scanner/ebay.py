from __future__ import annotations
import base64
import json
import os
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from .connectors import MarketplaceConnector, NormalizedListing, SearchResult

class EbayConnectorError(RuntimeError):
    pass

class EbayAuthenticationError(EbayConnectorError):
    pass

class EbayRateLimitError(EbayConnectorError):
    pass

@dataclass
class EbayConfig:
    client_id: str
    client_secret: str
    marketplace_id: str = "EBAY_US"
    environment: str = "production"
    timeout_seconds: int = 20
    max_retries: int = 3
    retry_backoff_seconds: float = 1.0

    @classmethod
    def from_env(cls) -> "EbayConfig":
        client_id = os.getenv("EBAY_CLIENT_ID", "").strip()
        client_secret = os.getenv("EBAY_CLIENT_SECRET", "").strip()
        if not client_id or not client_secret:
            raise EbayAuthenticationError("EBAY_CLIENT_ID and EBAY_CLIENT_SECRET must be configured")
        return cls(
            client_id=client_id,
            client_secret=client_secret,
            marketplace_id=os.getenv("EBAY_MARKETPLACE_ID", "EBAY_US"),
            environment=os.getenv("EBAY_ENVIRONMENT", "production"),
            timeout_seconds=int(os.getenv("EBAY_TIMEOUT_SECONDS", "20")),
            max_retries=int(os.getenv("EBAY_MAX_RETRIES", "3")),
            retry_backoff_seconds=float(os.getenv("EBAY_RETRY_BACKOFF_SECONDS", "1.0")),
        )

@dataclass
class _Token:
    access_token: str
    expires_at: float

class EbayConnector(MarketplaceConnector):
    connector_id = "ebay"
    platform = "eBay"
    OAUTH_SCOPE = "https://api.ebay.com/oauth/api_scope"

    def __init__(self, config: EbayConfig):
        self.config = config
        self._token: Optional[_Token] = None

    @property
    def api_base(self) -> str:
        return "https://api.sandbox.ebay.com" if self.config.environment.lower() == "sandbox" else "https://api.ebay.com"

    @property
    def token_url(self) -> str:
        return f"{self.api_base}/identity/v1/oauth2/token"

    def search(self, query: str, *, limit: int = 50, offset: int = 0, category_ids: Optional[List[str]] = None, filter_expression: Optional[str] = None, sort: Optional[str] = None, fieldgroups: Optional[str] = None, **_: Any) -> SearchResult:
        if not query.strip() and not category_ids:
            raise ValueError("query or category_ids is required")
        if limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        if offset < 0:
            raise ValueError("offset must be >= 0")
        params: Dict[str, str] = {"q": query.strip(), "limit": str(limit), "offset": str(offset)}
        if category_ids:
            params["category_ids"] = ",".join(category_ids)
        if filter_expression:
            params["filter"] = filter_expression
        if sort:
            params["sort"] = sort
        if fieldgroups:
            params["fieldgroups"] = fieldgroups
        payload = self._request_json("GET", f"{self.api_base}/buy/browse/v1/item_summary/search?{urlencode(params)}")
        return SearchResult(
            listings=[self.normalize_item_summary(i) for i in payload.get("itemSummaries", [])],
            total=_safe_int(payload.get("total")),
            next_url=payload.get("next"),
            warnings=payload.get("warnings") or [],
        )

    def normalize_item_summary(self, item: Mapping[str, Any]) -> NormalizedListing:
        buying_options = list(item.get("buyingOptions") or [])
        listing_type = self._listing_type(buying_options)
        price_obj = item.get("currentBidPrice") if "AUCTION" in buying_options else item.get("price")
        price_obj = price_obj or item.get("price") or item.get("currentBidPrice") or {}
        original_price_obj = item.get("marketingPrice", {}).get("originalPrice") or {}
        seller = item.get("seller") or {}
        location = item.get("itemLocation") or {}
        image = item.get("image") or {}
        categories = item.get("categories") or []
        stable_source_id = str(item.get("legacyItemId") or item.get("itemId") or "")
        if not stable_source_id:
            raise EbayConnectorError("eBay item payload missing item identifier")

        shipping_cost = self._extract_shipping(item)
        image_urls = []
        if image.get("imageUrl"):
            image_urls.append(str(image["imageUrl"]))
        for additional in item.get("additionalImages") or []:
            url = additional.get("imageUrl")
            if url and url not in image_urls:
                image_urls.append(str(url))

        shipping_display = "Free shipping" if shipping_cost == 0 else f"+ ${shipping_cost:.2f} shipping"
        current_price = _money(price_obj.get("value"))
        price_display = f"${current_price:.2f}"
        if listing_type == "AUCTION":
            price_display = f"${current_price:.2f} current bid"

        store = seller.get("sellerStoreName") or seller.get("storeName")
        return NormalizedListing(
            listing_id=f"ebay_{stable_source_id}",
            connector_id=self.connector_id,
            platform=self.platform,
            listing_type=listing_type,
            title=str(item.get("title") or "").strip(),
            listing_url=str(item.get("itemWebUrl") or item.get("itemAffiliateWebUrl") or ""),
            current_price=current_price,
            shipping_cost=shipping_cost,
            currency=str(price_obj.get("currency") or "USD"),
            condition=item.get("condition"),
            condition_id=_optional_str(item.get("conditionId")),
            seller_id=_optional_str(seller.get("username")),
            seller_feedback_score=_safe_int(seller.get("feedbackScore")),
            seller_feedback_percentage=_optional_decimal(seller.get("feedbackPercentage")),
            seller_location=_format_location(location),
            bid_count=_safe_int(item.get("bidCount")) or 0,
            end_time_iso=_optional_str(item.get("itemEndDate")),
            thumbnail_url=_optional_str(image.get("imageUrl")),
            category_ids=[str(c.get("categoryId")) for c in categories if c.get("categoryId")],
            buying_options=buying_options,
            subtitle=_optional_str(item.get("subtitle") or item.get("shortDescription")),
            original_price=_optional_money(original_price_obj.get("value")),
            price_display=price_display,
            shipping_display=shipping_display,
            delivery_display=self._delivery_display(item),
            image_urls=image_urls,
            item_location_country=_optional_str(location.get("country")),
            seller_top_rated=bool(seller.get("topRatedSeller")) if "topRatedSeller" in seller else None,
            seller_store_name=_optional_str(store),
            priority_listing=bool(item.get("priorityListing")) if "priorityListing" in item else None,
            best_offer_enabled="BEST_OFFER" in buying_options,
            raw_payload=dict(item),
        )

    def _listing_type(self, buying_options: List[str]) -> str:
        options = set(buying_options)
        if "AUCTION" in options:
            return "AUCTION"
        if "FIXED_PRICE" in options:
            return "BUY_IT_NOW"
        if "BEST_OFFER" in options:
            return "BEST_OFFER"
        if "CLASSIFIED_AD" in options:
            return "CLASSIFIED"
        return "UNKNOWN"

    def _extract_shipping(self, item: Mapping[str, Any]) -> Decimal:
        prices = []
        for option in item.get("shippingOptions") or []:
            shipping_cost = option.get("shippingCost") or {}
            if shipping_cost.get("value") is not None:
                prices.append(_money(shipping_cost.get("value")))
        return min(prices) if prices else Decimal("0")

    def _delivery_display(self, item: Mapping[str, Any]) -> Optional[str]:
        options = item.get("shippingOptions") or []
        if not options:
            return None
        option = options[0]
        min_date = option.get("minEstimatedDeliveryDate")
        max_date = option.get("maxEstimatedDeliveryDate")
        if min_date and max_date:
            return f"Estimated delivery {min_date} – {max_date}"
        if min_date:
            return f"Estimated delivery from {min_date}"
        return None

    def _get_access_token(self) -> str:
        now = time.time()
        if self._token and now < self._token.expires_at - 60:
            return self._token.access_token
        basic = base64.b64encode(f"{self.config.client_id}:{self.config.client_secret}".encode()).decode()
        req = Request(
            self.token_url,
            data=urlencode({"grant_type": "client_credentials", "scope": self.OAUTH_SCOPE}).encode(),
            method="POST",
            headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urlopen(req, timeout=self.config.timeout_seconds) as resp:
                payload = json.loads(resp.read().decode())
        except HTTPError as exc:
            raise EbayAuthenticationError(f"eBay OAuth token request failed with HTTP {exc.code}: {exc.read().decode(errors='replace')}") from exc
        except URLError as exc:
            raise EbayAuthenticationError(f"eBay OAuth request failed: {exc.reason}") from exc
        access_token = payload.get("access_token")
        if not access_token:
            raise EbayAuthenticationError("eBay OAuth response did not contain access_token")
        self._token = _Token(str(access_token), now + int(payload.get("expires_in", 7200)))
        return self._token.access_token

    def _request_json(self, method: str, url: str) -> Dict[str, Any]:
        last_error: Optional[BaseException] = None
        for attempt in range(self.config.max_retries + 1):
            req = Request(
                url,
                method=method,
                headers={"Authorization": f"Bearer {self._get_access_token()}", "Accept": "application/json", "X-EBAY-C-MARKETPLACE-ID": self.config.marketplace_id},
            )
            try:
                with urlopen(req, timeout=self.config.timeout_seconds) as resp:
                    return json.loads(resp.read().decode())
            except HTTPError as exc:
                last_error = exc
                detail = exc.read().decode(errors="replace")
                if exc.code == 401 and attempt < self.config.max_retries:
                    self._token = None
                    continue
                if exc.code == 429:
                    if attempt < self.config.max_retries:
                        self._sleep_backoff(attempt, exc.headers.get("Retry-After"))
                        continue
                    raise EbayRateLimitError("eBay API rate limit exceeded") from exc
                if 500 <= exc.code < 600 and attempt < self.config.max_retries:
                    self._sleep_backoff(attempt)
                    continue
                raise EbayConnectorError(f"eBay API request failed with HTTP {exc.code}: {detail}") from exc
            except URLError as exc:
                last_error = exc
                if attempt < self.config.max_retries:
                    self._sleep_backoff(attempt)
                    continue
                raise EbayConnectorError(f"eBay API request failed: {exc.reason}") from exc
        raise EbayConnectorError(f"eBay request exhausted retries: {last_error}")

    def _sleep_backoff(self, attempt: int, retry_after: Optional[str] = None) -> None:
        try:
            delay = float(retry_after) if retry_after else self.config.retry_backoff_seconds * (2 ** attempt)
        except ValueError:
            delay = self.config.retry_backoff_seconds * (2 ** attempt)
        time.sleep(max(0, delay))

def _money(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise EbayConnectorError(f"invalid monetary value from eBay: {value!r}") from exc

def _optional_money(value: Any) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    return _money(value)

def _optional_decimal(value: Any) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None

def _safe_int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None

def _optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    value = str(value).strip()
    return value or None

def _format_location(location: Mapping[str, Any]) -> Optional[str]:
    rendered = ", ".join(str(p).strip() for p in [location.get("city"), location.get("stateOrProvince"), location.get("postalCode"), location.get("country")] if p)
    return rendered or None
