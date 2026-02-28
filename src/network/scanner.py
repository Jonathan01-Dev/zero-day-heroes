"""
scanner.py — Découverte active par scan TCP rapide
Scanne le réseau local pour trouver les noeuds Archipel actifs.
Fonctionne sans Internet — hotspot local suffit.

IMPORTANT : Le port scanné = port annoncé + 1000
  Ex: noeud sur port 7777 → serveur TCP écoute sur 8777
  Le scan cherche 8777, mais retourne l'IP avec port 7777.
"""

import socket
import threading
import sys
import os
import re
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


def get_all_local_ips():
    """
    Retourne toutes les IPs locales de la machine (hors loopback 127.x).
    Compatible Windows (ipconfig), Linux/Mac (ip addr / ifconfig).
    """
    ips = []

    # Methode 1 : ipconfig / ip addr
    try:
        cmd = ["ipconfig"] if sys.platform == "win32" else ["ip", "addr"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        found = re.findall(r"(?:IPv4.*?|inet\s+)(\d+\.\d+\.\d+\.\d+)", result.stdout)
        for ip in found:
            if not ip.startswith("127.") and not ip.startswith("169."):
                ips.append(ip)
    except Exception:
        pass

    # Methode 2 : probe UDP vers les passerelles courantes
    for gateway in ["192.168.246.1", "192.168.43.1", "192.168.1.1",
                    "10.0.0.1", "172.16.0.1", "192.168.0.1",
                    "10.149.41.1", "10.149.41.160"]:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.2)
            s.connect((gateway, 80))
            ip = s.getsockname()[0]
            s.close()
            if not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
        except Exception:
            pass

    # Methode 3 : hostname
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if not ip.startswith("127.") and ip not in ips:
            ips.append(ip)
    except Exception:
        pass

    return ips


def get_my_ip():
    """
    Retourne l'IP locale réelle (celle qui permet de communiquer sur le réseau local)
    """
    try:
        # Méthode 1: Se connecter à une IP publique (sans vraiment se connecter)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.1)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        
        # Vérifie que c'est une IP locale valide
        if ip and not ip.startswith('127.'):
            print(f"[DEBUG] IP via connexion UDP: {ip}")
            return ip
    except Exception as e:
        print(f"[DEBUG] Méthode UDP a échoué: {e}")
        pass
    
    try:
        # Méthode 2: Lister toutes les interfaces réseau
        hostname = socket.gethostname()
        all_ips = socket.gethostbyname_ex(hostname)[2]
        print(f"[DEBUG] Toutes les IPs via gethostbyname_ex: {all_ips}")
        
        # Priorité 1: IP qui commence par 10. (comme la tienne)
        for ip in all_ips:
            if ip.startswith('10.'):
                print(f"[DEBUG] IP 10.x.x.x trouvée: {ip}")
                return ip
        
        # Priorité 2: IP qui commence par 192.168.
        for ip in all_ips:
            if ip.startswith('192.168.'):
                print(f"[DEBUG] IP 192.168.x.x trouvée: {ip}")
                return ip
        
        # Priorité 3: IP qui commence par 172.
        for ip in all_ips:
            if ip.startswith('172.'):
                print(f"[DEBUG] IP 172.x.x.x trouvée: {ip}")
                return ip
        
        # Sinon la première IP non-loopback
        for ip in all_ips:
            if ip and not ip.startswith('127.'):
                print(f"[DEBUG] Autre IP trouvée: {ip}")
                return ip
    except Exception as e:
        print(f"[DEBUG] Méthode gethostbyname_ex a échoué: {e}")
        pass
    
    # Méthode 3: Fallback
    try:
        ip = socket.gethostbyname(socket.gethostname())
        print(f"[DEBUG] Fallback IP: {ip}")
        return ip
    except:
        return '127.0.0.1'


def scan_network(port=7777, timeout=0.4):
    """
    Scanne TOUS les sous-reseaux actifs de la machine.
    Scanne le port TCP réel = port + 1000 (ex: 8777 pour le noeud 7777).
    Retourne la liste des IPs trouvées avec un noeud Archipel actif.
    """
    my_ips    = get_all_local_ips()
    found     = []
    lock      = threading.Lock()

    # ✅ CORRECTION : scanner le vrai port TCP (port + 1000)
    scan_port = port + 1000

    if not my_ips:
        my_ips = ["127.0.0.1"]

    print(f"\n[SCAN] Mes IPs detectees : {', '.join(my_ips)}")
    print(f"[SCAN] Port noeud : {port}  →  Port TCP scanné : {scan_port}")

    def check_host(ip):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            # ✅ On scanne scan_port (ex: 8777) mais on retourne port (ex: 7777)
            if sock.connect_ex((ip, scan_port)) == 0:
                with lock:
                    found.append(ip)
                    print(f"  [✅ TROUVE] {ip}:{port}")
            sock.close()
        except Exception:
            pass

    all_ips_to_scan = []

    for my_ip in my_ips:
        if my_ip.startswith("127."):
            if "127.0.0.1" not in all_ips_to_scan:
                all_ips_to_scan.append("127.0.0.1")
            continue
        base = ".".join(my_ip.split(".")[:3])
        print(f"[SCAN] Sous-reseau {base}.0/24 ...")
        for i in range(1, 255):
            ip = f"{base}.{i}"
            if ip != my_ip and ip not in all_ips_to_scan:
                all_ips_to_scan.append(ip)

    # Lancer 150 threads en parallele par batch
    BATCH_SIZE = 150
    for i in range(0, len(all_ips_to_scan), BATCH_SIZE):
        batch   = all_ips_to_scan[i:i + BATCH_SIZE]
        threads = [
            threading.Thread(target=check_host, args=(ip,), daemon=True)
            for ip in batch
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=timeout + 0.2)

    return found