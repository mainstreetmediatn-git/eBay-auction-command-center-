from __future__ import annotations

import json
import os
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Mapping, Optional
from urllib.parse import quote_plus

from .connectors import NormalizedListing, SearchResult
from .ebay import EbayConfig, EbayConnector


class TinyFishBrowserError(RuntimeError):
    pass


class TinyFishEbayEnricher:
    """Browser-level eBay enrichment using TinyFish.

    The official eBay Browse API remains the primary source of stable listing
    identifiers and structured commerce data. TinyFish is used to reproduce the
    buyer-visible search experience and fill fields that are absent, delayed, or
    rendered only in the browser.
    """

    def __init__(self, api_key: Optional[str] = None, *, browser_profile: str = "stealth"):
        self.api_key = (api_key or os.getenv("TINYFISH_API_KEY", "")).strip()
        self.browser_profile = browser_profile
        self.enabled = bool(self.api_key)

    def search_visible_listings(
        self,
        query: str,
        *,
        limit: int = 25,
        auctions_only: bool = False,
        ending_soonest: bool = False,
    ) -> List[Dict[str, Any]]:
        if not self.enabled:
            return []
        try:
            from tinyfish import TinyFish
        except ImportError as exc:
            raise TinyFishBrowserError(
                "TinyFish enrichment requested but the tinyfish package is not installed"
            ) from exc

        client = TinyFish(api_key=self.api_key)
        search_url = f"https://www.ebay.com/sch/i.html?_nkw={quote_plus(query)}"
        goal = (
            "Read the visible eBay search results like a shopper. "
            + ("Filter to Auction listings. " if auctions_only else "")
            + ("Sort by Time: ending soonest. " if ending_soonest else "")
            + f"Return up to {max(1, min(limit, 100))} visible listings as JSON. "
            "For each listing return title, url, image_url, price_text, shipping_text, "
            "bid_count, time_remaining, end_time, condition, seller, seller_feedback, "
            "buy_it_now, best_offer. Do not bid, watch, message, or purchase anything."
        )
        try:
            result = client.agent.run(
                url=search_url,
                goal=goal,
                browser_profile=self.browser_profile,
            )
        except Exception as exc:  # SDK errors vary by transport/version.
            raise TinyFishBrowserError(f"TinyFish browser run failed: {exc}") from exc

        payload = _coerce_result_payload(result)
        listings = payload.get("listings") if isinstance(payload, Mapping) else None
        if not isinstance(listings, list):
            return []
        return [dict(item) for item in listings if isinstance(item, Mapping)]


class HybridEbayConnector(EbayConnector):
    """eBay Browse API + TinyFish browser ingestion in one connector."""

    def __init__(
        self,
        config: EbayConfig,
        *,
        tinyfish: Optional[TinyFishEbayEnricher] = None,
        enrich_by_default: Optional[bool] = None,
    ):
        super().__init__(config)
        self.tinyfish = tinyfish or TinyFishEbayEnricher()
        if enrich_by_default is None:
            enrich_by_default = os.getenv("TINYFISH_EBAY_ENRICH", "1").strip().lower() not in {
                "0", "false", "no", "off"
            }
        self.enrich_by_default = bool(enrich_by_default)

    def search(self, query: str, *, limit: int = 50, **kwargs: Any) -> SearchResult:
        result = super().search(query, limit=limit, **kwargs)
        use_browser = kwargs.pop("browser_enrich", self.enrich_by_default)
        if not use_browser or not self.tinyfish.enabled:
            return result

        filter_expression = str(kwargs.get("filter_expression") or "")
        sort = kwargs.get("sort")
        auctions_only = "AUCTION" in filter_expression.upper()
        ending_soonest = str(sort or "").lower() == "endingsoonest"
        try:
            browser_rows = self.tinyfish.search_visible_listings(
                query,
                limit=limit,
                auctions_only=auctions_only,
                ending_soonest=ending_soonest,
            )
        except TinyFishBrowserError as exc:
            result.warnings.append({"source": "tinyfish", "message": str(exc)})
            return result

        merged = _merge_browser_rows(result.listings, browser_rows)
        return SearchResult(
            listings=merged,
            total=result.total,
            next_url=result.next_url,
            warnings=result.warnings,
        )


