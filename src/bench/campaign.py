#!/usr/bin/env python3
"""Banc de mesure : rejoue les incidents et mesure le délai de détection.

Avant la première répétition, le banc attend un cycle de sondage : en N1, l'effet
d'un essai précédent peut n'apparaître qu'au relevé suivant (jusqu'à 5 min après).

Pour chaque répétition d'un incident :
  1. remise à zéro : attendre qu'aucune alerte du niveau ne soit active ;
  2. phase aléatoire : attendre entre 0 et un intervalle de sondage, pour que
     l'incident ne tombe pas toujours au même moment du cycle de sondage ;
  3. injection : jouer l'incident, noter t_start et t_end ;
  4. détection : attendre la première alerte du bon type (étiquette « detects »
     des règles), au plus jusqu'à t_end + fenêtre de grâce ;
  5. écrire une ligne dans results/raw/<campagne>.csv.

Le trafic de fond tourne pendant toute la campagne, avec la même graine.
Définitions et choix de mesure : docs/protocole-mesure.md

Exemples :
    python3 src/bench/campaign.py --level N1                          # courte : 1 répétition par incident (~1 h)
    python3 src/bench/campaign.py --level N1 --scenarios saturation   # un seul incident (~15 min)
    python3 src/bench/campaign.py --level N1 --reps 10                # complète (8 à 11 h, machine dédiée)
"""

import argparse
import csv
import json
import logging
import random
import signal
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from scenarios import SCENARIOS, inject

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "raw"
ALERTMANAGER = "http://localhost:9093"
ALERTSINK = "clab-rt3p9-alertsink"

# scrape_s : intervalle de sondage du niveau (la phase aléatoire est tirée dans [0, scrape_s])
# grace_s  : délai après la fin de l'incident au-delà duquel on le déclare non détecté.
#            N1 : l'effet d'un incident apparaît au premier relevé qui suit sa fin,
#            donc 300 s de relevé + 30 s d'évaluation des règles + 30 s de marge.
LEVELS = {
    "N1": {"scrape_s": 300, "grace_s": 360},
    "N2": {"scrape_s": 1, "grace_s": 60},
}

# delay_s / alertname       : première alerte du BON type (étiquette « detects »)
# delay_any_s / alertname_any : première alerte quelle qu'elle soit (« quelque chose ne va pas »)
# other_alerts              : alertes d'un autre type reçues avant la détection, souvent
#                             causées par l'incident lui-même (ce ne sont pas des faux positifs)
COLUMNS = [
    "run_id", "level", "scenario", "rep", "seed", "phase_s",
    "t_start_ns", "t_end_ns", "detected", "t_detect_ns", "delay_s",
    "alertname", "alert_instance", "delay_any_s", "alertname_any",
    "other_alerts", "scrape_interval_s",
]

log = logging.getLogger("campaign")


# --- Lecture des alertes ------------------------------------------------------

def active_alerts(level: str) -> list[dict]:
    """Alertes actuellement actives dans Alertmanager pour ce niveau."""
    with urllib.request.urlopen(f"{ALERTMANAGER}/api/v2/alerts?active=true", timeout=10) as resp:
        alerts = json.load(resp)
    return [a for a in alerts if a["labels"].get("level") == level]


def received_alerts(since_ns: int) -> list[dict]:
    """Alertes reçues par alertsink depuis since_ns (une ligne JSON par alerte)."""
    out = subprocess.run(["docker", "logs", ALERTSINK], capture_output=True, text=True).stdout
    alerts = [json.loads(line) for line in out.splitlines() if line.startswith("{")]
    return [a for a in alerts if a["received_ns"] >= since_ns]


def detects(alert: dict, scenario: str) -> bool:
    """Une alerte est « du bon type » si sa règle liste ce scénario dans « detects »."""
    return scenario in alert["labels"].get("detects", "").split()


def summarize(alerts: list[dict], scenario: str, t_start_ns: int, deadline_ns: int) -> dict:
    """Résultat d'une répétition à partir des alertes reçues.

    `alerts` : alertes « firing » du niveau mesuré, reçues après t_start.
    """
    def delay_s(alert: dict) -> float:
        return round((alert["received_ns"] - t_start_ns) / 1e9, 1)

    in_time = sorted((a for a in alerts if a["received_ns"] <= deadline_ns), key=lambda a: a["received_ns"])
    first = next((a for a in in_time if detects(a, scenario)), None)
    seen = [a for a in in_time if first is None or a["received_ns"] <= first["received_ns"]]

    return {
        "detected": first is not None,
        "t_detect_ns": first["received_ns"] if first else "",
        "delay_s": delay_s(first) if first else "",
        "alertname": first["alertname"] if first else "",
        "alert_instance": first["labels"].get("instance", "") if first else "",
        "delay_any_s": delay_s(seen[0]) if seen else "",
        "alertname_any": seen[0]["alertname"] if seen else "",
        "other_alerts": sum(not detects(a, scenario) for a in seen),
    }


# --- Une répétition -------------------------------------------------------------

def wait_quiet(level: str, timeout_s: int = 1800) -> None:
    """Remise à zéro : attendre qu'aucune alerte du niveau ne soit active."""
    deadline = time.monotonic() + timeout_s
    while (alerts := active_alerts(level)) and time.monotonic() < deadline:
        log.info("  attente : %d alerte(s) %s encore active(s)", len(alerts), level)
        time.sleep(15)
    if alerts:
        log.warning("  %d alerte(s) toujours active(s) après %d s, on continue", len(alerts), timeout_s)


