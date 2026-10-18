"""alertsink : note l'heure d'arrivée de chaque alerte envoyée par Alertmanager.

C'est cette heure que le banc de mesure utilise comme t_detect.
Chaque alerte reçue est écrite sur la sortie standard en une ligne JSON :

    {"received_ns": 1792..., "status": "firing", "alertname": "LinkSaturation",
     "level": "N1", "starts_at": "2026-...", "labels": {...}}

Pour les lire :  docker logs clab-rt3p9-alertsink   (ou make alerts)
"""

import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 9095


class AlertHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        received_ns = time.time_ns()          # avant tout traitement
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")

        for alert in payload.get("alerts", []):
            labels = alert.get("labels", {})
            print(json.dumps({
                "received_ns": received_ns,
                "status": alert.get("status"),
                "alertname": labels.get("alertname"),
                "level": labels.get("level"),
                "starts_at": alert.get("startsAt"),
                "labels": labels,
            }), flush=True)

        self.send_response(200)
        self.end_headers()

    def log_message(self, *args) -> None:
        """Pas de journal HTTP : la sortie standard ne contient que les alertes."""


if __name__ == "__main__":
    HTTPServer(("", PORT), AlertHandler).serve_forever()
