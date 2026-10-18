# Collecteur de flux (niveau N2) : goflow2 décode sFlow et IPFIX, flow2prom en fait
# des métriques Prometheus. Le code de flow2prom est monté depuis src/flow2prom/
# (voir lab/topology.clab.yml) : le modifier ne demande pas de reconstruire l'image.
FROM netsampler/goflow2:v2.2.7 AS goflow2

FROM python:3.12-slim
COPY --from=goflow2 /goflow2 /usr/local/bin/goflow2
COPY entrypoint.sh /entrypoint.sh
ENTRYPOINT ["bash", "/entrypoint.sh"]
