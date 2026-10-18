# Projet 9 : commandes du labo.  `make` affiche la liste des cibles.
LAB  := lab/topology.clab.yml
CLAB := containerlab

# Paramètres modifiables :  make inject S=syn_flood   make campaign S=saturation   make campaign REPS=10
S     ?=
LEVEL ?= N1
REPS  ?= 1
HOURS ?= 1
NAME  ?=
FILES ?=

.DEFAULT_GOAL := help
# Volumes Docker des services qui gardent un état (voir lab/topology.clab.yml).
VOLUMES := rt3p9-prom-snmp rt3p9-prom-flow rt3p9-alertmanager rt3p9-grafana rt3p9-alertdb

.PHONY: help images up down reset-data check traffic flows alerts inject campaign normal calibrate summary test

help: ## Liste les cibles disponibles
	@grep -E '^[a-z]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  make %-9s %s\n", $$1, $$2}'

images: ## Construit les images du labo (rt3/router, host, flowcol, alertsink)
	docker build -t rt3/router:1.0 images/router
	docker build -t rt3/host:1.0 images/host
	docker build -t rt3/flowcol:1.0 images/flowcol
	docker build -t rt3/alertsink:1.0 images/alertsink

up: images ## Déploie le labo (reconstruit les images si besoin)
	$(CLAB) deploy -t $(LAB) --reconfigure

down: ## Détruit le labo (les données des volumes sont gardées)
	$(CLAB) destroy -t $(LAB) --cleanup

reset-data: ## Efface les données gardées : métriques, historique des alertes… (après make down)
	docker volume rm $(VOLUMES)

check: ## Vérifie le labo : réseau, services, flux, supervision
	bash lab/check.sh

traffic: ## Lance le trafic de fond (Ctrl+C pour arrêter)
	python3 src/traffic/bgtraffic.py

flows: ## Affiche le bilan des flux reçus par flowcol, toutes les 10 s (Ctrl+C pour arrêter)
	docker logs -f --tail 10 clab-rt3p9-flowcol

alerts: ## Affiche les alertes reçues par alertsink (Ctrl+C pour arrêter)
	docker logs -f --tail 20 clab-rt3p9-alertsink

inject: ## Lance un incident : make inject S=<nom> (sans S : liste des incidents)
	python3 src/bench/scenarios.py $(S)

campaign: ## Campagne courte (1 répétition par incident) ; S=<incident> pour un seul, REPS=10 pour la complète
	python3 src/bench/campaign.py --level $(LEVEL) --reps $(REPS) $(if $(S),--scenarios $(S))

normal: ## Trafic normal seul, compte les fausses alertes (1 h ; HOURS=3 pour la référence)
	python3 src/bench/normal.py --level $(LEVEL) --hours $(HOURS)

calibrate: ## Mesure les paquets/s du trafic normal (seuils N1, 10 min)
	python3 src/bench/calibrate.py

summary: ## Tableau de résultats : make summary NAME=<dossier> FILES="<csv/json de results/raw>"
	python3 src/analysis/summarize.py --name $(NAME) $(FILES)

test: ## Tests unitaires (flow2prom, alertsink, banc de mesure, synthèse)
	cd src/flow2prom && python3 -m unittest
	cd src/alertsink && python3 -m unittest
	cd src/bench && python3 -m unittest
	cd src/analysis && python3 -m unittest
