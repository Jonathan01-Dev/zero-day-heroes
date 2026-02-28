"""
scanner.py — Découverte active par scan TCP rapide
Scanne le réseau local pour trouver les nœuds Archipel actifs.
Fonctionne sans Internet — hotspot local suffit.
"""

import socket
import threading
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


def get_my_ip():
    """
    Récupère notre IP sur le réseau local.
    Fonctionne sans Internet grâce à la probe vers le réseau local.
    """
    # Méthode 1 : via UDP (ne nécessite pas de connexion réelle)
    for probe in ["192.168.1.1", "10.0.0.1", "172.16.0.1"]:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.2)
            s.connect((probe, 80))
            ip = s.getsockname()[0]
            s.close()
            if not ip.startswith("127."):
                return ip
        except Exception:
            pass

    # Méthode 2 : via hostname
    try:
        hostname = socket.gethostname()
        ip = socket.gethostbyname(hostname)
        if not ip.startswith("127."):
            return ip
    except Exception:
        pass

    # Méthode 3 : énumérer les interfaces
    try:
        import subprocess
        result = subprocess.run(
            ["ipconfig"] if sys.platform == "win32" else ["ip", "addr"],
            capture_output=True, text=True, timeout=3
        )
        import re
        ips = re.findall(r"IPv4.*?(\d+\.\d+\.\d+\.\d+)", result.stdout)
        for ip in ips:
            if not ip.startswith("127.") and not ip.startswith("169."):
                return ip
    except Exception:
        pass

    return "127.0.0.1"


def scan_network(port=7777, timeout=0.3):
    """
    Scanne tout le réseau local pour trouver les nœuds Archipel actifs.
    
    - Fonctionne sur hotspot sans Internet
    - Scanne aussi 127.0.0.1 pour tests multi-terminaux sur même machine
    - 100 threads en parallèle pour une rapidité maximale (~5s pour /24)
    - Retourne la liste des IPs trouvées
    """
    my_ip   = get_my_ip()
    found   = []
    lock    = threading.Lock()

    print(f"\n[SCAN] Mon IP : {my_ip}")
    print(f"[SCAN] Port cible : {port}")

    def check_host(ip):
        """Vérifie si un nœud Archipel écoute sur cet IP:port"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((ip, port))
            sock.close()
            if result == 0:
                with lock:
                    found.append(ip)
                    print(f"  [✅ TROUVÉ] {ip}:{port}")
        except Exception:
            pass

    all_ips = []

    # Test localhost (multi-terminaux sur même machine)
    all_ips.append("127.0.0.1")

    # Scan du réseau local basé sur notre IP
    if not my_ip.startswith("127."):
        base_ip = ".".join(my_ip.split(".")[:3])
        print(f"[SCAN] Scan réseau {base_ip}.0/24 ...")
        for i in range(1, 255):
            ip = f"{base_ip}.{i}"
            if ip != my_ip:
                all_ips.append(ip)
    else:
        print("[SCAN] Mode local uniquement (127.x.x.x)")

    # Lancer 100 threads en parallèle par batch
    BATCH_SIZE = 100
    for i in range(0, len(all_ips), BATCH_SIZE):
        batch = all_ips[i:i + BATCH_SIZE]
        threads = [threading.Thread(target=check_host, args=(ip,), daemon=True) for ip in batch]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=timeout + 0.1)

    return found