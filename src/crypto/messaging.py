"""
messaging.py — Service de messagerie chiffrée E2E
- Chaque nœud est à la fois client ET serveur
- Journalise TOUS les messages (envoyés + reçus) dans un fichier de log
- Port TCP = port annoncé (plus de +1000, cohérence avec le scanner)
- Affichage propre même pendant la saisie
"""

import os
import sys
import json
import time
import socket
import hashlib
import threading
import datetime

from Crypto.Cipher import AES
import nacl.signing
import nacl.encoding

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.crypto.packet   import build_packet, parse_packet, TYPE_MSG
from src.crypto.handshake import SessionManager


def _log_path(port):
    """Retourne le chemin du fichier log pour ce nœud."""
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    log_dir  = os.path.join(base_dir, ".archipel", "logs")
    os.makedirs(log_dir, exist_ok=True)
    return os.path.join(log_dir, f"messages_port{port}.log")


class MessagingService:
    """
    Service de messagerie chiffrée bout-en-bout.
    
    Chaque nœud est serveur ET client :
    - Serveur TCP : reçoit les messages entrants
    - Client TCP  : envoie les messages sortants
    - Journal     : enregistre TOUS les messages (envoyés + reçus)
    """

    def __init__(self, signing_key, node_id, session_manager, port=7777):
        self.signing_key     = signing_key
        self.node_id         = node_id
        self.session_manager = session_manager
        self.tcp_port        = port    # PORT DIRECT — plus de +1000
        self.running         = False
        self.messages        = []      # Historique en mémoire
        self.log_file        = _log_path(port)
        self._print_lock     = threading.Lock()

        # Entête du fichier log
        self._write_log(f"\n{'='*60}")
        self._write_log(f"  ARCHIPEL — Journal du nœud port {port}")
        self._write_log(f"  Démarré : {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self._write_log(f"{'='*60}\n")

    def _write_log(self, line):
        """Écrit une ligne dans le fichier journal."""
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    def _log_message(self, direction, peer_ip, peer_id, plaintext, encrypted_hex):
        """Journalise un message (envoyé ou reçu)."""
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = {
            "timestamp":   ts,
            "direction":   direction,      # "ENVOYÉ" ou "REÇU"
            "peer_ip":     peer_ip,
            "peer_id":     peer_id[:20] + "..." if len(peer_id) > 20 else peer_id,
            "message":     plaintext,
            "chiffré":     encrypted_hex[:32] + "..."
        }
        self.messages.append(entry)

        log_line = (
            f"[{ts}] {direction} | {peer_ip} | "
            f"{plaintext} | chiffré: {encrypted_hex[:32]}..."
        )
        self._write_log(log_line)

    def encrypt_message(self, plaintext, session_key):
        nonce = os.urandom(12)
        cipher = AES.new(session_key, AES.MODE_GCM, nonce=nonce)
        ciphertext, auth_tag = cipher.encrypt_and_digest(
            plaintext.encode('utf-8')
        )
        return {
            "nonce":      nonce.hex(),
            "ciphertext": ciphertext.hex(),
            "auth_tag":   auth_tag.hex()
        }

    def decrypt_message(self, encrypted_data, session_key):
        try:
            nonce      = bytes.fromhex(encrypted_data["nonce"])
            ciphertext = bytes.fromhex(encrypted_data["ciphertext"])
            auth_tag   = bytes.fromhex(encrypted_data["auth_tag"])

            cipher    = AES.new(session_key, AES.MODE_GCM, nonce=nonce)
            plaintext = cipher.decrypt_and_verify(ciphertext, auth_tag)
            return plaintext.decode('utf-8')

        except Exception as e:
            return None

    def send_message(self, peer_ip, peer_port, peer_node_id, message_text):
        """
        Envoie un message chiffré à un pair.
        Connexion directe sur peer_port (TCP).
        """
        try:
            session_key = self.session_manager.get_session_key(
                self.node_id, peer_node_id
            )
            encrypted = self.encrypt_message(message_text, session_key)

            payload = {
                "sender_id": self.node_id,
                "encrypted": encrypted,
                "timestamp": time.time()
            }

            msg_hash         = hashlib.sha256(
                json.dumps(payload, sort_keys=True).encode()
            ).digest()
            signature        = self.signing_key.sign(msg_hash).signature.hex()
            payload["signature"] = signature

            packet = build_packet(TYPE_MSG, self.node_id, payload)

            target_port = int(peer_port)   # PORT DIRECT — plus de +1000

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((peer_ip, target_port))

            size = len(packet).to_bytes(4, 'big')
            sock.sendall(size + packet)
            sock.close()

            # Journaliser le message envoyé
            self._log_message(
                "ENVOYÉ", peer_ip, peer_node_id,
                message_text, encrypted["ciphertext"]
            )

            with self._print_lock:
                print(f"\r[✉️  ENVOYÉ] → {peer_ip}:{target_port}  🔐 {encrypted['ciphertext'][:20]}...")
                print("Vous : ", end="", flush=True)
            return True

        except Exception as e:
            with self._print_lock:
                print(f"\r[⚠️] Envoi échoué vers {peer_ip}:{peer_port} — {e}")
                print("Vous : ", end="", flush=True)
            return False

    def start_tcp_server(self, port=7777):
        """Lance le serveur TCP sur le port annoncé (direct, pas +1000)."""
        self.tcp_port = port
        t = threading.Thread(
            target=self._tcp_server_loop,
            args=(port,),
            daemon=True
        )
        t.start()
        print(f"[TCP] Serveur messages actif sur port {port}")

    def _tcp_server_loop(self, port):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(('0.0.0.0', port))
        server.listen(20)

        while True:
            try:
                conn, addr = server.accept()
                threading.Thread(
                    target=self._handle_connection,
                    args=(conn, addr),
                    daemon=True
                ).start()
            except Exception as e:
                if self.running:
                    pass  # ignore lors de l'arrêt

    def _handle_connection(self, conn, addr):
        try:
            size_bytes = conn.recv(4)
            if not size_bytes:
                return
            size = int.from_bytes(size_bytes, 'big')

            data = b''
            while len(data) < size:
                chunk = conn.recv(min(4096, size - len(data)))
                if not chunk:
                    break
                data += chunk

            packet = parse_packet(data)
            if packet is None:
                return

            if packet["type"] == TYPE_MSG:
                self._handle_message(packet, addr)

        except Exception:
            pass
        finally:
            conn.close()

    def _handle_message(self, packet, addr):
        sender_id = packet["payload"]["sender_id"]
        encrypted = packet["payload"]["encrypted"]

        session_key = self.session_manager.get_session_key(
            self.node_id, sender_id
        )

        plaintext = self.decrypt_message(encrypted, session_key)

        if plaintext:
            timestamp = datetime.datetime.now().strftime("%H:%M:%S")

            # Journaliser le message reçu
            self._log_message(
                "REÇU", addr[0], sender_id,
                plaintext, encrypted["ciphertext"]
            )

            # Afficher proprement sans casser le prompt de saisie
            with self._print_lock:
                print(f"\r{'='*55}")
                print(f"  📨 MESSAGE REÇU [{timestamp}]")
                print(f"  De  : {addr[0]}  |  ID: {sender_id[:16]}...")
                print(f"  📝  : {plaintext}")
                print(f"{'='*55}")
                print("Vous : ", end="", flush=True)

    def get_all_messages(self):
        """Retourne l'historique complet des messages (envoyés + reçus)."""
        return list(self.messages)

    def get_log_path(self):
        """Retourne le chemin du fichier journal."""
        return self.log_file