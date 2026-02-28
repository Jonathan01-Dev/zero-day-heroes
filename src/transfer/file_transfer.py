"""
file_transfer.py — Service de transfert de fichiers par chunks (BitTorrent-like)
Protocole simplifie :
- MANIFEST broadcast via TCP (port+2000)
- CHUNK_REQ/DATA en mode synchrone sur un seul socket TCP
"""

import os
import sys
import json
import socket
import threading
import time
import hashlib
import base64

from Crypto.Cipher import AES

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.transfer.chunker import create_manifest, verify_manifest_signature, get_chunk_data, CHUNK_SIZE
from src.transfer.torrent import SwarmManager

MANIFEST_PORT_OFFSET = 1000  # port + 2000 : serveur manifest

class FileTransferService:
    def __init__(self, node_id, my_ip, base_port, print_lock, session_manager, signing_key, peer_table):
        self.node_id = node_id
        self.my_ip = my_ip
        self.base_port = base_port
        self.manifest_port = base_port + MANIFEST_PORT_OFFSET
        self._print_lock = print_lock
        self.session_manager = session_manager
        self.signing_key = signing_key
        self.peer_table = peer_table

        self.swarms = {}        # file_id -> SwarmManager
        self.local_files = {}   # file_id -> {filepath, manifest}

    def start(self):
        t = threading.Thread(target=self._manifest_server_loop, daemon=True)
        t.start()
        print(f"[TRANSFERT] Service ecoute sur port {self.manifest_port}")

    # ── SEED (envoyeur) ──────────────────────────────────────────────

    def seed_file(self, filepath):
        """Genere le manifest et le broadcast aux pairs."""
        manifest = create_manifest(filepath, self.signing_key)
        if not manifest:
            print("[ERREUR] Impossible de creer le manifest")
            return False

        file_id = manifest["file_id"]
        self.local_files[file_id] = {
            "filepath": os.path.abspath(filepath),
            "manifest": manifest
        }

        with self._print_lock:
            print(f"\n[🌱 SEED] Fichier {manifest['filename']} ({manifest['size'] / 1024:.1f} Ko)")
            print(f"[🔒 SÉCURISÉ] Chiffrement E2E : AES-GCM actif")
            print(f"[🌱 SEED] {manifest['nb_chunks']} chunk(s) de {manifest['chunk_size']//1024}KB")
            print(f"[🌱 SEED] Broadcast en cours...")

        peers = self.peer_table.get_all()
        envois = 0
        for peer_id, info in peers.items():
            if self._send_tcp(info["ip"], info["port"] + MANIFEST_PORT_OFFSET, {
                "type": "MANIFEST",
                "manifest": manifest,
                "sender_ip": self.my_ip,
                "sender_port": self.base_port
            }):
                envois += 1

        with self._print_lock:
            print(f"[SEED] Manifest envoye a {envois} pair(s).")
            print("Vous : ", end="", flush=True)

        return True

    # ── SERVEUR MANIFEST (recoit les MANIFEST des seeders) ────────────

    def _manifest_server_loop(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("0.0.0.0", self.manifest_port))
        server.listen(20)

        while True:
            try:
                conn, addr = server.accept()
                threading.Thread(
                    target=self._handle_manifest_conn,
                    args=(conn, addr),
                    daemon=True
                ).start()
            except Exception:
                pass



    def _handle_manifest_received(self, msg, addr):
        manifest = msg["manifest"]
        sender_ip   = msg.get("sender_ip", addr[0])
        sender_port = msg.get("sender_port", self.base_port)

        if not verify_manifest_signature(manifest):
            print("[ERREUR] Signature du manifest invalide")
            return

        file_id = manifest["file_id"]

        # Deja possede
        if file_id in self.local_files:
            return

        # Deja en cours de telechargement
        if file_id in self.swarms:
            self.swarms[file_id].add_peer_source(
                manifest["sender_id"], sender_ip, sender_port,
                list(range(manifest["nb_chunks"]))
            )
            return

        with self._print_lock:
            print(f"\n{'='*55}")
            print(f"  📥 NOUVEAU FICHIER DÉTECTÉ : {manifest['filename']}")
            print(f"  Taille : {manifest['size'] / (1024*1024):.2f} Mo")
            print(f"  Source : {sender_ip}")
            print(f"  [🔒 SÉCURISÉ] Chiffrement E2E : AES-GCM actif")
            print(f"  Téléchargement automatique en cours...")
            print(f"{'='*55}")
            print("Vous : ", end="", flush=True)

        # Creer et demarrer le Swarm
        swarm = SwarmManager(file_id, manifest, self.request_chunk_sync, self._on_download_complete)
        self.swarms[file_id] = swarm

        swarm.add_peer_source(
            manifest["sender_id"], sender_ip, sender_port,
            list(range(manifest["nb_chunks"]))
        )

        swarm.start_workers(num_workers=3)
        threading.Thread(target=self._progress_monitor_ui, args=(swarm,), daemon=True).start()

    # ── CHUNK REQUEST (synchrone) ─────────────────────────────────────

    def request_chunk_sync(self, peer_id, ip, port, file_id, chunk_idx):
        """
        Envoie CHUNK_REQ et ATTEND la reponse CHUNK_DATA dans le meme socket TCP.
        Retourne True si le chunk a ete recu et valide, False sinon.
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10)
            # Le seeder ecoute les CHUNK_REQ directement sur son port manifest
            sock.connect((ip, port + MANIFEST_PORT_OFFSET))

            # Envoyer la requete
            req = {
                "type": "CHUNK_REQ",
                "file_id": file_id,
                "chunk_idx": chunk_idx,
                "requester_id": self.node_id
            }
            payload = json.dumps(req).encode("utf-8")
            sock.sendall(len(payload).to_bytes(4, "big") + payload)

            # Lire la reponse directement sur ce meme socket
            size_b = sock.recv(4)
            if not size_b or len(size_b) < 4:
                sock.close()
                return False
            size = int.from_bytes(size_b, "big")

            data = b""
            while len(data) < size:
                chunk = sock.recv(min(65536, size - len(data)))
                if not chunk: break
                data += chunk

            sock.close()

            if not data:
                return False

            resp = json.loads(data.decode("utf-8"))
            if resp.get("type") != "CHUNK_DATA":
                return False

            # Dechiffrer AES-GCM
            enc = resp["enc_payload"]
            session_key = self.session_manager.get_session_key(self.node_id, resp["provider_id"])
            nonce      = base64.b64decode(enc["nonce"])
            ciphertext = base64.b64decode(enc["data"])
            tag        = base64.b64decode(enc["tag"])
            cipher     = AES.new(session_key, AES.MODE_GCM, nonce=nonce)
            raw_data   = cipher.decrypt_and_verify(ciphertext, tag)

            # Verifier hash
            chunk_hash = hashlib.sha256(raw_data).hexdigest()

            # Notifier le swarm
            swarm = self.swarms.get(file_id)
            if swarm:
                return swarm.receive_chunk(chunk_idx, raw_data, chunk_hash)

            return False

        except Exception as e:
            return False

    # ── SERVEUR CHUNKS (repond aux CHUNK_REQ) ─────────────────────────
    # Note: les CHUNK_REQ arrivent sur le meme port manifest (port+2000)
    # Le serveur manifest les dispatche ici selon le type

    def _handle_chunk_req(self, msg, conn):
        """Repond a une requete de chunk DIRECTEMENT sur le meme socket."""
        file_id   = msg["file_id"]
        chunk_idx = msg["chunk_idx"]
        req_id    = msg.get("requester_id", "")

        if file_id not in self.local_files:
            resp = {"type": "ERROR", "msg": "file not found"}
            payload = json.dumps(resp).encode("utf-8")
            conn.sendall(len(payload).to_bytes(4, "big") + payload)
            return

        filepath = self.local_files[file_id]["filepath"]
        manifest = self.local_files[file_id]["manifest"]

        raw_data = get_chunk_data(filepath, chunk_idx, manifest["chunk_size"])
        if raw_data is None:
            return

        # Chiffrer AES-GCM
        session_key = self.session_manager.get_session_key(self.node_id, req_id)
        nonce = os.urandom(12)
        cipher = AES.new(session_key, AES.MODE_GCM, nonce=nonce)
        ciphertext, tag = cipher.encrypt_and_digest(raw_data)

        resp = {
            "type": "CHUNK_DATA",
            "file_id": file_id,
            "chunk_idx": chunk_idx,
            "provider_id": self.node_id,
            "enc_payload": {
                "nonce": base64.b64encode(nonce).decode(),
                "data":  base64.b64encode(ciphertext).decode(),
                "tag":   base64.b64encode(tag).decode()
            }
        }
        payload = json.dumps(resp).encode("utf-8")
        conn.sendall(len(payload).to_bytes(4, "big") + payload)

    # ── Override _handle_manifest_conn pour gerer aussi CHUNK_REQ ─────

    def _handle_manifest_conn(self, conn, addr):
        try:
            size_b = conn.recv(4)
            if not size_b or len(size_b) < 4: return
            size = int.from_bytes(size_b, "big")
            if size > 50 * 1024 * 1024: return

            data = b""
            while len(data) < size:
                chunk = conn.recv(min(65536, size - len(data)))
                if not chunk: break
                data += chunk

            msg = json.loads(data.decode("utf-8"))
            msg_type = msg.get("type", "")

            if msg_type == "MANIFEST":
                conn.close()  # pas de reponse pour un MANIFEST
                self._handle_manifest_received(msg, addr)
                return

            elif msg_type == "CHUNK_REQ":
                # Repondre directement sur ce socket
                self._handle_chunk_req(msg, conn)

        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    # ── UI Progress ───────────────────────────────────────────────────

    def _progress_monitor_ui(self, swarm):
        while swarm.workers_running and not swarm.completed:
            done, total, pct = swarm.get_progress()
            bar = '#' * int(pct // 5)
            print(f"\r  [{bar:<20}] {pct:.0f}% ({done}/{total} chunks)", end="", flush=True)
            time.sleep(0.5)
        print()

    def _on_download_complete(self, filepath):
        with self._print_lock:
            print(f"\n[OK] Fichier sauvegarde : {filepath}")
            print("Vous : ", end="", flush=True)

    # ── Utilitaire TCP ────────────────────────────────────────────────

    def _send_tcp(self, ip, port, data_dict):
        try:
            payload = json.dumps(data_dict, ensure_ascii=False).encode("utf-8")
            size = len(payload).to_bytes(4, "big")
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((ip, port))
            sock.sendall(size + payload)
            sock.close()
            return True
        except Exception:
            return False