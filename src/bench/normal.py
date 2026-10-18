#!/usr/bin/env python3
"""Session de trafic normal : mesure les fausses alertes, sans aucun incident.

Le trafic de fond tourne seul pendant --hours heures. Aucun incident n'est
joué : toute alerte du niveau reçue pendant ce temps est une fausse alerte.

Écrit dans results/raw/ :
  <date>-<niveau>-normal.csv   une ligne par fausse alerte
  <date>-<niveau>-normal.json  durée, nombre de fausses alertes, taux par heure

    python3 src/bench/normal.py --level N1             # 1 h
    python3 src/bench/normal.py --level N1 --hours 3   # durée de référence (machine dédiée)
"""

import argparse
import csv
import json
import logging
import time
from datetime import datetime

from campaign import LEVELS, RESULTS, ROOT, git_commit, received_alerts, start_background, wait_quiet

log = logging.getLogger("normal")


def main() -> None:
    parser = argparse.ArgumentParser(description="Session de trafic normal (fausses alertes).")
    parser.add_argument("--level", choices=LEVELS, required=True)
    parser.add_argument("--hours", type=float, default=1,
                        help="durée en heures (défaut : 1 ; 3 pour les résultats de référence)")
    parser.add_argument("--seed", type=int, default=42, help="graine du trafic de fond")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    RESULTS.mkdir(parents=True, exist_ok=True)
    session = f"{datetime.now():%Y%m%d-%H%M%S}-{args.level}-normal"

    # Même préparation que le banc : laisser passer les effets d'un essai précédent.
    settle_s = LEVELS[args.level]["scrape_s"] + 60
    log.info("session %s : stabilisation %d s", session, settle_s)
    time.sleep(settle_s)
    wait_quiet(args.level)

    background = start_background(args.seed, RESULTS / f"{session}-bgtraffic.log")
    t_start_ns = time.time_ns()
    t_end_ns = t_start_ns + int(args.hours * 3600 * 10**9)
    log.info("trafic normal seul pendant %g h", args.hours)
    try:
        while time.time_ns() < t_end_ns:
            time.sleep(min(900, max(1, (t_end_ns - time.time_ns()) / 10**9)))
            log.info("  %.0f %% écoulé", 100 * (time.time_ns() - t_start_ns) / (t_end_ns - t_start_ns))
    finally:
        background.terminate()
    t_end_ns = min(t_end_ns, time.time_ns())   # durée réelle si la session est interrompue

    # Une alerte longue est renvoyée par Alertmanager (repeat_interval) :
    # on ne compte chaque alerte qu'une fois, identifiée par ses étiquettes et son heure de début.
    unique = {}
    for alert in received_alerts(t_start_ns):
        if alert["status"] == "firing" and alert["level"] == args.level and alert["received_ns"] <= t_end_ns:
            key = (json.dumps(alert["labels"], sort_keys=True), alert["starts_at"])
            unique.setdefault(key, alert)
    false_alerts = sorted(unique.values(), key=lambda a: a["received_ns"])

    with open(RESULTS / f"{session}.csv", "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["received_ns", "alertname", "instance", "ifName", "starts_at"])
        for a in false_alerts:
            writer.writerow([a["received_ns"], a["alertname"], a["labels"].get("instance", ""),
                             a["labels"].get("ifName", ""), a["starts_at"]])

    hours = (t_end_ns - t_start_ns) / 3600e9
    summary = {
        "session": session, "level": args.level, "seed": args.seed, "git": git_commit(),
        "t_start_ns": t_start_ns, "t_end_ns": t_end_ns, "hours": round(hours, 2),
        "false_alerts": len(false_alerts),
        "false_alerts_per_hour": round(len(false_alerts) / hours, 2) if hours else None,
    }
    (RESULTS / f"{session}.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    log.info("%d fausse(s) alerte(s) en %.2f h -> %s", len(false_alerts), hours,
             (RESULTS / f"{session}.csv").relative_to(ROOT))


if __name__ == "__main__":
    main()
