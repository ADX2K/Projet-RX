#!/usr/bin/env bash
# Vérifie que le labo rt3p9 fonctionne :
#   1. conteneurs démarrés        5. services web et DNS
#   2. voisins OSPFv2 et OSPFv3   6. flux sFlow et IPFIX reçus par goflow2
#   3. ping IPv4 et IPv6          7. supervision N1 : SNMP, Prometheus, Grafana,
#   4. débit limité à 100 Mb/s       chaîne d'alerte jusqu'à alertsink
# Code de sortie : nombre de vérifications en échec (0 = tout est bon).
set -uo pipefail

LAB=rt3p9
fails=0

ok()  { printf '  \033[32mOK\033[0m  %s\n' "$*"; }
ko()  { printf '  \033[31mKO\033[0m  %s\n' "$*"; fails=$((fails + 1)); }
run() { docker exec "clab-$LAB-$1" "${@:2}"; }      # run <nœud> <commande...>

# routeur:nombre de voisins OSPF attendus
ROUTERS=(r-core1:3 r-core2:3 r-hq:1 r-dc:1 r-br1:1 r-br2:1)
# hôte IPv4 IPv6 (cibles des pings lancés depuis h-user1)
HOSTS=(
  "h-user2 10.9.1.11 fd00:9:1::11"
  "h-web   10.9.2.10 fd00:9:2::10"
  "h-dns   10.9.2.11 fd00:9:2::11"
  "h-iperf 10.9.2.12 fd00:9:2::12"
  "h-br1   10.9.3.10 fd00:9:3::10"
  "h-atk   10.9.4.10 fd00:9:4::10"
)
NODES=(r-core1 r-core2 r-hq r-dc r-br1 r-br2 sw-hq sw-dc
       h-user1 h-user2 h-web h-dns h-iperf h-br1 h-atk
       goflow2 snmp-exporter prom-snmp alertmanager alertsink grafana)

echo "1. Conteneurs"
for node in "${NODES[@]}"; do
  state=$(docker inspect -f '{{.State.Running}}' "clab-$LAB-$node" 2>/dev/null)
  [ "$state" = true ] && ok "$node" || ko "$node n'est pas démarré"
done

echo "2. Voisins OSPF (attente jusqu'à 30 s)"
for entry in "${ROUTERS[@]}"; do
  router=${entry%%:*}
  want=${entry#*:}
  for _ in $(seq 15); do
    v4=$(run "$router" vtysh -c 'show ip ospf neighbor' | grep -c Full)
    v6=$(run "$router" vtysh -c 'show ipv6 ospf6 neighbor' | grep -c Full)
    [ "$v4" -ge "$want" ] && [ "$v6" -ge "$want" ] && break
    sleep 2
  done
  msg="$router : OSPFv2 $v4/$want, OSPFv3 $v6/$want"
  [ "$v4" -ge "$want" ] && [ "$v6" -ge "$want" ] && ok "$msg" || ko "$msg"
done

echo "3. Ping depuis h-user1"
for entry in "${HOSTS[@]}"; do
  read -r host v4 v6 <<< "$entry"
  run h-user1 ping -c 2 -W 1 -q "$v4" > /dev/null && ok "$host $v4" || ko "$host $v4"
  run h-user1 ping -6 -c 2 -W 1 -q "$v6" > /dev/null && ok "$host $v6" || ko "$host $v6"
done

echo "4. Débit h-br1 -> h-iperf (lien de l'agence limité à 100 Mb/s)"
mbps=$(run h-br1 iperf3 -c 10.9.2.12 -p 5204 -t 3 -f m | awk '/receiver/ {print $(NF-2)}')
if awk -v x="${mbps:-0}" 'BEGIN { exit !(x >= 80 && x <= 105) }'; then
  ok "${mbps} Mb/s"
else
  ko "${mbps:-aucune mesure} Mb/s (attendu entre 80 et 105)"
fi

echo "5. Services"
code=$(run h-user1 curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://10.9.2.10/)
[ "$code" = 200 ] && ok "web : HTTP $code" || ko "web : HTTP ${code:-sans réponse}"
answer=$(run h-user1 dig +short +time=2 @10.9.2.11 web.rt3.lab A)
[ "$answer" = 10.9.2.10 ] && ok "dns : web.rt3.lab = $answer" || ko "dns : réponse '${answer}'"

echo "6. Flux reçus par goflow2 (attente de 12 s pour l'export IPFIX)"
sleep 12
logs=$(docker logs --since 2m "clab-$LAB-goflow2" 2>&1)
sflow=$(grep -c '"type":"SFLOW_5"' <<< "$logs")
ipfix=$(grep -c '"type":"IPFIX"' <<< "$logs")
[ "$sflow" -gt 0 ] && ok "sFlow : $sflow enregistrements" || ko "sFlow : aucun enregistrement"
[ "$ipfix" -gt 0 ] && ok "IPFIX : $ipfix enregistrements" || ko "IPFIX : aucun enregistrement"

echo "7. Supervision N1"
for entry in "${ROUTERS[@]}"; do
  router=${entry%%:*}
  url="http://clab-$LAB-snmp-exporter:9116/snmp?target=clab-$LAB-$router&module=if_mib&auth=public_v2"
  n=$(run prom-snmp wget -qO- "$url" 2>/dev/null | grep -c '^ifHCInOctets{')
  [ "$n" -gt 0 ] && ok "SNMP $router : $n interfaces" || ko "SNMP $router : pas de réponse"
done
curl -sf localhost:9091/-/ready > /dev/null && ok "prom-snmp prêt (localhost:9091)" || ko "prom-snmp ne répond pas"
curl -sf localhost:3000/api/datasources/uid/prom-snmp/health | grep -q '"status":"OK"' \
  && ok "grafana interroge prom-snmp (localhost:3000)" || ko "grafana n'arrive pas à interroger prom-snmp"
curl -sf 'localhost:3000/api/search?query=' | grep -q rt3p9-n1-snmp \
  && ok "tableau de bord N1 chargé" || ko "tableau de bord N1 absent"

# Une alerte de test envoyée à Alertmanager doit arriver dans alertsink.
name="CheckChain$(date +%s)"
ends=$(date -u -d '+30 sec' +%Y-%m-%dT%H:%M:%SZ)
curl -sf -X POST -H 'Content-Type: application/json' localhost:9093/api/v2/alerts \
  -d "[{\"labels\": {\"alertname\": \"$name\", \"level\": \"test\"}, \"endsAt\": \"$ends\"}]"
sleep 3
docker logs "clab-$LAB-alertsink" 2>&1 | grep -q "$name" \
  && ok "chaîne d'alerte : Alertmanager -> alertsink" \
  || ko "chaîne d'alerte : l'alerte de test n'est pas arrivée dans alertsink"

echo
[ "$fails" -eq 0 ] && echo "Tout est bon." || echo "$fails vérification(s) en échec."
exit "$fails"
