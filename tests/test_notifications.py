import unittest

from app.main import build_notification_message
from app.quickbooks import QuickBooksEvent


class NotificationMessageTests(unittest.TestCase):
    def test_costco_message_uses_short_order_summary(self) -> None:
        event = QuickBooksEvent(
            event_key="9130356698663156:Estimate:98996:create:2026-04-22T20:00:00Z",
            realm_id="9130356698663156",
            entity_name="Estimate",
            entity_id="98996",
            action="create",
            happened_at="2026-04-22T20:00:00Z",
        )
        entity = {
            "DocNumber": "000760422133",
            "TotalAmt": 32895.48,
            "CustomField": [
                {
                    "Name": "PO",
                    "StringValue": "000760422133",
                }
            ],
            "Line": [
                {
                    "DetailType": "SalesItemLineDetail",
                    "SalesItemLineDetail": {
                        "ItemRef": {"name": "PVC:SONOMA PATIO RUG 5'X8'"},
                        "Qty": 2280,
                    },
                    "Amount": 34656.0,
                },
                {
                    "DetailType": "SalesItemLineDetail",
                    "SalesItemLineDetail": {
                        "ItemRef": {"name": "DEDUCTION:EDI-FRT%"},
                        "Qty": -1,
                    },
                    "Amount": -5285.04,
                },
            ],
        }

        self.assertEqual(
            build_notification_message(event=event, entity=entity),
            "New order (estimate) from Costco for 32895.48. 2280 units of "
            "PVC:SONOMA PATIO RUG 5'X8' PO#000760422133",
        )


if __name__ == "__main__":
    unittest.main()