def run_once(level: str, scenario: str, rep: int, seed: int, rng: random.Random) -> dict:
    cfg = LEVELS[level]
    wait_quiet(level)

    phase_s = rng.uniform(0, cfg["scrape_s"])
    log.info("  phase aléatoire : %.0f s", phase_s)
    time.sleep(phase_s)

    event = inject(scenario)
    deadline_ns = event["t_end_ns"] + cfg["grace_s"] * 10**9

    # Attente de la première alerte du bon type (ou de la fin de la fenêtre de grâce).
    while True:
        alerts = [a for a in received_alerts(event["t_start_ns"])
                  if a["status"] == "firing" and a["level"] == level]
        if any(detects(a, scenario) for a in alerts) or time.time_ns() >= deadline_ns:
            break
        time.sleep(5)

    return {
        "level": level, "scenario": scenario, "rep": rep, "seed": seed,
        "phase_s": round(phase_s, 1),
        "t_start_ns": event["t_start_ns"], "t_end_ns": event["t_end_ns"],
        **summarize(alerts, scenario, event["t_start_ns"], deadline_ns),
        "scrape_interval_s": cfg["scrape_s"],
    }


# --- Campagne -------------------------------------------------------------------

def git_commit() -> str:
    def git(*args: str) -> str:
        return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True).stdout.strip()
    return git("rev-parse", "--short", "HEAD") + ("-modifié" if git("status", "--porcelain") else "")


def start_background(seed: int, log_path: Path) -> subprocess.Popen:
    """Lance le trafic de fond (bgtraffic.py) ; son journal va dans log_path.

    Un arrêt par « pkill » (SIGTERM) passe alors par les blocs finally de
    l'appelant, qui arrêtent aussi le trafic de fond au lieu de le laisser tourner seul.
    """
    signal.signal(signal.SIGTERM, lambda *_: sys.exit("arrêté (SIGTERM)"))
    return subprocess.Popen(
        [sys.executable, str(ROOT / "src/traffic/bgtraffic.py"), "--seed", str(seed)],
        stdout=open(log_path, "w"), stderr=subprocess.STDOUT)


def main() -> None:
    parser = argparse.ArgumentParser(description="Banc de mesure du délai de détection.")
    parser.add_argument("--level", choices=LEVELS, required=True)
    parser.add_argument("--reps", type=int, default=1,
                        help="répétitions par incident (défaut : 1 ; 10 pour les résultats de référence)")
    parser.add_argument("--scenarios", nargs="+", choices=SCENARIOS, default=list(SCENARIOS))
    parser.add_argument("--seed", type=int, default=42, help="graine (ordre, phases, trafic de fond)")
    parser.add_argument("--no-background", action="store_true", help="sans trafic de fond")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    RESULTS.mkdir(parents=True, exist_ok=True)
    campaign = f"{datetime.now():%Y%m%d-%H%M%S}-{args.level}"
    csv_path = RESULTS / f"{campaign}.csv"

    rng = random.Random(args.seed)
    plan = [(s, rep) for s in args.scenarios for rep in range(1, args.reps + 1)]
    rng.shuffle(plan)                         # ordre aléatoire mais rejouable

    manifest = {
        "campaign": campaign, "level": args.level, "reps": args.reps,
        "scenarios": args.scenarios, "seed": args.seed,
        "background": not args.no_background, "git": git_commit(),
        "started": datetime.now().isoformat(timespec="seconds"),
    }
    (RESULTS / f"{campaign}.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))

    background = None
    if not args.no_background:
        background = start_background(args.seed, RESULTS / f"{campaign}-bgtraffic.log")

    log.info("campagne %s : %d répétitions -> %s", campaign, len(plan), csv_path.relative_to(ROOT))
    try:
        settle_s = LEVELS[args.level]["scrape_s"] + 60
        log.info("stabilisation : %d s (effets éventuels d'un essai précédent)", settle_s)
        time.sleep(settle_s)
        with open(csv_path, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=COLUMNS)
            writer.writeheader()
            for i, (scenario, rep) in enumerate(plan, 1):
                log.info("[%d/%d] %s, répétition %d", i, len(plan), scenario, rep)
                row = run_once(args.level, scenario, rep, args.seed, rng)
                row["run_id"] = f"{datetime.now():%Y%m%d-%H%M%S}-{args.level}-{scenario}-{rep}"
                writer.writerow(row)
                fh.flush()                    # une ligne écrite = une ligne gardée, même si on interrompt
                if row["detected"]:
                    log.info("  détecté en %s s (%s sur %s)", row["delay_s"], row["alertname"], row["alert_instance"])
                else:
                    log.info("  non détecté")
                if row["alertname_any"]:
                    log.info("  première alerte : %s en %s s · %d alerte(s) d'un autre type",
                             row["alertname_any"], row["delay_any_s"], row["other_alerts"])
    except KeyboardInterrupt:
        log.info("interrompu : les lignes déjà écrites sont dans %s", csv_path.relative_to(ROOT))
    finally:
        if background:
            background.terminate()


if __name__ == "__main__":
    main()
