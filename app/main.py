from __future__ import annotations

import logging
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .config import get_settings
from .db import EventStore
from .notifications import NotificationClient
from .quickbooks import QuickBooksClient, QuickBooksEvent, verify_webhook_signature

settings = get_settings()
store = EventStore(settings)
store.init_db()
qbo = QuickBooksClient(settings)
notifications = NotificationClient(settings)

logger = logging.getLogger("qbo-webhook-relay")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="qbo-webhook-relay", version="0.1.0")


@app.get("/")
def index() -> dict[str, str]:
    return {"service": "qbo-webhook-relay", "health": f"{settings.app_base_url}/health"}


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "quickbooks_ready": qbo.is_ready(),
        "webhook_signature_ready": bool(settings.qbo_webhook_verifier_token),
        "notification_channels": notifications.configured_channels(),
        "allowed_events": settings.qbo_allowed_events,
        "allowed_realms": settings.qbo_allowed_realm_ids,
    }


@app.post("/webhooks/quickbooks")
async def quickbooks_webhook(request: Request, background_tasks: BackgroundTasks) -> JSONResponse:
    body = await request.body()
    signature = request.headers.get("intuit-signature")
    if not verify_webhook_signature(
        body=body,
        signature=signature,
        verifier_token=settings.qbo_webhook_verifier_token,
    ):
        raise HTTPException(status_code=401, detail="Invalid QuickBooks webhook signature")

    payload = await request.json()
    events = qbo.normalize_events(payload)
    if not events:
        return JSONResponse({"ok": True, "processed": 0})

    for event in events:
        if not store.remember_event(event.event_key):
            continue
        background_tasks.add_task(process_event, event)

    return JSONResponse({"ok": True, "received": len(events)})


def process_event(event: QuickBooksEvent) -> None:
    try:
        if event.normalized_type not in {item.lower() for item in settings.qbo_allowed_events}:
            return

        entity = qbo.fetch_entity(
            entity_name=event.entity_name,
            entity_id=event.entity_id,
            realm_id=event.realm_id,
        )
        customer_name = str(entity.get("CustomerRef", {}).get("name") or "")
        if not _matches_customer(customer_name):
            return

        message = build_notification_message(event=event, entity=entity)
        sent_to = notifications.send(message)
        logger.info("Sent notification for %s to %s", event.event_key, sent_to or ["none"])
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to process QuickBooks event %s: %s", event.event_key, exc)


def _matches_customer(customer_name: str) -> bool:
    haystack = customer_name.upper()
    return any(term.upper() in haystack for term in settings.customer_match_terms)


def build_notification_message(*, event: QuickBooksEvent, entity: dict[str, Any]) -> str:
    customer_ref = entity.get("CustomerRef") or {}
    customer_name = str(customer_ref.get("name") or "Unknown customer")
    doc_number = str(entity.get("DocNumber") or event.entity_id)
    total_amount = entity.get("TotalAmt")
    txn_date = str(entity.get("TxnDate") or event.happened_at or "")
    po_number = _extract_po(entity)
    lines = _extract_lines(entity)

    parts = [
        f"QuickBooks {event.entity_name} created for Costco",
        f"Customer: {customer_name}",
        f"Doc #: {doc_number}",
    ]
    if po_number:
        parts.append(f"PO: {po_number}")
    if txn_date:
        parts.append(f"Date: {txn_date}")
    if total_amount is not None:
        parts.append(f"Total: {total_amount}")
    if lines:
        parts.append("Lines: " + "; ".join(lines[:3]))
    parts.append(f"Realm: {event.realm_id}")
    parts.append(f"Entity ID: {event.entity_id}")
    return "\n".join(parts)


def _extract_po(entity: dict[str, Any]) -> str:
    for entry in entity.get("CustomField", []) or []:
        name = str(entry.get("Name") or "").strip().upper()
        if name == "PO":
            return str(entry.get("StringValue") or "")
    return ""


def _extract_lines(entity: dict[str, Any]) -> list[str]:
    rendered: list[str] = []
    for line in entity.get("Line", []) or []:
        if line.get("DetailType") != "SalesItemLineDetail":
            continue
        detail = line.get("SalesItemLineDetail") or {}
        item_ref = detail.get("ItemRef") or {}
        item_name = str(item_ref.get("name") or line.get("Description") or "Item")
        qty = detail.get("Qty")
        amount = line.get("Amount")
        bits = [item_name]
        if qty is not None:
            bits.append(f"qty {qty}")
        if amount is not None:
            bits.append(f"amount {amount}")
        rendered.append(" | ".join(bits))
    return rendered
