import sys, os, time, threading
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
add_peer_manually(pt2, '127.0.0.1', 7111)

lock = threading.Lock()
ft1 = FileTransferService(nid1, '127.0.0.1', 7111, lock, SessionManager(sk1), sk1, pt1)
ft2 = FileTransferService(nid2, '127.0.0.1', 8111, lock, SessionManager(sk2), sk2, pt2)

ft1.start()
ft2.start()
time.sleep(0.5)

import tempfile
test_file = os.path.join(tempfile.gettempdir(), 'test_transfer.bin')
with open(test_file, 'wb') as f: f.write(os.urandom(1024 * 1024))  # 1 Mo

print('[*] seed...')
ft1.seed_file(test_file)

# Attendre jusqu'a 15 secondes
for i in range(15):
    time.sleep(1)
    dl = os.path.join('telechargements', 'test_transfer.bin')
    if os.path.exists(dl):
        import hashlib
        h1 = hashlib.sha256(open(test_file,'rb').read()).hexdigest()
        h2 = hashlib.sha256(open(dl,'rb').read()).hexdigest()
        print(f'Hash OK: {h1 == h2}')
        assert h1 == h2
        print('[SUCCES] Transfert de fichier OK!')
        break
else:
    print('[ECHEC] Fichier non recu')
