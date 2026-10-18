# Projet 9 : commandes du labo.  `make` affiche la liste des cibles.
LAB  := lab/topology.clab.yml
CLAB := containerlab

.DEFAULT_GOAL := help
.PHONY: help images up down check traffic flows

help: ## Liste les cibles disponibles
	@grep -E '^[a-z]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  make %-8s %s\n", $$1, $$2}'

images: ## Construit les images rt3/router et rt3/host
	docker build -t rt3/router:1.0 images/router
	docker build -t rt3/host:1.0 images/host

up: images ## Déploie le labo (reconstruit les images si besoin)
	$(CLAB) deploy -t $(LAB) --reconfigure

down: ## Détruit le labo
	$(CLAB) destroy -t $(LAB) --cleanup

check: ## Vérifie le labo : OSPF, ping, débit, services, flux
	bash lab/check.sh

traffic: ## Lance le trafic de fond (Ctrl+C pour arrêter)
	python3 src/traffic/bgtraffic.py

flows: ## Affiche les flux reçus par goflow2 (Ctrl+C pour arrêter)
	docker logs -f --tail 20 clab-rt3p9-goflow2
