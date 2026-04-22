import unittest

from app.config import Settings
from app.quickbooks import QuickBooksClient


class QuickBooksEventTests(unittest.TestCase):
    def test_legacy_create_operation_matches_created_event_name(self) -> None:
        qbo = QuickBooksClient(Settings())
        events = qbo.normalize_events(
            {
                "eventNotifications": [
                    {
                        "realmId": "9130356698663156",
                        "dataChangeEvent": {
                            "entities": [
                                {
                                    "name": "Estimate",
                                    "id": "98984",
                                    "operation": "Create",
                                    "lastUpdated": "2026-04-22T19:24:27Z",
                                }
                            ]
                        },
                    }
                ]
            }
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].normalized_type, "estimate.created")

    def test_cloudevent_created_action_stays_created(self) -> None:
        qbo = QuickBooksClient(Settings())
        events = qbo.normalize_events(
            [
                {
                    "id": "evt-1",
                    "type": "qbo.Invoice.created.v1",
                    "intuitaccountid": "9130356698663156",
                    "intuitentityid": "98994",
                    "time": "2026-04-22T19:24:27Z",
                }
            ]
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].normalized_type, "invoice.created")


if __name__ == "__main__":
    unittest.main()
