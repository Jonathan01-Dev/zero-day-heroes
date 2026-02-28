import sys, os, time, threading, traceback
sys.path.insert(0, '.')

from src.crypto.identity import load_identity
from src.crypto.handshake import SessionManager
from src.network.discovery import PeerTable, add_peer_manually
from src.transfer.file_transfer import FileTransferService

sk1, vk1 = load_identity(7111)
sk2, vk2 = load_identity(8111)
nid1, nid2 = vk1.encode().hex(), vk2.encode().hex()

pt1, pt2 = PeerTable(), PeerTable()
add_peer_manually(pt1, '127.0.0.1', 8111)

lock = threading.Lock()
ft1 = FileTransferService(nid1, '127.0.0.1', 7111, lock, SessionManager(sk1), sk1, pt1)
ft2 = FileTransferService(nid2, '127.0.0.1', 8111, lock, SessionManager(sk2), sk2, pt2)

ft1.start()
ft2.start()
time.sleep(0.5)

import tempfile
test_file = os.path.join(tempfile.gettempdir(), 'test_small.bin')
with open(test_file, 'wb') as f:
    f.write(os.urandom(10 * 1024))  # 10 Ko - petit fichier comme un .docx

print(f'[*] Fichier de test: {test_file} ({os.path.getsize(test_file)} bytes)')
print('[*] Demarrage seed...')

try:
    ok = ft1.seed_file(test_file)
    print(f'[*] seed_file retourne: {ok}')
except Exception as e:
    traceback.print_exc()

# Attendre max 15 secondes
dl_dir = 'telechargements'
dl = os.path.join(dl_dir, 'test_small.bin')
for i in range(15):
    time.sleep(1)
    print(f'  [{i+1}s] swarms actifs: {list(ft2.swarms.keys())}')
    if os.path.exists(dl):
        import hashlib
        h1 = hashlib.sha256(open(test_file,'rb').read()).hexdigest()
        h2 = hashlib.sha256(open(dl,'rb').read()).hexdigest()
        print(f'Hash OK: {h1 == h2}')
        if h1 == h2:
            print('[SUCCES] Transfert petit fichier OK!')
        else:
            print('[ERREUR] Hash different!')
        break
else:
    print('[ECHEC] Fichier non recu apres 15s')
    print(f'  ft2.swarms: {ft2.swarms}')
    for fid, sw in ft2.swarms.items():
        print(f'  swarm {fid[:8]}: status={sw.chunk_status}, completed={sw.completed}')
