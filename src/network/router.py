"""
router.py — Routage multi-hop des messages et fichiers
Permet à PC1 d'envoyer via PC2 pour atteindre PC3.
Le destinataire final voit toujours la SOURCE originale (PC1).

Protocole de routage :
  PC1 → [RELAY, dest=PC3, source=PC1, ttl=3] → PC2
  PC2 → [RELAY, dest=PC3, source=PC1, ttl=2] → PC3 (livraison finale)

TTL (Time To Live) : nombre de sauts maximum = 5
"""

import os
import sys
import json
import time
import socket
import hashlib
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.crypto.packet import build_packet, parse_packet, TYPE_MSG

# Type spécial pour les paquets relayés
TYPE_RELAY = 0x08
MAX_TTL    = 5   # Maximum 5 sauts


class RoutingTable:
    """
    Table de routage : association peer_id → ip:port
    Mis à jour automatiquement depuis la PeerTable.
    """

    def __init__(self, peer_table):
        self.peer_table = peer_table

    def get_route(self, dest_id):
        """
        Retourne (ip, port) du destinataire si connu directement,
        sinon retourne le premier pair connu comme relai.
        """
        peers = self.peer_table.get_all()

        # Chercher le destinataire directement
        if dest_id in peers:
            p = peers[dest_id]
            return p["ip"], p["port"], "direct"

        # Sinon, retourner un relai (premier pair disponible)
        for peer_id, peer_info in peers.items():
            if peer_id != dest_id:
                return peer_info["ip"], peer_info["port"], f"via_{peer_id[:8]}"

        return None, None, None

    def get_all_peers(self):
        return self.peer_table.get_all()


