#!/usr/bin/env python3
"""Trafic de fond du labo rt3p9.

Lance, à intervalles aléatoires, de courtes sessions entre hôtes du labo
(HTTP, DNS, iperf3) avec `docker exec`. La charge suit un cycle
« heures creuses / heures pleines » : une sinusoïde de période --period.
Avec la même graine (--seed), le script rejoue la même suite de sessions.

Exemples :
    python3 src/traffic/bgtraffic.py                      # jusqu'à Ctrl+C
    python3 src/traffic/bgtraffic.py --duration 600 --seed 7
"""

import argparse
import logging
import math
import random
import subprocess
import time

LAB = "rt3p9"
WEB, DNS, IPERF = "10.9.2.10", "10.9.2.11", "10.9.2.12"

# Postes qui génèrent le trafic normal. h-atk est réservé aux incidents.
CLIENTS = ["h-user1", "h-user2", "h-br1"]

log = logging.getLogger("bgtraffic")


def http_session(rng: random.Random) -> list[str]:
    """Télécharge le fichier de 1 Mo du serveur web."""
    return ["curl", "-s", "-o", "/dev/null", f"http://{WEB}/1M.bin"]


def dns_session(rng: random.Random) -> list[str]:
    """Résout un nom au hasard dans la zone rt3.lab."""
    return ["dig", "+short", f"@{DNS}", f"host{rng.randint(1, 50)}.rt3.lab"]


def iperf_session(rng: random.Random) -> list[str]:
    """Transfert TCP de quelques secondes à débit modéré.

    Les ports 5201 à 5203 servent au trafic de fond ; 5204 est gardé pour make check.
    """
    rate_mbps = rng.choice([2, 5, 10])
    seconds = rng.randint(5, 20)
    port = rng.choice([5201, 5202, 5203])
    return ["iperf3", "-c", IPERF, "-p", str(port), "-b", f"{rate_mbps}M", "-t", str(seconds)]


# (fabrique de commande, poids) : sur 14 sessions, en moyenne 5 HTTP, 8 DNS, 1 iperf3.
SESSIONS = [(http_session, 5), (dns_session, 8), (iperf_session, 1)]


def load_factor(elapsed: float, period: float) -> float:
    """Charge relative entre 0.2 (heures creuses) et 1.0 (heures pleines)."""
    return 0.6 + 0.4 * math.sin(2 * math.pi * elapsed / period)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rate", type=float, default=2.0,
                        help="sessions par seconde aux heures pleines (défaut : 2)")
    parser.add_argument("--period", type=float, default=600,
                        help="durée d'un cycle creux/plein en secondes (défaut : 600)")
    parser.add_argument("--duration", type=float, default=0,
                        help="durée totale en secondes, 0 = sans fin (défaut : 0)")
    parser.add_argument("--seed", type=int, default=42, help="graine aléatoire (défaut : 42)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    rng = random.Random(args.seed)
    makers, weights = zip(*SESSIONS)
    start = time.monotonic()
    log.info("trafic de fond : %.1f sessions/s max, cycle %.0f s, graine %d",
             args.rate, args.period, args.seed)

    try:
        while args.duration == 0 or time.monotonic() - start < args.duration:
            elapsed = time.monotonic() - start
            load = load_factor(elapsed, args.period)
            time.sleep(rng.expovariate(args.rate * load))

            client = rng.choice(CLIENTS)
            command = rng.choices(makers, weights)[0](rng)
            subprocess.run(["docker", "exec", "-d", f"clab-{LAB}-{client}", *command], check=False)
            log.info("charge %.2f  %-8s %s", load, client, " ".join(command))
    except KeyboardInterrupt:
        log.info("arrêt")


if __name__ == "__main__":
    main()
