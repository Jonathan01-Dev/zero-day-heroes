# 🏝️ ARCHIPEL — Réseau P2P Souverain

> Protocole de communication décentralisé, chiffré bout-en-bout,  
> fonctionnant sans Internet, sans serveur central, sans autorité de certification.  
> Conçu pour survivre à une coupure totale d'infrastructure.

---

## 👥 Notre équipe — Zero Day Heroes

| Nom | Rôle |
|-----|------|
| ANWONE Steeven | Réseau P2P |
| ODAH Ebenezer | Cryptographie |
| HYDE Karen Elisa | Transfert fichiers |
| ADABRA Koffi Ecclésiate | CLI & Documentation |

---

## 🛠️ Stack technique

**Langage principal : Python 3.11**

Nous avons choisi Python car :
- Bibliothèques réseau intégrées (socket, threading)
- Cryptographie solide avec PyNaCl et PyCryptodome
- Lisible et maintenable par toute l'équipe
- Debug rapide en contexte hackathon 24h

**Bibliothèques :**

| Bibliothèque | Usage |
|---|---|
| `pynacl` | Cryptographie Ed25519 et X25519 |
| `pycryptodome` | Chiffrement AES-256-GCM |
| `socket` + `threading` | Réseau UDP/TCP (built-in Python) |
| `hashlib` | SHA-256 et HMAC (built-in Python) |

**Transport réseau :**
- UDP Multicast `239.255.42.99:6000` — découverte automatique des pairs
- TCP port `7777` — messages chiffrés et transferts de données
- Scan réseau automatique — détection des PC Archipel sur le LAN

---

## 🏗️ Architecture
```
┌─────────────────────────────────────────────────────┐
│                   NŒUD ARCHIPEL                     │
│                                                     │
│  ┌─────────────┐        ┌─────────────────────┐    │
│  │    CLI      │◄──────►│   Peer Table        │    │
│  │  (main.py)  │        │ (carnet d'adresses) │    │
│  └──────┬──────┘        └──────────┬──────────┘    │
│         │                          │                │
│  ┌──────▼──────┐        ┌──────────▼──────────┐    │
│  │  Messaging  │        │   Network Layer      │    │
│  │  (chat E2E) │        │  UDP Multicast       │    │
│  └──────┬──────┘        │  TCP transfers       │    │
│         │               │  Scan automatique    │    │
│         │               └──────────┬──────────┘    │
│  ┌──────▼──────────────────────────▼──────────┐    │
│  │              Crypto Layer                   │    │
│  │  Ed25519 (identité) + X25519 (échange clé) │    │
│  │  AES-256-GCM (chiffrement) + HMAC-SHA256   │    │
│  └─────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────┘

Réseau local (LAN / Wi-Fi) — ZÉRO Internet requis

[Nœud A] ◄──UDP Multicast──► [Nœud B] ◄──UDP Multicast──► [Nœud C]
    │                              │                              │
    └──────────────── TCP direct ──┴──────────────────────────────┘
```

---

## 📦 Format des paquets
```
┌──────────┬──────────┬───────────┬─────────────┐
│  MAGIC   │   TYPE   │  NODE_ID  │ PAYLOAD_LEN │
│  4 bytes │  1 byte  │  32 bytes │   4 bytes   │
├──────────┴──────────┴───────────┴─────────────┤
│         PAYLOAD (JSON chiffré, variable)       │
├───────────────────────────────────────────────┤
│         HMAC-SHA256 (32 bytes)                 │
└───────────────────────────────────────────────┘
```

| Code | Nom | Description |
|------|-----|-------------|
| 0x01 | HELLO | Annonce de présence sur le réseau |
| 0x02 | PEER_LIST | Liste des nœuds connus |
| 0x03 | MSG | Message chiffré AES-256-GCM |
| 0x04 | CHUNK_REQ | Requête d'un bloc de fichier |
| 0x05 | CHUNK_DATA | Transfert d'un bloc de fichier |
| 0x06 | MANIFEST | Métadonnées d'un fichier |
| 0x07 | ACK | Acquittement |

---

## 🔐 Cryptographie

| Primitive | Usage | Bibliothèque | Justification |
|-----------|-------|-------------|---------------|
| Ed25519 | Identité du nœud + signatures | PyNaCl | Standard moderne, rapide, sécurisé |
| X25519 | Échange de clé Diffie-Hellman | PyNaCl | Forward secrecy sans CA centrale |
| AES-256-GCM | Chiffrement des messages | PyCryptodome | Authentifié, standard militaire |
| HKDF-SHA256 | Dérivation de clé de session | hashlib | Dérivation sécurisée |
| HMAC-SHA256 | Intégrité des paquets | hashlib | Détection de tampering |
| SHA-256 | Hash des fichiers et chunks | hashlib | Vérification d'intégrité |

