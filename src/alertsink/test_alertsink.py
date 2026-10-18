"""Tests d'alertsink (ligne d'historique).  Lancer :  make test"""

import json
import unittest

from alertsink import history_row

RECEIVED_NS = 1_792_000_000_000_000_000


def alert(status: str, **labels: str) -> dict:
    """Une alerte telle que l'envoie le webhook d'Alertmanager."""
    return {"status": status, "fingerprint": "abc123",
            "startsAt": "2026-10-18T14:49:51.000Z", "endsAt": "2026-10-18T14:50:31.000Z",
            "labels": {"level": "N2", **labels},
            "annotations": {"summary": "résumé de la règle"}}


class HistoryRowTest(unittest.TestCase):
    def test_firing_link_alert(self):
        row = history_row(alert("firing", alertname="LinkSaturation", instance="r-br1", device="eth1"), RECEIVED_NS)
        self.assertEqual((row["level"], row["alertname"], row["router"], row["interface"]),
                         ("N2", "LinkSaturation", "r-br1", "eth1"))
        self.assertIsNone(row["ends_at"])                # encore active
        self.assertIsNone(row["resolved_at"])
        self.assertEqual(row["summary"], "résumé de la règle")
        self.assertEqual(row["received_at"].timestamp(), RECEIVED_NS / 1e9)

    def test_resolved_alert_has_an_end(self):
        row = history_row(alert("resolved", alertname="LinkSaturation", instance="r-br1"), RECEIVED_NS)
        self.assertEqual(row["ends_at"], "2026-10-18T14:50:31.000Z")
        self.assertEqual(row["resolved_at"], row["received_at"])

    def test_flow_alert_names_its_router(self):
        row = history_row(alert("firing", alertname="SynFlood", router="r-br2"), RECEIVED_NS)
        self.assertEqual(row["router"], "r-br2")
        self.assertIsNone(row["interface"])

    def test_snmp_alert_names_its_interface(self):
        row = history_row(alert("firing", alertname="HighPacketRate", instance="r-dc", ifName="eth1"), RECEIVED_NS)
        self.assertEqual(row["interface"], "eth1")
        self.assertEqual(json.loads(row["labels"])["ifName"], "eth1")


if __name__ == "__main__":
    unittest.main()
