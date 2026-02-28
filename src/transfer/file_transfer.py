import os
import sys
import json
import socket
import threading
import hashlib
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.transfer.chunker import split_file, reassemble_file

TRANSFER_PORT_OFFSET = 2000  # port transfert = port nœud + 2000

class FileTransferService:
    """Service de transfert de fichiers par chunks"""

    def __init__(self, node_id, base_port=7777):
        self.node_id      = node_id
        self.base_port    = base_port
        self.transfer_port = base_port + TRANSFER_PORT_OFFSET
        self.received     = {}   # file_id -> chunks reçus
        self.manifests    = {}   # file_id -> manifest

    def start(self):
        """Démarre le serveur de transfert"""
        t = threading.Thread(
            target=self._server_loop,
            daemon=True
        )
        t.start()
        print(f"[TRANSFERT] Serveur sur port {self.transfer_port}")

    def send_file(self, filepath, peer_ip, peer_port):
        """
        Envoie un fichier complet à un pair.
        Découpe en chunks, envoie chunk par chunk.
        """
        result = split_file(filepath)
        if result is None:
            return False

        manifest, chunks, file_id = result

        target_port = int(peer_port) + TRANSFER_PORT_OFFSET

        print(f"\n[TRANSFERT] Envoi de {manifest['filename']}")
        print(f"[TRANSFERT] {manifest['nb_chunks']} chunks → {peer_ip}:{target_port}")
        print(f"[TRANSFERT] Taille : {manifest['size']} bytes\n")

        try:
            # Étape 1 — Envoyer le manifest
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10)
            sock.connect((peer_ip, target_port))

            msg = json.dumps({
                "type":     "MANIFEST",
                "manifest": manifest
            }).encode('utf-8')

            sock.sendall(len(msg).to_bytes(4, 'big') + msg)
            sock.close()
            time.sleep(0.5)

            # Étape 2 — Envoyer les chunks
            sent    = 0
            errors  = 0

            for chunk in chunks:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(10)
                    sock.connect((peer_ip, target_port))

                    msg = json.dumps({
                        "type":    "CHUNK",
                        "file_id": file_id,
                        "index":   chunk["index"],
                        "hash":    chunk["hash"],
                        "size":    chunk["size"],
                        "data":    chunk["data"]
                    }).encode('utf-8')

                    sock.sendall(len(msg).to_bytes(4, 'big') + msg)
                    sock.close()

                    sent += 1
                    # Barre de progression
                    pct = int((sent / manifest['nb_chunks']) * 100)
                    print(f"\r[TRANSFERT] Progression : {sent}/{manifest['nb_chunks']} chunks ({pct}%)", end="", flush=True)

                except Exception as e:
                    print(f"\n[ERREUR] Chunk {chunk['index']} : {e}")
                    errors += 1

            print(f"\n[TRANSFERT] Terminé ! {sent} chunks envoyés, {errors} erreurs")

            # Étape 3 — Signal de fin
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10)
            sock.connect((peer_ip, target_port))
            msg = json.dumps({
                "type":    "DONE",
                "file_id": file_id
            }).encode('utf-8')
            sock.sendall(len(msg).to_bytes(4, 'big') + msg)
            sock.close()

            return errors == 0

        except Exception as e:
            print(f"[ERREUR] Transfert : {e}")
            return False

    def _server_loop(self):
        """Écoute les transferts entrants"""
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(('0.0.0.0', self.transfer_port))
        server.listen(10)

        while True:
            try:
                conn, addr = server.accept()
                threading.Thread(
                    target=self._handle_transfer,
                    args=(conn, addr),
                    daemon=True
                ).start()
            except Exception as e:
                print(f"[ERREUR] Serveur transfert : {e}")

    def _handle_transfer(self, conn, addr):
        """Traite une connexion de transfert"""
        try:
            size_bytes = conn.recv(4)
            if not size_bytes:
                return
            size = int.from_bytes(size_bytes, 'big')

            data = b''
            while len(data) < size:
                chunk = conn.recv(min(65536, size - len(data)))
                if not chunk:
                    break
                data += chunk

            msg = json.loads(data.decode('utf-8'))

            if msg["type"] == "MANIFEST":
                manifest = msg["manifest"]
                file_id  = manifest["file_id"]
                self.manifests[file_id]  = manifest
                self.received[file_id]   = []
                print(f"\n[📥 REÇU] Manifest : {manifest['filename']}")
                print(f"[📥 REÇU] {manifest['nb_chunks']} chunks attendus")

            elif msg["type"] == "CHUNK":
                file_id = msg["file_id"]
                if file_id in self.received:
                    self.received[file_id].append({
                        "index": msg["index"],
                        "hash":  msg["hash"],
                        "size":  msg["size"],
                        "data":  msg["data"]
                    })
                    total    = self.manifests[file_id]["nb_chunks"]
                    received = len(self.received[file_id])
                    pct      = int((received / total) * 100)
                    print(f"\r[📥 REÇU] {received}/{total} chunks ({pct}%)", end="", flush=True)

            elif msg["type"] == "DONE":
                file_id = msg["file_id"]
                print(f"\n[📥 REÇU] Transfert terminé, réassemblage...")

                if file_id in self.manifests and file_id in self.received:
                    result = reassemble_file(
                        self.received[file_id],
                        self.manifests[file_id]
                    )
                    if result:
                        print(f"[✅ FICHIER] Sauvegardé : {result}")

        except Exception as e:
            print(f"[ERREUR] Traitement transfert : {e}")
        finally:
            conn.close()