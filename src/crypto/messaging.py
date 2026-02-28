import os
import sys
import json
import time
import socket
import hashlib
import threading

from Crypto.Cipher import AES
import nacl.signing
import nacl.encoding

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.crypto.packet   import build_packet, parse_packet, TYPE_MSG
from src.crypto.handshake import SessionManager


class MessagingService:
    """Service de messagerie chiffrée bout-en-bout"""

    def __init__(self, signing_key, node_id, session_manager):
        self.signing_key     = signing_key
        self.node_id         = node_id
        self.session_manager = session_manager
        self.tcp_port        = 7777
        self.running         = False
        self.messages        = []

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
            print(f"[ERREUR] Déchiffrement échoué : {e}")
            return None

    def send_message(self, peer_ip, peer_port, peer_node_id, message_text):
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

            msg_hash  = hashlib.sha256(
                json.dumps(payload, sort_keys=True).encode()
            ).digest()
            signature        = self.signing_key.sign(msg_hash).signature.hex()
            payload["signature"] = signature

            packet = build_packet(TYPE_MSG, self.node_id, payload)

            # Port TCP = port annoncé + 1000 pour séparer de l'UDP
            tcp_target = int(peer_port) + 1000

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((peer_ip, tcp_target))

            size = len(packet).to_bytes(4, 'big')
            sock.sendall(size + packet)
            sock.close()

            print(f"[✉️  ENVOYÉ] → {peer_ip}:{tcp_target}")
            print(f"[🔐 CHIFFRÉ] {encrypted['ciphertext'][:32]}...")
            return True

        except Exception as e:
            print(f"[ERREUR] Envoi message : {e}")
            return False

    def start_tcp_server(self, port=7777):
        # Port TCP = port annoncé + 1000
        tcp_port      = port + 1000
        self.tcp_port = tcp_port

        t = threading.Thread(
            target=self._tcp_server_loop,
            args=(tcp_port,),
            daemon=True
        )
        t.start()
        print(f"[TCP] Serveur messages sur port {tcp_port}")

    def _tcp_server_loop(self, port):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(('0.0.0.0', port))
        server.listen(10)

        while True:
            try:
                conn, addr = server.accept()
                threading.Thread(
                    target=self._handle_connection,
                    args=(conn, addr),
                    daemon=True
                ).start()
            except Exception as e:
                print(f"[ERREUR] TCP server : {e}")

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

        except Exception as e:
            print(f"[ERREUR] Connexion : {e}")
        finally:
            conn.close()

    def _handle_message(self, packet, addr):
        sender_id = packet["payload"]["sender_id"]
        encrypted = packet["payload"]["encrypted"]

        # sender_id ici est le node_id pur — get_session_key le nettoie
        session_key = self.session_manager.get_session_key(
            self.node_id, sender_id
        )

        plaintext = self.decrypt_message(encrypted, session_key)

        if plaintext:
            timestamp = time.strftime("%H:%M:%S")
            print(f"\n{'='*50}")
            print(f"  📨 MESSAGE REÇU [{timestamp}]")
            print(f"  De  : {sender_id[:16]}...")
            print(f"  IP  : {addr[0]}")
            print(f"  📝  : {plaintext}")
            print(f"{'='*50}\n")

            self.messages.append({
                "from":      sender_id,
                "text":      plaintext,
                "timestamp": timestamp
            })