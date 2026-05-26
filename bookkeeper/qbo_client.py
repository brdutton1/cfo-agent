"""
Thin HTTP wrapper around the QBO REST API.
Handles auth headers, base URL, error parsing, and rate-limit retries.
"""

import time
from typing import Any

import requests

from .config import Config


class QBOError(Exception):
    def __init__(self, status: int, message: str, fault: dict | None = None):
        super().__init__(message)
        self.status = status
        self.fault = fault


class QBOClient:
    def __init__(self, config: Config, access_token: str):
        self._base = config.api_base_url
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        })

    def _request(self, method: str, path: str, **kwargs) -> dict:
        url = f"{self._base}{path}"
        max_attempts = 4
        backoff = 2

        for attempt in range(max_attempts):
            resp = self._session.request(method, url, timeout=30, **kwargs)

            if resp.status_code == 429:
                if attempt < max_attempts - 1:
                    time.sleep(backoff ** attempt)
                    continue
                raise QBOError(429, "Rate limit exceeded after retries")

            if not resp.ok:
                fault = None
                try:
                    body = resp.json()
                    fault = body.get("Fault")
                    msg = fault["Error"][0]["Message"] if fault else resp.text
                except Exception:
                    msg = resp.text
                raise QBOError(resp.status_code, msg, fault)

            try:
                return resp.json()
            except Exception:
                return {}

        raise QBOError(0, "Max retry attempts exceeded")

    def get(self, path: str, params: dict | None = None) -> dict:
        return self._request("GET", path, params=params)

    def post(self, path: str, body: dict) -> dict:
        return self._request("POST", path, json=body)

    def query(self, sql: str) -> list[dict]:
        """Run a QBO query and return all rows, handling pagination."""
        results = []
        start = 1
        page_size = 200

        while True:
            paginated = f"{sql} STARTPOSITION {start} MAXRESULTS {page_size}"
            data = self.get("/query", params={"query": paginated, "minorversion": 65})
            qr = data.get("QueryResponse", {})

            # The entity name is the only key besides totalCount / startPosition
            entity_key = next(
                (k for k in qr if k not in ("totalCount", "startPosition", "maxResults")),
                None,
            )
            if not entity_key:
                break

            page = qr[entity_key]
            results.extend(page)

            if len(page) < page_size:
                break
            start += page_size

        return results
