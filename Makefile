# Projet 9 : commandes du labo.  `make` affiche la liste des cibles.
LAB  := lab/topology.clab.yml
CLAB := containerlab

# Paramètres modifiables :  make inject S=syn_flood   make campaign LEVEL=N1 REPS=10
S     ?=
LEVEL ?= N1
REPS  ?= 10

.DEFAULT_GOAL := help
.PHONY: help images up down check traffic flows alerts inject campaign calibrate test

help: ## Liste les cibles disponibles
	@grep -E '^[a-z]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  make %-9s %s\n", $$1, $$2}'

images: ## Construit les images rt3/router et rt3/host
	docker build -t rt3/router:1.0 images/router
	docker build -t rt3/host:1.0 images/host

up: images ## Déploie le labo (reconstruit les images si besoin)
	$(CLAB) deploy -t $(LAB) --reconfigure

down: ## Détruit le labo
	$(CLAB) destroy -t $(LAB) --cleanup

check: ## Vérifie le labo : réseau, services, flux, supervision
	bash lab/check.sh

traffic: ## Lance le trafic de fond (Ctrl+C pour arrêter)
	python3 src/traffic/bgtraffic.py

flows: ## Affiche les flux reçus par goflow2 (Ctrl+C pour arrêter)
	docker logs -f --tail 20 clab-rt3p9-goflow2

alerts: ## Affiche les alertes reçues par alertsink (Ctrl+C pour arrêter)
	docker logs -f --tail 20 clab-rt3p9-alertsink

inject: ## Lance un incident : make inject S=<nom> (sans S : liste des incidents)
	python3 src/bench/scenarios.py $(S)

campaign: ## Campagne de mesure : make campaign LEVEL=N1 REPS=10
	python3 src/bench/campaign.py --level $(LEVEL) --reps $(REPS)

calibrate: ## Mesure les paquets/s du trafic normal (seuils N1, 10 min)
	python3 src/bench/calibrate.py

test: ## Tests unitaires (flow2prom, banc de mesure)
	cd src/flow2prom && python3 -m unittest
	cd src/bench && python3 -m unittest
