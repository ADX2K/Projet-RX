# Protocole de mesure

Ce document fixe ce que le banc de mesure (`src/bench/campaign.py`) mesure et
comment. Toute campagne citée dans le rapport doit suivre ce protocole ; s'il
change, on le note ici avec la date.

## Ce qu'on mesure

| Indicateur | Définition | Jalon |
|---|---|---|
| Délai de détection | `t_detect − t_start`, pour la première alerte du bon type (`delay_s`) et pour la première alerte quelle qu'elle soit (`delay_any_s`) | J4 (N1), J6 (N2) |
| Détecté / non détecté | une alerte du bon type arrive-t-elle dans la fenêtre ? | J4, J6 |
| Fausses alertes | alertes reçues en trafic normal seul, sans incident, par heure | J4 (L4.2), J6 |
| Granularité | plus courte rafale détectée | J6 |
| Surcharge | CPU des routeurs, débit des exports | J6 |
| Effet de l'échantillonnage | volume estimé par sFlow comparé au volume réel | J6 |

## Définitions

- **t_start** : heure notée juste avant le `docker exec` qui lance l'incident.
  L'incident démarre réellement environ 0,1 s plus tard. C'est négligeable
  devant 300 s (N1), mais à garder en tête pour N2 (1 s).
- **t_end** : heure de fin de la commande de l'incident.
- **t_detect** : heure à laquelle `alertsink` reçoit l'alerte. C'est le bout de
  la chaîne : `D = T_collecte + T_évaluation + T_for + T_notification`.
  Tous les conteneurs partagent l'horloge de la même machine.
- **Alerte du bon type** : sa règle liste le scénario dans l'étiquette
  `detects` (voir `monitoring/prom-snmp/rules.yml`).
- **Détecté** : la première alerte du bon type et du bon niveau (`level`)
  arrive entre `t_start` et `t_end` + fenêtre de grâce.
  Fenêtre de grâce : N1 = 660 s (deux relevés SNMP + 60 s) ; N2 = 60 s.
- **Autre alerte (`other_alerts`)** : alerte du même niveau, d'un autre type,
  reçue entre `t_start` et la détection (ou la fin de la fenêtre). Ce n'est
  pas un faux positif : elle est le plus souvent causée par l'incident lui-même.
  Exemple observé le 2026-10-18 : une saturation à 100 Mb/s fait aussi
  environ 8000 paquets/s, et `HighPacketRate` arrive 5 min avant `LinkSaturation`.
- **Fausse alerte** : alerte reçue pendant une session de trafic normal seul,
  sans incident (mesurée au jalon J4).

## Déroulé d'une répétition

0. **Une fois, avant la première répétition** : attendre un cycle de sondage
   + 60 s. En N1, l'effet d'un essai précédent peut n'apparaître qu'au relevé
   suivant : sans cette attente, il serait compté dans la première répétition
   (observé lors de l'essai à blanc du 2026-10-18).
1. **Remise à zéro** : attendre qu'aucune alerte du niveau ne soit active.
2. **Phase aléatoire** : attendre un temps tiré au hasard entre 0 et un
   intervalle de sondage (300 s en N1). Sans cela, l'incident tomberait
   toujours au même moment du cycle SNMP et les 10 répétitions donneraient
   le même biais.
3. **Injection** de l'incident (`src/bench/scenarios.py`).
4. **Attente** de la première alerte du bon type, ou de la fin de la fenêtre.
5. **Une ligne** dans `results/raw/<campagne>.csv`, écrite tout de suite.

Règles communes :

- 10 répétitions par incident ; on rapporte la médiane et le min–max.
- Ordre des répétitions tiré au hasard, avec une graine notée (rejouable).
- Trafic de fond pendant toute la campagne, avec la même graine.
- Chaque campagne écrit aussi un manifeste `.json` (paramètres, commit Git)
  et le journal du trafic de fond.
- On garde et on rapporte les résultats négatifs.

## Incidents

| Nom | Source → cible | Intensité | Durée | Visible en N1 ? (attendu) |
|---|---|---|---|---|
| `saturation` | h-br1 → h-iperf | iperf3 TCP à 100 Mb/s | 6 min | oui, avec retard |
| `microburst` | h-br1 → h-iperf | iperf3 TCP à 100 Mb/s | 10 s | non (dilué dans 5 min) |
| `port_scan` | h-atk → h-web | scan SYN de 1000 ports (nmap -T4) | 0,2 s | non |
| `syn_flood` | h-atk → h-web:80 | ≈ 3800 SYN/s (hping3 -i u200) | 60 s | partiellement |
| `dns_anomaly` | h-atk → h-dns | 1000 requêtes/s, noms aléatoires | 60 s | partiellement |

La colonne « attendu » reprend les hypothèses de l'étude de faisabilité ; les
campagnes les confirment ou les infirment.

Intensités vérifiées le 2026-10-18 avec les compteurs des routeurs :

| Incident | Mesure |
|---|---|
| `port_scan` | 1001 paquets émis en 0,2 s ; 1000 réponses du serveur |
| `syn_flood` | 455 665 paquets émis en 60 s (≈ 3800 SYN/s + autant de RST du noyau de h-atk) ; 227 836 SYN-ACK du serveur |
| `dns_anomaly` | 997 requêtes/s ; 60 007 réponses de dnsmasq |
| `microburst` | 99,4 Mb/s en moyenne pendant 10,2 s sur r-br1:eth1 |

Le SYN flood (≈ 7600 paquets/s pendant 60 s) ajoute en moyenne environ
1500 paquets/s sur un relevé de 5 min s'il tombe en entier dans un seul
intervalle, mais seulement la moitié s'il est à cheval sur deux relevés.
Sa détection en N1 dépend donc de la phase : c'est ce que mesure la campagne.

## Seuils du niveau N1

Les règles sont dans `monitoring/prom-snmp/rules.yml`. Elles portent sur la
moyenne entre les deux derniers relevés SNMP, soit 5 minutes.

| Règle | Seuil | Justification |
|---|---|---|
| `LinkSaturation` | 80 Mb/s sortants | 80 % de la capacité des liens d'agence |
| `HighPacketRate` | 1300 paquets/s reçus | 1,5 × la pire moyenne sur 5 min du trafic de fond seul |

Calibration du 2026-10-18 : 10 minutes de trafic de fond (graine 42, un cycle
creux/plein complet), compteurs de paquets reçus relevés toutes les 10 s sur
chaque interface de données. Pire moyenne sur 5 min : 871 paquets/s
(r-core2:eth1 et r-dc:eth1) ; pire valeur sur 10 s : 1906 paquets/s.
Si le trafic de fond change, refaire la calibration (`make calibrate`) et ajuster le seuil.

En SNMP, on ne voit que des compteurs d'interface. N1 ne peut donc pas
distinguer un scan, un SYN flood et une anomalie DNS : une seule règle
(`HighPacketRate`) couvre les trois.

## Limites connues

- Le SYN flood part d'une seule adresse (h-atk). Le serveur répond par des
  SYN-ACK et le noyau de h-atk renvoie des RST : ce n'est pas un flood à
  adresses usurpées.
- La durée du scan dépend de nmap (quelques secondes) : `t_end` la mesure.
- Une répétition N1 dure 14 à 20 minutes (essais à blanc du 2026-10-18) :
  phase aléatoire, fenêtre de grâce de 11 min si rien n'est détecté, retour au
  calme après une saturation. Une campagne complète (5 incidents × 10
  répétitions) dure donc 12 à 16 heures. On peut la découper en plusieurs
  nuits avec `--scenarios` (ex. `--scenarios saturation microburst`).
