from __future__ import annotations

import json
import os
import re
from dataclasses import asdict
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Sequence
from urllib.request import Request, urlopen

from .dispatcher import DispatchCandidate, QualifiedDealDispatcher
from .ebay import EbayConnector
from .evaluation_pipeline import ListingEvaluationPipeline
from .models import Comp
from .saved_search_poller import SavedSearchPoller


class ActiveEbayCompProvider:
    """Fallback comp provider using current eBay asking prices.

    eBay Browse does not expose completed-sale history. These comps are therefore
    deliberately down-weighted by title similarity and should be treated as a
    conservative bootstrap source until a sold-comps provider is configured.
    """

    def __init__(self, connector: EbayConnector, *, limit: int = 30):
        self.connector = connector
        self.limit = max(5, min(int(limit), 100))

    def get_comps(self, listing, search) -> Sequence[Comp]:
        query = _comp_query(listing.title)
        result = self.connector.search(
            query,
            limit=self.limit,
            filter_expression="buyingOptions:{FIXED_PRICE}",
            sort="price",
        )
        source_title = _normalize_title(listing.title)
        comps: list[Comp] = []
        for candidate in result.listings:
            if candidate.listing_id == listing.listing_id:
                continue
            if candidate.current_price <= 0:
                continue
            candidate_title = _normalize_title(candidate.title)
            similarity = SequenceMatcher(None, source_title, candidate_title).ratio()
            if similarity < 0.35:
                continue
            comps.append(
                Comp(
                    listing_id=candidate.listing_id,
                    sold_price=candidate.current_price,
                    shipping=candidate.shipping_cost,
                    sold_days_ago=30,
                    condition_grade=(candidate.condition or "GOOD").upper(),
                    title_similarity=similarity,
                    exact_model_match=source_title == candidate_title,
                )
            )
        return comps


class ConsoleDispatchChannel:
    channel_id = "console"

    def send(self, candidate: DispatchCandidate) -> None:
        profit = candidate.expected_net_profit if candidate.expected_net_profit is not None else Decimal("0")
        ceiling = candidate.normal_ceiling or candidate.safe_ceiling or candidate.aggressive_ceiling
        print(
            f"[{candidate.decision_state}] {candidate.title} | "
            f"price=${candidate.current_price} | profit=${profit} | ceiling={ceiling} | "
            f"{candidate.listing_url or ''}"
        )


class WebhookDispatchChannel:
    def __init__(self, url: str, *, timeout_seconds: int = 10):
        if not url.startswith(("https://", "http://")):
            raise ValueError("webhook URL must start with http:// or https://")
        self.url = url
        self.timeout_seconds = timeout_seconds
        self.channel_id = "webhook:" + re.sub(r"[^a-zA-Z0-9_.-]", "_", url)[:96]

    def send(self, candidate: DispatchCandidate) -> None:
        payload = asdict(candidate)
        for key, value in list(payload.items()):
            if isinstance(value, Decimal):
                payload[key] = str(value)
        req = Request(
            self.url,
            data=json.dumps(payload, default=str).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", "User-Agent": "sale-scanner-agent/1.0"},
        )
        with urlopen(req, timeout=self.timeout_seconds) as response:
            if getattr(response, "status", 200) >= 400:
                raise RuntimeError(f"webhook returned HTTP {response.status}")


class SaleScannerAgent:
    def __init__(self, repository, connector: EbayConnector, *, min_expected_profit: Decimal = Decimal("50")):
        self.repository = repository
        self.connector = connector
        comp_provider = ActiveEbayCompProvider(connector)
        self.pipeline = ListingEvaluationPipeline(
            repository,
            comp_provider,
            min_profit=min_expected_profit,
        )
        self.poller = SavedSearchPoller(
            repository,
            {connector.connector_id: connector},
            self.pipeline,
        )
        channels = [ConsoleDispatchChannel()]
        webhook_url = os.getenv("DEAL_WEBHOOK_URL", "").strip()
        if webhook_url:
            channels.append(WebhookDispatchChannel(webhook_url))
        self.dispatcher = QualifiedDealDispatcher(
            repository,
            channels,
            min_expected_profit=min_expected_profit,
        )

    def run_once(self, *, search_limit: int = 25, dispatch_limit: int = 50) -> dict[str, int]:
        evaluated = self.poller.run_once(limit=search_limit)
        dispatched = self.dispatcher.run_once(limit_per_channel=dispatch_limit)
        return {"evaluated": evaluated, "dispatched": dispatched}


def _normalize_title(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def _comp_query(title: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9._+-]*", title)
    stop = {"new", "used", "sale", "free", "shipping", "lot", "with", "for", "the", "and"}
    selected = [token for token in tokens if token.lower() not in stop]
    return " ".join(selected[:10]) or title.strip()
