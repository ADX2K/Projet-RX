# Versions utilisées

Relevées le 2026-10-18. On ne monte une version qu'en le notant ici.

| Composant | Version | Source |
|---|---|---|
| Image de base | ubuntu:24.04 | Docker Hub |
| FRRouting | 8.4.4 | paquet Ubuntu 24.04 |
| hsflowd (sFlow) | 2.1.26-1 | compilé (`images/router/Dockerfile`) |
| softflowd (IPFIX) | 1.1.0 + correctif `f5c0f99` | compilé, voir `docs/decisions/ADR-001-export-flux.md` |
| node_exporter | 1.12.1 | release GitHub |
| goflow2 | v2.2.7 | `netsampler/goflow2` sur Docker Hub |
| Containerlab | 0.81.1 | script d'installation officiel |
| Docker Engine | 29.1.3 | paquet Ubuntu (relevé sur le poste d'Adel) |

À ajouter aux jalons suivants : snmp_exporter v0.30.1 (J3), Prometheus v3.15.0,
Alertmanager v0.34.1, Grafana 13.2.4 (J3 à J5).
