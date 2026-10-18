#!/usr/bin/env python3
"""flow2prom : transforme les flux JSON de goflow2 en métriques Prometheus (niveau N2).

goflow2 décode sFlow et IPFIX mais n'agrège rien (voir le plan, précision P1).
flow2prom lit une ligne JSON par flux sur son entrée standard et expose sur
http://<hôte>:9199/metrics :

  rt3_flow_bytes_total{exporter, router, proto}         octets estimés
  rt3_flow_packets_total{exporter, router, proto}       paquets estimés
  rt3_flow_talker_bytes_total{exporter, router, src_addr, dst_addr}
                                                        octets estimés par couple source -> destination
  rt3_flow_tcp_syn_total{exporter, router}              paquets SYN sans ACK (ouvertures de connexion)
  rt3_flow_tcp_synack_total{exporter, router}           paquets SYN+ACK (réponses des serveurs)
  rt3_flow_dns_queries_total{exporter, router}          paquets vers UDP/53
  rt3_flow_syn_dst_ports{exporter, router, src_addr}    ports destination distincts visés par des
                                                        SYN depuis cette source, sur 10 s (scan)
  rt3_flow2prom_bad_lines_total                         lignes illisibles ignorées (santé de flow2prom)

exporter : « sflow » ou « ipfix » (les deux exports sont mesurés séparément).
router   : nom du routeur qui exporte, d'après la variable d'environnement ROUTERS
           (« 172.20.30.15=r-br1 ... », fixée dans lab/topology.clab.yml) ; sinon son adresse.

Estimation : un enregistrement sFlow est UN paquet échantillonné sur N, compté
N fois (champ sampling_rate). Un enregistrement IPFIX est un flux complet, compté
tel quel ; ses drapeaux TCP cumulent ceux de tous ses paquets.

Dans le labo, flow2prom tourne dans le conteneur flowcol, derrière goflow2 :
    goflow2 -format=json ... | python3 flow2prom.py
Toutes les 10 s, il écrit combien d'enregistrements il a reçus : docker logs clab-rt3p9-flowcol
"""

import json
import os
import sys
import threading
import time
from collections import Counter, defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 9199
SCAN_WINDOW_S = 10                 # fenêtre des ports distincts visés par des SYN
REPORT_EVERY_S = 10                # période du journal « enregistrements reçus »
TCP_SYN, TCP_ACK = 0x02, 0x10
EXPORTERS = {"SFLOW_5": "sflow", "IPFIX": "ipfix"}


def parse_routers(text: str) -> dict[str, str]:
    """« 172.20.30.15=r-br1 172.20.30.16=r-br2 » -> {"172.20.30.15": "r-br1", ...}"""
    return dict(pair.split("=", 1) for pair in text.split())


DECODER = json.JSONDecoder()


def parse_line(line: str) -> tuple[list[dict], bool]:
    """Enregistrements JSON d'une ligne de goflow2, et True si une partie était illisible.

    Sous forte charge, goflow2 écrit parfois deux enregistrements sur la même ligne
    (« {...}{...} ») : ses écritures concurrentes s'entrecroisent entre un
    enregistrement et son retour à la ligne (vu pendant le SYN flood, J5). Un
    enregistrement n'est jamais coupé (écriture atomique de moins de 4096 octets
    dans un tube) : on les récupère tous, l'un après l'autre.
    """
    records, position, text = [], 0, line.strip()
    while position < len(text):
        try:
            record, position = DECODER.raw_decode(text, position)
        except json.JSONDecodeError:
            return records, True
        records.append(record)
    return records, False


