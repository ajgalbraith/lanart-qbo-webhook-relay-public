from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from .config import Settings


def verify_webhook_signature(*, body: bytes, signature: str | None, verifier_token: str) -> bool:
    if not signature or not verifier_token:
        return False
    digest = hmac.digest(verifier_token.encode("utf-8"), body, hashlib.sha256)
    expected = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, signature)


@dataclass
class QuickBooksEvent:
    event_key: str
    realm_id: str
    entity_name: str
    entity_id: str
    action: str
    happened_at: str

    @property
    def normalized_type(self) -> str:
        return f"{self.entity_name.lower()}.{self.action.lower()}"


class QuickBooksClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._access_token: str | None = None
        self._access_token_expires_at: datetime | None = None
        self._refresh_token: str = settings.quickbooks_refresh_token
        self._realm_id: str = settings.quickbooks_realm_id

    def is_ready(self) -> bool:
        return bool(
            self.settings.quickbooks_client_id
            and self.settings.quickbooks_client_secret
            and (
                (self._refresh_token and self._realm_id)
                or (
                    self.settings.quickbooks_token_broker_url
                    and self.settings.quickbooks_token_broker_secret
                )
            )
        )

    def normalize_events(self, payload: Any) -> list[QuickBooksEvent]:
        if isinstance(payload, list):
            return self._normalize_cloudevents(payload)
        if isinstance(payload, dict) and "eventNotifications" in payload:
            return self._normalize_legacy(payload["eventNotifications"])
        return []

    def fetch_entity(self, *, entity_name: str, entity_id: str, realm_id: str) -> dict[str, Any]:
        access_token = self._get_access_token(realm_id=realm_id)
        entity_path = entity_name.lower()
        url = f"{self.settings.quickbooks_api_base_url}/v3/company/{realm_id}/{entity_path}/{entity_id}"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
        payload = response.json()
        entity = payload.get(entity_name) or payload.get(entity_name.capitalize()) or {}
        if not entity:
            raise RuntimeError(f"QuickBooks returned no {entity_name} payload for {entity_id}")
        return entity

    def _normalize_cloudevents(self, payload: list[Any]) -> list[QuickBooksEvent]:
        events: list[QuickBooksEvent] = []
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            event_type = str(entry.get("type") or "")
            parts = event_type.split(".")
            if len(parts) < 4 or parts[0].lower() != "qbo":
                continue
            entity_name = parts[1]
            action = parts[2]
            realm_id = str(entry.get("intuitaccountid") or "")
            entity_id = str(entry.get("intuitentityid") or "")
            happened_at = str(entry.get("time") or "")
            event_key = str(entry.get("id") or f"{realm_id}:{entity_name}:{entity_id}:{action}:{happened_at}")
            if realm_id and entity_id:
                events.append(
                    QuickBooksEvent(
                        event_key=event_key,
                        realm_id=realm_id,
                        entity_name=entity_name,
                        entity_id=entity_id,
                        action=action,
                        happened_at=happened_at,
                    )
                )
        return events

    def _normalize_legacy(self, payload: list[Any]) -> list[QuickBooksEvent]:
        events: list[QuickBooksEvent] = []
        for notification in payload:
            if not isinstance(notification, dict):
                continue
            realm_id = str(notification.get("realmId") or "")
            entities = notification.get("dataChangeEvent", {}).get("entities", [])
            for entity in entities:
                entity_name = str(entity.get("name") or "")
                entity_id = str(entity.get("id") or "")
                action = str(entity.get("operation") or "").lower()
                happened_at = str(entity.get("lastUpdated") or "")
                event_key = f"{realm_id}:{entity_name}:{entity_id}:{action}:{happened_at}"
                if realm_id and entity_name and entity_id:
                    events.append(
                        QuickBooksEvent(
                            event_key=event_key,
                            realm_id=realm_id,
                            entity_name=entity_name,
                            entity_id=entity_id,
                            action=action,
                            happened_at=happened_at,
                        )
                    )
        return events

    def _get_access_token(self, *, realm_id: str) -> str:
        if self._access_token and self._access_token_expires_at:
            if datetime.now(timezone.utc) + timedelta(seconds=60) < self._access_token_expires_at:
                self._validate_realm(realm_id)
                return self._access_token

        self._sync_tokens_from_broker()
        if not self._refresh_token:
            raise RuntimeError("QuickBooks refresh token is not configured")

        credentials = f"{self.settings.quickbooks_client_id}:{self.settings.quickbooks_client_secret}"
        headers = {
            "Accept": "application/json",
            "Authorization": f"Basic {base64.b64encode(credentials.encode('utf-8')).decode('utf-8')}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        data = {
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
        }
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
                headers=headers,
                data=data,
            )
            response.raise_for_status()
        payload = response.json()
        self._access_token = str(payload["access_token"])
        self._access_token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(payload.get("expires_in", 3600)))
        self._refresh_token = str(payload.get("refresh_token") or self._refresh_token)
        self._realm_id = str(payload.get("realmId") or self._realm_id or realm_id)
        self._push_tokens_to_broker()
        self._validate_realm(realm_id)
        return self._access_token

    def _validate_realm(self, realm_id: str) -> None:
        allowed = set(self.settings.qbo_allowed_realm_ids)
        if allowed and realm_id not in allowed:
            raise RuntimeError(f"Realm {realm_id} is not allowed")
        if self._realm_id and realm_id != self._realm_id:
            raise RuntimeError(f"Webhook realm {realm_id} does not match configured QuickBooks realm")

    def _sync_tokens_from_broker(self) -> None:
        if not (self.settings.quickbooks_token_broker_url and self.settings.quickbooks_token_broker_secret):
            return
        url = self.settings.quickbooks_token_broker_url.rstrip("/") + "/token"
        headers = {
            "Accept": "application/json",
            "x-broker-secret": self.settings.quickbooks_token_broker_secret,
        }
        with httpx.Client(timeout=15.0) as client:
            response = client.get(url, headers=headers)
            if response.status_code == 404:
                return
            response.raise_for_status()
        payload = response.json()
        self._refresh_token = str(payload.get("refresh_token") or self._refresh_token)
        self._realm_id = str(payload.get("realm_id") or self._realm_id)

    def _push_tokens_to_broker(self) -> None:
        if not (
            self.settings.quickbooks_token_broker_url
            and self.settings.quickbooks_token_broker_secret
            and self._refresh_token
        ):
            return
        url = self.settings.quickbooks_token_broker_url.rstrip("/") + "/token"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-broker-secret": self.settings.quickbooks_token_broker_secret,
        }
        payload = {
            "refresh_token": self._refresh_token,
            "realm_id": self._realm_id,
        }
        with httpx.Client(timeout=15.0) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
