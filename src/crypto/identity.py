import nacl.signing
import json
import os

IDENTITY_PATH = ".archipel/identity.json"

def generate_identity():
    """Génère une paire de clés Ed25519 pour ce nœud"""
    os.makedirs(".archipel", exist_ok=True)
    
    # Génère la clé privée (pour signer) et publique (pour s'identifier)
    signing_key = nacl.signing.SigningKey.generate()
    verify_key = signing_key.verify_key
    
    data = {
        "private": signing_key.encode().hex(),
        "public": verify_key.encode().hex()
    }
    
    with open(IDENTITY_PATH, "w") as f:
        json.dump(data, f, indent=2)
    
    print(f"[OK] Identité créée !")
    print(f"[OK] Clé publique (votre ID) : {data['public'][:16]}...")
    return signing_key, verify_key

def load_identity():
    """Charge l'identité existante depuis le disque"""
    if not os.path.exists(IDENTITY_PATH):
        print("[INFO] Pas d'identité trouvée, création...")
        return generate_identity()
    
    with open(IDENTITY_PATH) as f:
        data = json.load(f)
    
    signing_key = nacl.signing.SigningKey(bytes.fromhex(data["private"]))
    verify_key = signing_key.verify_key
    
    print(f"[OK] Identité chargée : {data['public'][:16]}...")
    return signing_key, verify_key

def get_node_id():
    """Retourne juste la clé publique en hex (l'ID du nœud)"""
    _, verify_key = load_identity()
    return verify_key.encode().hex()