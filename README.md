# qbo-webhook-relay

Small FastAPI service that receives QuickBooks Online webhooks, verifies the Intuit signature, fetches the full entity from QuickBooks, filters for Costco transactions, and sends notifications to Slack and/or Twilio.

## Endpoints

- `GET /health`
- `POST /webhooks/quickbooks`

## Local run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install .
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Render

Build command:

```bash
pip install .
```

Start command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```
