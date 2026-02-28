import sys, os, time
sys.path.insert(0, '.')
from src.crypto.identity import load_identity
from src.crypto.handshake import SessionManager
from src.crypto.messaging import MessagingService

sk1, vk1 = load_identity(9001)
sk2, vk2 = load_identity(9002)
nid1, nid2 = vk1.encode().hex(), vk2.encode().hex()

msg1 = MessagingService(sk1, nid1, SessionManager(sk1), 9001)
msg2 = MessagingService(sk2, nid2, SessionManager(sk2), 9002)
msg1.start_tcp_server(9001)
msg2.start_tcp_server(9002)
time.sleep(0.5)

ok = msg1.send_message('127.0.0.1', 9002, nid2, 'Bonjour PC2 !')
print(f'Envoye: {ok}')
time.sleep(0.5)

msgs = msg2.get_all_messages()
print(f'Recu ({len(msgs)}): {[m.get("text") for m in msgs]}')
assert len(msgs) > 0, 'ECHEC'
print('[SUCCES] Messages passent correctement.')