class FlowAggregator:
    """Cumule les flux reçus et produit le texte /metrics."""

    def __init__(self, routers: dict[str, str] | None = None) -> None:
        self.routers = routers or {}
        self.lock = threading.Lock()
        self.counters: dict[tuple, float] = defaultdict(float)   # (métrique, étiquettes) -> valeur
        self.syn_ports: dict[tuple, dict] = defaultdict(dict)    # (exporter, router, src) -> {port: heure}
        self.received: Counter = Counter()                       # enregistrements reçus par exporteur

    def _inc(self, name: str, value: float, **labels: str) -> None:
        self.counters[(name, tuple(labels.items()))] += value

    def add(self, flow: dict, now: float | None = None) -> None:
        """Prend en compte un enregistrement goflow2 (déjà décodé du JSON)."""
        exporter = EXPORTERS.get(flow.get("type"))
        if exporter is None:
            return
        now = time.monotonic() if now is None else now
        sampler = flow.get("sampler_address", "")
        router = self.routers.get(sampler, sampler)
        scale = max(flow.get("sampling_rate", 1), 1)
        packets = flow.get("packets", 0) * scale
        nbytes = flow.get("bytes", 0) * scale
        proto = flow.get("proto", "")
        flags = flow.get("tcp_flags", 0)
        src, dst = flow.get("src_addr", ""), flow.get("dst_addr", "")
        where = {"exporter": exporter, "router": router}

        with self.lock:
            self.received[exporter] += 1
            self._inc("rt3_flow_bytes_total", nbytes, **where, proto=proto)
            self._inc("rt3_flow_packets_total", packets, **where, proto=proto)
            self._inc("rt3_flow_talker_bytes_total", nbytes, **where, src_addr=src, dst_addr=dst)
            if proto == "TCP" and flags & TCP_SYN:
                if flags & TCP_ACK:
                    self._inc("rt3_flow_tcp_synack_total", packets, **where)
                else:
                    self._inc("rt3_flow_tcp_syn_total", packets, **where)
                    # Seuls les SYN comptent pour le scan : les SYN-ACK d'un serveur
                    # vers des ports clients aléatoires ne sont pas un scan.
                    self.syn_ports[(exporter, router, src)][flow.get("dst_port")] = now
            if proto == "UDP" and flow.get("dst_port") == 53:
                self._inc("rt3_flow_dns_queries_total", packets, **where)

    def metrics(self, now: float | None = None) -> str:
        """Texte au format d'exposition Prometheus."""
        now = time.monotonic() if now is None else now
        lines = []
        with self.lock:
            for (name, labels), value in sorted(self.counters.items(), key=str):
                text = ",".join(f'{key}="{val}"' for key, val in labels)
                lines.append(f"{name}{{{text}}} {value:g}" if text else f"{name} {value:g}")

            for key in list(self.syn_ports):
                ports = self.syn_ports[key]
                for port in [p for p, seen in ports.items() if now - seen > SCAN_WINDOW_S]:
                    del ports[port]
                if not ports:                # source inactive : la série disparaît
                    del self.syn_ports[key]
                    continue
                exporter, router, src = key
                lines.append(f'rt3_flow_syn_dst_ports{{exporter="{exporter}",router="{router}",'
                             f'src_addr="{src}"}} {len(ports)}')
        return "\n".join(lines) + "\n"

    def add_line(self, line: str) -> None:
        """Prend en compte une ligne de goflow2 ; une ligne illisible est comptée, jamais fatale."""
        if not line.startswith("{"):         # lignes de journal de goflow2
            return
        records, bad = parse_line(line)
        for record in records:
            self.add(record)
        if bad:
            with self.lock:
                self.counters[("rt3_flow2prom_bad_lines_total", ())] += 1

    def take_received(self) -> Counter:
        """Enregistrements reçus depuis le dernier appel (pour le journal)."""
        with self.lock:
            received, self.received = self.received, Counter()
        return received


def serve_metrics(aggregator: FlowAggregator) -> None:
    class MetricsHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = aggregator.metrics().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args) -> None:
            """Pas de journal HTTP."""

    ThreadingHTTPServer(("", PORT), MetricsHandler).serve_forever()


def report(aggregator: FlowAggregator) -> None:
    while True:
        time.sleep(REPORT_EVERY_S)
        received = aggregator.take_received()
        print(f"flow2prom : {REPORT_EVERY_S} s, sflow {received['sflow']}, ipfix {received['ipfix']} "
              "enregistrements reçus", file=sys.stderr, flush=True)


def main() -> None:
    aggregator = FlowAggregator(parse_routers(os.environ.get("ROUTERS", "")))
    threading.Thread(target=serve_metrics, args=(aggregator,), daemon=True).start()
    threading.Thread(target=report, args=(aggregator,), daemon=True).start()
    for line in sys.stdin:
        aggregator.add_line(line)


if __name__ == "__main__":
    main()
