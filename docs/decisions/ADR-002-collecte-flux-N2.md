# ADR-002 : collecte des flux du niveau N2

Date : 2026-10-18 · Statut : adopté

## Décisions

| Sujet | Décision | Pourquoi |
|---|---|---|
| goflow2 et flow2prom | Un seul conteneur, `flowcol` : `goflow2 -format=json \| python3 flow2prom.py` | Pas de fichier partagé ni de file de messages ; l'adresse .50, déjà utilisée par les routeurs, ne change pas |
| Nom des routeurs | flow2prom traduit l'adresse de l'exporteur en nom (`router="r-br1"`) d'après la variable `ROUTERS` de la topologie | Alertes et tableaux de bord lisibles |
| Source de chaque règle | débit : node_exporter ; SYN et DNS : sFlow ; scan : IPFIX | sFlow est quasi temps réel et suffit aux forts débits ; un scan de 1000 paquets ne laisse qu'environ 2 échantillons sFlow à 1/512, alors qu'IPFIX voit tous les flux |
| Signature du scan | ports destination distincts visés par des **SYN** (sans ACK) depuis une source, sur 10 s | Sans ce filtre, pendant un SYN flood, les SYN-ACK du serveur vers des milliers de ports clients ressemblent à un scan venant du serveur |
| « Qui parle à qui » | maximum entre les points de mesure, pas la somme | Un flux siège → datacenter est vu par trois routeurs |

## Problèmes trouvés en testant les incidents, et corrections

| Problème observé | Cause | Correction |
|---|---|---|
| Le scan de ports n'est pas détecté ; goflow2 écrit des dizaines de `template error` | IPFIX sur UDP : le collecteur ne décode les flux qu'après avoir reçu le template de l'exporteur. Les routeurs ont envoyé le leur avant que flowcol n'écoute, et softflowd ne le renvoie que tous les 16 paquets d'export, soit plusieurs minutes à faible trafic | Chaque routeur redemande son template toutes les 10 s (`softflowctl send-template`), comme le prévoit IPFIX sur UDP (RFC 7011) |
| L'anomalie DNS est détectée en 34 s au lieu de quelques secondes | flow2prom plantait pendant le SYN flood précédent : sous forte charge, goflow2 écrit parfois deux enregistrements sur la même ligne (`{…}{…}`). Docker le relançait avec des délais croissants : flowcol était arrêté au début de l'essai DNS | flow2prom récupère tous les enregistrements d'une ligne et compte les lignes illisibles (`rt3_flow2prom_bad_lines_total`) au lieu de s'arrêter |

Diagnostic : les datagrammes sFlow partaient bien de r-br2 chaque seconde
(capture `tcpdump` sur eth0), et flow2prom les comptait 0,7 s après le début
d'une rafale isolée. Le retard venait donc de flowcol, dont le journal
montrait les plantages et les redémarrages.

## Résultat après correction

Chaque incident joué une fois (`make inject`), alerte N2 du bon type :

| Incident | Délai N2 | Alerte |
|---|---|---|
| microburst | 3,7 s | LinkSaturation |
| saturation | 3,6 s | LinkSaturation |
| syn_flood | 3,0 s | SynFlood |
| dns_anomaly | 3,8 s | DnsFlood |
| port_scan | 12,3 s | PortScan (IPFIX exporte chaque flux au plus tard 10 s après son début) |

flowcol : aucun redémarrage, aucune erreur de template, aucune ligne illisible.

## Conséquences

- Un redémarrage de flowcol perd au plus 10 s de flux IPFIX (le temps de recevoir un template).
- Le délai du scan est dominé par `maxlife=10` de softflowd : c'est le compromis
  délai / volume exporté qu'étudie le jalon J6 (L6.5).
