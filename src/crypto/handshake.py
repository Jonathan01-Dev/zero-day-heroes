import hashlib
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

# Clé partagée fixe pour le hackathon
# Les 2 nœuds utilisent TOUJOURS cette clé → déchiffrement garanti
SHARED_SECRET = "archipel-hackathon-2026-zero-day-heroes"

class SessionManager:
    def __init__(self, my_signing_key):
        self.my_signing_key = my_signing_key
        self.sessions = {}

    def create_session(self, my_node_id, peer_node_id):
        """
        Clé de session = SHA256(secret + node_ids triés).
        Le tri garantit que les 2 côtés arrivent au même résultat.
        """
        # Prendre seulement les 16 premiers chars pour éviter
        # le problème node_id_port vs node_id pur
        id_a = my_node_id[:16]
        id_b = peer_node_id[:16]

        # Tri alphabétique → même ordre des 2 côtés
        ids_sorted = sorted([id_a, id_b])

        combined = (
            SHARED_SECRET +
            ids_sorted[0] +
            ids_sorted[1]
        ).encode('utf-8')

        session_key = hashlib.sha256(combined).digest()

        self.sessions[peer_node_id] = {
            "key":        session_key,
            "created_at": time.time()
        }

        print(f"[SESSION] Clé créée avec {peer_node_id[:16]}...")
        return session_key

    def get_session_key(self, my_node_id, peer_node_id):
        """
        Récupère ou crée la clé.
        On nettoie le peer_node_id au cas où il contient _port
        """
        # Nettoyer le peer_node_id — enlever le suffixe _port si présent
        clean_peer_id = peer_node_id.split("_")[0]
        clean_my_id   = my_node_id.split("_")[0]

        if clean_peer_id not in self.sessions:
            return self.create_session(clean_my_id, clean_peer_id)
        return self.sessions[clean_peer_id]["key"]

    def has_session(self, peer_node_id):
        clean = peer_node_id.split("_")[0]
        return clean in self.sessions