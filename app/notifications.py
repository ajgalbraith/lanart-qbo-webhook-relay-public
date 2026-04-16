from __future__ import annotations

from typing import Iterable

import httpx

from .config import Settings


class NotificationClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def configured_channels(self) -> list[str]:
        channels: list[str] = []
        if self.settings.slack_webhook_url:
            channels.append("slack")
        if self.settings.twilio_account_sid and self.settings.twilio_auth_token and self.settings.twilio_to_numbers:
            channels.append("twilio")
        return channels

    def send(self, text: str) -> list[str]:
        sent_to: list[str] = []
        if self.settings.slack_webhook_url:
            self._send_slack(text)
            sent_to.append("slack")
        if self.settings.twilio_account_sid and self.settings.twilio_auth_token and self.settings.twilio_to_numbers:
            count = self._send_twilio(text, self.settings.twilio_to_numbers)
            if count:
                sent_to.append(f"twilio:{count}")
        return sent_to

    def _send_slack(self, text: str) -> None:
        with httpx.Client(timeout=20.0) as client:
            response = client.post(self.settings.slack_webhook_url, json={"text": text})
            response.raise_for_status()

    def _send_twilio(self, text: str, recipients: Iterable[str]) -> int:
        payload_base: dict[str, str] = {"Body": text}
        if self.settings.twilio_messaging_service_sid:
            payload_base["MessagingServiceSid"] = self.settings.twilio_messaging_service_sid
        elif self.settings.twilio_from_number:
            payload_base["From"] = self.settings.twilio_from_number
        else:
            raise RuntimeError("Twilio requires TWILIO_FROM_NUMBER or TWILIO_MESSAGING_SERVICE_SID")

        sent = 0
        account_sid = self.settings.twilio_account_sid
        url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
        with httpx.Client(timeout=20.0, auth=(account_sid, self.settings.twilio_auth_token)) as client:
            for recipient in recipients:
                response = client.post(url, data={**payload_base, "To": recipient})
                response.raise_for_status()
                sent += 1
        return sent
