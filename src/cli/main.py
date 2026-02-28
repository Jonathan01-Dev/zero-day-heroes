import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.crypto.identity   import load_identity
from src.crypto.messaging  import MessagingService
from src.crypto.handshake  import SessionManager
from src.network.discovery import DiscoveryService, PeerTable

peer_table = PeerTable()

def cmd_listen(port=7777):
    signing_key, verify_key = load_identity()
    node_id = verify_key.encode().hex()

    print("=" * 50)
    print("   ARCHIPEL - Mode Écoute")
    print("=" * 50)
    print(f"[NŒUD] ID   : {node_id[:16]}...")
    print(f"[NŒUD] Port : {port}")
    print("[INFO] Ctrl+C pour arrêter\n")

    session_manager = SessionManager(signing_key)
    messaging = MessagingService(signing_key, node_id, session_manager)
    messaging.start_tcp_server(port)

    discovery = DiscoveryService(peer_table, node_id, tcp_port=port)
    discovery.start()

    print(f"[OK] En écoute sur le port {port}...")
    print("[INFO] Les messages reçus s'affichent automatiquement\n")

    try:
        while True:
            time.sleep(20)
            peers = peer_table.get_all()
            print(f"\n--- Pairs connus ({len(peers)}) ---")
            for i, (nid, info) in enumerate(peers.items()):
                print(f"  [{i}] {info['ip']}:{info['port']}")
            print("--- fin ---\n")

    except KeyboardInterrupt:
        print("\n[ARRÊT] Nœud arrêté")
        discovery.stop()


def cmd_chat(port=8888):
    signing_key, verify_key = load_identity()
    node_id = verify_key.encode().hex()

    print("=" * 50)
    print("   ARCHIPEL - Mode Chat")
    print("=" * 50)
    print(f"[NŒUD] ID   : {node_id[:16]}...")
    print(f"[NŒUD] Port : {port}\n")

    session_manager = SessionManager(signing_key)
    messaging = MessagingService(signing_key, node_id, session_manager)
    messaging.start_tcp_server(port)

    discovery = DiscoveryService(peer_table, node_id, tcp_port=port)
    discovery.start()

    print("[INFO] Attente découverte des pairs (15 secondes)...")
    time.sleep(15)

    peers = peer_table.get_all()
    if not peers:
        print("[ERREUR] Aucun pair trouvé.")
        print("[INFO] Assurez-vous que l'autre terminal tourne avec : listen 7777")
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
    except (ValueError, IndexError):
        print("[ERREUR] Choix invalide")
        return

    print(f"\n[OK] Connecté à {peer_ip}:{peer_port}")
    print("[INFO] Tapez votre message + Entrée pour envoyer")
    print("[INFO] Tapez 'quit' pour quitter\n")

    # Boucle de chat — input() sans thread = stable
    while True:
        try:
            texte = input("Vous : ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n[ARRÊT]")
            break

        if not texte:
            continue

        if texte.lower() == "quit":
            print("[ARRÊT] Chat terminé")
            break

        # ✅ CORRECTION : on passe my_node_id ET peer_id
        # pour que les 2 côtés calculent la même clé de session
        success = messaging.send_message(
            peer_ip,
            int(peer_port),
            peer_id,   # ← vrai node_id du pair, plus "peer"
            texte
        )

        if not success:
            print("[❌] Échec envoi — le pair est peut-être déconnecté")


def cmd_msg(peer_ip, peer_port, message_text):
    """Envoi rapide sans mode interactif"""
    signing_key, verify_key = load_identity()
    node_id = verify_key.encode().hex()

    session_manager = SessionManager(signing_key)
    messaging = MessagingService(signing_key, node_id, session_manager)

    # Cherche le node_id du pair dans la peer table
    # Si pas trouvé on utilise l'IP:port comme identifiant
    peer_node_id = f"{peer_ip}_{peer_port}"
    peers = peer_table.get_all()
    for nid, info in peers.items():
        if info["ip"] == peer_ip and str(info["port"]) == str(peer_port):
            peer_node_id = nid
            break

    print(f"[ENVOI] → {peer_ip}:{peer_port}")
    print(f"[MSG]   : {message_text}")

    success = messaging.send_message(
        peer_ip,
        int(peer_port),
        peer_node_id,
        message_text
    )

    if success:
        print("[✅] Message envoyé et chiffré !")
    else:
        print("[❌] Échec de l'envoi")


def show_help():
    print("""
ARCHIPEL — Commandes :

  python src/cli/main.py listen 7777
      → Mode écoute (reçoit les messages)

  python src/cli/main.py chat 8888
      → Mode chat interactif (envoie les messages)

  python src/cli/main.py msg <ip> <port> "Bonjour"
      → Envoi rapide sans mode interactif

  python src/cli/main.py help
      → Cette aide

WORKFLOW DEMO (2 terminaux) :
  Terminal 1 : python src/cli/main.py listen 7777
  Terminal 2 : python src/cli/main.py chat 8888
    """)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        show_help()
        sys.exit(0)

    command = sys.argv[1]

    if command == "listen":
        port = int(sys.argv[2]) if len(sys.argv) > 2 else 7777
        cmd_listen(port)

    elif command == "chat":
        port = int(sys.argv[2]) if len(sys.argv) > 2 else 8888
        cmd_chat(port)

    elif command == "msg":
        if len(sys.argv) < 5:
            print("[ERREUR] Usage : msg <ip> <port> <message>")
            print("         Exemple : msg 192.168.1.10 7777 Bonjour")
        else:
            cmd_msg(sys.argv[2], sys.argv[3], sys.argv[4])

    elif command == "help":
        show_help()

    else:
        print(f"[ERREUR] Commande inconnue : {command}")
        show_help()