**Modèle de confiance :** TOFU (Trust On First Use) inspiré de Signal.
Pas de CA centrale — chaque nœud mémorise la clé publique de ses pairs
et détecte toute tentative d'attaque MITM à la reconnexion.

**Handshake :** inspiré du Noise Protocol Framework.
Clés éphémères X25519 à chaque session pour assurer le Forward Secrecy.

---

## 🚀 Installation
```bash
# 1. Cloner le repo
git clone https://github.com/VOTRE_NOM/archipel.git
cd archipel

# 2. Créer l'environnement virtuel
python -m venv venv

# 3. Activer l'environnement
# Windows :
venv\Scripts\Activate.ps1
# Mac/Linux :
source venv/bin/activate

# 4. Installer les dépendances
pip install -r requirements.txt
```

---

## 💻 Guide de la démo

### Lancer un nœud

La même commande sur tous les PC :
```bash
python src/cli/main.py node 7777
```

Le programme fait automatiquement :
1. Affiche votre IP sur le réseau local
2. Scanne le réseau local à la recherche de PC Archipel
3. Affiche la liste des PC trouvés avec leur index
4. Vous demande à qui vous voulez envoyer un message
5. Lance le chat chiffré bout-en-bout

### Scénario démo — 3 PC
```
PC1 : python src/cli/main.py node 7777  ← lance en premier
PC2 : python src/cli/main.py node 7777  ← lance 10s après
PC3 : python src/cli/main.py node 7777  ← lance 10s après
```

### Commandes disponibles dans le chat
```
Vous : Bonjour !    → envoie un message chiffré au PC choisi
Vous : changer      → choisir un autre PC destinataire
Vous : liste        → voir tous les PC disponibles sur le réseau
Vous : quit         → quitter Archipel
```

### Ce que le jury verra
```
=======================================================
   🏝️  ARCHIPEL — Réseau P2P Souverain
=======================================================
  ID     : 9008c96c99cd7d1d...
  Port   : 7777
  Mon IP : 10.149.41.70
=======================================================

[SCAN] Réseau 10.149.41.0/24 sur port 7777...
[✅ TROUVÉ] 10.149.41.181:7777
[✅ TROUVÉ] 10.149.41.xxx:7777

=======================================================
  2 PC(S) DISPONIBLES SUR LE RÉSEAU
=======================================================
  [0] 10.149.41.181:7777  (vu il y a 1s)
  [1] 10.149.41.xxx:7777  (vu il y a 2s)
=======================================================

👉 Choisir le PC destinataire (numéro) : 0

Vous : Bonjour depuis Archipel !

==================================================
  📨 MESSAGE REÇU [14:32:01]
  De  : 10.149.41.70
  📝  : Bonjour depuis Archipel !
==================================================
```

---

État d'avancement des sprints

| Sprint | Titre | Statut | Livrable validé |
|--------|-------|--------|----------------|
| Sprint 0 | Bootstrap & Architecture |  Terminé | PKI Ed25519, format paquets, README |
| Sprint 1 | Couche Réseau P2P |  Terminé | Découverte UDP multicast, Peer Table, scan LAN |
| Sprint 2 | Chiffrement E2E | Terminé | AES-256-GCM, chat bidirectionnel multi-PC |
| Sprint 3 | Chunking & Transfert | Terminé | Transfert fichier 50 Mo, vérification SHA-256 |
| Sprint 4 | Intégration & Polish | Encours | CLI final, Gemini AI, démo jury |

---

Limitations connues

- La clé de session est dérivée d'un secret partagé fixe pour le hackathon. En production un vrai handshake Noise Protocol avec clés éphémères serait utilisé.
- Le Web of Trust est en mode TOFU uniquement. La propagation de confiance et la révocation de clés ne sont pas encore implémentées.
- Le scan réseau automatique nécessite que le pare-feu Windows soit configuré pour autoriser les connexions sur les ports Archipel (7777, 8777, 6000).
- Le transfert de fichiers par chunks est en cours d'implémentation (Sprint 3).
- Interface en ligne de commande uniquement — pas d'UI graphique.

Pistes d'amélioration

- Implémentation complète du Noise Protocol pour le handshake
- Web of Trust avec propagation et révocation de clés
- Interface graphique web locale (HTML/React)
- Persistance des messages sur disque chiffré
- Support Bluetooth L2CAP pour fonctionner sans WiFi
- Transfert multi-sources simultané (style BitTorrent)

---

*Hackathon Archipel 2026 — La Piscine LBS — Groupe Zero Day Heroes*