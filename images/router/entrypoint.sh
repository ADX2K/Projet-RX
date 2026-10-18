#!/usr/bin/env bash
# Démarrage d'un routeur rt3/router.
#
# Variables d'environnement (fixées dans lab/topology.clab.yml) :
#   SHAPE           liens à limiter, ex. "eth3=100mbit"        (vide = aucun)
#   ENABLE_SNMP     true pour démarrer l'agent SNMP            (défaut : false)
#   ENABLE_FLOW     true pour exporter sFlow + IPFIX           (défaut : false)
#   FLOW_IFACES     interfaces mesurées, ex. "eth2"
#   FLOW_COLLECTOR  adresse du collecteur goflow2               ex. 172.20.30.50
#   SFLOW_N         échantillonnage sFlow : 1 paquet sur N      ex. 512
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

# 5. SNMP (référence N1) : agent Net-SNMP, config dans lab/snmp/snmpd.conf.
#    -f premier plan · -Lo journal sur la sortie standard · -C ignorer les configs par défaut
#    MIBS= : ne charger aucun fichier MIB (un agent n'en a pas besoin, et ceux
#    d'Ubuntu sont incomplets : 42 avertissements « Cannot find module »)
if [ "${ENABLE_SNMP:-false}" = true ]; then
  MIBS= snmpd -f -Lo -C -c /etc/snmp/snmpd.conf &
  log "SNMP : agent démarré (udp/161)"
fi

# 6. Export de flux (sFlow avec hsflowd, IPFIX avec softflowd).
if [ "${ENABLE_FLOW:-false}" = true ]; then
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
  log "sFlow : 1/${SFLOW_N} sur ${FLOW_IFACES} -> ${FLOW_COLLECTOR}:6343"

  # Une instance softflowd par interface ; maxlife=10 exporte chaque flux
  # au plus tard 10 s après son début, expint=1 vérifie le cache chaque seconde.
  for dev in ${FLOW_IFACES}; do
    softflowd -d -i "$dev" -n "${FLOW_COLLECTOR}:4739" -v 10 -P udp \
      -t maxlife=10 -t expint=1 \
      -c "/run/softflowd-${dev}.ctl" -p "/run/softflowd-${dev}.pid" &
  done
  log "IPFIX : ${FLOW_IFACES} -> ${FLOW_COLLECTOR}:4739"
fi

log "prêt"
trap 'log "arrêt"; exit 0' TERM INT
sleep infinity &
wait
