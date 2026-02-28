"""
messaging.py — Service de messagerie chiffree E2E
- Chaque noeud est à la fois client ET serveur
- Gere les paquets normaux (ARCH) ET les paquets relayés (RLAY)
- Journalise TOUS les messages (envoyés + recus) dans .archipel/logs/
- Port TCP direct (identique au port annonce)
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

from src.crypto.packet    import build_packet, parse_packet, TYPE_MSG
from src.crypto.handshake import SessionManager

RELAY_MAGIC = b"RLAY"
ARCH_MAGIC  = b"ARCH"


def _log_path(port):
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    log_dir  = os.path.join(base_dir, ".archipel", "logs")
    os.makedirs(log_dir, exist_ok=True)
    return os.path.join(log_dir, f"messages_port{port}.log")


class MessagingService:
    """
    Service de messagerie chiffree + relayage.
    Serveur TCP unique sur le port annonce.
    Distingue les paquets ARCH (direct) et RLAY (relaye) par magic bytes.
    """

    def __init__(self, signing_key, node_id, session_manager, port=7777):
        self.signing_key     = signing_key
        self.node_id         = node_id
        self.session_manager = session_manager
        self.tcp_port        = port
        self.running         = False
        self.messages        = []
        self.log_file        = _log_path(port)
        self._print_lock     = threading.Lock()
        self._relay_service  = None
        self._file_transfer  = None

        self._write_log(f"\n{'='*60}")
        self._write_log(f"  ARCHIPEL — Journal du noeud port {port}")
        self._write_log(f"  Demarre : {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self._write_log(f"{'='*60}\n")

    @property
    def print_lock(self):
        return self._print_lock

    def set_relay_service(self, relay_service):
        self._relay_service = relay_service

    def set_file_transfer(self, file_transfer):
        self._file_transfer = file_transfer

    # --- Journal ---

    def _write_log(self, line):
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    def _log_message(self, direction, peer_ip, peer_id, plaintext, encrypted_hex):
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = {
            "timestamp": ts, "direction": direction,
            "peer_ip":   peer_ip, "peer_id": peer_id[:20] + "...",
            "message":   plaintext, "chiffre": encrypted_hex[:32] + "..."
        }
        self.messages.append(entry)
        self._write_log(
            f"[{ts}] {direction} | {peer_ip} | {plaintext} | chiffre: {encrypted_hex[:32]}..."
        )

    # --- Chiffrement ---

    def encrypt_message(self, plaintext, session_key):
        nonce = os.urandom(12)
        cipher = AES.new(session_key, AES.MODE_GCM, nonce=nonce)
        ciphertext, auth_tag = cipher.encrypt_and_digest(plaintext.encode("utf-8"))
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
            cipher     = AES.new(session_key, AES.MODE_GCM, nonce=nonce)
            return cipher.decrypt_and_verify(ciphertext, auth_tag).decode("utf-8")
        except Exception:
            return None

    # --- Envoi direct ---

    def send_message(self, peer_ip, peer_port, peer_node_id, message_text):
        """Envoie un message chiffre directement (connexion TCP directe)."""
        try:
            session_key = self.session_manager.get_session_key(self.node_id, peer_node_id)
            encrypted   = self.encrypt_message(message_text, session_key)

            payload = {
                "sender_id": self.node_id,
                "encrypted": encrypted,
                "timestamp": time.time()
            }
            msg_hash             = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).digest()
            payload["signature"] = self.signing_key.sign(msg_hash).signature.hex()

            packet = build_packet(TYPE_MSG, self.node_id, payload)

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((peer_ip, int(peer_port)))
            sock.sendall(len(packet).to_bytes(4, "big") + packet)
            sock.close()

            self._log_message("ENVOYE", peer_ip, peer_node_id, message_text, encrypted["ciphertext"])

            with self._print_lock:
                print(f"\r[ENVOYE] -> {peer_ip}:{peer_port}")
                print("Vous : ", end="", flush=True)
            return True

        except Exception as e:
            with self._print_lock:
                print(f"\r[ERREUR] Envoi echoue vers {peer_ip}:{peer_port} — {e}")
                print("Vous : ", end="", flush=True)
            return False

    # --- Serveur TCP ---

    def start_tcp_server(self, port=7777):
        self.tcp_port = port
        t = threading.Thread(target=self._tcp_server_loop, args=(port,), daemon=True)
        t.start()
        print(f"[TCP] Serveur messages actif sur port {port}")

    def _tcp_server_loop(self, port):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("0.0.0.0", port))
        server.listen(20)

        while True:
            try:
                conn, addr = server.accept()
                threading.Thread(
                    target=self._handle_connection,
                    args=(conn, addr),
                    daemon=True
                ).start()
            except Exception:
                pass

    def _handle_connection(self, conn, addr):
        """
        Lit la taille de la frame TCP (4 bytes), puis le contenu complet.
        Dispatche selon les magic bytes ARCH ou RLAY.
        """
        try:
            # 1. Lire la taille globale de la frame TCP (int32 big endian)
            size_b = conn.recv(4)
            if not size_b or len(size_b) < 4:
                return

            size = int.from_bytes(size_b, "big")

            # Securite anti-OOM
            if size > 10 * 1024 * 1024 or size == 0:
                return

            # 2. Lire tout le payload
            data = b""
            while len(data) < size:
                chunk = conn.recv(min(65536, size - len(data)))
                if not chunk:
                    break
                data += chunk

            if len(data) < 4:
                return

            # 3. Verifier les magic bytes inclus dans la data
            magic = data[:4]

            if magic == RELAY_MAGIC:
                if self._relay_service:
                    self._relay_service.handle_relay_packet(size_b + data, addr)

            elif magic == ARCH_MAGIC:
                packet = parse_packet(data)
                if packet and packet["type"] == TYPE_MSG:
                    self._handle_message(packet, addr)

        except Exception:
            pass
        finally:
            conn.close()

    def _handle_message(self, packet, addr):
        """Traite un message chiffre recu directement."""
        sender_id   = packet["payload"]["sender_id"]
        encrypted   = packet["payload"]["encrypted"]
        session_key = self.session_manager.get_session_key(self.node_id, sender_id)
        plaintext   = self.decrypt_message(encrypted, session_key)

        if plaintext:
            timestamp = datetime.datetime.now().strftime("%H:%M:%S")
            self._log_message("RECU", addr[0], sender_id, plaintext, encrypted["ciphertext"])

            with self._print_lock:
                print(f"\r{'='*55}")
                print(f"  MESSAGE RECU [{timestamp}]")
                print(f"  De : {addr[0]}  (ID: {sender_id[:16]}...)")
                print(f"  >> {plaintext}")
                print(f"{'='*55}")
                print("Vous : ", end="", flush=True)

            self.messages.append({
                "from":      sender_id,
                "text":      plaintext,
                "relay":     False,
                "timestamp": timestamp
            })

    # --- Accesseurs ---

    def get_all_messages(self):
        return list(self.messages)

    def get_log_path(self):
        return self.log_file