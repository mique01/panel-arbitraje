from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import requests

from app.config import Settings


@dataclass(slots=True)
class AuthState:
    token: str | None = None
    expires_at: datetime | None = None

    def valid(self) -> bool:
        return bool(self.token and self.expires_at and datetime.utcnow() < self.expires_at)


class PrimaryAuthClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.session = requests.Session()
        self.state = AuthState(token=settings.primary_auth_token or None)
        if self.state.token:
            self.state.expires_at = datetime.utcnow() + timedelta(hours=23)

    def get_valid_token(self, force_refresh: bool = False) -> str:
        if not force_refresh and self.state.valid():
            return str(self.state.token)
        return self.refresh_token()

    def refresh_token(self) -> str:
        if not self.settings.primary_username or not self.settings.primary_password:
            if self.settings.primary_auth_token:
                self.state.token = self.settings.primary_auth_token
                self.state.expires_at = datetime.utcnow() + timedelta(hours=23)
                return self.settings.primary_auth_token
            raise RuntimeError("Primary credentials are missing")
        response = self.session.post(
            f"{self.settings.primary_rest_url.rstrip('/')}/auth/getToken",
            headers={
                "X-Username": self.settings.primary_username,
                "X-Password": self.settings.primary_password,
            },
            timeout=15,
        )
        response.raise_for_status()
        token = response.headers.get("X-Auth-Token")
        if not token:
            raise RuntimeError("Primary auth response did not include X-Auth-Token")
        self.state.token = token
        self.state.expires_at = datetime.utcnow() + timedelta(hours=23, minutes=55)
        return token
