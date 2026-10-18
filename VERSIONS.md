# Versions utilisées

Relevées le 2026-10-18. On ne monte une version qu'en le notant ici.

| Composant | Version | Source |
|---|---|---|
| Image de base | ubuntu:24.04 | Docker Hub |
| FRRouting | 8.4.4 | paquet Ubuntu 24.04 |
| hsflowd (sFlow) | 2.1.26-1 | compilé (`images/router/Dockerfile`) |
| softflowd (IPFIX) | 1.1.0 + correctif `f5c0f99` | compilé, voir `docs/decisions/ADR-001-export-flux.md` |
| node_exporter | 1.12.1 | release GitHub |
| goflow2 | v2.2.7 | binaire copié de `netsampler/goflow2` dans l'image `rt3/flowcol` |
| Python (flowcol, alertsink) | 3.12 | `python:3.12-slim` |
| PostgreSQL (alertdb) | 17.11 | `postgres:17.11-alpine` |
| psycopg (pilote PostgreSQL d'alertsink) | 3.3.6 | PyPI, installé dans `rt3/alertsink` |
| Net-SNMP (snmpd) | 5.9.4 | paquet Ubuntu 24.04 |
| snmp_exporter | v0.30.1 | `prom/snmp-exporter` |
| Prometheus | v3.15.0 | `prom/prometheus` |
| Alertmanager | v0.34.1 | `prom/alertmanager` |
| Grafana | 13.2.4 | `grafana/grafana` (l'image `grafana-oss` n'est plus publiée après 13.0.2) |
| Containerlab | 0.81.1 | script d'installation officiel |
| Docker Engine | 29.1.3 | paquet Ubuntu (relevé sur le poste d'Adel) |
