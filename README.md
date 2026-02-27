ARCHIPEL — Réseau P2P Souverain

ARCHIPEL est une technologie utilisant les Protocoles de communication décentralisé, chiffré bout-en-bout,fonctionnant sans Internet, sans serveur central, sans autorité de certification.

Notre équipe

ANWONE Steeven:  Réseau P2P 
ODAH Ebenezer :  Cryptographie 
HYDE Karen Elisa: Transfert fichiers 
ADABRA Koffi Ecclésiate:  CLI & Documentation 

Stack technique

Langage principal : Python 3.11

Nous avons choisi le langage Python. Parce qu'il possède:
- Bibliothèques réseau intégrées (socket, asyncio)
- Cryptographie solide avec PyNaCl et PyCryptodome
- Lisible et maintenable par toute l'équipe
- Debug rapide

Bibliothèques Utiles
- `pynacl` — Cryptographie Ed25519 et X25519
- `pycryptodome` — AES-256-GCM
- `socket` + `asyncio` — Réseau UDP/TCP (built-in Python)
- `hashlib` — SHA-256 (built-in Python)

Transport réseau :
- UDP Multicast `239.255.42.99:6000` pour la découverte de pairs
- TCP port `7777` pour les transferts de données


Architecture du projet 

┌────────────────────────────────────────────────────┐
│                   NŒUD ARCHIPEL                    │
│                                                    │
│  ┌─────────────┐        ┌─────────────────────┐    │
│  │    CLI      │◄──────►│   Peer Table        │    │
│  │  (main.py)  │        │ (carnet d'adresses) │    │
│  └──────┬──────┘        └──────────┬──────────┘    │
│         │                          │               │
│  ┌──────▼──────┐        ┌──────────▼──────────┐    │
│  │  Messaging  │        │   Network Layer     │    │
│  │  (chat E2E) │        │  UDP discovery      │    │
│  └──────┬──────┘        │  TCP transfers      │    │
│         │               └──────────┬──────────┘    │
│  ┌──────▼──────────────────────────▼──────────┐    │
│  │           Crypto Layer                     │    │
│  │  Ed25519 (identité) + X25519 (échange clé) │    │
│  │  AES-256-GCM (chiffrement) + HMAC-SHA256   │    │
│  └────────────────────────────────────────────┘    │
└────────────────────────────────────────────────────┘

Réseau local (LAN / Wi-Fi) — ZÉRO Internet requis

  [Nœud A] ◄──UDP Multicast──► [Nœud B]
     │                              │
     └──────── TCP direct ──────────┘


Format des paquets utilisés

Chaque paquet Archipel suit cette structure binaire :
┌──────────┬──────────┬───────────┬─────────────┐
│  MAGIC   │   TYPE   │  NODE_ID  │ PAYLOAD_LEN │
│  4 bytes │  1 byte  │  32 bytes │   4 bytes   │
├──────────┴──────────┴───────────┴─────────────┤
│         PAYLOAD (JSON chiffré, variable)      │
├───────────────────────────────────────────────┤
│         HMAC-SHA256 (32 bytes)                │
└───────────────────────────────────────────────┘

Types de paquets :

| Code | Nom        | Description                       |
|------|------------|-----------------------------------|
| 0x01 | HELLO      | Annonce de présence sur le réseau |
| 0x02 | PEER_LIST  | Liste des nœuds connus            |
| 0x03 | MSG        | Message chiffré                   |
| 0x04 | CHUNK_REQ  | Requête d'un bloc de fichier      |
| 0x05 | CHUNK_DATA | Transfert d'un bloc de fichier    |
| 0x06 | MANIFEST   | Métadonnées d'un fichier          |
| 0x07 | ACK        | Acquittement                      |


Cryptographie

| Primitive   | Usage                         | Bibliothèque |
|-------------|-------------------------------|--------------|
| Ed25519     |Identité du nœud + signatures  | PyNaCl       |
| X25519      | Échange de clé Diffie-Hellman | PyNaCl       |
| AES-256-GCM | Chiffrement des données       | PyCryptodome |
| HKDF-SHA256 | Dérivation de clé de session  | hashlib      |
| HMAC-SHA256 | Intégrité des paquets         | hashlib      |
| SHA-256     | Hash des fichiers et chunks   | hashlib      |


Installation
```bash
1. Cloner le repo

git clone https://github.com/VOTRE_NOM/archipel.git
cd archipel

2. Créer l'environnement virtuel
python -m venv venv

3. Activer l'environnement
# Windows :
venv\Scripts\activate
# Mac/Linux :
source venv/bin/activate

# 4. Installer les dépendances
pip install -r requirements.txt

Lancer un nœud
```bash
Démarrer le nœud
python src/cli/main.py start

# Voir le statut
python src/cli/main.py status

# Tester les paquets
python src/cli/main.py test-packet
```
État d'avancement des sprints

Sprint 0: Bootstrap & Architecture (Terminé)
Sprint 1: Couche Réseau P2P (En cours)
Sprint 2: Chiffrement E2E  (À faire)
Sprint 3: Chunking & Transfert (À faire)
Sprint 4: Intégration & Polish (À faire)


Limitations connues

- Sprint 0 uniquement : pas encore de réseau actif
- Identification du protocol à utiliser et du mode de connexion entre les différents appareils
- La découverte de pairs sera implémentée au Sprint 1
- Le chiffrement des messages au Sprint 2


*Hackathon Archipel 2026 — La Piscine LBS par le groupe Zero_Day_Heroes*