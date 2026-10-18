# ADR-003 : historique des alertes et données conservées

Date : 2026-10-18 · Statut : adopté

## Contexte

Les alertes n'étaient visibles qu'actives : une alerte N2 se résout quelques
secondes après la fin de l'incident et disparaissait d'Alertmanager et de
Grafana avant qu'on ait pu la lire. Les panneaux « alertes actives » ne
montraient ni l'heure ni le résumé. Enfin, chaque `make up` recréait les
conteneurs : métriques, journal d'alertsink et réglages de Grafana étaient perdus.

## Décisions

| Sujet | Décision | Pourquoi |
|---|---|---|
| Historique des alertes | alertsink enregistre chaque alerte dans une base PostgreSQL (`alertdb`), une ligne par occurrence : début, fin, niveau, routeur, interface, résumé, heure de réception | La série `ALERTS` de Prometheus n'a ni résumé, ni début et fin par occurrence ; Grafana lit PostgreSQL sans extension |
| Consultation | Un seul tableau de bord « Alertes (N1 et N2) » : alertes actives + historique, filtre par niveau | Un seul endroit pour les deux niveaux ; les tableaux N1 et N2 n'affichent plus d'alertes, ils renvoient vers celui-ci |
| Données conservées | Volumes Docker nommés `rt3p9-…` pour prom-snmp, prom-flow, Alertmanager, Grafana et alertdb | Les données survivent à `make down` / `make up`. Un volume nommé reprend les droits prévus par l'image : pas de problème de droits, contrairement à un dossier monté (Prometheus et Grafana ne tournent pas en root) |
| Effacer les données | `make reset-data`, à lancer après `make down` | Effacement volontaire et explicite |
| Rétention des métriques | prom-snmp : 30 jours ; prom-flow : 7 jours ou 2 Go | Un point par seconde remplirait vite le disque d'un portable |
| Panne de la base | alertsink écrit d'abord sa ligne JSON (lue par le banc), puis la base ; si elle est injoignable, il continue | La mesure du délai de détection ne dépend pas de la base |

Les routeurs et les hôtes n'ont pas de volume : leur configuration vient
entièrement des fichiers du dépôt.

## Vérifié le 2026-10-18

- Une micro-rafale donne 4 lignes d'historique (une par interface du chemin),
  durée 8 s, résumé lisible.
- Après un nouveau `make up`, l'historique est intact et prom-flow a gardé ses
  métriques d'avant le redéploiement.
