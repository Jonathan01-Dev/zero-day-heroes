"""
main.py — Point d'entrée principal du nœud Archipel
- Chaque nœud est serveur ET client
- Découverte automatique : multicast UDP + scan TCP en parallèle
- Journalisation de tous les messages (envoyés + reçus)
- Fonctionne sur hotspot sans Internet
- UX propre : messages reçus n'interrompent pas la saisie
"""

import sys
import os
import time
import threading
import socket

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.crypto.identity   import load_identity
from src.crypto.messaging  import MessagingService
from src.crypto.handshake  import SessionManager
from src.network.discovery import DiscoveryService, PeerTable, add_peer_manually
from src.network.scanner   import scan_network, get_my_ip

peer_table = PeerTable()
messaging  = None
my_port    = 7777


# ─────────────────────────────────────────────
#   Affichage des pairs
# ─────────────────────────────────────────────

def afficher_pairs():
    """Affiche tous les PC disponibles avec numérotation."""
    peers     = peer_table.get_all()
    peer_list = list(peers.items())

    print(f"\n{'═'*55}")
    print(f"  🌐  {len(peer_list)} PC(S) DISPONIBLE(S) SUR LE RÉSEAU")
    print(f"{'═'*55}")
    if not peer_list:
        print("  (Aucun pair trouvé pour l'instant...)")
    for i, (nid, info) in enumerate(peer_list):
        age = int(time.time() - info["last_seen"])
        type_peer = "local" if info["ip"] in ("127.0.0.1", "::1") else "réseau"
        print(f"  [{i}] {info['ip']}:{info['port']}  (vu il y a {age}s, {type_peer})")
    print(f"{'═'*55}\n")

    return peer_list


# ─────────────────────────────────────────────
#   Choix du destinataire
# ─────────────────────────────────────────────

def choisir_pair(peer_list):
    """Demande à l'utilisateur de choisir un destinataire."""
    while True:
        try:
            choix = input(f"👉 Choisir le destinataire [0-{len(peer_list)-1}] : ").strip()
            index = int(choix)
            if 0 <= index < len(peer_list):
                peer_id, peer_info = peer_list[index]
                return peer_id, peer_info["ip"], peer_info["port"]
            else:
                print(f"[ERREUR] Entrez un numéro entre 0 et {len(peer_list)-1}")
        except ValueError:
            print("[ERREUR] Numéro invalide")
        except KeyboardInterrupt:
            return None, None, None


# ─────────────────────────────────────────────
#   Boucle de chat
# ─────────────────────────────────────────────

def boucle_chat(peer_id, peer_ip, peer_port):
    """
    Boucle principale du chat.
    Retourne True si l'utilisateur veut changer de destinataire.
    Retourne False pour quitter.
    """
    global messaging

    print(f"\n{'─'*55}")
    print(f"  💬 Chat avec {peer_ip}:{peer_port}")
    print(f"  Commandes :")
    print(f"    'changer'  → choisir un autre PC")
    print(f"    'pairs'    → rafraîchir la liste des PC")
    print(f"    'log'      → voir le chemin du journal des messages")
    print(f"    'quit'     → quitter Archipel")
    print(f"{'─'*55}\n")

    while True:
        try:
            print("Vous : ", end="", flush=True)
            texte = input("").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n[ARRÊT]")
            return False

        if not texte:
            continue

        if texte.lower() == "quit":
            return False

        if texte.lower() == "changer":
            return True

        if texte.lower() == "pairs":
            afficher_pairs()
            continue

        if texte.lower() == "log":
            print(f"\n[📁 JOURNAL] {messaging.get_log_path()}")
            print(f"[📊 TOTAL]   {len(messaging.get_all_messages())} messages enregistrés\n")
            continue

        # Envoi du message
        success = messaging.send_message(
            peer_ip,
            int(peer_port),
            peer_id,
            texte
        )
        if not success:
            print(f"[⚠️] Envoi échoué — {peer_ip} est-il toujours connecté ?")
            print("[INFO] Tapez 'pairs' pour voir les PC disponibles")
            print("[INFO] Tapez 'changer' pour choisir un autre PC")


