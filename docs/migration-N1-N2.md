# Migration N1 → N2 (jalon J5)

Le sujet impose une migration : d'une supervision SNMP toutes les 5 minutes
(N1) vers la télémétrie de flux et des métriques à la seconde (N2). Dans le
labo, **N2 s'ajoute à côté de N1** : les deux niveaux observent les mêmes
routeurs, les mêmes incidents et le même trafic de fond. Seule la supervision
change, ce qui rend la comparaison juste.

## Avant / après

| | N1 (avant) | N2 (après) |
|---|---|---|
| Source | SNMP (compteurs d'interfaces) | node_exporter (compteurs d'interfaces) + sFlow et IPFIX (flux) |
| Cadence | un relevé toutes les 5 min | un relevé par seconde ; flux en continu (sFlow) ou au plus tard 10 s après leur début (IPFIX) |
| Ce qu'on voit | octets et paquets par interface, en moyenne sur 5 min | qui parle à qui, ports, SYN, requêtes DNS |
| Règles | `LinkSaturation`, `HighPacketRate` | `LinkSaturation`, `PortScan`, `SynFlood`, `DnsFlood` |
| Prometheus | prom-snmp (`monitoring/prom-snmp/`, localhost:9091) | prom-flow (`monitoring/prom-flow/`, localhost:9090) |
| Tableau de bord | « N1 · Supervision SNMP » | « N2 · Télémétrie de flux » (avec un panneau N1 contre N2) |

Les deux niveaux envoient leurs alertes au même Alertmanager. Chaque alerte
porte son niveau (`level: N1` ou `N2`), et le banc de mesure filtre dessus :
`make campaign LEVEL=N2`.

## Ce qui a changé dans le dépôt

- `images/router/entrypoint.sh` : node_exporter et export de flux (variables
  `ENABLE_NODE_EXPORTER`, `ENABLE_FLOW`), template IPFIX redemandé toutes les 10 s.
- `images/flowcol/` : nouvelle image, goflow2 relié à flow2prom par un tube.
  Elle remplace le nœud goflow2 du spike J2, à la même adresse (.50).
- `src/flow2prom/` : nom des routeurs, « qui parle à qui », scan compté sur
  les SYN seulement, lignes illisibles jamais fatales.
- `monitoring/prom-flow/` : config et règles N2.
- `monitoring/grafana/` : source prom-flow et tableau de bord N2.
- `lab/topology.clab.yml` : flux et node_exporter activés pour tous les
  routeurs, nœuds flowcol et prom-flow.
- `lab/check.sh` : section « Supervision N2 ».

Choix techniques et problèmes rencontrés : [ADR-002](decisions/ADR-002-collecte-flux-N2.md).

## Passer un labo existant au jalon J5

```bash
git pull
docker rm -f clab-rt3p9-goflow2     # l'ancien nœud n'est plus dans la topologie : make up ne le supprime pas
make up                             # reconstruit les images (dont rt3/flowcol) et redéploie
make check                          # sections 7 (N2) et 8 comprises
```

Après un `make up`, la courbe N1 du panneau de comparaison n'apparaît qu'au
deuxième relevé SNMP, soit 5 à 10 minutes plus tard.

## Pour une démo

```bash
make inject S=microburst
```

Dans Grafana (tableau « N2 · Télémétrie de flux »), le panneau du haut montre
la rafale à 100 Mb/s sur la courbe N2 ; la courbe N1 reste plate. L'alerte N2
arrive en quelques secondes (`make alerts`) ; N1 n'en produit aucune.