def _merge_browser_rows(
    api_listings: Iterable[NormalizedListing], browser_rows: Iterable[Mapping[str, Any]]
) -> List[NormalizedListing]:
    rows = list(browser_rows)
    by_url = {_canonical_url(str(row.get("url") or "")): row for row in rows if row.get("url")}
    by_title = {_title_key(str(row.get("title") or "")): row for row in rows if row.get("title")}

    merged: List[NormalizedListing] = []
    seen_browser_ids: set[int] = set()
    for listing in api_listings:
        row = by_url.get(_canonical_url(listing.listing_url)) or by_title.get(_title_key(listing.title))
        if row is None:
            merged.append(listing)
            continue
        seen_browser_ids.add(id(row))
        merged.append(_enrich_listing(listing, row))

    # Keep browser-only records instead of silently dropping them. These use a
    # deterministic synthetic id until the API observes the same listing.
    for row in rows:
        if id(row) in seen_browser_ids:
            continue
        title = str(row.get("title") or "").strip()
        url = str(row.get("url") or "").strip()
        if not title or not url:
            continue
        merged.append(_browser_only_listing(row))
    return merged


def _enrich_listing(listing: NormalizedListing, row: Mapping[str, Any]) -> NormalizedListing:
    shipping_text = _optional_str(row.get("shipping_text")) or listing.shipping_display
    price_text = _optional_str(row.get("price_text")) or listing.price_display
    return replace(
        listing,
        thumbnail_url=_optional_str(row.get("image_url")) or listing.thumbnail_url,
        image_urls=_prepend_unique(_optional_str(row.get("image_url")), listing.image_urls),
        price_display=price_text,
        shipping_display=shipping_text,
        condition=_optional_str(row.get("condition")) or listing.condition,
        seller_id=_optional_str(row.get("seller")) or listing.seller_id,
        bid_count=_safe_int(row.get("bid_count"), listing.bid_count),
        end_time_iso=_optional_str(row.get("end_time")) or listing.end_time_iso,
        best_offer_enabled=_safe_bool(row.get("best_offer"), listing.best_offer_enabled),
        raw_payload={
            **listing.raw_payload,
            "tinyfish_browser": dict(row),
            "tinyfish_time_remaining": _optional_str(row.get("time_remaining")),
            "tinyfish_seller_feedback": _optional_str(row.get("seller_feedback")),
        },
    )


def _browser_only_listing(row: Mapping[str, Any]) -> NormalizedListing:
    title = str(row.get("title") or "").strip()
    url = str(row.get("url") or "").strip()
    price = _parse_money(row.get("price_text"))
    image = _optional_str(row.get("image_url"))
    return NormalizedListing(
        listing_id=f"tinyfish_{abs(hash(url))}",
        connector_id="ebay",
        platform="eBay",
        listing_type="AUCTION" if _safe_int(row.get("bid_count"), 0) > 0 else "UNKNOWN",
        title=title,
        listing_url=url,
        current_price=price,
        shipping_cost=Decimal("0"),
        condition=_optional_str(row.get("condition")),
        seller_id=_optional_str(row.get("seller")),
        bid_count=_safe_int(row.get("bid_count"), 0),
        end_time_iso=_optional_str(row.get("end_time")),
        thumbnail_url=image,
        image_urls=[image] if image else [],
        price_display=_optional_str(row.get("price_text")),
        shipping_display=_optional_str(row.get("shipping_text")),
        best_offer_enabled=_safe_bool(row.get("best_offer"), False),
        raw_payload={"tinyfish_browser": dict(row), "browser_only": True},
    )


def _coerce_result_payload(result: Any) -> Mapping[str, Any]:
    candidates = [
        getattr(result, "result", None),
        getattr(result, "data", None),
        result,
    ]
    for value in candidates:
        if value is None:
            continue
        if hasattr(value, "model_dump"):
            value = value.model_dump()
        elif hasattr(value, "dict"):
            value = value.dict()
        if isinstance(value, Mapping):
            if isinstance(value.get("result"), Mapping):
                return value["result"]
            return value
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError:
                continue
            if isinstance(decoded, Mapping):
                return decoded
    return {}


def _canonical_url(value: str) -> str:
    return value.split("?", 1)[0].rstrip("/").lower()


def _title_key(value: str) -> str:
    return " ".join(value.lower().split())


def _optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    rendered = str(value).strip()
    return rendered or None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    return default


def _parse_money(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    text = str(value)
    filtered = "".join(ch for ch in text if ch.isdigit() or ch in ".-")
    try:
        return Decimal(filtered or "0").quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _prepend_unique(value: Optional[str], items: List[str]) -> List[str]:
    if not value:
        return list(items)
    return [value] + [item for item in items if item != value]
