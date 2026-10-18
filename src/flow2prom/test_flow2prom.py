"""Tests de flow2prom.  Lancer :  make test"""

import json
import unittest
from pathlib import Path

from flow2prom import FlowAggregator, parse_line, parse_routers

HERE = Path(__file__).resolve().parent
WHERE = 'exporter="sflow",router="r-br1"'


def sflow(**fields) -> dict:
    """Un paquet échantillonné 1 sur 512 par r-br1 (172.20.30.15), à compléter."""
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
        self.agg = FlowAggregator(routers={"172.20.30.15": "r-br1"})

    def test_parse_routers(self):
        self.assertEqual(parse_routers("172.20.30.15=r-br1 172.20.30.16=r-br2"),
                         {"172.20.30.15": "r-br1", "172.20.30.16": "r-br2"})
        self.assertEqual(parse_routers(""), {})

    def test_parse_line(self):
        self.assertEqual(parse_line('{"a": 1}\n'), ([{"a": 1}], False))
        # Deux enregistrements collés, vus pendant le SYN flood (J5).
        self.assertEqual(parse_line('{"a": 1}{"b": 2}\n'), ([{"a": 1}, {"b": 2}], False))
        # Ligne illisible : on garde ce qui précède et on le signale.
        self.assertEqual(parse_line('{"a": 1}{"b": \n'), ([{"a": 1}], True))

    def test_bad_line_is_counted_and_never_fatal(self):
        self.agg.add_line(json.dumps(sflow(proto="TCP")) + json.dumps(sflow(proto="UDP")) + "\n")
        self.agg.add_line('{"type": "SFLOW_5", "pack\n')
        self.agg.add_line("time=2026-10-18 level=WARN msg=\"template error\"\n")   # journal goflow2 : ignoré
        text = self.agg.metrics()
        self.assertEqual(value(text, f'rt3_flow_packets_total{{{WHERE},proto="TCP"}}'), 512)
        self.assertEqual(value(text, f'rt3_flow_packets_total{{{WHERE},proto="UDP"}}'), 512)
        self.assertEqual(value(text, "rt3_flow2prom_bad_lines_total"), 1)

    def test_unknown_router_keeps_its_address(self):
        self.agg.add(sflow(sampler_address="172.20.30.99", proto="TCP"))
        self.assertIn('router="172.20.30.99"', self.agg.metrics())

    def test_sflow_record_is_scaled_by_sampling_rate(self):
        self.agg.add(sflow(proto="TCP"))
        text = self.agg.metrics()
        self.assertEqual(value(text, f'rt3_flow_packets_total{{{WHERE},proto="TCP"}}'), 512)
        self.assertEqual(value(text, f'rt3_flow_bytes_total{{{WHERE},proto="TCP"}}'), 512 * 1500)

    def test_ipfix_record_is_counted_as_is(self):
        self.agg.add({"type": "IPFIX", "sampler_address": "172.20.30.15", "sampling_rate": 1,
                      "proto": "ICMP", "packets": 300, "bytes": 25200})
        series = 'rt3_flow_packets_total{exporter="ipfix",router="r-br1",proto="ICMP"}'
        self.assertEqual(value(self.agg.metrics(), series), 300)

    def test_talkers(self):
        self.agg.add(sflow(proto="TCP", src_addr="10.9.3.10", dst_addr="10.9.2.12"))
        series = f'rt3_flow_talker_bytes_total{{{WHERE},src_addr="10.9.3.10",dst_addr="10.9.2.12"}}'
        self.assertEqual(value(self.agg.metrics(), series), 512 * 1500)

    def test_syn_and_synack_are_counted_separately(self):
        self.agg.add(sflow(proto="TCP", tcp_flags=0x02))     # SYN
        self.agg.add(sflow(proto="TCP", tcp_flags=0x12))     # SYN+ACK
        self.agg.add(sflow(proto="TCP", tcp_flags=0x10))     # ACK seul : ni l'un ni l'autre
        text = self.agg.metrics()
        self.assertEqual(value(text, f"rt3_flow_tcp_syn_total{{{WHERE}}}"), 512)
        self.assertEqual(value(text, f"rt3_flow_tcp_synack_total{{{WHERE}}}"), 512)

    def test_dns_queries(self):
        self.agg.add(sflow(proto="UDP", dst_port=53))
        self.agg.add(sflow(proto="UDP", dst_port=123))
        self.assertEqual(value(self.agg.metrics(), f"rt3_flow_dns_queries_total{{{WHERE}}}"), 512)

    def test_scan_counts_distinct_ports_over_sliding_window(self):
        for port in range(1, 101):                          # un scan SYN de 100 ports à t = 0
            self.agg.add(sflow(proto="TCP", tcp_flags=0x02, src_addr="10.9.4.10", dst_port=port), now=0)
        series = f'rt3_flow_syn_dst_ports{{{WHERE},src_addr="10.9.4.10"}}'
        self.assertEqual(value(self.agg.metrics(now=5), series), 100)    # dans la fenêtre
        self.assertNotIn(series, self.agg.metrics(now=11))               # 11 s plus tard : oublié

    def test_synack_to_many_ports_is_not_a_scan(self):
        """Pendant un SYN flood, le serveur répond SYN-ACK vers des milliers de ports clients."""
        for port in range(40000, 40100):
            self.agg.add(sflow(proto="TCP", tcp_flags=0x12, src_addr="10.9.2.10", dst_port=port))
        self.assertNotIn("rt3_flow_syn_dst_ports", self.agg.metrics())

    def test_unknown_records_are_ignored(self):
        self.agg.add({"type": "NETFLOW_V5", "packets": 10})
        self.assertEqual(self.agg.metrics(), "\n")

    def test_received_counts_for_the_log(self):
        self.agg.add(sflow(proto="TCP"))
        self.agg.add(sflow(proto="UDP"))
        self.assertEqual(self.agg.take_received()["sflow"], 2)
        self.assertEqual(self.agg.take_received()["sflow"], 0)          # remis à zéro

    def test_real_goflow2_records(self):
        """Enregistrements réels capturés dans le labo : aucun ne doit faire échouer l'agrégation."""
        for line in (HERE / "samples.jsonl").read_text().splitlines():
            self.agg.add(json.loads(line))
        text = self.agg.metrics()
        self.assertIn('exporter="sflow",router="r-br1"', text)
        self.assertIn('exporter="ipfix",router="r-br1"', text)


if __name__ == "__main__":
    unittest.main()
