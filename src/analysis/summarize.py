#!/usr/bin/env python3
"""Synthèse des mesures : des CSV du banc vers un tableau de résultats versionné.

Crée le dossier results/<nom>/ avec :
  - une copie des fichiers bruts utilisés (CSV et manifestes .json) ;
  - summary.md : détections et délais par incident, fausses alertes par heure.

results/raw/ est un brouillon (hors Git) ; results/<nom>/ contient les
résultats de référence cités dans le rapport (versionnés).

    python3 src/analysis/summarize.py --name J4-baseline-snmp \\
        results/raw/20261019-0300-N1.csv results/raw/20261018-2200-N1-normal.json

Plusieurs CSV de campagne peuvent être donnés (campagne découpée en plusieurs nuits).
"""

import argparse
import csv
import json
import shutil
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORDER = ["saturation", "microburst", "port_scan", "syn_flood", "dns_anomaly"]


def load_runs(paths: list[Path]) -> list[dict]:
    """Lignes de un ou plusieurs CSV de campagne."""
    runs = []
    for path in paths:
        with open(path, newline="") as fh:
            runs.extend(csv.DictReader(fh))
    return runs


def spread(values: list[float]) -> str:
    """« médiane [min – max] » en secondes, ou « — » sans valeur."""
    if not values:
        return "—"
    return f"{statistics.median(values):.0f} s [{min(values):.0f} – {max(values):.0f}]"


def summarize_scenario(runs: list[dict]) -> dict:
    """Résumé des répétitions d'un même incident."""
    detected = [r for r in runs if r["detected"] == "True"]
    first_alerts = Counter(r["alertname_any"] for r in runs if r["alertname_any"])
    top = first_alerts.most_common(1)
    return {
        "detected": f"{len(detected)}/{len(runs)}",
        "delay": spread([float(r["delay_s"]) for r in detected]),
        "delay_any": spread([float(r["delay_any_s"]) for r in runs if r["delay_any_s"]]),
        "first_alert": f"{top[0][0]} ({top[0][1]}/{len(runs)})" if top else "aucune",
        "other_alerts": f"{statistics.median(int(r['other_alerts']) for r in runs):.0f}",
    }


def render(name: str, runs: list[dict], campaigns: list[dict], normals: list[dict]) -> str:
    levels = sorted({r["level"] for r in runs})
    lines = [
        f"# Résultats : {name}",
        "",
        f"Généré le {datetime.now():%Y-%m-%d %H:%M} par `src/analysis/summarize.py`. "
        "Définitions : [docs/protocole-mesure.md](../../docs/protocole-mesure.md).",
        "",
        "## Données",
        "",
    ]
    for c in campaigns:
        lines.append(f"- Campagne `{c['campaign']}` : niveau {c['level']}, {c['reps']} répétition(s) par incident, "
                     f"graine {c['seed']}, commit `{c['git']}`")
    for n in normals:
        lines.append(f"- Trafic normal `{n['session']}` : niveau {n['level']}, {n['hours']} h, commit `{n['git']}`")

    for level in levels:
        level_runs = [r for r in runs if r["level"] == level]
        scrape = level_runs[0]["scrape_interval_s"]
        lines += [
            "",
            f"## Détection des incidents (niveau {level}, sondage toutes les {scrape} s)",
            "",
            "| Incident | Détectés | Délai, bon type : médiane [min – max] | Première alerte : médiane [min – max] "
            "| Première alerte la plus fréquente | Autres alertes (médiane) |",
            "|---|---|---|---|---|---|",
        ]
        scenarios = sorted({r["scenario"] for r in level_runs},
                           key=lambda s: ORDER.index(s) if s in ORDER else len(ORDER))
        for scenario in scenarios:
            s = summarize_scenario([r for r in level_runs if r["scenario"] == scenario])
            lines.append(f"| {scenario} | {s['detected']} | {s['delay']} | {s['delay_any']} "
                         f"| {s['first_alert']} | {s['other_alerts']} |")
        lines += [
            "",
            "Délai : du début de l'incident à la réception de l'alerte par alertsink. "
            "« Bon type » : alerte dont la règle liste l'incident dans « detects ». "
            "« Première alerte » : la première alerte reçue, quel que soit son type.",
        ]

    if normals:
        lines += ["", "## Fausses alertes (trafic normal seul, sans incident)", "",
                  "| Niveau | Durée | Fausses alertes | Par heure |", "|---|---|---|---|"]
        for n in normals:
            lines.append(f"| {n['level']} | {n['hours']} h | {n['false_alerts']} | {n['false_alerts_per_hour']} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthèse des mesures du banc.")
    parser.add_argument("--name", required=True, help="nom du dossier de résultats, ex. J4-baseline-snmp")
    parser.add_argument("files", nargs="+", type=Path,
                        help="CSV de campagne et/ou .json de session de trafic normal")
    args = parser.parse_args()

    out = ROOT / "results" / args.name
    out.mkdir(parents=True, exist_ok=True)

    campaign_csvs = [f for f in args.files if f.suffix == ".csv"]
    normal_jsons = [f for f in args.files if f.suffix == ".json"]
    campaigns = [json.loads(f.with_suffix(".json").read_text()) for f in campaign_csvs]
    normals = [json.loads(f.read_text()) for f in normal_jsons]

    # Copie des données brutes de référence (le CSV d'une session normale suit son .json).
    for f in campaign_csvs + normal_jsons:
        for companion in (f.with_suffix(".csv"), f.with_suffix(".json")):
            if companion.exists():
                shutil.copy2(companion, out / companion.name)

    (out / "summary.md").write_text(render(args.name, load_runs(campaign_csvs), campaigns, normals))
    print(f"Résultats écrits dans {out.relative_to(ROOT)}/summary.md")


if __name__ == "__main__":
    main()
