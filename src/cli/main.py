"""
main.py — Point d'entree principal du noeud Archipel
Interface minimaliste : lister les PC, option 1=Chat, option 2=Fichier
"""

import sys
import os
import time
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.crypto.identity   import load_identity
from src.crypto.messaging  import MessagingService
from src.crypto.handshake  import SessionManager
from src.network.discovery import DiscoveryService, PeerTable, add_peer_manually
from src.network.scanner   import scan_network, get_my_ip
from src.network.router    import RelayService
from src.transfer.file_transfer import FileTransferService

peer_table    = PeerTable()
messaging     = None
relay_service = None
file_transfer = None
my_node_id    = None
my_ip         = None
my_port       = 7777


def afficher_pairs():
    peers     = peer_table.get_all()
    peer_list = list(peers.items())

    print(f"\n{'='*55}")
    print(f"  {len(peer_list)} PC(S) DETECTE(S) SUR LE RESEAU")
    print(f"{'='*55}")
    if not peer_list:
        print("  (Aucun pair trouve pour l'instant...)")
    for i, (nid, info) in enumerate(peer_list):
        age = int(time.time() - info["last_seen"])
        print(f"  [{i}] {info['ip']}:{info['port']}  (il y a {age}s)")
    print(f"{'='*55}\n")
    return peer_list


def boucle_chat(peer_id, peer_ip, peer_port):
    global messaging

    print(f"\n{'-'*55}")
    print(f"  Chat avec {peer_ip}:{peer_port}")
    print(f"  Tapez votre message + Entree")
    print(f"  Tapez 'quit' pour revenir au menu")
    print(f"{'-'*55}\n")

    while True:
        try:
            print("Vous : ", end="", flush=True)
            texte = input("").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n[RETOUR MENU]")
            return

        if not texte:
            continue
        if texte.lower() == "quit":
            return

        success = messaging.send_message(peer_ip, int(peer_port), peer_id, texte)
        if not success:
            print(f"[ERREUR] Envoi echoue. {peer_ip} est-il connecte ?")


def thread_scan(port):
    time.sleep(3)
    ips = scan_network(port=port, timeout=0.4)
    if ips:
        for ip in ips:
            add_peer_manually(peer_table, ip, port)


def attendre_et_chatter():
    global messaging, file_transfer
    print(f"\n[ATTENTE] Recherche des autres PC sur le reseau...")
    # Attendre jusqu'a 8s pour laisser le temps à la découverte multicast/broadcast + scan
    for _ in range(8):
        if peer_table.count() > 0:
            break
        time.sleep(1)

    while True:
        # Si toujours aucun pair, relancer le scan et attendre encore
        if peer_table.count() == 0:
            print("[SCAN] Aucun PC trouve. Nouveau scan en cours...")
            thread_scan(my_port)
            time.sleep(4)

        peer_list = afficher_pairs()

        if not peer_list:
            print("  Toujours aucun PC detecte.")
            print("  [actualiser] -> nouveau scan    [quit] -> quitter")
            print(f"{'-'*55}\n")
        else:
            print(f"  Entrez le NUMERO du PC pour interagir")
            print(f"  [actualiser] -> rafraichir la liste")
            print(f"  [quit] -> quitter")
            print(f"{'-'*55}\n")

        try:
            choix = input("Votre choix : ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n[ARRET]")
            break

        if not choix:
            continue

        if choix.lower() == "quit":
            break

        if choix.lower() == "actualiser":
            threading.Thread(target=thread_scan, args=(my_port,), daemon=True).start()
            print("[SCAN] Scan en cours...")
            time.sleep(3)
            continue

        try:
            index = int(choix)
            if 0 <= index < len(peer_list):
                peer_id, peer_info = peer_list[index]

                print(f"\n  PC selectionne : {peer_info['ip']}")
                print("  1. Envoyer un message")
                print("  2. Envoyer un fichier")
                print("  3. Retour")
                print()

                try:
                    action = input("  Choix [1/2/3] : ").strip()
                except (KeyboardInterrupt, EOFError):
                    continue

                if action == "1":
                    boucle_chat(peer_id, peer_info["ip"], peer_info["port"])

                elif action == "2":
                    try:
                        chemin = input("  Chemin du fichier : ").strip()
                    except (KeyboardInterrupt, EOFError):
                        continue
                    if os.path.exists(chemin):
                        threading.Thread(
                            target=file_transfer.seed_file,
                            args=(chemin,),
                            daemon=True
                        ).start()
                        print("[OK] Transfert demarre en arriere-plan.")
                    else:
                        print(f"[ERREUR] Fichier introuvable : {chemin}")

            elif len(peer_list) == 0:
                print("[INFO] Aucun PC detecte pour l'instant. Tapez 'actualiser'.")
            else:
                print(f"[ERREUR] Entrez un numero entre 0 et {len(peer_list)-1}")
        except ValueError:
            print("[ERREUR] Entrez un numero ou une commande.")



def cmd_node(port=7777):
    global messaging, relay_service, file_transfer, my_node_id, my_ip, my_port
    my_port = port

    signing_key, verify_key = load_identity(port)
    my_node_id = verify_key.encode().hex()
    my_ip      = get_my_ip()

    print()
    print("=" * 55)
    print("  ARCHIPEL P2P — Zero-Day Heroes Hackathon 2026")
    print("=" * 55)
    print(f"  Mon IP   : {my_ip}")
    print(f"  Port     : {port}")
    print(f"  ID       : {my_node_id[:24]}...")
    print("=" * 55)

    session_manager = SessionManager(signing_key)
    messaging = MessagingService(signing_key, my_node_id, session_manager, port)
    messaging.start_tcp_server(port)

    relay_service = RelayService(my_node_id, peer_table, messaging)
    messaging.set_relay_service(relay_service)

    file_transfer = FileTransferService(my_node_id, my_ip, port, messaging.print_lock, session_manager, signing_key, peer_table)
    file_transfer.start()
    messaging.set_file_transfer(file_transfer)

    discovery = DiscoveryService(peer_table, my_node_id, tcp_port=port)
    discovery.start()

    # Lancer le scan réseau en arrière-plan périodiquement
    def periodic_scan():
        while True:
            thread_scan(port)
            time.sleep(30)
    
    threading.Thread(target=periodic_scan, daemon=True).start()

    t_chat = threading.Thread(target=attendre_et_chatter, daemon=True)
    t_chat.start()

    try:
        while t_chat.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        discovery.stop()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python src/cli/main.py node 7777")
        sys.exit(0)
    if sys.argv[1] == "node":
        port = int(sys.argv[2]) if len(sys.argv) > 2 else 7777
        cmd_node(port)