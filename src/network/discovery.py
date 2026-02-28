"""
discovery.py — Découverte des pairs sur le réseau local
Utilise UDP Multicast pour annoncer sa présence et découvrir les autres noeuds.
Compatible Windows — bind sur '' au lieu de l'adresse multicast.
"""

import socket
import threading
import time
import struct
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.crypto.packet import build_packet, parse_packet, TYPE_HELLO

MULTICAST_GROUP = '239.255.42.99'
MULTICAST_PORT  = 6000
HELLO_INTERVAL  = 30
PEER_TIMEOUT    = 90


class PeerTable:
    """
    Table des pairs connus sur le réseau.
    Thread-safe grâce au verrou.
    """

    def __init__(self):
        self.peers = {}
        self.lock  = threading.Lock()

    def upsert(self, node_id, ip, port):
        """Ajoute ou met à jour un pair."""
        with self.lock:
            is_new = node_id not in self.peers
            self.peers[node_id] = {
                "ip":        ip,
                "port":      port,
                "last_seen": time.time()
            }
            if is_new:
                print(f"\n[🟢 NOUVEAU PAIR] {node_id[:16]}... @ {ip}:{port}")

    def remove_dead_peers(self):
        """Supprime les pairs inactifs."""
        with self.lock:
            now  = time.time()
            dead = [
                nid for nid, info in self.peers.items()
                if now - info["last_seen"] > PEER_TIMEOUT
            ]
            for nid in dead:
                print(f"[❌ PAIR MORT] {self.peers[nid]['ip']}")
                del self.peers[nid]

    def get_all(self):
        """Retourne une copie de tous les pairs."""
        with self.lock:
            return dict(self.peers)

    def count(self):
        """Retourne le nombre de pairs connus."""
        with self.lock:
            return len(self.peers)

    def display(self):
        """Affiche la table des pairs."""
        peers = self.get_all()
        if not peers:
            print("[TABLE] Aucun pair connu pour l'instant...")
            return
        print(f"\n{'='*55}")
        print(f"  {len(peers)} PAIR(S) CONNU(S)")
        print(f"{'='*55}")
        for nid, info in peers.items():
            age = int(time.time() - info["last_seen"])
            print(f"  ID  : {nid[:20]}...")
            print(f"  IP  : {info['ip']}:{info['port']}")
            print(f"  Vu  : il y a {age}s")
            print(f"  {'-'*51}")


class DiscoveryService:
    """
    Service de découverte des pairs par UDP Multicast.
    Envoie des HELLO toutes les 30s et écoute les HELLO des autres.
    """

    def __init__(self, peer_table, node_id, tcp_port=7777):
        self.peer_table = peer_table
        self.node_id    = node_id
        self.tcp_port   = tcp_port
        self.running    = False

    def start(self):
        """Démarre les threads de découverte"""
        self.running = True
        
        # Obtenir la bonne IP locale
        from src.network.scanner import get_my_ip
        my_real_ip = get_my_ip()
        
        # Thread d'envoi des HELLO
        self.broadcast_thread = threading.Thread(target=self._hello_sender, daemon=True)
        self.broadcast_thread.start()
        
        # Thread d'écoute des HELLO
        self.listen_thread = threading.Thread(target=self._hello_listener, daemon=True)
        self.listen_thread.start()
        
        # Thread de nettoyage - AJOUTE CETTE MÉTHODE
        self.cleanup_thread = threading.Thread(target=self._cleanup, daemon=True)
        self.cleanup_thread.start()
        
        print(f"[DÉCOUVERTE] Service démarré sur IP {my_real_ip}")

    def _hello_sender(self):
        """Envoie HELLO en multicast toutes les 30s."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)

        from src.network.scanner import get_my_ip
        local_ip = get_my_ip()
        print(f"[DEBUG SENDER] Envoi depuis {local_ip} vers {MULTICAST_GROUP}:{MULTICAST_PORT}")

        first = True
        while self.running:
            try:
                payload = {
                    "node_id":   self.node_id,
                    "tcp_port":  self.tcp_port,
                    "timestamp": time.time()
                }
                packet = build_packet(TYPE_HELLO, self.node_id, payload)
                sock.sendto(packet, (MULTICAST_GROUP, MULTICAST_PORT))
                
                print(f"[DEBUG SENDER] Paquet HELLO envoyé à {MULTICAST_GROUP}:{MULTICAST_PORT}")

                if first:
                    print(f"[HELLO] Première annonce envoyée sur le réseau")
                    first = False

                time.sleep(HELLO_INTERVAL)

            except Exception as e:
                print(f"[ERREUR] Envoi HELLO : {e}")
                time.sleep(5)

    def _hello_listener(self):
        """Écoute les HELLO — version compatible Windows."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('', MULTICAST_PORT))

            mreq = struct.pack("4sL",
                socket.inet_aton(MULTICAST_GROUP),
                socket.INADDR_ANY
            )
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            sock.settimeout(2.0)

            print(f"[DEBUG LISTENER] Écoute sur 0.0.0.0:{MULTICAST_PORT}")
            print(f"[DEBUG LISTENER] Groupe multicast: {MULTICAST_GROUP}")
            
            from src.network.scanner import get_my_ip
            print(f"[DEBUG LISTENER] IP locale: {get_my_ip()}")

            while self.running:
                try:
                    data, addr = sock.recvfrom(4096)
                    print(f"[DEBUG LISTENER] Paquet reçu de {addr[0]}:{addr[1]}")
                    
                    packet = parse_packet(data)

                    if packet is None:
                        print("[DEBUG LISTENER] Paquet invalide")
                        continue
                    if packet["type"] != TYPE_HELLO:
                        print(f"[DEBUG LISTENER] Type incorrect: {packet['type']}")
                        continue

                    sender_id = packet["payload"]["node_id"]
                    tcp_port  = packet["payload"]["tcp_port"]
                    sender_ip = addr[0]

                    peer_key = f"{sender_id}_{tcp_port}"
                    my_key   = f"{self.node_id}_{self.tcp_port}"

                    if peer_key == my_key:
                        print("[DEBUG LISTENER] Message de soi-même ignoré")
                        continue

                    print(f"[DEBUG LISTENER] NOUVEAU PAIR: {sender_ip}:{tcp_port}")
                    self.peer_table.upsert(peer_key, sender_ip, tcp_port)

                except socket.timeout:
                    continue
                except Exception as e:
                    print(f"[DEBUG LISTENER] Erreur: {e}")
                    continue

        except Exception as e:
            print(f"[ERREUR FATALE] Listener : {e}")

    def _cleanup(self):  # Renommé de _cleanup_loop à _cleanup
        """Nettoie les pairs morts toutes les 30s."""
        while self.running:
            time.sleep(30)
            self.peer_table.remove_dead_peers()
            print("[DEBUG CLEANUP] Nettoyage des pairs morts effectué")

    def stop(self):
        """Arrête le service de découverte"""
        self.running = False
        print("[DÉCOUVERTE] Service arrêté")


def add_peer_manually(peer_table, ip, port):
    """Ajoute un pair manuellement par IP directe sans multicast."""
    node_id = f"manual_{ip}_{port}"
    peer_table.upsert(node_id, ip, port)
    print(f"[OK] Pair ajouté manuellement : {ip}:{port}")