import struct
import hashlib
import json

# La "signature magique" au début de chaque paquet Archipel
MAGIC = b'ARCH'

# Les types de paquets
TYPE_HELLO      = 0x01
TYPE_PEER_LIST  = 0x02
TYPE_MSG        = 0x03
TYPE_CHUNK_REQ  = 0x04
TYPE_CHUNK_DATA = 0x05
TYPE_MANIFEST   = 0x06
TYPE_ACK        = 0x07

def build_packet(packet_type, node_id_hex, payload_dict):
    """
    Construit un paquet binaire Archipel
    Structure : MAGIC(4) + TYPE(1) + NODE_ID(32) + PAYLOAD_LEN(4) + PAYLOAD + HMAC(32)
    """
    # Convertit le payload en JSON puis en bytes
    payload_bytes = json.dumps(payload_dict).encode('utf-8')
    
    # Convertit le node_id hex en bytes (32 bytes)
    node_id_bytes = bytes.fromhex(node_id_hex)[:32]
    # Complète à 32 bytes si nécessaire
    node_id_bytes = node_id_bytes.ljust(32, b'\x00')
    
    # Construit le header
    header = (
        MAGIC +                                    # 4 bytes
        struct.pack('B', packet_type) +            # 1 byte
        node_id_bytes +                            # 32 bytes
        struct.pack('>I', len(payload_bytes))      # 4 bytes (uint32 big-endian)
    )
    
    # Calcule le HMAC-SHA256 pour l'intégrité
    packet_without_hmac = header + payload_bytes
    hmac = hashlib.sha256(packet_without_hmac).digest()  # 32 bytes
    
    return header + payload_bytes + hmac

def parse_packet(data):
    """
    Décode un paquet binaire Archipel
    Retourne un dictionnaire ou None si paquet invalide
    """
    try:
        # Vérifie la signature magique
        if data[:4] != MAGIC:
            print("[ERREUR] Paquet invalide : mauvais magic bytes")
            return None
        
        # Lit le type
        packet_type = struct.unpack('B', data[4:5])[0]
        
        # Lit le node_id
        node_id = data[5:37].hex()
        
        # Lit la taille du payload
        payload_len = struct.unpack('>I', data[37:41])[0]
        
        # Lit le payload
        payload_bytes = data[41:41 + payload_len]
        
        # Vérifie le HMAC
        hmac_received = data[41 + payload_len:]
        hmac_expected = hashlib.sha256(data[:41 + payload_len]).digest()
        
        if hmac_received != hmac_expected:
            print("[ERREUR] Paquet corrompu : HMAC invalide")
            return None
        
        # Décode le payload JSON
        payload = json.loads(payload_bytes.decode('utf-8'))
        
        return {
            "type": packet_type,
            "node_id": node_id,
            "payload": payload
        }
        
    except Exception as e:
        print(f"[ERREUR] Impossible de décoder le paquet : {e}")
        return None