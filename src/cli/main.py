import sys
import os
import time
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.crypto.identity   import load_identity
from src.crypto.messaging  import MessagingService
from src.crypto.handshake  import SessionManager
from src.network.discovery import DiscoveryService, PeerTable, add_peer_manually

peer_table    = PeerTable()
messaging     = None
file_transfer = None

def input_thread(peer_list_ref):
    """Thread séparé pour lire les messages à envoyer"""
    global messaging

    # Attendre que les pairs soient découverts
    print("[INFO] En attente de pairs... (max 30 secondes)")
    for _ in range(30):
        time.sleep(1)
        peers = peer_table.get_all()
        if peers:
            break

    peers = peer_table.get_all()
    if not peers:
        print("\n[⚠️] Aucun pair trouvé automatiquement.")
        print("[INFO] Utilisez la connexion manuelle :")
        print("       python src/cli/main.py node 7777 <IP_DU_PAIR>")
        return

    # Affiche les pairs
    print(f"\n{len(peers)} pair(s) trouvé(s) :")
    peer_list = list(peers.items())
    for i, (nid, info) in enumerate(peer_list):
        print(f"  [{i}] {info['ip']}:{info['port']}")

    # Choix du pair
    try:
        choix     = input("\nChoisir le pair (numéro) : ").strip()
        index     = int(choix)
        peer_id, peer_info = peer_list[index]
        peer_ip   = peer_info["ip"]
        peer_port = peer_info["port"]
        peer_list_ref["id"]   = peer_id
        peer_list_ref["ip"]   = peer_ip
        peer_list_ref["port"] = peer_port
    except (ValueError, IndexError):
        print("[ERREUR] Choix invalide")
        return

    print(f"\n[OK] Connecté à {peer_ip}:{peer_port}")
    print("─" * 50)
    print("  Tapez votre message + Entrée pour envoyer")
    print("  Tapez 'quit' pour quitter")
    print("─" * 50 + "\n")

    # Boucle chat
    while True:
        try:
            texte = input("Vous : ").strip()
        except (KeyboardInterrupt, EOFError):
            break

        if not texte:
            continue

        if texte.lower() == "quit":
            print("[ARRÊT] Chat terminé")
            break

        messaging.send_message(
            peer_ip,
            int(peer_port),
            peer_id,
            texte
        )


def cmd_node(port=7777, peer_ip=None):
    """
    Mode nœud complet.
    Si peer_ip est fourni : connexion directe sans multicast.
    """
    global messaging

    signing_key, verify_key = load_identity()
    node_id = verify_key.encode().hex()

    print("=" * 50)
    print("   ARCHIPEL - Nœud Complet")
    print("=" * 50)
    print(f"[NŒUD] ID   : {node_id[:16]}...")
    print(f"[NŒUD] Port : {port}\n")

    # Démarre les services
    session_manager = SessionManager(signing_key)
    messaging = MessagingService(signing_key, node_id, session_manager)
    messaging.start_tcp_server(port)

    discovery = DiscoveryService(peer_table, node_id, tcp_port=port)
    discovery.start()

    # Si IP fournie → connexion directe immédiate
    if peer_ip:
        print(f"[INFO] Connexion directe vers {peer_ip}:{port}")
        add_peer_manually(peer_table, peer_ip, port)

    # Thread pour l'input
    peer_ref = {}
    t = threading.Thread(
        target=input_thread,
        args=(peer_ref,),
        daemon=True
    )
    t.start()

    # Boucle principale
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[ARRÊT] Nœud arrêté proprement")
        discovery.stop()


def show_help():
    print("""
ARCHIPEL — Commandes :

  python src/cli/main.py node 7777
      → Nœud automatique (découverte multicast)

  python src/cli/main.py node 7777 192.168.1.10
      → Connexion directe vers IP (si multicast bloqué)

  python src/cli/main.py help
      → Cette aide

WORKFLOW 2 PC MÊME RÉSEAU :
  PC1 : python src/cli/main.py node 7777
  PC2 : python src/cli/main.py node 7777 <IP_DE_PC1>

WORKFLOW MÊME MACHINE :
  Terminal 1 : python src/cli/main.py node 7777
  Terminal 2 : python src/cli/main.py node 8888
    """)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        show_help()
        sys.exit(0)

    command = sys.argv[1]

    if command == "node":
        port     = int(sys.argv[2]) if len(sys.argv) > 2 else 7777
        peer_ip  = sys.argv[3] if len(sys.argv) > 3 else None
        cmd_node(port, peer_ip)

    elif command == "help":
        show_help()

    else:
        print(f"[ERREUR] Commande inconnue : {command}")
        show_help()