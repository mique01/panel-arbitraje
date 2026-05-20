from __future__ import annotations

from typing import Any

import requests

from app.config import Settings
from app.marketdata.auth import PrimaryAuthClient


class PrimaryRestClient:
    def __init__(self, settings: Settings, auth_client: PrimaryAuthClient):
        self.settings = settings
        self.auth_client = auth_client
        self.session = requests.Session()

    def _headers(self) -> dict[str, str]:
        token = self.auth_client.get_valid_token()
        return {"X-Auth-Token": token}

    def get_instruments_detail(self) -> dict[str, Any]:
        response = self.session.get(
            f"{self.settings.primary_rest_url.rstrip('/')}/rest/instruments/details",
            headers=self._headers(),
            timeout=20,
        )
        response.raise_for_status()
        return response.json()

    def get_instruments_by_cfi(self, cfi_code: str) -> dict[str, Any]:
        response = self.session.get(
            f"{self.settings.primary_rest_url.rstrip('/')}/rest/instruments/byCFICode",
            headers=self._headers(),
            params={"CFICode": cfi_code},
            timeout=20,
        )
        response.raise_for_status()
        return response.json()

    def get_market_data(
        self,
        symbol: str,
        entries: list[str],
        depth: int,
        market_id: str | None = None,
    ) -> dict[str, Any]:
        response = self.session.get(
            f"{self.settings.primary_rest_url.rstrip('/')}/rest/marketdata/get",
            headers=self._headers(),
            params={
                "marketId": market_id or self.settings.primary_market_id,
                "symbol": symbol,
                "entries": ",".join(entries),
                "depth": depth,
            },
            timeout=20,
        )
        response.raise_for_status()
        return response.json()