# ─────────────────────────────────────────────
#   Thread de scan (non-bloquant)
# ─────────────────────────────────────────────

def thread_scan(port):
    """Lance le scan réseau en arrière-plan et ajoute les pairs trouvés."""
    time.sleep(2)  # Laisser le multicast partir d'abord
    ips_trouvees = scan_network(port=port, timeout=0.3)

    if ips_trouvees:
        print(f"\n[SCAN] {len(ips_trouvees)} PC(s) Archipel trouvé(s) par scan TCP !")
        for ip in ips_trouvees:
            add_peer_manually(peer_table, ip, port)
    else:
        print("\n[SCAN] Scan terminé — aucun PC supplémentaire trouvé.")


# ─────────────────────────────────────────────
#   Thread d'attente de pairs
# ─────────────────────────────────────────────

def attendre_et_chatter():
    """
    Attend que des pairs soient découverts (multicast ou scan),
    puis lance l'interface de chat.
    """
    global messaging

    print(f"\n[⏳] En attente de pairs sur le réseau...")
    print(f"[INFO] Découverte multicast active + scan TCP en cours...")
    print(f"[INFO] Les autres PC doivent aussi lancer Archipel\n")

    # Attente de pairs — max 60s avec vérification toutes les secondes
    max_wait = 60
    for elapsed in range(max_wait):
        if peer_table.count() > 0:
            break
        time.sleep(1)
        # Afficher un point de progression toutes les 10s
        if elapsed > 0 and elapsed % 10 == 0:
            print(f"[⏳] Toujours en attente... ({elapsed}s écoulées, {max_wait - elapsed}s restantes)")

    peers = peer_table.get_all()
    if not peers:
        print("\n[⚠️] Aucun PC trouvé sur le réseau après 60s.")
        print("[CONSEIL] Vérifiez que :")
        print("  1) Les autres PC ont lancé : python src/cli/main.py node 7777")
        print("  2) Tous les PC sont sur le même WiFi/hotspot")
        print("  3) Le pare-feu Windows ne bloque pas Python")
        print("\n[INFO] Continuez quand même en tapant 'pairs' si un pair arrive plus tard.")
        # On ne quitte pas — le nœud reste actif pour recevoir des connexions
        try:
            while True:
                cmd = input("Commande (pairs/quit) : ").strip().lower()
                if cmd == "quit":
                    return
                elif cmd == "pairs":
                    peers = peer_table.get_all()
                    if peers:
                        break
                    else:
                        print("[INFO] Toujours aucun pair...")
        except (KeyboardInterrupt, EOFError):
            return

    # Boucle principale de chat
    while True:
        peer_list = afficher_pairs()
        if not peer_list:
            print("[INFO] Aucun pair disponible — en attente...")
            time.sleep(5)
            continue

        peer_id, peer_ip, peer_port = choisir_pair(peer_list)
        if peer_id is None:
            break

        while True:
            rechoisir = boucle_chat(peer_id, peer_ip, peer_port)
            if not rechoisir:
                return
            # Rechoisir un pair
            peer_list = afficher_pairs()
            if not peer_list:
                print("[INFO] Aucun pair disponible")
                break
            peer_id, peer_ip, peer_port = choisir_pair(peer_list)
            if peer_id is None:
                return


# ─────────────────────────────────────────────
#   Commande principale : démarrage du nœud
# ─────────────────────────────────────────────

