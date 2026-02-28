"""
identity.py — Gestion de l'identité cryptographique du nœud
Chaque nœud (port) a sa propre paire de clés Ed25519.
"""

import nacl.signing
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


def _identity_path(port=7777):
    """Retourne le chemin du fichier identité pour ce port."""
    # On s'assure que le dossier .archipel est créé à la racine du projet
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    archipel_dir = os.path.join(base_dir, ".archipel")
    os.makedirs(archipel_dir, exist_ok=True)
    return os.path.join(archipel_dir, f"identity_{port}.json")


def generate_identity(port=7777):
    """Génère une paire de clés Ed25519 unique pour ce nœud/port."""
    path = _identity_path(port)

    signing_key = nacl.signing.SigningKey.generate()
    verify_key  = signing_key.verify_key

    data = {
        "port":    port,
        "private": signing_key.encode().hex(),
        "public":  verify_key.encode().hex()
    }

    with open(path, "w") as f:
        json.dump(data, f, indent=2)

    print(f"[🆔] Nouvelle identité créée (port {port})")
    print(f"[🆔] Clé publique : {data['public'][:20]}...")
    return signing_key, verify_key


def load_identity(port=7777):
    """Charge ou génère l'identité pour ce port spécifique."""
    path = _identity_path(port)

    if not os.path.exists(path):
        print(f"[INFO] Pas d'identité pour le port {port}, création...")
        return generate_identity(port)

    with open(path) as f:
        data = json.load(f)

    signing_key = nacl.signing.SigningKey(bytes.fromhex(data["private"]))
    verify_key  = signing_key.verify_key

    print(f"[🆔] Identité chargée (port {port}) : {data['public'][:20]}...")
    return signing_key, verify_key


def get_node_id(port=7777):
    """Retourne la clé publique en hex (l'ID du nœud)."""
    _, verify_key = load_identity(port)
    return verify_key.encode().hex()