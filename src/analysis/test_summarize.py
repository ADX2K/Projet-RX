"""Tests de la synthèse des mesures.  Lancer :  make test"""

import unittest

from summarize import spread, summarize_scenario


def run(detected: bool, delay: str = "", delay_any: str = "", first: str = "", others: str = "0") -> dict:
    return {"detected": str(detected), "delay_s": delay, "delay_any_s": delay_any,
            "alertname_any": first, "other_alerts": others}


class SummarizeTest(unittest.TestCase):
    def test_spread(self):
        self.assertEqual(spread([300, 420, 360]), "360 s [300 – 420]")
        self.assertEqual(spread([]), "—")

    def test_scenario_with_partial_detection(self):
        runs = [run(True, "330", "240", "HighPacketRate", "4"),
                run(True, "430", "130", "HighPacketRate", "2"),
                run(False, first="LinkSaturation", delay_any="500", others="0")]
        s = summarize_scenario(runs)
        self.assertEqual(s["detected"], "2/3")
        self.assertEqual(s["delay"], "380 s [330 – 430]")       # seulement les répétitions détectées
        self.assertEqual(s["delay_any"], "240 s [130 – 500]")
        self.assertEqual(s["first_alert"], "HighPacketRate (2/3)")
        self.assertEqual(s["other_alerts"], "2")

    def test_scenario_never_detected(self):
        s = summarize_scenario([run(False), run(False)])
        self.assertEqual(s["detected"], "0/2")
        self.assertEqual(s["delay"], "—")
        self.assertEqual(s["first_alert"], "aucune")


if __name__ == "__main__":
    unittest.main()
