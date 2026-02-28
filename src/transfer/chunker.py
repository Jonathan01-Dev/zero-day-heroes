"""
chunker.py — Découpe et réassemblage de fichiers façon BitTorrent (Sprint 3)
- Génère le MANIFEST avec signature Ed25519
- Chunks de 512 KB par défaut
- Hachage SHA-256 complet
"""

import os
import sys
import hashlib
import json
import time

import nacl.signing

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

CHUNK_SIZE = 512 * 1024  # 512 KB par chunk
MAX_FILE_SIZE = 200 * 1024 * 1024  # 200 Mo max
DOWNLOAD_DIR = "telechargements"


def create_manifest(filepath, signing_key: nacl.signing.SigningKey):
    """
    Crée un manifeste conforme au Sprint 3 (BitTorrent-like).
    Lit le fichier par blocs de 512 KB.
    """
    if not os.path.exists(filepath):
        print(f"[ERREUR] Fichier introuvable : {filepath}")
        return None

    file_size = os.path.getsize(filepath)
    if file_size == 0:
        print(f"[ERREUR] Fichier vide")
        return None
    if file_size > MAX_FILE_SIZE:
        print(f"[ERREUR] Fichier trop grand (> 200 Mo)")
        return None

    filename = os.path.basename(filepath)

    # 1. Hacher le fichier entier et récolter les infos des chunks
    file_hash_obj = hashlib.sha256()
    chunks_info = []
    
    index = 0
    with open(filepath, "rb") as f:
        while True:
            raw = f.read(CHUNK_SIZE)
            if not raw:
                break
            
            chunk_hash = hashlib.sha256(raw).hexdigest()
            chunks_info.append({
                "index": index,
                "hash": chunk_hash,
                "size": len(raw)
            })
            
            file_hash_obj.update(raw)
            index += 1

    file_id = file_hash_obj.hexdigest()
    verify_key_hex = signing_key.verify_key.encode().hex()

    manifest_dict = {
        "file_id": file_id,
        "filename": filename,
        "size": file_size,
        "chunk_size": CHUNK_SIZE,
        "nb_chunks": len(chunks_info),
        "chunks": chunks_info,
        "sender_id": verify_key_hex
    }

    # Créer la signature sur le hash du manifeste
    manifest_str = json.dumps(manifest_dict, sort_keys=True)
    manifest_hash = hashlib.sha256(manifest_str.encode()).digest()
    signature_hex = signing_key.sign(manifest_hash).signature.hex()

    manifest_dict["signature"] = signature_hex

    return manifest_dict


def verify_manifest_signature(manifest_dict):
    """
    Verifie la signature Ed25519 du manifeste sans muter le dict.
    """
    try:
        sig_hex        = manifest_dict.get("signature", "")
        sender_id_hex  = manifest_dict["sender_id"]

        # Copie sans la signature pour verifier
        manifest_copy = {k: v for k, v in manifest_dict.items() if k != "signature"}

        verify_key = nacl.signing.VerifyKey(bytes.fromhex(sender_id_hex))

        manifest_str  = json.dumps(manifest_copy, sort_keys=True)
        manifest_hash = hashlib.sha256(manifest_str.encode()).digest()

        verify_key.verify(manifest_hash, bytes.fromhex(sig_hex))
        return True
    except Exception as e:
        print(f"[ERREUR] Signature manifeste invalide : {e}")
        return False


def get_chunk_data(filepath, chunk_index, chunk_size=CHUNK_SIZE):
    """
    Lit un chunk spécifique depuis le disque en fonction de son index.
    Utile pour répondre aux CHUNK_REQ sans tout charger en mémoire.
    """
    try:
        with open(filepath, "rb") as f:
            f.seek(chunk_index * chunk_size)
            data = f.read(chunk_size)
            if not data:
                return None
            return data
    except Exception:
        return None
