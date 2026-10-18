# Projet 9 — Observabilité : plan de projet (socle sans IA)

> Version 1.1 · 2026-10-18 · statut : **validé** (décisions D1 à D7 adoptées) · base : étude de faisabilité du 2026-10-06 + énoncé « mini-projets RT3 »
> Versions effectivement utilisées : voir `VERSIONS.md`.
>
> **Écarts constatés au jalon J2** (détail dans `docs/decisions/ADR-001-export-flux.md`) :
> - D1 : pas de supervisord ; un `entrypoint.sh` court démarre FRR puis les agents au premier plan (plus simple à lire, messages dans `docker logs`).
> - FRR 8.4.4 (paquet Ubuntu) au lieu de 10.x : suffisant pour OSPFv2/v3.
> - hsflowd et softflowd sont compilés dans l'image (softflowd 1.1.0 + correctif amont pour le faible trafic).
> - Deux commutateurs L2 ajoutés (`sw-hq`, `sw-dc`) pour les LAN à plusieurs hôtes.
>
> **Écarts constatés au jalon J3** (détail dans `docs/protocole-mesure.md`) :
> - Incidents et banc de mesure réunis dans `src/bench/` (au lieu de `src/scenarios/` et `src/campaign/`).
> - `alertsink` écrit les alertes sur sa sortie standard (`docker logs`) au lieu d'un fichier `alerts.jsonl` : pas de problème de droits sur les fichiers.
> - Grafana : image `grafana/grafana` (l'image `grafana-oss` n'est plus publiée).
> - SYN flood mesuré à ≈ 3800 SYN/s (hping3 n'atteint pas les 5000/s visés).
> - Seuil N1 `HighPacketRate` = 1300 paquets/s, calibré sur le trafic de fond (`make calibrate`).

## 0. En bref

- **But** : migrer une supervision SNMP à 5 min vers de la télémétrie de flux (sFlow/IPFIX) + métriques haute fréquence (Prometheus/Grafana/Alertmanager), et **mesurer le gain**.
- **8 jalons = 8 semaines** (J1 = S1 … J8 = S8). Chaque jalon a des livrables numérotés (`L5.3` = 3e livrable du jalon 5) et un critère de sortie.
- **IA retirée** du socle (options en §11). Comparaison sur **2 niveaux** : N1 = SNMP 5 min + seuils fixes ; N2 = flux + Prometheus 1 s + seuils fixes.
- Le jalon de migration reste en **S5** (imposé par le sujet) ; la place libérée par l'IA (S6–S7) sert à fiabiliser les mesures et à valider les flux.
- Quelques points de l'étude sont à corriger avant de coder (§2, surtout **P1** et **P2**).

## 1. Périmètre et correspondance avec l'énoncé

**Dans le périmètre** : réseau d'entreprise simulé (6 routeurs FRR, hôtes, services), IPv4 + IPv6, SNMP, sFlow, IPFIX, Prometheus, Grafana, Alertmanager, 5 scénarios d'incident, mesures comparatives, rapport, démo.
**Hors périmètre (pour l'instant)** : Isolation Forest / autoencodeur, assistant LLM via MCP, LibreNMS, ntopng.

| Exigence de l'énoncé (sujet 9) | Livrables |
|---|---|
| Déploiement initial : SNMP toutes les 5 min | L3.1–L3.3 |
| Injection d'incidents + délai de détection SNMP | L3.4–L3.6, L4.1–L4.3 |
| Migration : sFlow/IPFIX, Prometheus, Grafana, alertes, top talkers | L5.1–L5.7 |
| Alertes : saturation, micro-rafale, scan, SYN flood, DNS | L3.4, L5.6 |
| Compromis échantillonnage / précision / surcharge | L6.4–L6.6 |
| Indicateurs : délai, FP/FN, granularité, surcharge CPU + bande passante, effet de l'échantillonnage | §9, L4.3, L6.2–L6.6 |
| Analyse Wireshark des exports (S7) | L7.1 |
| Rapport + démo en direct (S8) | L8.1–L8.3 |

## 2. Architecture cible et précisions par rapport à l'étude

```
 RÉSEAU SIMULÉ (Containerlab, plan de données)
   h-user1 h-user2            h-web h-dns h-iperf
        \   /                      \  |  /
        [r-hq] ──┐              ┌─ [r-dc]
                 [r-core1] ═══ [r-core2]
        [r-br1] ─┘              └─ [r-br2] ── h-atk
           │
         h-br1                  6 routeurs FRR · OSPFv2/v3 · IPv4+IPv6

 RÉSEAU DE GESTION hors-bande (172.20.30.0/24, toute la télémétrie passe ici)
   routeurs ─ SNMP udp/161 ──► snmp_exporter :9116 ──► prom-snmp  :9091 (scrape 300 s)
   routeurs ─ node_exporter :9100 (1 s) ─────────────► prom-flow  :9090 (scrape 1 s) ◄─ flow2prom :9199
   routeurs ─ sFlow udp/6343 + IPFIX udp/4739 ──► goflow2 ─ JSON ─► flow2prom (à écrire)
   prom-snmp, prom-flow ──► Alertmanager :9093 ──► alertsink :9095 (journal horodaté = vérité de mesure)
   Grafana :3000 lit les deux Prometheus
```

| # | Précision | Pourquoi (et conséquence sur le plan) |
|---|---|---|
| **P1** | **goflow2 ne produit pas de métriques par flux.** Son README le dit : « *entry point of a pipeline — storage, transport, enrichment, graphing, alerting are not provided* ». Ses métriques Prometheus ne décrivent que son propre fonctionnement. | L'étude écrit « goflow2 expose des métriques » : c'est insuffisant pour le *top talkers*, le scan ou le SYN flood. → Il faut un petit service **`flow2prom`** (Python) qui lit le JSON de goflow2, agrège par fenêtre et expose `/metrics`. C'est le **vrai chantier de J5** ; on le démarre dès J3 (L3.8). |
| **P2** | **Un scrape à 300 s est au bord de la péremption Prometheus** (`--query.lookback-delta` = 5 min, réglage *global*) : les séries SNMP « clignotent » dans les requêtes instantanées ; la doc recommande ≤ 2 min. | → **Deux instances Prometheus** : `prom-snmp` (300 s, `--query.lookback-delta=10m`, règles en `rate(...[10m])`) et `prom-flow` (1 s). Bonus : comparaison A/B propre et surcharge mesurée séparément. |
| **P3** | **`ifHighSpeed` d'un veth = 10 Gb/s**, pas la capacité réelle. Un lien « saturé à 100 % » n'existe pas sans limitation. | → Imposer la capacité avec `tc tbf` (ex. 100 Mb/s sur les liens agences), garder **une table unique des capacités**, exprimer les seuils en bits/s. |
| **P4** | **`group_wait` d'Alertmanager vaut 30 s par défaut** : il fausse le délai de détection. | → `group_wait: 0s`, et documenter `T_notification` dans le protocole (§9). |
| **P5** | **Le SNMP à 300 s mesure surtout la phase** (où tombe l'incident dans le cycle de sondage). | → Injecter à des instants **aléatoires** dans le cycle ; sinon les 10 répétitions donnent le même biais. La campagne N1 dure ≈ 8 h de machine → **à automatiser et lancer de nuit** (§9). |
| **P6** | **Double comptage** : en mode `pcap`, hsflowd/softflowd voient un paquet en entrée *et* en sortie de routeur. | → Choisir les points de mesure (D6), sinon l'étude « volume estimé vs réel » est faussée. |
| **P7** | **Le poste n'est pas un PC Linux** (Windows 11). | → Tout tourne dans **WSL2 Ubuntu 24.04** (déjà présent, Docker OK, Containerlab à installer) ; voir §6.1. |

## 3. Décisions techniques à trancher

| # | Question | Options | Recommandation | À décider |
|---|---|---|---|---|
| D1 | Image des routeurs | A : `quay.io/frrouting/frr:10.7.1` (Alpine) + `apk` ; hsflowd à compiler. B : `ubuntu:24.04` + FRR (apt/dépôt FRR) + `snmpd`, `softflowd` (apt) + hsflowd (.deb des releases) | **B** : tous les paquets existent, même base que les hôtes (couches Docker partagées). Un *superviseur de processus* (supervisord) lance frr, snmpd, hsflowd, softflowd, node_exporter, activables par variable d'env (`ENABLE_SNMP`, `ENABLE_FLOW`) → mêmes images pour « sans télémétrie / SNMP / flux ». | fin de L2.1 |
| D2 | Un ou deux Prometheus | 1 ou 2 | **2** (voir P2) | maintenant |
| D3 | Du flux aux métriques | `flow2prom` maison ; ntopng/pmacct + traitement a posteriori | **`flow2prom`** ; repli = pmacct → CSV (perte du temps réel) | maintenant |
| D4 | Où vit la stack de supervision | dans la topologie Containerlab ; docker-compose externe | **dans Containerlab** (même réseau de gestion, IP statiques, un seul `make up`) | fin de L2.2 |
| D5 | Chemin de la télémétrie | hors-bande (réseau de gestion) ; en bande | **hors-bande** : n'influence pas les liens simulés ; surcharge mesurée sur `eth0` des routeurs | maintenant |
| D6 | Points de mesure flux | toutes les interfaces ; bordure seulement | **interfaces d'accès/agences + un lien cœur** (anti double comptage, P6) | J1 (topologie) |
| D7 | Langue | tout FR ; tout EN ; mixte | **identifiants en anglais, commentaires/README/rapport en français** | maintenant |

## 4. Jalons et livrables

Rôles (issus de l'énoncé) : **CP** chef de projet · **RES** réseau & trafic de fond (2) · **SUP** supervision (2) · **SCA** scénarios & alertes (2) · **WSH** analyse Wireshark (1).
*« Dép. »* = livrables à terminer avant de commencer celui-ci.

### J1 — S1 · Cadrage et socle de travail
| ID | Livrable | Resp. | Dép. |
|---|---|---|---|
| L1.1 | Étude de faisabilité (**fait**, 06/10) | CP | — |
| L1.2 | Plan de projet validé par le groupe (ce document) | CP | L1.1 |
| L1.3 | Topologie cible : schéma + tableau nœuds / liens / capacités | RES | L1.1 |
| L1.4 | Plan d'adressage IPv4 / IPv6 / gestion (`docs/adressage.md` + `lab/addressing.yml`) | RES | L1.3 |
| L1.5 | Catalogue des métriques : métrique → source (SNMP / flux / node) → période → usage | SUP | L1.3 |
| L1.6 | Matrice de prérequis par membre (WSL2/Docker/Containerlab/RAM) | tous | — |
| L1.7 | Dépôt Git, conventions (§7), `Makefile`, `make lint` | CP | — |
| L1.8 | Réponses de l'enseignant : IA obligatoire ? nb min d'incidents ? format de la démo ? | CP | L1.2 |

**Sortie** : topologie + adressage validés ; L1.6 tout vert (sinon plan B : un PC « serveur » partagé).

### J2 — S2 · Réseau, trafic de fond, spike d'export de flux
| ID | Livrable | Resp. | Dép. |
|---|---|---|---|
| L2.1 | Images `rt3/router` et `rt3/host` (`make images`) ; test des options D1-A/B | RES | L1.6, L1.7 |
| L2.2 | `topology.clab.yml` + configs FRR (OSPFv2/v3, v4+v6) | RES | L1.4, L2.1 |
| L2.3 | Capacités de lien (`tc tbf`) + table unique des capacités (P3) | RES | L2.2 |
| L2.4 | Services : DNS, HTTP, serveur iperf3 | RES | L2.2 |
| L2.5 | `bgtraffic` : trafic de fond avec profils creux/pleine charge, **graine** rejouable | RES + SCA | L2.4 |
| L2.6 | **Spike flux** : 1 routeur exporte sFlow + IPFIX → goflow2 → JSON ; preuve par `tcpdump`. Décide D1/D6. | SUP + WSH | L2.2 |
| L2.7 | `make check` : smoke tests (voisins OSPF full, ping v4/v6 entre sites, cibles Prometheus `up`) | CP | L2.2 |

**Sortie** : ping + iperf3 entre tous les sites en IPv4 et IPv6, OSPF full, **un export reçu** par goflow2.
**Repli** si l'export échoue en conteneur : exporter depuis un pont Linux / Open vSwitch (sFlow natif), comme prévu dans l'étude.

### J3 — S3 · Supervision SNMP, scénarios, banc de mesure
| ID | Livrable | Resp. | Dép. |
|---|---|---|---|
| L3.1 | `snmpd` dans les routeurs + `snmp_exporter` (IF-MIB, mémoire/CPU) | SUP | L2.2 |
| L3.2 | `prom-snmp` (300 s) + Alertmanager (`group_wait: 0s`) + `alertsink` (journal horodaté) | SUP + SCA | L3.1 |
| L3.3 | Dashboard Grafana « SNMP » (JSON versionné, provisionné) | SUP | L3.2 |
| L3.4 | 5 scripts d'incident reproductibles + journal de vérité terrain `events.jsonl` | SCA | L2.5, L2.3 |
| L3.5 | **Banc de mesure `campaign`** : matrice scénario×répétition, graine, phase aléatoire, remise à zéro entre runs, sortie CSV | SCA + CP | L3.4, L3.2 |
| L3.6 | Règles d'alerte N1 (seuils fixes SNMP) | SCA | L3.2 |
| L3.7 | Protocole de mesure (1 page, §9 mis au propre) | CP | L3.4 |
| L3.8 | `flow2prom` : squelette + tests sur les JSON du spike (**avance sur J5**) | WSH + SUP | L2.6 |

**Sortie** : un run à blanc de bout en bout (1 incident → ligne CSV) ; dashboard SNMP ; scripts rejouables avec la même graine.

### J4 — S4 · Campagne de référence SNMP
| ID | Livrable | Resp. | Dép. |
|---|---|---|---|
| L4.1 | Campagne N1 : 5 incidents × 10 répétitions (brut + manifest) | SCA | L3.5, L3.6 |
| L4.2 | Sessions de trafic normal N1 (mesure des faux positifs / h) | SCA | L3.5 |
| L4.3 | Tableau de mesures N1 : médiane, min–max, détecté oui/non, granularité | SUP | L4.1 |
| L4.4 | Fiche « limites du SNMP observées » (brouillon du rapport) | CP | L4.3 |
| L4.5 | Tag Git `J4-baseline-snmp` + gel de la configuration | CP | L4.1 |

**Sortie** : 10 répétitions par incident, résultats versionnés. Attendu à vérifier (pas un résultat) : la micro-rafale n'est pas vue.

### J5 — S5 · Migration (jalon imposé)
| ID | Livrable | Resp. | Dép. |
|---|---|---|---|
| L5.1 | Export de flux activé : hsflowd (N=512 par défaut) + softflowd (IPFIX) | RES | L2.6, L2.1 |
| L5.2 | goflow2 en conteneur (sFlow `:6343`, IPFIX `:4739`) | SUP | L5.1 |
| L5.3 | `flow2prom` v1 : débit par site/proto, SYN, SYN-ACK, ports destination distincts par source, requêtes DNS | SUP + WSH | L3.8, L5.2 |
| L5.4 | `node_exporter` dans les routeurs + `prom-flow` (scrape 1 s) | SUP | L2.3 |
| L5.5 | Grafana : top talkers v4/v6, micro-rafales, SNMP vs 1 s côte à côte | SUP | L5.3, L5.4 |
| L5.6 | Règles N2 pour les 5 incidents (seuils initiaux) | SCA | L5.3, L5.4, L3.2 |
| L5.7 | Tag `J5-migration-v1` + note de migration (ce qui change avant/après) | CP | L5.6 |

**Sortie** : au moins une alerte correcte pour **chacun** des 5 incidents.
**Repli** : si `flow2prom` glisse, alerter d'abord saturation/micro-rafale avec `node_exporter` seul (déjà haute fréquence), puis ajouter scan/SYN/DNS.

### J6 — S6 · Mesures N2 et compromis échantillonnage / surcharge
| ID | Livrable | Resp. | Dép. |
|---|---|---|---|
| L6.1 | Réglage des seuils (valeurs + justification) | SCA | L5.6 |
| L6.2 | Campagne N2 : 5 × 10 répétitions | SCA | L6.1, L3.5 |
| L6.3 | Sessions de trafic normal N2 (faux positifs / h) | SCA | L6.1 |
| L6.4 | Étude de l'échantillonnage N = 64 / 512 / 2048 : volume estimé vs réel (iperf3), erreur vs théorie `196/√c %` | SUP | L5.1, L5.3 |
| L6.5 | Étude des timeouts IPFIX (actif 60 / 10 / 5 s) : délai vs volume exporté | SUP | L5.1 |
| L6.6 | Surcharge : CPU routeur et bande passante d'export pour 3 configurations (sans télémétrie / SNMP / flux N) | RES | L5.1, L3.1 |
| L6.7 | Archive du trafic normal (flows JSON + pcap) — utile à l'option IA | WSH | L6.3 |

**Sortie** : tableaux N2 complets + surcharge. **Porte de décision « options » (§11)** à la revue de fin de S6.

### J7 — S7 · Validation et analyse
| ID | Livrable | Resp. | Dép. |
|---|---|---|---|
| L7.1 | Analyse Wireshark : décodage des paquets sFlow/IPFIX, comparaison avec la capture réelle (paquets/octets) | WSH | L6.4, L6.5 |
| L7.2 | Analyse comparative N1 vs N2 (délai, FP/FN, granularité, surcharge) : graphes + tableaux | SUP + SCA | L4.3, L6.2, L6.3 |
| L7.3 | Reproductibilité : `make up && make check && make campaign` depuis un clone propre sur ≥ 2 PC | CP + RES | tous |
| L7.4 | Rapport : plan + sections rédigées (contexte, architecture, méthode, résultats) | tous | L4.4, L7.2 |
| L7.5 | *(option)* extension IA si la porte est ouverte | — | porte §11 |

**Sortie** : comparaison des 2 niveaux + validation des flux par captures.

### J8 — S8 · Rapport et démonstration
| ID | Livrable | Resp. | Dép. |
|---|---|---|---|
| L8.1 | Rapport d'ingénierie final | tous | L7.4 |
| L8.2 | Script de démo `make demo` (micro-rafale + scan, SNMP et flux côte à côte) | SCA | L7.3 |
| L8.3 | Répétition générale chronométrée (≥ 1) + plan B (captures/vidéo si le labo plante) | CP | L8.2 |
| L8.4 | Dépôt final tagué `v1.0` + archive d'images `docker save` | CP | L8.1 |

**Sortie** : rapport rendu, démo répétée.

## 5. Dépendances entre livrables

**Chemin critique** : `L2.1 → L2.2 → L3.4 → L3.5 → L4.1 → L5.6 → L6.2 → L7.2 → L8.1`
**Deuxième chaîne (flux)** : `L2.6 → L3.8 → L5.3 → L5.6`. Si elle prend du retard, c'est elle qui bloque J5 : d'où le démarrage de `flow2prom` en S3.

Points de blocage à surveiller : `L2.1` (images) bloque tout ; `L3.5` (banc de mesure) bloque les deux campagnes ; `L5.3` bloque les règles N2.
Charge : WSH n'attend pas S7 — capture/validation du spike en S2, `flow2prom` en S3–S5.

Revue de **15 min** en fin de chaque semaine : on vérifie le critère de sortie ; un critère manqué déclenche le repli du registre des risques (§10). La livraison de base (J1–J6) prime sur toute extension.

## 6. Ressources et dépendances logicielles

### 6.1 Poste de travail
| Élément | Cible | Notes |
|---|---|---|
| OS | Linux natif **ou** WSL2 Ubuntu 24.04 (Windows 11) | noyau ≥ 5.15, cgroup v2 |
| Docker Engine | ≥ 24 (dans WSL, pas besoin de Docker Desktop) | l'utilisateur doit être dans le groupe `docker` |
| Containerlab | **0.81.1** (dernière vue) — à figer | s'exécute avec `sudo` |
| Python | 3.12 (celui d'Ubuntu 24.04) + venv | |
| Outils | `make`, `git`, `jq`, `curl`, `tcpdump`, `shellcheck`, `yamllint` | Wireshark côté Windows, ouvre les `.pcap` via `\\wsl$\Ubuntu-24.04\…` |
| Validation de config | `promtool`, `amtool` | utilisables via `docker run --entrypoint promtool prom/prometheus …` |

**État de ton PC (relevé le 2026-10-18)** : Windows 11, **31,5 Go de RAM**, 16 cœurs logiques, 149 Go libres sur D:. WSL2 Ubuntu 24.04 (noyau 6.18, systemd, cgroup v2) ; Docker Engine 29.1.3 **fonctionnel** ; `git`, `make`, `python3` présents ; **Containerlab absent** ; pas de `.wslconfig` (WSL limité à ~15 Go par défaut). → ton PC convient comme **machine de campagne** du groupe.

### 6.2 Images Docker
Toujours un tag explicite (jamais `latest`) ; on note aussi le *digest* dans `VERSIONS.md`.

| Rôle | Image | Version vue | Port(s) |
|---|---|---|---|
| Routeur (maison) | `rt3/router:1.0` ← `ubuntu:24.04` + FRR + snmpd + hsflowd + softflowd + node_exporter | FRR 10.7.1 (ou paquet distro) · hsflowd 2.1.26-1 · softflowd 1.1.1 (ou apt) · node_exporter 1.12.1 | 161/udp, 9100 |
| Hôte (maison) | `rt3/host:1.0` ← `ubuntu:24.04` + iperf3, hping3, nmap, dnsutils, curl, python3, nginx, DNS (unbound/dnsmasq) | — | — |
| Collecteur de flux | `netsampler/goflow2` | v2.2.7 | 6343/udp (sFlow), 4739/udp (IPFIX), 8080 (ses métriques) |
| Flux → métriques (maison) | `rt3/flow2prom:1.0` ← `python:3.12-slim` | — | 9199 |
| Exporter SNMP | `prom/snmp-exporter` | v0.30.1 | 9116 |
| Prometheus ×2 | `prom/prometheus` | v3.15.0 | 9091 (snmp), 9090 (flow) |
| Alertmanager | `prom/alertmanager` | v0.34.1 | 9093 |
| Récepteur d'alertes (maison) | `rt3/alertsink:1.0` ← `python:3.12-slim` | — | 9095 *(pas 9094 : port de gossip d'Alertmanager)* |
| Tableaux de bord | `grafana/grafana-oss` | 13.2.4 | 3000 |

> Sur les tags : l'image FRR officielle existe en `quay.io/frrouting/frr:10.7.1` ; pour les autres, confirmer par `docker pull` en J1.

### 6.3 Bibliothèques Python (épinglées `==` dans `requirements.txt`)
`prometheus-client`, `PyYAML`, `requests`, `pytest`, `ruff` ; analyse : `pandas`, `matplotlib` ; options : `jinja2` (génération des `frr.conf` depuis `addressing.yml`), `dnspython` (anomalie DNS), `scapy`.

### 6.4 Budget de ressources (estimations, à valider en J2)
| Composant | Qté | RAM unitaire | Total |
|---|---|---|---|
| Routeurs `rt3/router` (FRR + snmpd + hsflowd + softflowd + node_exporter) | 6 | 100–200 Mo | 0,6–1,2 Go |
| Hôtes `rt3/host` | 7 | 20–60 Mo | 0,15–0,4 Go |
| goflow2 + flow2prom | 2 | 50–150 Mo | 0,1–0,3 Go |
| Prometheus | 2 | 0,2–0,6 Go | 0,4–1,2 Go |
| Alertmanager, alertsink, snmp_exporter | 3 | 20–50 Mo | ~0,15 Go |
| Grafana | 1 | 0,15–0,3 Go | ~0,3 Go |
| Docker + WSL2 (surcoût) | — | — | 1–2 Go |
| **Total** | | | **≈ 3–5,5 Go** |

- **WSL2** : allouer 8 Go (PC 16 Go) ; 12–16 Go sur ton PC. **CPU** : 4 cœurs minimum ; un `hping3 --flood` ou un iperf3 à 100 Mb/s peut saturer 1–2 cœurs.
- **Disque** : images ≈ 3–5 Go ; Prometheus (rétention 7 j) < 2 Go ; captures et flux archivés 5–20 Go → prévoir **30–50 Go** (comme l'étude).
- **Réseau de l'école** : pré-télécharger les images, puis partager une archive `make bundle` (`docker save`) par clé USB/NAS.

### 6.5 Adresses et ports (proposition à valider en L1.4)
- IPv4 : `10.9.<site>.0/24` (HQ=1, DC=2, BR1=3, BR2=4) · P2P `10.9.250.0/24` en /31 · loopbacks `10.9.255.<n>/32`.
- IPv6 (ULA, labo) : `fd00:9:<site>::/64` · P2P `fd00:9:fa::/64` en /127 · loopbacks `fd00:9:ff::<n>/128`.
- Gestion : `172.20.30.0/24` — routeurs `.11–.16`, hôtes `.101–.107`, services `.50–.57` (goflow2 .50, flow2prom .51, prom-snmp .52, prom-flow .53, alertmanager .54, grafana .55, snmp-exporter .56, alertsink .57). **IP statiques** déclarées dans la topologie.

## 7. Style de code et conventions

| Domaine | Règle | Contrôle |
|---|---|---|
| **Python** | 3.12 ; PEP 8, ligne ≤ 100 ; annotations de type sur les fonctions publiques ; CLI en `argparse`, logs en `logging` (pas de `print`) ; horodatage `time.time_ns()` (UTC), ISO 8601 dans les CSV ; aucune valeur magique (config YAML ou variable d'env) | `ruff check`, `ruff format`, `pytest` |
| **Shell** | `bash`, `set -euo pipefail`, variables entre guillemets, scripts **idempotents**, pas de chemin absolu en dur | `shellcheck` |
| **YAML** | 2 espaces, pas de tabulation | `yamllint`, `promtool check config/rules`, `amtool check-config` |
| **FRR** | un `frr.conf` par routeur ; commentaire d'en-tête (rôle, interfaces) ; sections séparées par `!` ; généré depuis `addressing.yml` si Jinja | `make check` (voisins OSPF) |
| **Dockerfile** | base épinglée, `--no-install-recommends`, pas de `latest`, un seul gestionnaire de processus | `hadolint` (option) |
| **Nommage** | nœuds `r-<rôle>` / `h-<rôle>` ; métriques maison préfixées `rt3_`, `snake_case`, unité en suffixe (`_bytes_total`, `_seconds`, `_bps`) ; **cardinalité bornée** (jamais le port source en label) | `promtool check metrics` |
| **Données de mesure** | CSV UTF-8, 1 ligne = 1 répétition, colonnes fixes (§9) ; `run_id = AAAAMMJJ-HHMMSS-<niveau>-<scénario>-<rep>` ; un `manifest.json` par campagne (commit Git, digests d'images, N, timeouts, graine) | `make lint` |
| **Git** | `main` protégée ; branches `feat/J5-flow2prom` ; commits *Conventional Commits* (`feat:`, `fix:`, `docs:`, `chore:`) ; PR relue par **un membre d'un autre rôle** ; tag à chaque sortie de jalon ; 1 *issue* par livrable (`L5.3`) étiquetée `J5` | revue de PR |
| **Docs** | Markdown dans `docs/` ; décisions en **ADR** courts (`docs/decisions/ADR-001-….md` : contexte, décision, conséquences) ; un README par composant (quoi / lancer / tester) | |
| **Langue** | identifiants en anglais ; commentaires, README, rapport en français | |
| **Définition de « terminé »** | (1) dans Git, (2) relancé depuis zéro par **un autre** membre via `make`, (3) README à jour, (4) lint vert, (5) montré à la revue de fin de semaine | |

**Cibles `make`** : `setup · images · up · down · check · lint · test · campaign LEVEL=1|2 · demo · bundle`.

**Arborescence proposée**
```
projet9/
├─ README.md  Makefile  VERSIONS.md  .editorconfig  pyproject.toml  requirements.txt
├─ docs/            (plan, adressage, decisions/ADR-*, schemas, rapport/)
├─ images/          (router/  host/  flow2prom/  alertsink/  — Dockerfile + entrypoint)
├─ lab/             (topology.clab.yml, addressing.yml, configs/<noeud>/{daemons,frr.conf,snmpd.conf,hsflowd.conf}, tc/)
├─ monitoring/      (prometheus-snmp/, prometheus-flow/, alertmanager/, snmp_exporter/, grafana/{provisioning,dashboards})
├─ src/             (flow2prom/  alertsink/  traffic/  scenarios/  campaign/  analysis/)
├─ results/         (raw/<campagne>/…  summary/)   captures/ (pcap, hors Git)   tests/
```

## 8. Configurations nécessaires

| Fichier | Où | Contenu clé | Jalon |
|---|---|---|---|
| `.wslconfig` | `%UserProfile%` (Windows) | `memory`, `processors`, `swap` | J1 |
| `/etc/wsl.conf` | WSL | `[boot] systemd=true` (déjà actif chez toi) | J1 |
| `topology.clab.yml` | `lab/` | nœuds, liens, IP de gestion statiques, `binds`, `exec` (sysctl, IP des hôtes) | J2 |
| `daemons`, `frr.conf` | `lab/configs/<nœud>/` | `zebra`, `ospfd`, `ospf6d` ; interfaces v4+v6 ; `router-id` | J2 |
| `tc-setup.sh` | `lab/tc/` | `tc tbf` par interface selon la table des capacités | J2 |
| `snmpd.conf` | idem | communauté lecture seule, `agentaddress` v4+v6 | J3 |
| `generator.yml` / `snmp.yml` | `monitoring/snmp_exporter/` | module IF-MIB, `auth` v2c | J3 |
| `prometheus.yml` ×2 + `rules/*.yml` | `monitoring/` | scrape 300 s + `lookback-delta` / scrape 1 s ; règles N1 / N2 | J3 / J5 |
| `alertmanager.yml` | `monitoring/alertmanager/` | `group_wait: 0s`, webhook vers `alertsink` | J3 |
| `hsflowd.conf`, ligne de commande `softflowd` | `lab/configs/` / entrypoint | N, `polling`, collecteur ; timeouts actif/inactif, `expint` | J5 |
| commande `goflow2` | `lab/` | `-listen`, format JSON, sortie vers `flow2prom` | J5 |
| `provisioning/` + `dashboards/*.json` | `monitoring/grafana/` | sources de données (2 Prometheus), tableaux | J3 / J5 |

Squelettes en **annexe A** (à valider au spike J2/J3).

## 9. Protocole de mesure

**Définitions**
- `t_start` : heure de début de l'incident, écrite par le script d'injection (`events.jsonl`).
- `t_detect` : heure de **réception du webhook** par `alertsink` (identique pour N1 et N2). Délai = `t_detect − t_start`. `startsAt` de l'alerte sert à décomposer `D = T_collecte + T_évaluation + T_for + T_notification`.
- **Détecté** : alerte du bon type (`alertname` ↔ scénario) reçue entre `t_start` et `t_end + fenêtre de grâce` (N1 : 2×300 s + 60 s ; N2 : 60 s).
- **Faux positif** : alerte hors de toute fenêtre d'incident ; taux = FP par heure de trafic normal. **Faux négatif** : incident sans alerte du bon type.
- **Granularité** : plus petite durée de rafale détectée, balayage {1, 2, 5, 10, 30 s}, 3 répétitions chacune.

**Règles de rigueur** : ≥ 10 répétitions ; médiane + min–max ; **injection à phase aléatoire** (P5) ; graine du trafic de fond journalisée ; remise à zéro entre runs (aucune alerte active, compteurs stables) ; mêmes seuils sémantiques aux deux niveaux ; on rapporte aussi les résultats négatifs.

**Colonnes du CSV** : `run_id, level, scenario, rep, seed, t_start_ns, t_end_ns, t_detect_ns, delay_s, detected, alertname, fp_count, sampling_n, ipfix_active_timeout_s, scrape_interval_s`.

**Volumétrie (estimation)** : N1 ≈ 50 runs × ≤ 10 min ≈ **8 h** (nuit, machine dédiée) · N2 ≈ 50 × 2 min ≈ 2 h · échantillonnage 3 × 10 ≈ 1 h · surcharge 3 configs ≈ 1 h.
Bonus possible : les deux Prometheus tournent en parallèle ⇒ une même injection peut être mesurée à N1 et N2 (comparaison « à l'identique »), mais **pas** pour la mesure de surcharge.

## 10. Risques (mis à jour sans l'IA)

| Risque | Gravité | Mitigation |
|---|---|---|
| Exporteurs sFlow/IPFIX capricieux dans les conteneurs | Moyenne | Spike en J2 sur 1 routeur ; repli pont Linux / Open vSwitch |
| **`flow2prom` à écrire** (P1) : effort sous-estimé | Moyenne | Démarrage en J3 sur JSON réels ; repli : alertes saturation/micro-rafale via node_exporter, puis pmacct → CSV |
| Campagne N1 trop longue (≈ 8 h) | Moyenne | Banc automatisé (L3.5), exécution de nuit sur ton PC |
| Mesures faussées (P4, P5, P6) | Moyenne | Protocole L3.7 relu par un autre membre ; ADR pour chaque réglage |
| Trafic de fond trop artificiel → anomalies trop évidentes | Moyenne | Profils variables, graine, validation avec l'enseignant |
| « Ça marche chez moi » (PC hétérogènes, WSL) | Moyenne | Versions épinglées, `make check`, `make bundle`, test sur ≥ 2 PC (L7.3) |
| Mémoire insuffisante sur un PC | Faible | `.wslconfig`, moins de routeurs, PC serveur partagé |
| Retard cumulé | Moyenne | Revue hebdomadaire ; J1–J6 prioritaires ; extensions abandonnées en premier |

## 11. Options après le socle (IA) — non planifiées

| Option | Contenu | Prérequis |
|---|---|---|
| **O1** | Détection non supervisée (Isolation Forest) → métrique `rt3_anomaly_score`, évaluée comme **N3** avec le même banc de mesure | sorties J1–J6 atteintes, ≥ 1 semaine de marge, accord de l'enseignant |
| **O2** | Assistant LLM via MCP (outils en lecture seule sur Prometheus) | O1 terminée |

**Points d'accroche conservés dans le socle** : (1) `flow2prom` expose des métriques adaptées à des *features* ; (2) l'API HTTP de `prom-flow` reste accessible ; (3) L6.7 archive le trafic normal pour l'entraînement ; (4) le banc `campaign` accepte un 3e « détecteur » avec le même format CSV.
**Porte de décision** : revue de fin de S6.

## 12. Questions ouvertes (pour la discussion)

1. **Calendrier réel** : S1 a démarré quand ? date de rendu et de démo ? (l'étude date du 06/10, nous sommes le 18/10 : on est peut-être déjà en S2–S3)
2. **Équipe** : combien de membres, qui prend quel rôle (CP / RES / SUP / SCA / WSH) ?
3. **Machine de campagne** : chaque PC lance son labo, ou un PC « serveur » (le tien) pour les longues campagnes ?
4. **Décisions D1–D7** : d'accord avec les recommandations ?
5. **Enseignant** (M. Karoui) : IA obligatoire ? nombre minimum d'incidents ? format de la démo ? → je peux rédiger le mail.
6. **Dépôt Git** : GitHub / GitLab / autre ? suivi des tâches par *issues* ?

---

## Annexe A — Squelettes de configuration (à valider au spike)

**A.1 `%UserProfile%\.wslconfig`** (puis `wsl --shutdown`)
```ini
[wsl2]
memory=12GB      # PC 16 Go : 8GB
processors=8     # PC 16 Go : 4
swap=4GB
```

**A.2 Installation de Containerlab (dans WSL)**
```bash
bash -c "$(curl -sL https://get.containerlab.dev)" -- -v 0.81.1
sudo containerlab version
```

**A.3 `lab/topology.clab.yml`** (extrait)
```yaml
name: rt3p9
mgmt:
  network: rt3p9-mgmt
  ipv4-subnet: 172.20.30.0/24
topology:
  nodes:
    r-core1:
      kind: linux
      image: rt3/router:1.0
      mgmt-ipv4: 172.20.30.11
      binds:
        - configs/r-core1/daemons:/etc/frr/daemons
        - configs/r-core1/frr.conf:/etc/frr/frr.conf
        - configs/r-core1/snmpd.conf:/etc/snmp/snmpd.conf
        - configs/r-core1/hsflowd.conf:/etc/hsflowd.conf
      exec:
        - sysctl -w net.ipv4.ip_forward=1
        - sysctl -w net.ipv6.conf.all.forwarding=1
    h-web:
      kind: linux
      image: rt3/host:1.0
      mgmt-ipv4: 172.20.30.103
  links:
    - endpoints: ["r-core1:eth1", "r-core2:eth1"]
```

**A.4 FRR — `daemons` et `frr.conf` (extrait)**
```
# daemons
zebra=yes
ospfd=yes
ospf6d=yes
bgpd=no
vtysh_enable=yes
```
```
frr defaults traditional
hostname r-core1
service integrated-vtysh-config
!
interface lo
 ip address 10.9.255.1/32
 ipv6 address fd00:9:ff::1/128
 ip ospf area 0
 ipv6 ospf6 area 0
!
interface eth1
 ip address 10.9.250.0/31
 ipv6 address fd00:9:fa::/127
 ip ospf area 0
 ip ospf network point-to-point
 ipv6 ospf6 area 0
 ipv6 ospf6 network point-to-point
!
router ospf
 ospf router-id 10.9.255.1
!
router ospf6
 ospf6 router-id 10.9.255.1
```

**A.5 Capacité de lien (P3)**
```bash
tc qdisc replace dev eth1 root tbf rate 100mbit burst 256kb latency 50ms
```

**A.6 Export de flux (routeur) et collecteur**
```
# hsflowd.conf (mode pcap ; une ligne pcap par interface mesurée, voir D6)
sflow {
  agent = eth0
  polling = 5
  sampling = 512          # puis 64 et 2048 pour L6.4
  collector { ip = 172.20.30.50  udpport = 6343 }
  pcap { dev = eth1 }
}
```
```bash
# IPFIX : une instance softflowd par interface mesurée ; expint = période de vérification du cache
softflowd -i eth1 -n 172.20.30.50:4739 -P udp -v 10 -t maxlife=10 -t expint=1
# Collecteur (une ligne JSON par flux ; flow2prom la lit, et multiplie par sampling_rate pour sFlow)
goflow2 -listen 'sflow://:6343,netflow://:4739' -format=json -transport.file=/data/flows.jsonl
```

**A.7 Prometheus**
```yaml
# prom-flow : scrape 1 s
global: { scrape_interval: 1s, evaluation_interval: 1s }
alerting:
  alertmanagers: [{ static_configs: [{ targets: ["172.20.30.54:9093"] }] }]
rule_files: ["rules/*.yml"]
scrape_configs:
  - job_name: node
    static_configs: [{ targets: ["172.20.30.11:9100", "172.20.30.12:9100"] }]
  - job_name: flow2prom
    static_configs: [{ targets: ["172.20.30.51:9199"] }]
```
```yaml
# prom-snmp : scrape 300 s ; lancer avec --query.lookback-delta=10m
global: { scrape_interval: 300s, scrape_timeout: 30s, evaluation_interval: 60s }
scrape_configs:
  - job_name: snmp
    metrics_path: /snmp
    params: { module: [if_mib], auth: [public_v2] }
    static_configs: [{ targets: ["172.20.30.11", "172.20.30.12"] }]
    relabel_configs:
      - { source_labels: [__address__], target_label: __param_target }
      - { source_labels: [__param_target], target_label: instance }
      - { target_label: __address__, replacement: "172.20.30.56:9116" }
```

**A.8 Alertmanager et règles d'exemple**
```yaml
route:
  receiver: alertsink
  group_by: [alertname, instance]
  group_wait: 0s            # défaut = 30 s (P4)
  group_interval: 5s
  repeat_interval: 1h
receivers:
  - name: alertsink
    webhook_configs: [{ url: "http://172.20.30.57:9095/alert", send_resolved: true }]
```
```yaml
# N1 (prom-snmp) — seuil absolu en bits/s (capacité réelle imposée par tc, cf. P3)
- alert: LinkSaturation
  expr: rate(ifHCOutOctets{ifDescr=~"eth[1-9]"}[10m]) * 8 > 80e6
# N2 (prom-flow) — valeurs initiales, réglées en L6.1
- alert: LinkSaturation
  expr: rate(node_network_transmit_bytes_total{device=~"eth[1-9]"}[5s]) * 8 > 80e6
  for: 5s
- alert: SynFlood
  expr: rate(rt3_flow_tcp_syn_total[5s]) - rate(rt3_flow_tcp_synack_total[5s]) > 100
  for: 3s
- alert: PortScan
  expr: max by (src_addr) (rt3_flow_distinct_dst_ports) > 50
```
