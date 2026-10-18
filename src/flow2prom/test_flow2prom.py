"""Tests de flow2prom.  Lancer :  make test"""

import json
import unittest
from pathlib import Path

from flow2prom import FlowAggregator

HERE = Path(__file__).resolve().parent


def sflow(**fields) -> dict:
    """Un paquet échantillonné 1 sur 512 par r-br1, à compléter."""
    return {"type": "SFLOW_5", "sampler_address": "172.20.30.15", "sampling_rate": 512,
            "packets": 1, "bytes": 1500, **fields}


def value(text: str, series: str) -> float:
    """Valeur d'une série dans le texte /metrics (0 si absente)."""
    for line in text.splitlines():
        if line.startswith(series + " "):
            return float(line.split()[-1])
    return 0.0


class FlowAggregatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.agg = FlowAggregator()

    def test_sflow_record_is_scaled_by_sampling_rate(self):
        self.agg.add(sflow(proto="TCP"))
        text = self.agg.metrics()
        labels = 'exporter="sflow",sampler="172.20.30.15",proto="TCP"'
        self.assertEqual(value(text, f"rt3_flow_packets_total{{{labels}}}"), 512)
        self.assertEqual(value(text, f"rt3_flow_bytes_total{{{labels}}}"), 512 * 1500)

    def test_ipfix_record_is_counted_as_is(self):
        self.agg.add({"type": "IPFIX", "sampler_address": "172.20.30.15", "sampling_rate": 1,
                      "proto": "ICMP", "packets": 300, "bytes": 25200})
        labels = 'exporter="ipfix",sampler="172.20.30.15",proto="ICMP"'
        self.assertEqual(value(self.agg.metrics(), f"rt3_flow_packets_total{{{labels}}}"), 300)

    def test_syn_and_synack_are_counted_separately(self):
        self.agg.add(sflow(proto="TCP", tcp_flags=0x02))     # SYN
        self.agg.add(sflow(proto="TCP", tcp_flags=0x12))     # SYN+ACK
        self.agg.add(sflow(proto="TCP", tcp_flags=0x10))     # ACK seul : ni l'un ni l'autre
        text = self.agg.metrics()
        labels = 'exporter="sflow",sampler="172.20.30.15"'
        self.assertEqual(value(text, f"rt3_flow_tcp_syn_total{{{labels}}}"), 512)
        self.assertEqual(value(text, f"rt3_flow_tcp_synack_total{{{labels}}}"), 512)

    def test_dns_queries(self):
        self.agg.add(sflow(proto="UDP", dst_port=53))
        self.agg.add(sflow(proto="UDP", dst_port=123))
        labels = 'exporter="sflow",sampler="172.20.30.15"'
        self.assertEqual(value(self.agg.metrics(), f"rt3_flow_dns_queries_total{{{labels}}}"), 512)

    def test_distinct_ports_over_sliding_window(self):
        for port in range(1, 101):                          # un scan de 100 ports à t = 0
            self.agg.add(sflow(proto="TCP", src_addr="10.9.4.10", dst_port=port), now=0)
        series = ('rt3_flow_distinct_dst_ports{exporter="sflow",'
                  'sampler="172.20.30.15",src_addr="10.9.4.10"}')
        self.assertEqual(value(self.agg.metrics(now=5), series), 100)    # dans la fenêtre
        self.assertNotIn(series, self.agg.metrics(now=11))               # 11 s plus tard : oublié

    def test_unknown_records_are_ignored(self):
        self.agg.add({"type": "NETFLOW_V5", "packets": 10})
        self.assertEqual(self.agg.metrics(), "\n")

    def test_real_goflow2_records(self):
        """Enregistrements réels capturés dans le labo : aucun ne doit faire échouer l'agrégation."""
        lines = (HERE / "samples.jsonl").read_text().splitlines()
        for line in lines:
            self.agg.add(json.loads(line))
        text = self.agg.metrics()
        self.assertIn('exporter="sflow"', text)
        self.assertIn('exporter="ipfix"', text)


if __name__ == "__main__":
    unittest.main()
