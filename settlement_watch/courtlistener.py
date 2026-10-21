from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests

from settlement_watch.models import DocketRecord, WatchTarget

SEARCH_URL = "https://www.courtlistener.com/api/rest/v4/search/"
USER_AGENT = (
    "SettlementWatch/1.0 "
    "(public-docket screening tool; respectful sequential requests)"
)
DEFAULT_MAX_PER_NAME = 25
MIN_INTERVAL_SECONDS = 1.25


class CourtListenerError(RuntimeError):
    pass


class CourtListenerClient:
    def __init__(
        self,
        token: str | None = None,
        session: requests.Session | None = None,
        timeout: float = 45.0,
    ) -> None:
        self.token = (token or "").strip() or None
        self.timeout = timeout
        self._session = session or requests.Session()
        self._last_request = 0.0
        self._session.headers.update({"User-Agent": USER_AGENT})
        if self.token:
            self._session.headers["Authorization"] = f"Token {self.token}"

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < MIN_INTERVAL_SECONDS:
            time.sleep(MIN_INTERVAL_SECONDS - elapsed)

    def _get(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._throttle()
        try:
            response = self._session.get(url, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise CourtListenerError(f"Network error talking to CourtListener: {exc}") from exc
        self._last_request = time.monotonic()
        if response.status_code in {401, 403}:
            raise CourtListenerError(
                "CourtListener refused the request (HTTP "
                f"{response.status_code}). Get a free API token at "
                "https://www.courtlistener.com/help/api/rest/ and pass it with "
                "--token or COURT_LISTENER_TOKEN."
            )
        if response.status_code == 429:
            retry_after = float(response.headers.get("Retry-After", "15"))
            time.sleep(min(retry_after, 60))
            return self._get(url, params=params)
        if not response.ok:
            raise CourtListenerError(
                f"CourtListener HTTP {response.status_code}: {response.text[:300]}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise CourtListenerError("CourtListener returned non-JSON.") from exc
        if not isinstance(payload, dict):
            raise CourtListenerError("Unexpected CourtListener payload.")
        return payload

    def search_dockets(
        self,
        target: WatchTarget,
        max_per_name: int = DEFAULT_MAX_PER_NAME,
    ) -> list[DocketRecord]:
        found: dict[str, DocketRecord] = {}
        for query_name in target.query_names():
            remaining = max_per_name - len(found)
            if remaining <= 0:
                break
            for params in _query_variants(query_name):
                self._collect(params, found, remaining)
                remaining = max_per_name - len(found)
                if remaining <= 0:
                    break
        return list(found.values())

    def _collect(
        self,
        params: dict[str, str],
        found: dict[str, DocketRecord],
        limit: int,
    ) -> None:
        url: str | None = SEARCH_URL
        query_params: dict[str, Any] | None = dict(params)
        while url and len(found) < limit:
            payload = self._get(url, query_params)
            query_params = None
            results = payload.get("results") or []
            if not isinstance(results, list):
                break
            for row in results:
                if not isinstance(row, dict):
                    continue
                record = DocketRecord.from_api(row)
                if record.docket_id and record.docket_id not in found:
                    found[record.docket_id] = record
                if len(found) >= limit:
                    break
            url = payload.get("next")
            if not url:
                break


def _query_variants(name: str) -> list[dict[str, str]]:
    quoted = f'"{name}"'
    return [
        {
            "type": "r",
            "party_name": name,
            "order_by": "dateFiled desc",
        },
        {
            "type": "r",
            "party_name": name,
            "q": "settlement OR \"consent judgment\" OR stipulation",
            "order_by": "score desc",
        },
        {
            "type": "d",
            "q": quoted,
            "order_by": "dateFiled desc",
        },
    ]


def load_demo_dockets(path: str | Path) -> list[DocketRecord]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Demo fixture must be a JSON list of dockets.")
    return [DocketRecord.from_api(row) for row in payload if isinstance(row, dict)]


def demo_search(
    target: WatchTarget,
    dockets: list[DocketRecord],
) -> list[DocketRecord]:
    from settlement_watch.scoring import name_appears

    return [docket for docket in dockets if name_appears(target, docket)]
