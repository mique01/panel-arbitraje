from __future__ import annotations

import json
import threading
import time
from queue import Queue
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import websocket

from app.config import Settings
from app.marketdata.auth import PrimaryAuthClient
from app.utils.logging import get_logger


class PrimaryWebSocketClient:
    def __init__(self, settings: Settings, auth_client: PrimaryAuthClient, message_queue: Queue):
        self.settings = settings
        self.auth_client = auth_client
        self.message_queue = message_queue
        self.logger = get_logger("primary.ws")
        self._app: websocket.WebSocketApp | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._subscriptions: list[dict[str, Any]] = []

    def _build_url(self) -> str:
        url = self.settings.primary_ws_url
        mode = self.settings.primary_ws_auth_mode
        token = self.auth_client.get_valid_token() if mode != "none" else ""
        if mode != "query_param":
            return url
        parts = urlsplit(url)
        params = dict(parse_qsl(parts.query))
        params[self.settings.primary_ws_token_query_param] = token
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), parts.fragment))

    def _headers(self) -> list[str]:
        headers: list[str] = []
        mode = self.settings.primary_ws_auth_mode
        if self.settings.primary_ws_use_header_auth or mode == "header":
            token = self.auth_client.get_valid_token()
            headers.append(f"X-Auth-Token: {token}")
        return headers

    def _subprotocols(self) -> list[str] | None:
        if self.settings.primary_ws_auth_mode == "subprotocol" and self.settings.primary_ws_subprotocol:
            token = self.auth_client.get_valid_token()
            return [self.settings.primary_ws_subprotocol.format(token=token)]
        if self.settings.primary_ws_subprotocol:
            return [self.settings.primary_ws_subprotocol]
        return None

    def add_market_data_subscription(self, products: list[dict[str, str]], entries: list[str], depth: int) -> None:
        self._subscriptions = [
            {
                "type": "smd",
                "level": 1,
                "entries": entries,
                "products": products,
                "depth": depth,
            }
        ]
        if self._app and self._running:
            for payload in self._subscriptions:
                self._send_json(payload)

    def start(self) -> None:
        if not self.settings.primary_ws_url:
            self.logger.warning("PRIMARY_WS_URL is not configured; websocket client will stay idle")
            return
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._app:
            self._app.close()
        if self._thread:
            self._thread.join(timeout=5)

    def _run_forever(self) -> None:
        backoff = 1
        while self._running:
            try:
                self._connect_once()
                backoff = 1
            except Exception as exc:
                self.logger.exception("WebSocket connection cycle failed: %s", exc)
                self.message_queue.put({"type": "ws_error", "error": str(exc)})
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)

    def _connect_once(self) -> None:
        self._app = websocket.WebSocketApp(
            self._build_url(),
            header=self._headers(),
            subprotocols=self._subprotocols(),
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self._app.run_forever(ping_interval=20, ping_timeout=10)

    def _on_open(self, ws) -> None:
        self.logger.info("Primary websocket connected")
        self.message_queue.put({"type": "ws_status", "status": "CONNECTED"})
        if self.settings.primary_ws_auth_mode == "post_connect_message":
            token = self.auth_client.get_valid_token()
            payload = self.settings.primary_ws_auth_message_template or {"type": "auth", "token": "{token}"}
            resolved = json.loads(json.dumps(payload).replace("{token}", token))
            self._send_json(resolved)
        for payload in self._subscriptions:
            self._send_json(payload)

    def _on_message(self, ws, message: str) -> None:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            self.logger.warning("Received non-JSON websocket payload")
            return
        self.message_queue.put(payload)

    def _on_error(self, ws, error: Exception) -> None:
        self.logger.error("Primary websocket error: %s", error)
        self.message_queue.put({"type": "ws_error", "error": str(error)})

    def _on_close(self, ws, status_code: int, msg: str) -> None:
        self.logger.warning("Primary websocket closed: code=%s msg=%s", status_code, msg)
        self.message_queue.put({"type": "ws_status", "status": "DISCONNECTED", "detail": msg})

    def _send_json(self, payload: dict[str, Any]) -> None:
        if self._app and self._app.sock and self._app.sock.connected:
            self._app.send(json.dumps(payload))
