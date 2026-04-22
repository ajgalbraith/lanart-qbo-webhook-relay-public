from __future__ import annotations

import logging
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .config import get_settings
from .db import EventStore
from .filters import matches_customer_name
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


@app.api_route("/", methods=["GET", "HEAD"])
def index() -> dict[str, str]:
    return {"service": "qbo-webhook-relay", "health": f"{settings.app_base_url}/health"}


@app.api_route("/health", methods=["GET", "HEAD"])
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "quickbooks_ready": qbo.is_ready(),
        "webhook_signature_ready": bool(settings.qbo_webhook_verifier_token),
        "notification_channels": notifications.configured_channels(),
        "allowed_events": settings.qbo_allowed_events,
        "allowed_realms": settings.qbo_allowed_realm_ids,
        "customer_match_terms": settings.customer_match_terms,
        "customer_exclude_terms": settings.customer_exclude_terms,
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
    return matches_customer_name(
        customer_name,
        include_terms=settings.customer_match_terms,
        exclude_terms=settings.customer_exclude_terms,
    )


def build_notification_message(*, event: QuickBooksEvent, entity: dict[str, Any]) -> str:
    doc_number = str(entity.get("DocNumber") or event.entity_id)
    total_amount = entity.get("TotalAmt")
    po_number = _extract_po(entity) or doc_number
    primary_line = _extract_primary_line(entity)

    order_type = event.entity_name.lower()
    message = f"New order ({order_type}) from Costco"
    if total_amount is not None:
        message += f" for {_format_number(total_amount)}"
    message += "."

    if primary_line:
        item_name, qty = primary_line
        if qty is not None:
            message += f" {_format_number(qty)} units of {item_name}"
        else:
            message += f" {item_name}"
    if po_number:
        message += f" PO#{po_number}"
    return message


def _extract_po(entity: dict[str, Any]) -> str:
    for entry in entity.get("CustomField", []) or []:
        name = str(entry.get("Name") or "").strip().upper()
        if name == "PO":
            return str(entry.get("StringValue") or "")
    return ""


def _extract_primary_line(entity: dict[str, Any]) -> tuple[str, Any | None] | None:
    for line in entity.get("Line", []) or []:
        if line.get("DetailType") != "SalesItemLineDetail":
            continue
        detail = line.get("SalesItemLineDetail") or {}
        qty = detail.get("Qty")
        if _is_non_positive(qty):
            continue
        item_ref = detail.get("ItemRef") or {}
        item_name = str(item_ref.get("name") or line.get("Description") or "Item")
        return item_name, qty
    return None


def _is_non_positive(value: Any) -> bool:
    if value is None:
        return False
    try:
        return float(value) <= 0
    except (TypeError, ValueError):
        return False


def _format_number(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)
