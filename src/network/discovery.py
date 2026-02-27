import socket
import threading
import time
import json
import struct
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.crypto.packet import build_packet, parse_packet, TYPE_HELLO

MULTICAST_GROUP = '239.255.42.99'
MULTICAST_PORT  = 6000
HELLO_INTERVAL  = 10
PEER_TIMEOUT    = 90

class PeerTable:
    def __init__(self):
        self.peers = {}
        self.lock  = threading.Lock()

    def upsert(self, node_id, ip, port):
        with self.lock:
            is_new = node_id not in self.peers
            self.peers[node_id] = {
                "ip":        ip,
                "port":      port,
                "last_seen": time.time()
            }
            if is_new:
                print(f"\n[CONNECTE A UN NOUVEAU PAIR] {node_id[:16]}... @ {ip}:{port}")
            else:
                print(f"[PAIR] Mis à jour : {node_id[:16]}... @ {ip}:{port}")

    def remove_dead_peers(self):
        with self.lock:
            now  = time.time()
            dead = [
                nid for nid, info in self.peers.items()
                if now - info["last_seen"] > PEER_TIMEOUT
            ]
            for nid in dead:
                print(f"[PAIR MORT] {nid[:16]}...")
                del self.peers[nid]

    def get_all(self):
        with self.lock:
            return dict(self.peers)

    def display(self):
        peers = self.get_all()
        if not peers:
            print("[TABLE] Aucun pair connu pour l'instant...")
            return
        print(f"\n{'='*50}")
        print(f"  {len(peers)} PAIR(S) CONNU(S)")
        print(f"{'='*50}")
        for nid, info in peers.items():
            age = int(time.time() - info["last_seen"])
            print(f"  ID  : {nid[:20]}...")
            print(f"  IP  : {info['ip']}:{info['port']}")
            print(f"  Vu  : il y a {age}s")
            print(f"  {'-'*46}")


class DiscoveryService:
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

        print(f"[DÉCOUVERTE] Service démarré")

    def _hello_sender(self):
        """Envoie HELLO en multicast"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        # Important sur Windows : bind sur l'interface locale
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)

        while self.running:
            try:
                payload = {
                    "node_id":   self.node_id,
                    "tcp_port":  self.tcp_port,
                    "timestamp": time.time()
                }
                packet = build_packet(TYPE_HELLO, self.node_id, payload)
                sock.sendto(packet, (MULTICAST_GROUP, MULTICAST_PORT))
                print(f"[HELLO] Annonce envoyée (port {self.tcp_port})")
                time.sleep(HELLO_INTERVAL)
            except Exception as e:
                print(f"[ERREUR] Envoi HELLO : {e}")
                time.sleep(5)

    def _hello_listener(self):
        """Écoute les HELLO — version compatible Windows"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            # Sur Windows il faut bind sur '' pas sur l'adresse multicast
            sock.bind(('', MULTICAST_PORT))

            # Rejoindre le groupe multicast
            mreq = struct.pack("4sL",
                socket.inet_aton(MULTICAST_GROUP),
                socket.INADDR_ANY
            )
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            sock.settimeout(2.0)

            print(f"[DÉCOUVERTE] Écoute sur port {MULTICAST_PORT}...")

            while self.running:
                try:
                    data, addr = sock.recvfrom(4096)
                    packet = parse_packet(data)

                    if packet is None:
                        continue

                    if packet["type"] != TYPE_HELLO:
                        continue

                    sender_id = packet["payload"]["node_id"]
                    tcp_port  = packet["payload"]["tcp_port"]
                    sender_ip = addr[0]

                    # Sur la même machine : différencier par le port TCP
                    # pas par le node_id (qui est identique)
                    peer_key = f"{sender_id}_{tcp_port}"
                    my_key   = f"{self.node_id}_{self.tcp_port}"

                    if peer_key == my_key:
                        continue  # C'est moi-même, on ignore

                    self.peer_table.upsert(peer_key, sender_ip, tcp_port)

                except socket.timeout:
                    continue
                except Exception as e:
                    print(f"[ERREUR] Réception : {e}")

        except Exception as e:
            print(f"[ERREUR FATALE] Listener : {e}")

    def _cleanup_loop(self):
        while self.running:
            time.sleep(30)
            self.peer_table.remove_dead_peers()

    def stop(self):
        self.running = False