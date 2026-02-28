"""
discovery.py — Service de découverte de pairs via UDP Multicast
- Fonctionne sur réseau local / hotspot sans Internet
- Envoie plusieurs HELLO rapides au démarrage pour une découverte immédiate
- Nettoyage automatique des pairs morts
"""

import socket
import threading
import time
import struct
import struct
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.crypto.packet import build_packet, parse_packet, TYPE_HELLO

MULTICAST_GROUP  = '239.255.42.99'
MULTICAST_PORT   = 6000
HELLO_INTERVAL   = 15      # Annonce toutes les 15s (plus réactif)
HELLO_BURST      = 5       # 5 HELLO rapides au démarrage
HELLO_BURST_GAP  = 1.0     # 1s entre chaque HELLO du burst
PEER_TIMEOUT     = 60      # Pair considéré mort après 60s sans HELLO


class PeerTable:
    """Table des pairs connus sur le réseau."""

    def __init__(self):
        self.peers = {}
        self.lock  = threading.Lock()

    def upsert(self, node_id, ip, port):
        """Ajoute ou met à jour un pair. Retourne True si c'est un nouveau pair."""
        with self.lock:
            is_new = node_id not in self.peers
            self.peers[node_id] = {
                "ip":        ip,
                "port":      port,
                "last_seen": time.time()
            }
            if is_new:
                print(f"\n[🟢 PAIR DÉCOUVERT] {ip}:{port}")
                print("Vous : ", end="", flush=True)
            return is_new

    def remove_dead_peers(self):
        with self.lock:
            now  = time.time()
            dead = [
                nid for nid, info in self.peers.items()
                if now - info["last_seen"] > PEER_TIMEOUT
            ]
            for nid in dead:
                ip = self.peers[nid]['ip']
                print(f"\n[❌ PAIR DÉCONNECTÉ] {ip}")
                del self.peers[nid]

    def get_all(self):
        with self.lock:
            return dict(self.peers)

    def count(self):
        with self.lock:
            return len(self.peers)

    def display(self):
        peers = self.get_all()
        if not peers:
            print("[TABLE] Aucun pair connu pour l'instant")
            return
        print(f"\n{'='*55}")
        print(f"  {len(peers)} PC(S) DISPONIBLE(S) SUR LE RÉSEAU")
        print(f"{'='*55}")
        for i, (nid, info) in enumerate(peers.items()):
            age = int(time.time() - info["last_seen"])
            print(f"  [{i}] {info['ip']}:{info['port']}  (vu il y a {age}s)")
        print(f"{'='*55}\n")


class DiscoveryService:
    """
    Service de découverte multicast UDP.
    
    - Envoie des HELLO en burst au démarrage pour une découverte rapide
    - Écoute les HELLO des autres nœuds
    - Fonctionne sur hotspot local sans Internet
    """

    def __init__(self, peer_table, node_id, tcp_port=7777):
        self.peer_table = peer_table
        self.node_id    = node_id
        self.tcp_port   = tcp_port
        self.running    = False

    def start(self):
        self.running = True
        threading.Thread(target=self._hello_sender,   daemon=True).start()
        threading.Thread(target=self._hello_listener, daemon=True).start()
        threading.Thread(target=self._cleanup_loop,   daemon=True).start()
        print(f"[📡 DÉCOUVERTE] Service multicast démarré ({MULTICAST_GROUP}:{MULTICAST_PORT})")

    def _build_hello_packet(self):
        payload = {
            "node_id":   self.node_id,
            "tcp_port":  self.tcp_port,
            "timestamp": time.time()
        }
        return build_packet(TYPE_HELLO, self.node_id, payload)

    def _hello_sender(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 10)  # TTL=10 pour hotspot
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)  # loopback pour tests locaux

        # BURST au démarrage : envoyer plusieurs HELLO rapidement
        print(f"[📡 HELLO] Annonce burst au démarrage...")
        for i in range(HELLO_BURST):
            try:
                packet = self._build_hello_packet()
                sock.sendto(packet, (MULTICAST_GROUP, MULTICAST_PORT))
                if i == 0:
                    print(f"[📡 HELLO] Annonce envoyée sur le réseau")
            except Exception as e:
                print(f"[ERREUR] Envoi HELLO burst {i}: {e}")
            time.sleep(HELLO_BURST_GAP)

        # Ensuite, envoyer périodiquement
        while self.running:
            try:
                packet = self._build_hello_packet()
                sock.sendto(packet, (MULTICAST_GROUP, MULTICAST_PORT))
            except Exception as e:
                print(f"[ERREUR] Envoi HELLO : {e}")
            time.sleep(HELLO_INTERVAL)

        sock.close()

    def _hello_listener(self):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            # Tenter SO_REUSEPORT (Linux/Mac — ignoré sur Windows)
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except AttributeError:
                pass

            sock.bind(('', MULTICAST_PORT))

            # Rejoindre le groupe multicast
            mreq = struct.pack("4sL",
                socket.inet_aton(MULTICAST_GROUP),
                socket.INADDR_ANY
            )
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            sock.settimeout(2.0)

            while self.running:
                try:
                    data, addr = sock.recvfrom(8192)
                    packet = parse_packet(data)
                    if packet is None:
                        continue
                    if packet["type"] != TYPE_HELLO:
                        continue

                    sender_id = packet["payload"]["node_id"]
                    tcp_port  = packet["payload"]["tcp_port"]
                    sender_ip = addr[0]

                    # Clé unique par nœud (node_id + port) pour multinode sur même machine
                    peer_key = f"{sender_id}_{tcp_port}"
                    my_key   = f"{self.node_id}_{self.tcp_port}"

                    if peer_key == my_key:
                        continue  # Ignorer notre propre HELLO

                    self.peer_table.upsert(peer_key, sender_ip, tcp_port)

                except socket.timeout:
                    continue
                except Exception:
                    continue

        except Exception as e:
            print(f"[ERREUR FATALE] Listener multicast : {e}")

    def _cleanup_loop(self):
        while self.running:
            time.sleep(30)
            self.peer_table.remove_dead_peers()

    def stop(self):
        self.running = False
        print("[📡] Service de découverte arrêté")


def add_peer_manually(peer_table, ip, port):
    """Ajoute un pair manuellement par IP directe (résultat du scan TCP)."""
    node_id = f"scanned_{ip}_{port}"
    peer_table.upsert(node_id, ip, port)