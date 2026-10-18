# Récepteur d'alertes : Python et le pilote PostgreSQL (historique dans alertdb).
# Le code est monté depuis src/alertsink/ (voir lab/topology.clab.yml) : le modifier
# ne demande pas de reconstruire l'image.
FROM python:3.12-slim
RUN pip install --no-cache-dir "psycopg[binary]==3.3.6"
CMD ["python3", "-u", "/app/alertsink.py"]
