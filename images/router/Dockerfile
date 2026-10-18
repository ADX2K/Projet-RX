# Image des routeurs du labo : FRR (OSPFv2 + OSPFv3) et agents de télémétrie.
# Les agents sont installés ici ; entrypoint.sh ne les démarre que s'ils sont activés.

# --- Étape 1 : compiler hsflowd (il n'existe pas en paquet Ubuntu) ----------
FROM ubuntu:24.04 AS hsflowd
ARG HSFLOWD_VERSION=2.1.26-1
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential clang ca-certificates curl libpcap-dev \
 && curl -fsSL "https://github.com/sflow/host-sflow/archive/refs/tags/v${HSFLOWD_VERSION}.tar.gz" \
    | tar -xz -C /tmp \
 && make -C "/tmp/host-sflow-${HSFLOWD_VERSION}" FEATURES="PCAP" \
 && make -C "/tmp/host-sflow-${HSFLOWD_VERSION}" install

# --- Étape 2 : compiler softflowd 1.1.0 avec un correctif amont ---------------
# Sans le correctif f5c0f99, softflowd ne traite aucun paquet à faible débit :
# libpcap les garde en mémoire tant que son tampon n'est pas plein
# (vérifié au spike J2 : 638 paquets reçus, 0 traité).
FROM ubuntu:24.04 AS softflowd
ARG SOFTFLOWD_VERSION=1.1.0
ARG SOFTFLOWD_FIX=f5c0f99103755b8588159cc8c70e44fc8e7d3b12
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential autoconf automake ca-certificates curl patch libpcap-dev \
 && curl -fsSL "https://github.com/irino/softflowd/archive/refs/tags/softflowd-v${SOFTFLOWD_VERSION}.tar.gz" \
    | tar -xz -C /tmp \
 && cd "/tmp/softflowd-softflowd-v${SOFTFLOWD_VERSION}" \
 && curl -fsSL "https://github.com/irino/softflowd/commit/${SOFTFLOWD_FIX}.patch" | patch -p1 \
 && autoreconf -if && ./configure && make && make install

# --- Étape 3 : image finale -------------------------------------------------
FROM ubuntu:24.04
ARG NODE_EXPORTER_VERSION=1.12.1
ENV DEBIAN_FRONTEND=noninteractive

# frr : routage · snmpd : SNMP (J3) · tcpdump : captures (et libpcap pour les agents)
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      frr snmpd tcpdump iproute2 iputils-ping procps ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

# hsflowd (sFlow) et softflowd (IPFIX) : compilés aux étapes 1 et 2
COPY --from=hsflowd /usr/sbin/hsflowd /usr/sbin/hsflowd
COPY --from=hsflowd /etc/hsflowd/modules /etc/hsflowd/modules
COPY --from=softflowd /usr/local/sbin/softflowd /usr/local/sbin/softflowctl /usr/local/sbin/

# node_exporter : métriques des interfaces à haute fréquence (J5)
RUN curl -fsSL "https://github.com/prometheus/node_exporter/releases/download/v${NODE_EXPORTER_VERSION}/node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64.tar.gz" \
    | tar -xz -C /tmp \
 && mv "/tmp/node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64/node_exporter" /usr/local/bin/ \
 && rm -rf /tmp/node_exporter-*

COPY entrypoint.sh /entrypoint.sh
ENTRYPOINT ["bash", "/entrypoint.sh"]