class RelayService:
    """
    Service de relayage de messages.

    Chaque nœud peut servir de relai :
    - reçoit un paquet RELAY destiné à quelqu'un d'autre
    - le retransmet au destinataire (ou à un pair plus proche)
    - décrémente le TTL pour éviter les boucles infinies
    """

    def __init__(self, node_id, peer_table, messaging_service):
        self.node_id   = node_id
        self.routing   = RoutingTable(peer_table)
        self.messaging = messaging_service
        self._seen     = set()   # Anti-boucle : IDs de paquets déjà vus
        self._lock     = threading.Lock()

    def should_relay(self, packet_id):
        """Retourne True si ce paquet n'a pas déjà été relayé."""
        with self._lock:
            if packet_id in self._seen:
                return False
            self._seen.add(packet_id)
            # Nettoyer les vieux IDs (garder max 1000)
            if len(self._seen) > 1000:
                self._seen = set(list(self._seen)[-500:])
            return True

    def route_message(self, dest_id, dest_ip, dest_port, message_text,
                      original_sender_id, original_sender_ip,
                      ttl=MAX_TTL, via_ids=None):
        """
        Envoie un message en passant par un relai si nécessaire.

        dest_id     : ID du destinataire final
        original_sender_id : ID de l'expéditeur original (toujours visible)
        ttl         : nombre de sauts restants
        via_ids     : liste des IDs déjà traversés (chemin)

        Retourne (success, route_taken)
        """
        if via_ids is None:
            via_ids = [self.node_id]

        # Paquet unique pour anti-boucle
        packet_id = hashlib.sha256(
            f"{original_sender_id}{dest_id}{message_text}{time.time()}".encode()
        ).hexdigest()[:16]

        # Essai direct d'abord
        if dest_ip and dest_port:
            relay_payload = {
                "relay_type":    "message",
                "packet_id":     packet_id,
                "origin_id":     original_sender_id,
                "origin_ip":     original_sender_ip,
                "dest_id":       dest_id,
                "message":       message_text,
                "ttl":           ttl - 1,
                "via":           via_ids,
                "timestamp":     time.time()
            }
            success = self._send_relay_packet(dest_ip, int(dest_port), relay_payload)
            if success:
                route = " → ".join(via_ids) + f" → {dest_ip}"
                return True, route

        # Si échec ou pas de route directe, passer par un relai
        peers = self.routing.get_all_peers()
        for peer_id, peer_info in peers.items():
            if peer_id == dest_id:
                continue
            if peer_id in via_ids:
                continue   # Ne pas repasser par un nœud déjà visité

            relay_payload = {
                "relay_type": "message",
                "packet_id":  packet_id,
                "origin_id":  original_sender_id,
                "origin_ip":  original_sender_ip,
                "dest_id":    dest_id,
                "message":    message_text,
                "ttl":        ttl - 1,
                "via":        via_ids + [peer_id[:8]],
                "timestamp":  time.time()
            }
            success = self._send_relay_packet(
                peer_info["ip"], int(peer_info["port"]), relay_payload
            )
            if success:
                route = " → ".join(via_ids) + f" → {peer_info['ip']} → {dest_id[:8]}"
                return True, route

        return False, "aucune route"

    def _send_relay_packet(self, ip, port, payload):
        """Envoie un paquet RELAY brut via TCP."""
        try:
            data  = json.dumps(payload).encode("utf-8")
            size  = len(data).to_bytes(4, "big")
            magic = b"RLAY"  # Magic bytes pour distinguer des paquets ARCH normaux

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((ip, port))
            sock.sendall(magic + size + data)
            sock.close()
            return True
        except Exception:
            return False

    def handle_relay_packet(self, raw_data, from_addr):
        """
        Traite un paquet RELAY entrant.
        Appelé par le serveur TCP quand magic = RLAY.
        """
        try:
            size    = int.from_bytes(raw_data[:4], "big")
            payload = json.loads(raw_data[4:4 + size].decode("utf-8"))
        except Exception as e:
            print(f"[RELAY] Paquet invalide : {e}")
            return

        packet_id = payload.get("packet_id", "")
        if not self.should_relay(packet_id):
            return   # Paquet déjà traité (anti-boucle)

        relay_type   = payload.get("relay_type", "message")
        dest_id      = payload.get("dest_id", "")
        origin_id    = payload.get("origin_id", "")
        origin_ip    = payload.get("origin_ip", from_addr[0])
        ttl          = payload.get("ttl", 0)
        via          = payload.get("via", [])

        # Suis-je le destinataire final ?
        am_i_dest = dest_id == self.node_id or dest_id.startswith(self.node_id[:16])

        if relay_type == "message":
            message = payload.get("message", "")

            if am_i_dest:
                # LIVRAISON FINALE — afficher avec la vraie source
                self._deliver_message(message, origin_id, origin_ip, via, from_addr[0])
            elif ttl > 0:
                # RELAYAGE — retransmettre vers le destinataire
                self._forward_message(payload, ttl, via)
            else:
                print(f"[RELAY] TTL expiré pour paquet {packet_id[:8]} — abandonné")

        elif relay_type == "file_chunk":
            self._handle_relay_file_chunk(payload, am_i_dest, ttl, via, from_addr)

    def _deliver_message(self, message, origin_id, origin_ip, via, last_hop_ip):
        """Affiche le message reçu avec la source originale et le chemin."""
        timestamp = time.strftime("%H:%M:%S")
        route_str = " → ".join(via) if via else last_hop_ip

        print(f"\n{'═'*55}")
        print(f"  📨 MESSAGE REÇU (relayé) [{timestamp}]")
        print(f"  🌍 Source   : {origin_ip}  (ID: {origin_id[:16]}...)")
        print(f"  🔀 Chemin   : {route_str} → MOI")
        print(f"  📝 Message  : {message}")
        print(f"{'═'*55}")
        print("Vous : ", end="", flush=True)

        # Journaliser
        if self.messaging:
            self.messaging._log_message(
                "REÇU(relayé)", origin_ip, origin_id,
                message, "<relayé>"
            )
            self.messaging.messages.append({
                "from":    origin_id,
                "text":    message,
                "relay":   True,
                "via":     via,
                "timestamp": timestamp
            })

    def _forward_message(self, payload, ttl, via):
        """Retransmet un paquet RELAY vers le destinataire."""
        dest_id = payload.get("dest_id", "")
        peers   = self.routing.get_all_peers()

        # Chercher le destinataire directement
        for peer_id, peer_info in peers.items():
            if peer_id == dest_id or peer_id.startswith(dest_id[:16]):
                payload["ttl"] = ttl - 1
                payload["via"] = via + [self.node_id[:8]]
                success = self._send_relay_packet(
                    peer_info["ip"], int(peer_info["port"]), payload
                )
                if success:
                    print(f"[🔀 RELAY] Relayé vers {peer_info['ip']} (dest finale)")
                    print("Vous : ", end="", flush=True)
                return

        # Sinon, retransmettre au premier pair qui n'est pas dans via
        for peer_id, peer_info in peers.items():
            if peer_id not in via:
                payload["ttl"] = ttl - 1
                payload["via"] = via + [self.node_id[:8]]
                success = self._send_relay_packet(
                    peer_info["ip"], int(peer_info["port"]), payload
                )
                if success:
                    print(f"[🔀 RELAY] Relayé via {peer_info['ip']}")
                    print("Vous : ", end="", flush=True)
                return

        print(f"[RELAY] Impossible de relayer (aucun pair valide)")

    def _handle_relay_file_chunk(self, payload, am_i_dest, ttl, via, from_addr):
        """Gère le relayage d'un chunk de fichier."""
        if am_i_dest:
            # Déléguer au service de transfert de fichiers
            if self.messaging and hasattr(self.messaging, '_file_transfer'):
                self.messaging._file_transfer.handle_incoming_chunk_payload(payload)
        elif ttl > 0:
            dest_id = payload.get("dest_id", "")
            peers   = self.routing.get_all_peers()
            for peer_id, peer_info in peers.items():
                if peer_id not in via:
                    payload["ttl"] = ttl - 1
                    payload["via"] = via + [self.node_id[:8]]
                    self._send_relay_packet(
                        peer_info["ip"], int(peer_info["port"]), payload
                    )
                    return
