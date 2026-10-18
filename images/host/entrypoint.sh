#!/usr/bin/env bash
# Démarrage d'un conteneur rt3/host.
#
# Variables d'environnement (fixées dans lab/topology.clab.yml) :
#   ROLE      host (défaut) ou switch
#   ADDR4     adresse IPv4 de eth1, ex. 10.9.1.10/24
#   GW4       passerelle IPv4,      ex. 10.9.1.1
#   ADDR6     adresse IPv6 de eth1, ex. fd00:9:1::10/64
#   GW6       passerelle IPv6,      ex. fd00:9:1::1
#   SERVICES  services à lancer parmi : web dns iperf   (vide = aucun)
set -euo pipefail

log() { echo "[$(hostname)] $*"; }

data_interfaces() { ls /sys/class/net | grep -E '^eth[1-9][0-9]*$' || true; }

# Commutateur : un pont Linux relie toutes les interfaces de données.
start_switch() {
  ip link add br0 type bridge
  ip link set br0 up
  for dev in $(data_interfaces); do
    ip link set "$dev" master br0
    ip link set "$dev" up
  done
  log "commutateur : $(data_interfaces | tr '\n' ' ')dans br0"
}

# Hôte : adresses, routes vers le labo, puis services.
start_host() {
  sysctl -qw net.ipv6.conf.all.disable_ipv6=0
  ip addr add "$ADDR4" dev eth1
  ip -6 addr add "$ADDR6" dev eth1 nodad
  ip link set eth1 up
  # Le trafic du labo passe par le routeur du site ;
  # eth0 (réseau de gestion) garde la route par défaut.
  ip route add 10.9.0.0/16 via "$GW4"
  ip -6 route add fd00:9::/32 via "$GW6"
  log "hôte : $ADDR4 via $GW4 · $ADDR6 via $GW6"

  for svc in ${SERVICES:-}; do
    case "$svc" in
      web)
        python3 -m http.server 80 --directory /srv/www >/dev/null 2>&1 &
        ;;
      dns)
        # Répond pour *.rt3.lab avec l'adresse du serveur web.
        dnsmasq --no-resolv --no-hosts --interface=eth1 --bind-interfaces \
          --address=/rt3.lab/10.9.2.10 --address=/rt3.lab/fd00:9:2::10
        ;;
      iperf)
        # Un serveur iperf3 ne sert qu'un client à la fois : 4 ports.
        for port in 5201 5202 5203 5204; do iperf3 -s -D -p "$port"; done
        ;;
      *)
        log "service inconnu : $svc" && exit 1
        ;;
    esac
    log "service démarré : $svc"
  done
}

# Attendre les interfaces de données (Containerlab les branche après le démarrage).
until [ "$(data_interfaces | wc -l)" -ge "${CLAB_INTFS:-0}" ]; do sleep 1; done

# MTU d'un Ethernet réel : Containerlab crée les liens en 9500 (trames jumbo).
for dev in $(data_interfaces); do ip link set "$dev" mtu 1500; done

case "${ROLE:-host}" in
  switch) start_switch ;;
  host)   start_host ;;
  *)      log "rôle inconnu : $ROLE" && exit 1 ;;
esac

log "prêt"
trap 'log "arrêt"; exit 0' TERM INT
sleep infinity &
wait
