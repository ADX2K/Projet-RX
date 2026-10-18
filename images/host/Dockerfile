# Image des hôtes du labo : postes, serveurs (web, DNS, iperf3), générateurs
# d'incidents et commutateurs L2. Le rôle est choisi au démarrage par des
# variables d'environnement (voir entrypoint.sh).
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive

# iperf3 : débit · hping3, nmap : incidents (labo isolé) · dnsutils : dig
# dnsmasq-base : serveur DNS · python3 : serveur web
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      iproute2 iputils-ping traceroute tcpdump curl python3 \
      iperf3 hping3 nmap bind9-dnsutils dnsmasq-base \
 && rm -rf /var/lib/apt/lists/*

# Contenu du serveur web : une page et un fichier de 1 Mo pour le trafic de fond.
RUN mkdir -p /srv/www \
 && echo "rt3p9 web" > /srv/www/index.html \
 && head -c 1048576 /dev/urandom > /srv/www/1M.bin

COPY entrypoint.sh /entrypoint.sh
ENTRYPOINT ["bash", "/entrypoint.sh"]
