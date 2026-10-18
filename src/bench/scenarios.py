#!/usr/bin/env python3
"""Les 5 incidents du projet, rejouables à l'identique (labo isolé uniquement).

Chaque incident est une commande lancée dans un conteneur du labo avec
`docker exec`. inject() la lance, attend sa fin et renvoie la vérité terrain :
heure de début et de fin en nanosecondes (horloge commune à tous les conteneurs).

Lancer un incident à la main (démo) :
    python3 src/bench/scenarios.py --list
    python3 src/bench/scenarios.py saturation
"""

import argparse
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

LAB = "rt3p9"
WEB, DNS, IPERF = "10.9.2.10", "10.9.2.11", "10.9.2.12"
HERE = Path(__file__).resolve().parent


@dataclass
class Scenario:
    description: str
    host: str                 # conteneur qui génère l'incident
    target: str               # adresse visée
    command: list[str]        # commande lancée dans le conteneur
    stdin: str | None = None  # script envoyé sur l'entrée standard (python3 -)


SCENARIOS = {
    "saturation": Scenario(
        "Lien de l'agence 1 saturé pendant 6 min (iperf3 TCP à 100 Mb/s)",
        "h-br1", IPERF,
        ["iperf3", "-c", IPERF, "-p", "5204", "-b", "100M", "-t", "360"],
    ),
    "microburst": Scenario(
        "Rafale de 10 s à pleine capacité sur le lien de l'agence 1",
        "h-br1", IPERF,
        ["iperf3", "-c", IPERF, "-p", "5204", "-b", "100M", "-t", "10"],
    ),
    "port_scan": Scenario(
        "Scan SYN des 1000 premiers ports TCP du serveur web",
        "h-atk", WEB,
        ["nmap", "-sS", "-n", "-Pn", "-T4", "-p", "1-1000", WEB],
    ),
    # hping3 vise un SYN toutes les 200 µs (5000/s) mais en envoie environ 3800/s
    # (mesuré le 2026-10-18). Le noyau de h-atk répond RST à chaque SYN-ACK reçu.
    "syn_flood": Scenario(
        "SYN flood vers le port 80 du serveur web pendant 60 s (~3800 SYN/s)",
        "h-atk", WEB,
        ["timeout", "60", "hping3", "-S", "-p", "80", "-i", "u200", "-q", WEB],
    ),
    "dns_anomaly": Scenario(
        "1000 requêtes DNS/s pour des noms aléatoires pendant 60 s",
        "h-atk", DNS,
        ["python3", "-", DNS, "1000", "60"],
        stdin="dnsflood.py",
    ),
}


def inject(name: str) -> dict:
    """Joue l'incident `name` jusqu'au bout et renvoie sa vérité terrain."""
    scenario = SCENARIOS[name]
    command = ["docker", "exec", "-i", f"clab-{LAB}-{scenario.host}", *scenario.command]
    stdin = open(HERE / scenario.stdin, "rb") if scenario.stdin else subprocess.DEVNULL

    t_start_ns = time.time_ns()
    subprocess.run(command, stdin=stdin, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    t_end_ns = time.time_ns()

    return {
        "scenario": name,
        "host": scenario.host,
        "target": scenario.target,
        "t_start_ns": t_start_ns,
        "t_end_ns": t_end_ns,
        "duration_s": round((t_end_ns - t_start_ns) / 1e9, 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Lance un incident du labo.")
    parser.add_argument("scenario", nargs="?", choices=SCENARIOS)
    parser.add_argument("--list", action="store_true", help="liste les incidents")
    args = parser.parse_args()

    if args.list or not args.scenario:
        for name, scenario in SCENARIOS.items():
            print(f"{name:12} {scenario.host:6} -> {scenario.target:10} {scenario.description}")
        return

    def clock(ns: int) -> str:
        return datetime.fromtimestamp(ns / 1e9).strftime("%H:%M:%S")

    print(f"{args.scenario} : {SCENARIOS[args.scenario].description}")
    print(f"  début {datetime.now():%H:%M:%S}…", flush=True)
    event = inject(args.scenario)
    print(f"  fin   {clock(event['t_end_ns'])} ({event['duration_s']} s)")
    print("Alertes : make alerts, ou Grafana http://localhost:3000. "
          "En N1, elles arrivent au relevé SNMP suivant, jusqu'à 5 min après la fin.")


if __name__ == "__main__":
    main()
