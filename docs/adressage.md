# Plan d'adressage du labo rt3p9

Source de vérité : `lab/topology.clab.yml` (nœuds, liens, adresses des hôtes)
et `lab/frr/*.conf` (adresses des routeurs). Ce document les résume.

## Préfixes

| Usage | IPv4 | IPv6 |
|---|---|---|
| LAN siège (HQ) | 10.9.1.0/24 | fd00:9:1::/64 |
| LAN datacenter (DC) | 10.9.2.0/24 | fd00:9:2::/64 |
| LAN agence 1 (BR1) | 10.9.3.0/24 | fd00:9:3::/64 |
| LAN agence 2 (BR2) | 10.9.4.0/24 | fd00:9:4::/64 |
| Liens point à point | 10.9.250.0/24 en /31 | fd00:9:fa::/64 en /127 |
| Loopbacks des routeurs | 10.9.255.0/24 en /32 | fd00:9:ff::/64 en /128 |
| Réseau de gestion (hors-bande) | 172.20.30.0/24 | — |

Toujours la même règle : la passerelle d'un LAN est `.1` (ou `::1`), les hôtes commencent à `.10`.

## Liens point à point

| Lien | IPv4 | IPv6 | Capacité |
|---|---|---|---|
| r-core1:eth1 ⇄ r-core2:eth1 | 10.9.250.0/31 | fd00:9:fa::/127 | 1 Gb/s |
| r-core1:eth2 ⇄ r-hq:eth1 | 10.9.250.2/31 | fd00:9:fa::2/127 | 1 Gb/s |
| r-core1:eth3 ⇄ r-br1:eth1 | 10.9.250.4/31 | fd00:9:fa::4/127 | 100 Mb/s (tc) |
| r-core2:eth2 ⇄ r-dc:eth1 | 10.9.250.6/31 | fd00:9:fa::6/127 | 1 Gb/s |
| r-core2:eth3 ⇄ r-br2:eth1 | 10.9.250.8/31 | fd00:9:fa::8/127 | 100 Mb/s (tc) |

Le premier routeur cité prend l'adresse paire (`.0`, `.2`…), l'autre l'adresse impaire.
Toutes les interfaces de données sont en MTU 1500, comme un Ethernet réel
(Containerlab crée les liens en 9500 ; les `entrypoint.sh` corrigent au démarrage).
Les liens « 1 Gb/s » ne sont pas limités : un veth n'a pas de débit maximal.
Seuls les liens des agences sont limités, avec `tc` (variable `SHAPE` dans la topologie).

## Nœuds

| Nœud | Rôle | Adresses de données | Gestion |
|---|---|---|---|
| r-core1 | cœur | lo 10.9.255.1 · fd00:9:ff::1 | 172.20.30.11 |
| r-core2 | cœur | lo 10.9.255.2 · fd00:9:ff::2 | 172.20.30.12 |
| r-hq | accès siège | lo 10.9.255.3 · LAN 10.9.1.1 · fd00:9:1::1 | 172.20.30.13 |
| r-dc | accès datacenter | lo 10.9.255.4 · LAN 10.9.2.1 · fd00:9:2::1 | 172.20.30.14 |
| r-br1 | agence 1 | lo 10.9.255.5 · LAN 10.9.3.1 · fd00:9:3::1 | 172.20.30.15 |
| r-br2 | agence 2 | lo 10.9.255.6 · LAN 10.9.4.1 · fd00:9:4::1 | 172.20.30.16 |
| sw-hq, sw-dc | commutateurs L2 (pont Linux) | — | 172.20.30.121, .122 |
| h-user1, h-user2 | postes du siège | 10.9.1.10, .11 · fd00:9:1::10, ::11 | 172.20.30.101, .102 |
| h-web | serveur HTTP (port 80) | 10.9.2.10 · fd00:9:2::10 | 172.20.30.103 |
| h-dns | serveur DNS (`*.rt3.lab`) | 10.9.2.11 · fd00:9:2::11 | 172.20.30.104 |
| h-iperf | serveur iperf3 (ports 5201 à 5204) | 10.9.2.12 · fd00:9:2::12 | 172.20.30.105 |
| h-br1 | poste agence 1 | 10.9.3.10 · fd00:9:3::10 | 172.20.30.106 |
| h-atk | générateur d'incidents (labo isolé) | 10.9.4.10 · fd00:9:4::10 | 172.20.30.107 |
| snmp-exporter | N1 · traduit SNMP pour Prometheus (:9116) | — | 172.20.30.56 |
| prom-snmp | N1 · Prometheus, SNMP toutes les 5 min (:9090, publié en localhost:9091) | — | 172.20.30.52 |
| flowcol | N2 · reçoit sFlow (udp/6343) et IPFIX (udp/4739) ; métriques de flux (:9199) | — | 172.20.30.50 |
| prom-flow | N2 · Prometheus, relevé toutes les secondes (:9090, publié en localhost:9090) | — | 172.20.30.53 |
| alertmanager | commun · routage des alertes (:9093, publié en localhost:9093) | — | 172.20.30.54 |
| alertsink | commun · heure d'arrivée et historique des alertes (:9095) | — | 172.20.30.57 |
| alertdb | commun · base de l'historique des alertes, PostgreSQL (:5432) | — | 172.20.30.58 |
| grafana | commun · tableaux de bord (:3000, publié en localhost:3000) | — | 172.20.30.55 |

Chaque routeur expose aussi node_exporter (:9100) pour N2 et son agent SNMP (udp/161) pour N1.
Entre conteneurs, on utilise les noms Docker (`clab-rt3p9-<nœud>`) plutôt que les adresses.

## Points de mesure des flux

| Routeur | Interface | Pourquoi |
|---|---|---|
| r-hq, r-dc, r-br1, r-br2 | eth2 (LAN) | tout le trafic des hôtes du site |
| r-core1 | eth1 (lien de cœur) | trafic entre les deux moitiés du réseau |

Un flux HQ → DC passe par r-hq:eth2 **et** par r-core1:eth1 : on ne fait pas la
somme des volumes d'un point de mesure à l'autre.
