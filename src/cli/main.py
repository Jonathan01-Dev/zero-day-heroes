import sys
import os

# Permet d'importer les modules src depuis n'importe où
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.crypto.identity import load_identity, get_node_id
from src.crypto.packet import build_packet, parse_packet, TYPE_HELLO

def cmd_start():
    """Démarre le nœud Archipel"""
    print("=" * 50)
    print("   ARCHIPEL - Réseau P2P Souverain")
    print("=" * 50)
    signing_key, verify_key = load_identity()
    node_id = verify_key.encode().hex()
    print(f"[NŒUD] ID complet : {node_id}")
    print("[INFO] Prêt. Sprints suivants : réseau P2P...")

def cmd_status():
    """Affiche le statut du nœud"""
    node_id = get_node_id()
    print(f"[STATUT] Nœud ID : {node_id[:16]}...")
    print(f"[STATUT] Pairs connectés : 0 (Sprint 1 pas encore fait)")

def cmd_test_packet():
    """Teste la création et lecture d'un paquet"""
    node_id = get_node_id()
    
    # Crée un paquet HELLO de test
    packet = build_packet(TYPE_HELLO, node_id, {
        "message": "hello world",
        "port": 7777
    })
    
    print(f"[TEST] Paquet créé : {len(packet)} bytes")
    print(f"[TEST] Hex : {packet.hex()[:40]}...")
    
    # Relit le paquet
    parsed = parse_packet(packet)
    if parsed:
        print(f"[TEST] Paquet décodé OK !")
        print(f"[TEST] Type : {hex(parsed['type'])}")
        print(f"[TEST] Payload : {parsed['payload']}")
    else:
        print("[TEST] Échec du décodage")

def show_help():
    print("""
ARCHIPEL — Commandes disponibles :

  python src/cli/main.py start        → Démarrer le nœud
  python src/cli/main.py status       → Voir le statut
  python src/cli/main.py test-packet  → Tester les paquets
  python src/cli/main.py help         → Cette aide
    """)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        show_help()
        sys.exit(0)
    
    command = sys.argv[1]
    
    if command == "start":
        cmd_start()
    elif command == "status":
        cmd_status()
    elif command == "test-packet":
        cmd_test_packet()
    elif command == "help":
        show_help()
    else:
        print(f"[ERREUR] Commande inconnue : {command}")
        show_help()