def cmd_node(port=7777):
    """
    Démarre un nœud Archipel complet.
    
    Chaque nœud est simultanément :
    - Serveur TCP (reçoit les messages)
    - Client TCP  (envoie les messages)  
    - Émetteur multicast UDP (annonce sa présence)
    - Récepteur multicast UDP (découvre les pairs)
    - Scanner TCP (cherche activement les pairs)
    - Journaliste (enregistre tous les messages)
    """
    global messaging, my_port
    my_port = port

    signing_key, verify_key = load_identity(port)
    node_id = verify_key.encode().hex()
    my_ip   = get_my_ip()

    print()
    print("╔══════════════════════════════════════════════════╗")
    print("║       🏝️   ARCHIPEL — Réseau P2P Souverain       ║")
    print("║         Zero-Day Heroes | Hackathon 2026         ║")
    print("╠══════════════════════════════════════════════════╣")
    print(f"║  ID     : {node_id[:20]}...         ║")
    print(f"║  Port   : {port:<41} ║")
    print(f"║  Mon IP : {my_ip:<41} ║")
    print("╠══════════════════════════════════════════════════╣")
    print("║  Ce nœud est SERVEUR + CLIENT simultanément      ║")
    print("║  Tous les messages sont journalisés sur disque   ║")
    print("╚══════════════════════════════════════════════════╝")
    print()

    # 1. Démarrer le service de messagerie (serveur TCP sur port direct)
    session_manager = SessionManager(signing_key)
    messaging = MessagingService(signing_key, node_id, session_manager, port)
    messaging.start_tcp_server(port)

    # 2. Démarrer la découverte multicast
    discovery = DiscoveryService(peer_table, node_id, tcp_port=port)
    discovery.start()

    # 3. Lancer le scan réseau en arrière-plan (non-bloquant)
    t_scan = threading.Thread(target=thread_scan, args=(port,), daemon=True)
    t_scan.start()

    # 4. Afficher le chemin du journal
    print(f"\n[📁 JOURNAL] Messages enregistrés dans :")
    print(f"   {messaging.get_log_path()}\n")

    # 5. Thread d'attente et de chat
    t_chat = threading.Thread(target=attendre_et_chatter, daemon=True)
    t_chat.start()

    # 6. Boucle principale (garde le processus vivant)
    try:
        while t_chat.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n[ARRÊT] Nœud Archipel arrêté proprement")
        print(f"[📊] {len(messaging.get_all_messages())} messages enregistrés dans le journal")
        discovery.stop()


# ─────────────────────────────────────────────
#   Aide
# ─────────────────────────────────────────────

def show_help():
    print("""
╔══════════════════════════════════════════════════╗
║         ARCHIPEL — Guide de démarrage           ║
╠══════════════════════════════════════════════════╣
║                                                  ║
║  DÉMARRER UN NŒUD :                              ║
║    python src/cli/main.py node 7777              ║
║                                                  ║
║  MULTI-TERMINAUX (même PC) :                     ║
║    Terminal 1 : python src/cli/main.py node 7777 ║
║    Terminal 2 : python src/cli/main.py node 8888 ║
║    Terminal 3 : python src/cli/main.py node 9999 ║
║                                                  ║
║  MULTI-PCS (hotspot/WiFi partagé) :              ║
║    Chaque PC : python src/cli/main.py node 7777  ║
║                                                  ║
║  COMMANDES PENDANT LE CHAT :                     ║
║    changer  → choisir un autre destinataire      ║
║    pairs    → rafraîchir liste des PC            ║
║    log      → voir le journal des messages       ║
║    quit     → quitter                            ║
╠══════════════════════════════════════════════════╣
║  JOURNAL : .archipel/logs/messages_port{N}.log   ║
╚══════════════════════════════════════════════════╝
    """)


# ─────────────────────────────────────────────
#   Point d'entrée
# ─────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        show_help()
        sys.exit(0)

    command = sys.argv[1]

    if command == "node":
        port = int(sys.argv[2]) if len(sys.argv) > 2 else 7777
        cmd_node(port)

    elif command == "help":
        show_help()

    else:
        print(f"[ERREUR] Commande inconnue : '{command}'")
        show_help()