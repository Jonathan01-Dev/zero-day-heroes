import hashlib
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

# Clé partagée fixe — identique sur tous les nœuds du réseau
NETWORK_SECRET = "archipel-zero-day-heroes-2026"

class SessionManager:
    def __init__(self, my_signing_key):
        self.my_signing_key = my_signing_key
        self.sessions = {}

    def get_session_key(self, my_node_id, peer_node_id):
        """
        Retourne toujours la même clé fixe dérivée du secret réseau.
        Tous les nœuds arrivent au même résultat peu importe leur ID.
        """
        # Clé identique pour tout le réseau
        session_key = hashlib.sha256(
            NETWORK_SECRET.encode('utf-8')
        ).digest()

        # Stocker pour éviter de recalculer
        self.sessions[peer_node_id] = {
            "key":        session_key,
            "created_at": time.time()
        }

        return session_key

    def create_session(self, my_node_id, peer_node_id):
        return self.get_session_key(my_node_id, peer_node_id)

    def has_session(self, peer_node_id):
        return peer_node_id in self.sessions