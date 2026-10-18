# ADR-001 : export de flux dans les conteneurs (spike J2)

Date : 2026-10-18 · Statut : adopté

## Contexte

Le risque R1 du plan : les exporteurs sFlow et IPFIX pourraient mal fonctionner
dans des conteneurs. Le spike L2.6 a testé hsflowd (sFlow) et softflowd (IPFIX)
dans l'image `rt3/router`, avec goflow2 comme collecteur, à faible trafic
(300 pings à 100 paquets/s).

## Ce que le spike a montré

| Problème observé | Cause | Correction |
|---|---|---|
| hsflowd échantillonne 1 paquet sur 10 000 au lieu de N | Un veth annonce 10 Gb/s ; hsflowd calcule alors N à partir de la vitesse et ignore `sampling` | `sampling.bps_ratio = 0` dans `hsflowd.conf` (code source : *falls back on global default*) |
| softflowd 1.1.0 ne traite aucun paquet à faible débit (638 reçus, 0 traité) | libpcap garde les paquets en mémoire tant que son tampon n'est pas plein | softflowd 1.1.0 compilé avec le correctif amont `f5c0f99` (`pcap_set_immediate_mode`) |
| softflowd s'arrête sans message en mode démon | non élucidé | les agents tournent au premier plan (`-d`) en tâche de fond de l'entrypoint ; leurs messages vont dans `docker logs` |
| hsflowd et softflowd ne sont pas installables par apt | hsflowd n'est pas empaqueté ; softflowd d'Ubuntu n'a pas le correctif | compilation dans des étapes séparées du `Dockerfile` |
| Dans le labo, 14 échantillons sFlow pour 3 s d'iperf3 à 100 Mb/s au lieu d'environ 70 | Containerlab crée les liens en MTU 9500 : les paquets TCP font 9 448 octets, donc 6 fois moins de paquets qu'en Ethernet réel | MTU 1500 sur toutes les interfaces de données, fixée par les `entrypoint.sh` ; ensuite 132 échantillons et des paquets de 1 448 octets au plus |

## Résultat après correction

300 pings vers le routeur, N = 16 :

- goflow2 reçoit 39 enregistrements sFlow et 12 enregistrements IPFIX ;
- l'enregistrement IPFIX du flux ICMP compte exactement 300 paquets et 25 200 octets.

## Conséquences

- La précision P3 du plan (« un veth annonce 10 Gb/s ») touche aussi hsflowd, pas seulement SNMP.
- La version de softflowd est épinglée : 1.1.0 + `f5c0f99`. À revoir quand une version publiée contiendra le correctif.
- `goflow2` produit une ligne JSON par flux ; les champs utiles pour J5 sont
  `type` (`SFLOW_5` ou `IPFIX`), `sampling_rate`, `sampler_address`, `src_addr`,
  `dst_addr`, `proto`, `src_port`, `dst_port`, `bytes`, `packets`, `tcp_flags`.
