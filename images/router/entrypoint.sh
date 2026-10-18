#!/usr/bin/env bash
# Démarrage d'un routeur rt3/router.
#
# Variables d'environnement (fixées dans lab/topology.clab.yml) :
#   SHAPE                 liens à limiter, ex. "eth3=100mbit"       (vide = aucun)
#   ENABLE_SNMP           true : agent SNMP (N1)                    (défaut : false)
#   ENABLE_NODE_EXPORTER  true : compteurs d'interfaces à 1 s (N2)  (défaut : false)
#   ENABLE_FLOW           true : export sFlow + IPFIX (N2)          (défaut : false)
#   FLOW_IFACES           interfaces mesurées par les flux, ex. "eth2"  (vide = aucune)
#   FLOW_COLLECTOR        adresse du collecteur flowcol, ex. 172.20.30.50
#   SFLOW_N               échantillonnage sFlow : 1 paquet sur N, ex. 512
set -euo pipefail

log() { echo "[$(hostname)] $*"; }

data_interfaces() { ls /sys/class/net | grep -E '^eth[1-9][0-9]*$' || true; }

# 1. Attendre les interfaces de données.
#    Containerlab les branche après le démarrage du conteneur et indique
#    leur nombre dans CLAB_INTFS.
until [ "$(data_interfaces | wc -l)" -ge "${CLAB_INTFS:-0}" ]; do sleep 1; done
log "interfaces prêtes : $(data_interfaces | tr '\n' ' ')"

# MTU d'un Ethernet réel : Containerlab crée les liens en 9500 (trames jumbo),
# ce qui diviserait par 6 le nombre de paquets mesurés.
for dev in $(data_interfaces); do ip link set "$dev" mtu 1500; done

# 2. Routage IPv4 + IPv6.
sysctl -qw net.ipv6.conf.all.disable_ipv6=0
sysctl -qw net.ipv4.ip_forward=1
sysctl -qw net.ipv6.conf.all.forwarding=1

# 3. Capacité des liens : un veth n'a pas de débit maximal, on l'impose avec tc.
for rule in ${SHAPE:-}; do
  dev="${rule%%=*}"
  rate="${rule#*=}"
  tc qdisc replace dev "$dev" root tbf rate "$rate" burst 256kb latency 50ms
  log "débit limité : $dev = $rate"
done

# 4. FRR lit /etc/frr/daemons et /etc/frr/frr.conf (montés depuis lab/frr/).
/usr/lib/frr/frrinit.sh start

# Les agents de télémétrie tournent au premier plan en tâche de fond de ce
# script : leurs messages arrivent dans « docker logs ». (En mode démon,
# softflowd s'arrêtait sans message au spike J2.)

# 5. N1 · SNMP : agent Net-SNMP, config dans lab/snmp/snmpd.conf.
#    -f premier plan · -Lo journal sur la sortie standard · -C ignorer les configs par défaut
#    MIBS= : ne charger aucun fichier MIB (un agent n'en a pas besoin, et ceux
#    d'Ubuntu sont incomplets : 42 avertissements « Cannot find module »)
if [ "${ENABLE_SNMP:-false}" = true ]; then
  MIBS= snmpd -f -Lo -C -c /etc/snmp/snmpd.conf &
  log "N1 · SNMP : agent démarré (udp/161)"
fi

# 6. N2 · node_exporter : seulement les compteurs des interfaces de données,
#    lus toutes les secondes par prom-flow (:9100).
if [ "${ENABLE_NODE_EXPORTER:-false}" = true ]; then
  node_exporter --collector.disable-defaults --collector.netdev \
    --collector.netdev.device-include='^eth[1-9][0-9]*$' --log.level=warn &
  log "N2 · node_exporter : compteurs d'interfaces (:9100)"
fi

# 7. N2 · export de flux vers flowcol : sFlow avec hsflowd, IPFIX avec softflowd.
if [ "${ENABLE_FLOW:-false}" = true ] && [ -n "${FLOW_IFACES:-}" ]; then
  {
    echo "sflow {"
    echo "  agent = eth0"
    echo "  polling = 5"
    echo "  sampling = ${SFLOW_N}"
    # Un veth annonce 10 Gb/s : sans cette ligne, hsflowd ignore "sampling"
    # et calcule N à partir de la vitesse (1 sur 10 000).
    echo "  sampling.bps_ratio = 0"
    echo "  collector { ip = ${FLOW_COLLECTOR} udpport = 6343 }"
    for dev in ${FLOW_IFACES}; do echo "  pcap { dev = ${dev} }"; done
    echo "}"
  } > /etc/hsflowd.conf
  hsflowd -d -f /etc/hsflowd.conf &
  log "N2 · sFlow : 1/${SFLOW_N} sur ${FLOW_IFACES} -> ${FLOW_COLLECTOR}:6343"

  # Une instance softflowd par interface ; maxlife=10 exporte chaque flux
  # au plus tard 10 s après son début, expint=1 vérifie le cache chaque seconde.
  for dev in ${FLOW_IFACES}; do
    softflowd -d -i "$dev" -n "${FLOW_COLLECTOR}:4739" -v 10 -P udp \
      -t maxlife=10 -t expint=1 \
      -c "/run/softflowd-${dev}.ctl" -p "/run/softflowd-${dev}.pid" &
  done
  log "N2 · IPFIX : ${FLOW_IFACES} -> ${FLOW_COLLECTOR}:4739"

  # IPFIX sur UDP : le collecteur ne décode les flux qu'après avoir reçu le
  # template de l'exporteur. softflowd ne le renvoie que tous les 16 paquets
  # d'export, soit plusieurs minutes à faible trafic (J5 : scan perdu après un
  # redémarrage de flowcol). On le redemande toutes les 10 s, comme le prévoit
  # IPFIX sur UDP (RFC 7011).
  while sleep 10; do
    for dev in ${FLOW_IFACES}; do
      softflowctl -c "/run/softflowd-${dev}.ctl" send-template > /dev/null || true
    done
  done &
elif [ "${ENABLE_FLOW:-false}" = true ]; then
  log "N2 · flux : aucune interface mesurée sur ce routeur (FLOW_IFACES vide)"
fi

log "prêt"
trap 'log "arrêt"; exit 0' TERM INT
sleep infinity &
wait
