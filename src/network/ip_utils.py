# src/network/ip_utils.py
import socket
import subprocess
import platform
import re

def get_all_ips():
    """Retourne toutes les IPs de la machine"""
    ips = []
    
    # Méthode 1: via gethostbyname_ex
    try:
        hostname = socket.gethostname()
        ips.extend(socket.gethostbyname_ex(hostname)[2])
    except:
        pass
    
    # Méthode 2: via ipconfig/ifconfig
    try:
        if platform.system() == "Windows":
            output = subprocess.check_output("ipconfig", shell=True, text=True)
            # Pattern pour trouver les IPv4 dans ipconfig
            matches = re.findall(r'IPv4.*:\s*(\d+\.\d+\.\d+\.\d+)', output)
            ips.extend(matches)
        else:
            output = subprocess.check_output("ifconfig", shell=True, text=True)
            # Pattern pour trouver les IPs dans ifconfig
            matches = re.findall(r'inet\s+(\d+\.\d+\.\d+\.\d+)', output)
            ips.extend([m for m in matches if not m.startswith('127.')])
    except:
        pass
    
    # Déduplique et nettoie
    unique_ips = []
    for ip in ips:
        if ip and ip not in unique_ips and not ip.startswith('127.'):
            unique_ips.append(ip)
    
    return unique_ips

def get_best_local_ip():
    """Retourne la meilleure IP locale pour la communication P2P"""
    ips = get_all_ips()
    
    if not ips:
        return "127.0.0.1"
    
    # Priorité aux IPs qui commencent par 10. (réseau d'entreprise)
    for ip in ips:
        if ip.startswith('10.'):
            return ip
    
    # Ensuite 192.168.
    for ip in ips:
        if ip.startswith('192.168.'):
            return ip
    
    # Ensuite 172.16-31.
    for ip in ips:
        if ip.startswith('172.'):
            parts = ip.split('.')
            if len(parts) > 1 and 16 <= int(parts[1]) <= 31:
                return ip
    
    # Sinon la première IP non-loopback
    return ips[0]