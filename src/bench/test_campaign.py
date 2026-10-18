"""Tests du calcul de résultat du banc de mesure.  Lancer :  make test"""

import unittest

from campaign import summarize

S = 10**9                                   # une seconde en nanosecondes
PACKETS = "port_scan syn_flood dns_anomaly"  # étiquette detects de HighPacketRate
BANDWIDTH = "saturation microburst"          # étiquette detects de LinkSaturation


def alert(name: str, at_s: int, detects: str, instance: str = "r-dc") -> dict:
    return {"alertname": name, "received_ns": at_s * S,
            "labels": {"detects": detects, "instance": instance}}


class SummarizeTest(unittest.TestCase):
    def test_saturation_seen_first_as_packet_rate(self):
        """Cas réel du 2026-10-18 : HighPacketRate arrive 5 min avant LinkSaturation."""
        alerts = [alert("HighPacketRate", 130, PACKETS),
                  alert("HighPacketRate", 160, PACKETS, "r-br1"),
                  alert("LinkSaturation", 430, BANDWIDTH)]
        result = summarize(alerts, "saturation", t_start_ns=0, deadline_ns=1020 * S)
        self.assertTrue(result["detected"])
        self.assertEqual(result["delay_s"], 430)
        self.assertEqual(result["alertname"], "LinkSaturation")
        self.assertEqual(result["delay_any_s"], 130)
        self.assertEqual(result["alertname_any"], "HighPacketRate")
        self.assertEqual(result["other_alerts"], 2)

    def test_not_detected(self):
        result = summarize([], "microburst", t_start_ns=0, deadline_ns=670 * S)
        self.assertFalse(result["detected"])
        self.assertEqual(result["delay_s"], "")
        self.assertEqual(result["delay_any_s"], "")
        self.assertEqual(result["other_alerts"], 0)

    def test_alert_after_the_grace_window_does_not_count(self):
        result = summarize([alert("LinkSaturation", 700, BANDWIDTH)], "microburst",
                           t_start_ns=0, deadline_ns=670 * S)
        self.assertFalse(result["detected"])

    def test_alerts_after_detection_are_not_counted(self):
        alerts = [alert("LinkSaturation", 300, BANDWIDTH), alert("HighPacketRate", 400, PACKETS)]
        result = summarize(alerts, "saturation", t_start_ns=0, deadline_ns=1000 * S)
        self.assertEqual(result["other_alerts"], 0)


if __name__ == "__main__":
    unittest.main()
