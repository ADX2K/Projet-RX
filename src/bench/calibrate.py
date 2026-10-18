#!/usr/bin/env python3
"""Calibration des seuils N1 : paquets/s reçus par interface en trafic normal.

Lance le trafic de fond seul (aucun incident), relève toutes les 10 s le
compteur de paquets reçus de chaque interface de données des routeurs, puis
affiche pour chaque interface le pire débit sur 10 s et la pire moyenne sur
5 min (ce que voit N1). Le seuil HighPacketRate vaut 1,5 × la pire moyenne
sur 5 min (voir docs/protocole-mesure.md).

    python3 src/bench/calibrate.py                 # 10 min, graine 42
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROUTERS = ["r-core1", "r-core2", "r-hq", "r-dc", "r-br1", "r-br2"]
STEP_S = 10
WINDOW_S = 300

READ_COUNTERS = 'for d in /sys/class/net/eth[1-9]*; do echo "${d##*/} $(cat $d/statistics/rx_packets)"; done'


def read_counters() -> dict[str, int]:
    """{ "r-core1:eth1": paquets reçus, ... } pour toutes les interfaces de données."""
    counters = {}
    for router in ROUTERS:
        out = subprocess.run(["docker", "exec", f"clab-rt3p9-{router}", "sh", "-c", READ_COUNTERS],
                             capture_output=True, text=True).stdout
        for line in out.splitlines():
            iface, packets = line.split()
            counters[f"{router}:{iface}"] = int(packets)
    return counters


def max_rate(points: list[tuple[float, int]], span: int) -> float:
    """Pire débit moyen (paquets/s) sur des fenêtres de `span` relevés consécutifs."""
    rates = [(points[i + span][1] - points[i][1]) / (points[i + span][0] - points[i][0])
             for i in range(len(points) - span)]
    return max(rates, default=0.0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--duration", type=int, default=600, help="durée en s (défaut : 600)")
    parser.add_argument("--seed", type=int, default=42, help="graine du trafic de fond")
    args = parser.parse_args()
    if args.duration < 2 * WINDOW_S:
        parser.error(f"--duration doit valoir au moins {2 * WINDOW_S} s pour mesurer des moyennes sur 5 min")

    background = subprocess.Popen(
        [sys.executable, str(ROOT / "src/traffic/bgtraffic.py"), "--seed", str(args.seed),
         "--duration", str(args.duration)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"Trafic de fond seul pendant {args.duration} s, relevé toutes les {STEP_S} s…")

    series: dict[str, list[tuple[float, int]]] = {}
    end = time.monotonic() + args.duration
    while time.monotonic() <= end:
        now = time.monotonic()
        for iface, packets in read_counters().items():
            series.setdefault(iface, []).append((now, packets))
        time.sleep(STEP_S)
    background.wait()

    print(f"\n{'interface':16} {'pire 10 s':>10} {'pire 5 min':>11}   (paquets/s)")
    worst = 0.0
    for iface, points in sorted(series.items()):
        worst_5min = max_rate(points, WINDOW_S // STEP_S)
        worst = max(worst, worst_5min)
        print(f"{iface:16} {max_rate(points, 1):10.0f} {worst_5min:11.0f}")
    print(f"\nPire moyenne sur 5 min : {worst:.0f} paquets/s -> seuil proposé : {1.5 * worst:.0f}")


if __name__ == "__main__":
    main()
