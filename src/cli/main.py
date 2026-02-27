import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.crypto.identity import load_identity, get_node_id
from src.crypto.packet import build_packet, parse_packet, TYPE_HELLO
from src.network.discovery import DiscoveryService, PeerTable

# Objets globaux
peer_table = PeerTable()
discovery  = None
my_node_id = None

def cmd_start(port=7777):
    """Démarre le nœud Archipel"""
    global discovery, my_node_id
    
    print("=" * 50)
    print("   ARCHIPEL - Réseau P2P Souverain")
    print("=" * 50)
    
    signing_key, verify_key = load_identity()
    my_node_id = verify_key.encode().hex()
    
    print(f"[NŒUD] ID : {my_node_id[:16]}...")
    print(f"[NŒUD] Port TCP : {port}")
    
    # Démarre la découverte
    discovery = DiscoveryService(peer_table, my_node_id, tcp_port=port)
    discovery.start()
    
    print("\n[OK] Nœud démarré ! En attente de pairs...")
    print("[INFO] Tapez Ctrl+C pour arrêter\n")
    
    # Boucle principale — affiche les pairs toutes les 15s
    try:
        while True:
            time.sleep(15)
            peer_table.display()
    except KeyboardInterrupt:
        print("\n[ARRÊT] Nœud arrêté proprement")
        if discovery:
            discovery.stop()

def cmd_peers():
    """Affiche les pairs connus"""
    peer_table.display()

def cmd_status():
    """Affiche le statut du nœud"""
    node_id = get_node_id()
    peers   = peer_table.get_all()
    print(f"[STATUT] Nœud ID   : {node_id[:16]}...")
    print(f"[STATUT] Pairs actifs : {len(peers)}")

def show_help():
    print("""
ARCHIPEL — Commandes disponibles :

  python src/cli/main.py start          → Démarrer le nœud
  python src/cli/main.py start 8888     → Démarrer sur port custom
  python src/cli/main.py peers          → Voir les pairs découverts
  python src/cli/main.py status         → Voir le statut
  python src/cli/main.py help           → Cette aide
    """)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        show_help()
        sys.exit(0)
    
    command = sys.argv[1]
    
    if command == "start":
        port = int(sys.argv[2]) if len(sys.argv) > 2 else 7777
        cmd_start(port)
    elif command == "peers":
        cmd_peers()
    elif command == "status":
        cmd_status()
    elif command == "help":
        show_help()
    else:
        print(f"[ERREUR] Commande inconnue : {command}")
        show_help()