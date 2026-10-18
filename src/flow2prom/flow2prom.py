#!/usr/bin/env python3
"""flow2prom : transforme les flux JSON de goflow2 en métriques Prometheus.

goflow2 décode sFlow et IPFIX mais n'agrège rien (voir le plan, précision P1).
flow2prom lit une ligne JSON par flux sur son entrée standard et expose sur
http://<hôte>:9199/metrics :

  rt3_flow_bytes_total{exporter, sampler, proto}       octets estimés
  rt3_flow_packets_total{exporter, sampler, proto}     paquets estimés
  rt3_flow_tcp_syn_total{exporter, sampler}            paquets SYN sans ACK (ouvertures)
  rt3_flow_tcp_synack_total{exporter, sampler}         paquets SYN+ACK (réponses)
  rt3_flow_dns_queries_total{exporter, sampler}        paquets vers UDP/53
  rt3_flow_distinct_dst_ports{exporter, sampler, src_addr}
                                                       ports destination distincts vus
                                                       depuis cette source sur 10 s

exporter vaut « sflow » ou « ipfix » (les deux exports sont mesurés séparément),
sampler est l'adresse du routeur qui exporte.

Estimation : un enregistrement sFlow est UN paquet échantillonné sur N ;
on le compte N fois (champ sampling_rate). Un enregistrement IPFIX est un flux
complet, compté tel quel.

Statut (jalon J3) : squelette testé (test_flow2prom.py). Déploiement au jalon J5 :
    goflow2 ... -format=json | python3 flow2prom.py
"""

import json
import sys
import threading
import time
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 9199
PORT_WINDOW_S = 10                 # fenêtre des ports destination distincts
TCP_SYN, TCP_ACK = 0x02, 0x10
EXPORTERS = {"SFLOW_5": "sflow", "IPFIX": "ipfix"}


class FlowAggregator:
    """Cumule les flux reçus et produit le texte /metrics."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.counters: dict[tuple, float] = defaultdict(float)     # (métrique, labels) -> valeur
        self.dst_ports: dict[tuple, dict] = defaultdict(dict)      # (exporter, sampler, src) -> {port: heure}

    def add(self, flow: dict, now: float | None = None) -> None:
        """Prend en compte un enregistrement goflow2 (déjà décodé du JSON)."""
        exporter = EXPORTERS.get(flow.get("type"))
        if exporter is None:
            return
        now = time.monotonic() if now is None else now
        sampler = flow.get("sampler_address", "")
        scale = max(flow.get("sampling_rate", 1), 1)
        packets = flow.get("packets", 0) * scale
        proto = flow.get("proto", "")
        flags = flow.get("tcp_flags", 0)

        with self.lock:
            self.counters[("rt3_flow_bytes_total", exporter, sampler, proto)] += flow.get("bytes", 0) * scale
            self.counters[("rt3_flow_packets_total", exporter, sampler, proto)] += packets
            if proto == "TCP" and flags & TCP_SYN:
                name = "rt3_flow_tcp_synack_total" if flags & TCP_ACK else "rt3_flow_tcp_syn_total"
                self.counters[(name, exporter, sampler, None)] += packets
            if proto == "UDP" and flow.get("dst_port") == 53:
                self.counters[("rt3_flow_dns_queries_total", exporter, sampler, None)] += packets
            if proto in ("TCP", "UDP"):
                self.dst_ports[(exporter, sampler, flow.get("src_addr", ""))][flow.get("dst_port")] = now

    def metrics(self, now: float | None = None) -> str:
        """Texte au format d'exposition Prometheus."""
        now = time.monotonic() if now is None else now
        lines = []
        with self.lock:
            for (name, exporter, sampler, proto), value in sorted(self.counters.items(), key=str):
                labels = f'exporter="{exporter}",sampler="{sampler}"'
                if proto is not None:
                    labels += f',proto="{proto}"'
                lines.append(f"{name}{{{labels}}} {value:g}")

            for key in list(self.dst_ports):
                ports = self.dst_ports[key]
                for port in [p for p, seen in ports.items() if now - seen > PORT_WINDOW_S]:
                    del ports[port]
                if not ports:                # source inactive : la série disparaît
                    del self.dst_ports[key]
                    continue
                exporter, sampler, src = key
                lines.append(f'rt3_flow_distinct_dst_ports{{exporter="{exporter}",'
                             f'sampler="{sampler}",src_addr="{src}"}} {len(ports)}')
        return "\n".join(lines) + "\n"


AGGREGATOR = FlowAggregator()


class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = AGGREGATOR.metrics().encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        """Pas de journal HTTP."""


def main() -> None:
    server = ThreadingHTTPServer(("", PORT), MetricsHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    for line in sys.stdin:
        if line.startswith("{"):             # goflow2 écrit aussi des lignes de journal
            AGGREGATOR.add(json.loads(line))


if __name__ == "__main__":
    main()
