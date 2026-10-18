#!/usr/bin/env bash
# Démarrage du collecteur de flux rt3/flowcol.
#
# goflow2 écoute sFlow (udp/6343) et IPFIX (udp/4739) et écrit une ligne JSON par
# flux ; flow2prom les lit sur son entrée standard et expose les métriques (:9199).
# Journal de goflow2 et bilan de flow2prom toutes les 10 s :  docker logs clab-rt3p9-flowcol
#
# Variable d'environnement (fixée dans lab/topology.clab.yml) :
#   ROUTERS   correspondance adresse de gestion -> nom, ex. "172.20.30.15=r-br1 ..."
set -euo pipefail

goflow2 -listen=sflow://:6343,netflow://:4739 -format=json \
  | python3 -u /app/flow2prom.py
