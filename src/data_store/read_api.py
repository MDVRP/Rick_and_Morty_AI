from __future__ import annotations

from typing import Any, Dict, List, Optional

import json
import time

import requests

from src.config import (
    GRAPHQL_URL,
    MAX_RETRIES,
    QUERY_FILE_PATH,
    REQUEST_HEADERS,
    REQUEST_TIMEOUT_SECONDS,
)


class LocationsReader:
    """
    Read locations and their residents from the Rick and Morty GraphQL API.
    """

    def __init__(self, graphql_url: Optional[str] = None) -> None:
        self.graphql_url: str = graphql_url or GRAPHQL_URL
        self.query: str = self._load_query(QUERY_FILE_PATH)
        self.session = requests.Session()

    def _load_query(self, path: str) -> str:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()

    def _execute(self, variables: Dict[str, Any]) -> Dict[str, Any]:
        attempt = 0
        while True:
            try:
                response = self.session.post(
                    self.graphql_url,
                    headers=REQUEST_HEADERS,
                    json={"query": self.query, "variables": variables},
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                data = response.json()
                if "errors" in data and data["errors"]:
                    raise RuntimeError(json.dumps(data["errors"]))
                if "data" not in data:
                    raise RuntimeError("No 'data' in GraphQL response")
                return data["data"]
            except (requests.RequestException, ValueError, RuntimeError) as exc:
                attempt += 1
                if attempt >= MAX_RETRIES:
                    raise
                # simple linear backoff
                time.sleep(0.5 * attempt)

    def fetch_locations_page(self, page: int = 1) -> Dict[str, Any]:
        payload = {"page": page}
        data = self._execute(payload)
        locations = data.get("locations") or {}
        return locations

    def fetch_all_locations(self) -> List[Dict[str, Any]]:
        page = 1
        all_results: List[Dict[str, Any]] = []
        while True:
            data = self.fetch_locations_page(page)
            results = data.get("results") or []
            all_results.extend(results)
            info = data.get("info") or {}
            next_page = info.get("next")
            if next_page is None:
                break
            page = next_page
        return all_results

