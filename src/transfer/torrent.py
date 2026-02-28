"""
torrent.py — Gestionnaire de swarm pour le téléchargement multi-sources
Inspiré de BitTorrent : télécharge les chunks en parallèle depuis plusieurs pairs.
"""

import os
import sys
import threading
import hashlib
import time
import queue

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

DOWNLOAD_DIR = "telechargements"


class ChunkState:
    """État d'un chunk : pending, downloading, done, error"""
    PENDING     = "pending"
    DOWNLOADING = "downloading"
    DONE        = "done"
    ERROR       = "error"


class SwarmManager:
    """
    Gère le téléchargement d'un fichier depuis plusieurs sources.
    Stratégie : file d'attente de chunks + workers parallèles.
    """

    def __init__(self, file_id, manifest, request_chunk_func, on_complete_func):
        self.file_id       = file_id
        self.manifest      = manifest
        self.nb_chunks     = manifest["nb_chunks"]
        self.filename      = manifest["filename"]

        # Fonction pour demander un chunk : (peer_id, ip, port, file_id, idx) -> bool
        self.request_chunk = request_chunk_func
        # Callback quand le téléchargement est terminé : (filepath) -> None
        self.on_complete   = on_complete_func

        # État des chunks
        self.chunks_state  = {i: ChunkState.PENDING for i in range(self.nb_chunks)}
        self.chunks_data   = {}   # idx -> bytes
        self.lock          = threading.Lock()

        # Sources disponibles : liste de (peer_id, ip, port, [chunk_ids])
        self.sources       = []
        self.sources_lock  = threading.Lock()

        # File de travail
        self.work_queue    = queue.Queue()

        # Contrôle des workers
        self.workers_running = False
        self.completed       = False
        self.workers         = []

        # Remplir la file avec tous les chunks
        for i in range(self.nb_chunks):
            self.work_queue.put(i)

    def add_peer_source(self, peer_id, ip, port, available_chunks):
        """Ajoute une source de chunks."""
        with self.sources_lock:
            self.sources.append({
                "peer_id": peer_id,
                "ip":      ip,
                "port":    port,
                "chunks":  set(available_chunks)
            })
        print(f"[SWARM] Source ajoutée : {ip}:{port} ({len(available_chunks)} chunks)")

    def start_workers(self, num_workers=3):
        """Démarre les workers de téléchargement."""
        self.workers_running = True
        for i in range(num_workers):
            t = threading.Thread(
                target=self._worker_loop,
                args=(i,),
                daemon=True
            )
            self.workers.append(t)
            t.start()
        print(f"[SWARM] {num_workers} workers démarrés pour {self.filename}")

    def _worker_loop(self, worker_id):
        """Boucle d'un worker : prend des chunks et les télécharge."""
        while self.workers_running and not self.completed:
            try:
                chunk_idx = self.work_queue.get(timeout=2)
            except queue.Empty:
                # Vérifier si tous les chunks sont terminés
                if self._all_done():
                    self._finalize()
                continue

            # Vérifier si déjà téléchargé
            with self.lock:
                if self.chunks_state.get(chunk_idx) == ChunkState.DONE:
                    self.work_queue.task_done()
                    continue
                self.chunks_state[chunk_idx] = ChunkState.DOWNLOADING

            # Choisir une source
            source = self._pick_source(chunk_idx)
            if source is None:
                # Remettre dans la file
                with self.lock:
                    self.chunks_state[chunk_idx] = ChunkState.PENDING
                self.work_queue.put(chunk_idx)
                self.work_queue.task_done()
                time.sleep(0.5)
                continue

            # Télécharger
            success = self.request_chunk(
                source["peer_id"],
                source["ip"],
                source["port"],
                self.file_id,
                chunk_idx
            )

            if success:
                # Le chunk est stocké via receive_chunk()
                pass
            else:
                # Remettre dans la file pour réessai
                with self.lock:
                    self.chunks_state[chunk_idx] = ChunkState.PENDING
                self.work_queue.put(chunk_idx)

            self.work_queue.task_done()

        # Vérification finale
        if self._all_done() and not self.completed:
            self._finalize()

    def receive_chunk(self, chunk_idx, data, received_hash):
        """
        Appelé quand un chunk est reçu.
        Vérifie le hash SHA-256 et stocke le chunk.
        Retourne True si valide, False sinon.
        """
        expected_hash = self.manifest["chunks"][chunk_idx]["hash"]

        if received_hash != expected_hash:
            print(f"[SWARM] ❌ Chunk {chunk_idx} corrompu — hash invalide")
            with self.lock:
                self.chunks_state[chunk_idx] = ChunkState.ERROR
            # Remettre dans la file
            self.work_queue.put(chunk_idx)
            return False

        with self.lock:
            self.chunks_data[chunk_idx]    = data
            self.chunks_state[chunk_idx]   = ChunkState.DONE

        return True

    def _pick_source(self, chunk_idx):
        """Choisit une source qui a ce chunk."""
        with self.sources_lock:
            for source in self.sources:
                if chunk_idx in source["chunks"]:
                    return source
            # Si aucune source spécifique, prendre la première dispo
            if self.sources:
                return self.sources[0]
        return None

    def _all_done(self):
        """Vérifie si tous les chunks sont téléchargés."""
        with self.lock:
            done = sum(
                1 for s in self.chunks_state.values()
                if s == ChunkState.DONE
            )
            return done >= self.nb_chunks

    def _finalize(self):
        """Réassemble le fichier et appelle le callback."""
        if self.completed:
            return
        self.completed       = True
        self.workers_running = False

        print(f"\n[SWARM] Tous les chunks reçus — réassemblage de {self.filename}...")

        # Créer le dossier de téléchargement
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        output_path = os.path.join(DOWNLOAD_DIR, self.filename)

        # Écrire les chunks dans l'ordre
        errors = 0
        with open(output_path, "wb") as f:
            for i in range(self.nb_chunks):
                data = self.chunks_data.get(i)
                if data is None:
                    print(f"[SWARM] ❌ Chunk {i} manquant !")
                    errors += 1
                    continue
                f.write(data)

        if errors == 0:
            # Vérification SHA-256 finale
            with open(output_path, "rb") as f:
                final_hash = hashlib.sha256(f.read()).hexdigest()

            if final_hash == self.manifest["file_id"]:
                size_mb = self.manifest["size"] / (1024 * 1024)
                print(f"[✅ SWARM] Fichier vérifié : {output_path}")
                print(f"[✅ SWARM] Taille : {size_mb:.2f} Mo")
                print(f"[✅ SWARM] SHA-256 : {final_hash[:16]}...")
                if self.on_complete:
                    self.on_complete(output_path)
            else:
                print(f"[❌ SWARM] Hash final invalide — fichier corrompu")
        else:
            print(f"[❌ SWARM] {errors} chunk(s) manquant(s)")

    def get_progress(self):
        """Retourne (chunks_done, total, pourcentage)."""
        with self.lock:
            done = sum(
                1 for s in self.chunks_state.values()
                if s == ChunkState.DONE
            )
        total = self.nb_chunks
        pct   = (done / total * 100) if total > 0 else 0
        return done, total, pct