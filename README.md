# Projet 9 : observabilité et détection d'anomalies

Cours Réseaux IP · RT3. On supervise un réseau d'entreprise simulé, d'abord par
SNMP toutes les 5 minutes, puis par export de flux (sFlow, IPFIX) et métriques
à 1 seconde, et on mesure ce que la migration apporte : délai de détection,
faux positifs, surcharge.

- Plan de projet, jalons et livrables : [docs/Plan/plan-projet.md](docs/Plan/plan-projet.md)
- Architecture de projet : [docs/Plan/Architecture.html](docs/Plan/Architecture.html)
- Plan d'adressage : [docs/adressage.md](docs/adressage.md)
- Protocole de mesure : [docs/protocole-mesure.md](docs/protocole-mesure.md)
- Décisions techniques : [docs/decisions/](docs/decisions/)
- Versions : [VERSIONS.md](VERSIONS.md)

## Prérequis (une fois par poste)

1. Linux, ou Windows 11 avec WSL2 (Ubuntu 24.04).
2. Docker Engine dans WSL, avec ton utilisateur dans le groupe `docker`.
3. Containerlab 0.81.1 :
   ```bash
   bash -c "$(curl -sL https://get.containerlab.dev)" -- -v 0.81.1
   ```
   puis ouvre un nouveau terminal : l'installeur t'ajoute au groupe `clab_admins`,
   ce qui permet de lancer `containerlab` sans `sudo`.
4. Le dépôt dans le système de fichiers Linux (`~/projet9`), pas sous `/mnt/c` ou `/mnt/d`.
   Sous Windows, ouvre-le dans VS Code avec l'extension WSL : `code ~/projet9`.

## Utilisation

```bash
make up        # construit les images et déploie le labo (quelques minutes la première fois)
make check     # vérifie réseau, services, flux et supervision
make traffic   # trafic de fond (Ctrl+C pour arrêter)
make flows     # affiche les flux reçus par goflow2
make alerts    # affiche les alertes reçues par alertsink
make inject S=syn_flood         # lance un incident (make inject seul : liste)
make campaign LEVEL=N1 REPS=10  # campagne de mesure, résultats dans results/raw/
make test      # tests unitaires
make down      # détruit le labo
```

Depuis le navigateur Windows :

| Service | Adresse | Rôle |
|---|---|---|
| Grafana | http://localhost:3000 | tableaux de bord (dossier « Projet 9 ») |
| prom-snmp | http://localhost:9091 | Prometheus du niveau N1 (SNMP toutes les 5 min) |
| Alertmanager | http://localhost:9093 | alertes actives |

Se connecter à un nœud :

```bash
docker exec -it clab-rt3p9-r-core1 vtysh    # console FRR (show ip ospf neighbor…)
docker exec -it clab-rt3p9-h-user1 bash     # shell d'un hôte
docker logs clab-rt3p9-r-br1                # démarrage d'un nœud et messages des agents
```

## Organisation

```
images/router/      image des routeurs : FRR + agents de télémétrie (Dockerfile, entrypoint.sh)
images/host/        image des hôtes, serveurs et commutateurs
lab/topology.clab.yml   tous les nœuds, leurs rôles et les liens
lab/frr/            une config FRR par routeur (+ daemons, commun)
lab/snmp/           config de l'agent SNMP (commune aux routeurs)
lab/check.sh        vérification du labo
monitoring/         configs de Prometheus, Alertmanager et Grafana (tableaux de bord en JSON)
src/traffic/        trafic de fond
src/bench/          incidents (scenarios.py) et banc de mesure (campaign.py)
src/alertsink/      récepteur d'alertes horodaté
src/flow2prom/      conversion des flux goflow2 en métriques (J5) et ses tests
docs/               plan, adressage, protocole de mesure, décisions
results/raw/        résultats des campagnes (hors Git)
```

Un nœud se règle à un seul endroit : sa section dans `lab/topology.clab.yml`
(groupe, adresse de gestion, variables d'environnement). Les variables
disponibles sont listées en tête de chaque `entrypoint.sh`.

## Conventions

- Identifiants et noms de fichiers en anglais ; commentaires, docs et rapport en français.
- Chaque fichier de config commence par un commentaire qui dit à quoi il sert.
- Pas de valeur cachée : ce qui change d'un nœud à l'autre est dans la topologie.
- Les scripts sont lancés par `bash` ou `python3` explicitement : pas besoin de bit exécutable.
- Toute version d'outil est épinglée et notée dans `VERSIONS.md`.
