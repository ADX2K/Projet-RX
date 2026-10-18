"""alertsink : reçoit les alertes d'Alertmanager, note leur heure d'arrivée et garde leur historique.

Pour chaque alerte reçue, déclenchée ou résolue :

1. une ligne JSON sur la sortie standard, avec l'heure de réception :
       {"received_ns": 1792..., "status": "firing", "alertname": "LinkSaturation",
        "level": "N1", "starts_at": "2026-...", "summary": "...", "labels": {...}}
   Le banc de mesure lit ces lignes (docker logs) : received_ns est son t_detect.
   Pour les voir :  make alerts

2. une ligne par occurrence dans la base alertdb (table alerts, voir
   monitoring/alertdb/schema.sql) : début, fin, niveau, routeur, résumé.
   Grafana l'affiche dans le tableau de bord « Alertes ». Si la base est
   injoignable, alertsink continue : seule cette étape est sautée.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 9095
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Un déclenchement crée la ligne ; sa résolution la complète (fin).
# Un nouvel envoi du même déclenchement (repeat_interval) ne change rien.
UPSERT = """
INSERT INTO alerts (fingerprint, starts_at, ends_at, received_at, resolved_at,
                    level, alertname, router, interface, summary, labels)
VALUES (%(fingerprint)s, %(starts_at)s, %(ends_at)s, %(received_at)s, %(resolved_at)s,
        %(level)s, %(alertname)s, %(router)s, %(interface)s, %(summary)s, %(labels)s)
ON CONFLICT (fingerprint, starts_at) DO UPDATE
   SET ends_at = EXCLUDED.ends_at, resolved_at = EXCLUDED.resolved_at
 WHERE EXCLUDED.resolved_at IS NOT NULL
"""


def history_row(alert: dict, received_ns: int) -> dict:
    """Ligne de la table alerts pour une alerte du webhook d'Alertmanager."""
    labels = alert.get("labels", {})
    resolved = alert.get("status") == "resolved"
    received_at = datetime.fromtimestamp(received_ns / 1e9, tz=timezone.utc)
    return {
        "fingerprint": alert.get("fingerprint", ""),
        "starts_at": alert.get("startsAt"),
        "ends_at": alert.get("endsAt") if resolved else None,
        "received_at": received_at,
        "resolved_at": received_at if resolved else None,
        "level": labels.get("level"),
        "alertname": labels.get("alertname"),
        "router": labels.get("instance") or labels.get("router"),    # règles de débit / de flux
        "interface": labels.get("ifName") or labels.get("device"),   # SNMP (N1) / node_exporter (N2)
        "summary": alert.get("annotations", {}).get("summary"),
        "labels": json.dumps(labels),
    }


class AlertStore:
    """Historique dans PostgreSQL. Ne fait jamais échouer la réception d'une alerte."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.conn = None

    def save(self, rows: list[dict]) -> None:
        if not self.url or not rows:
            return
        import psycopg                       # ici : les tests de history_row tournent sans le pilote
        try:
            if self.conn is None or self.conn.closed:
                self.conn = psycopg.connect(self.url, autocommit=True, connect_timeout=3)
            with self.conn.cursor() as cur:
                cur.executemany(UPSERT, rows)
        except psycopg.Error as err:
            print(f"alertsink : historique non enregistré, base injoignable ({err})", file=sys.stderr, flush=True)
            self.conn = None


STORE = AlertStore(DATABASE_URL)


class AlertHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        received_ns = time.time_ns()          # avant tout traitement
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")
        alerts = payload.get("alerts", [])

        for alert in alerts:
            labels = alert.get("labels", {})
            print(json.dumps({
                "received_ns": received_ns,
                "status": alert.get("status"),
                "alertname": labels.get("alertname"),
                "level": labels.get("level"),
                "starts_at": alert.get("startsAt"),
                "summary": alert.get("annotations", {}).get("summary"),
                "labels": labels,
            }), flush=True)
        STORE.save([history_row(alert, received_ns) for alert in alerts])

        self.send_response(200)
        self.end_headers()

    def log_message(self, *args) -> None:
        """Pas de journal HTTP : la sortie standard ne contient que les alertes."""


if __name__ == "__main__":
    HTTPServer(("", PORT), AlertHandler).serve_forever()
