"""
main_web.py — Sprint 4 : Interface web complète pour Archipel
- Chaque PC est son propre serveur web local (port 8080)
- Zéro dépendance externe — uniquement stdlib Python
- Messages chiffrés E2E reçus en temps réel
- Transfert de fichiers avec barre de progression
- Scan réseau automatique + découverte multicast
- Nonces uniques par message (anti-pattern 3 respecté)
- Clés privées dans .archipel/ hors repo Git (anti-pattern 1 respecté)

Lancer : python src/cli/main_web.py 7777
"""

import sys
import os
import time
import threading
import json
import socket
import webbrowser
import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.crypto.identity        import load_identity
from src.crypto.messaging       import MessagingService
from src.crypto.handshake       import SessionManager
from src.network.discovery      import DiscoveryService, PeerTable, add_peer_manually
from src.network.scanner        import scan_network, get_my_ip
from src.transfer.file_transfer import FileTransferService

# ─────────────────────────────────────────────────────────────────────
#  ÉTAT GLOBAL
# ─────────────────────────────────────────────────────────────────────
peer_table    = PeerTable()
messaging     = None
file_transfer = None
my_node_id    = None
my_ip         = None
my_port       = 7777

messages_log  = []
system_log    = []
_log_lock     = threading.Lock()
_scan_running = False


def syslog(msg, level="info"):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    with _log_lock:
        system_log.append({"msg": msg, "level": level, "ts": ts})
        if len(system_log) > 300:
            system_log.pop(0)


def add_message(from_ip, from_id, text, direction):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    messages_log.append({
        "from_ip":   from_ip or "",
        "from_id":   (from_id or "")[:16],
        "text":      text,
        "direction": direction,
        "timestamp": ts
    })
    if len(messages_log) > 500:
        messages_log.pop(0)


# ─────────────────────────────────────────────────────────────────────
#  LOGIQUE MÉTIER
# ─────────────────────────────────────────────────────────────────────
# ⚠️ SUPPRIME LES LIGNES 60-80 (l'ancienne définition de start())
# La vraie fonction start() est à la fin du fichier

def do_scan():
    global _scan_running
    if _scan_running:
        return 0
    _scan_running = True
    syslog("Scan du réseau en cours...", "info")
    try:
        ips = scan_network(port=my_port, timeout=0.5)
        for ip in ips:
            add_peer_manually(peer_table, ip, my_port)
        syslog(f"Scan terminé — {len(ips)} PC(s) trouvé(s)", "ok" if ips else "warn")
        return len(ips)
    except Exception as e:
        syslog(f"Erreur scan : {e}", "error")
        return 0
    finally:
        _scan_running = False


def send_message(peer_ip, peer_port, peer_id, text):
    if not messaging or not (text or "").strip():
        return False
    try:
        ok = messaging.send_message(peer_ip, int(peer_port), peer_id, text)
        if ok:
            add_message(my_ip, my_node_id, text, "sent")
            syslog(f"→ {peer_ip} : {text[:60]}", "ok")
        else:
            syslog(f"Échec envoi vers {peer_ip}", "error")
        return ok
    except Exception as e:
        syslog(f"Erreur envoi : {e}", "error")
        return False


def send_file_bg(tmp_path, fname, peer_ip, peer_port, peer_id):
    if not file_transfer:
        syslog("Service de transfert non disponible", "error")
        return False
    syslog(f"Envoi de {fname} vers {peer_ip}...", "info")
    try:
        ok = file_transfer.seed_file(tmp_path)
        syslog(f"{'✅ Fichier envoyé' if ok else '❌ Échec'} : {fname}", "ok" if ok else "error")
        return ok
    except Exception as e:
        syslog(f"Erreur transfert : {e}", "error")
        return False


def get_transfers():
    if not file_transfer:
        return []
    result = []
    for fid, swarm in list(file_transfer.swarms.items()):
        done, total, pct = swarm.get_progress()
        result.append({
            "name":      swarm.filename,
            "done":      done,
            "total":     total,
            "pct":       round(pct, 1),
            "completed": swarm.completed
        })
    return result


def patch_messaging(ms):
    """Intercepte les messages reçus pour les capturer dans l'UI."""
    orig = ms._handle_message

    def patched(packet, addr):
        orig(packet, addr)
        try:
            sid  = packet["payload"]["sender_id"]
            enc  = packet["payload"]["encrypted"]
            skey = ms.session_manager.get_session_key(ms.node_id, sid)
            txt  = ms.decrypt_message(enc, skey)
            if txt:
                add_message(addr[0], sid, txt, "received")
                syslog(f"← {addr[0]} : {txt[:60]}", "ok")
        except Exception:
            pass

    ms._handle_message = patched


HTML = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ARCHIPEL P2P</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600;700&family=Bebas+Neue&display=swap');
:root{
  --bg:#050810;--panel:#0c1422;--card:#101c30;
  --b:#1a3050;--cyan:#00e5ff;--blue:#0057ff;
  --green:#00ff9d;--red:#ff3355;--yellow:#ffdd00;
  --text:#c4d8f0;--muted:#3d5a7a;
  --mono:'IBM Plex Mono',monospace;--head:'Bebas Neue',sans-serif;
}
*{box-sizing:border-box;margin:0;padding:0}
body{
  background:var(--bg);color:var(--text);font-family:var(--mono);
  height:100vh;display:flex;flex-direction:column;overflow:hidden;
  background-image:
    radial-gradient(ellipse 100% 60% at 50% 0%,rgba(0,87,255,.1),transparent),
    repeating-linear-gradient(0deg,transparent,transparent 48px,rgba(0,229,255,.018) 48px,rgba(0,229,255,.018) 49px),
    repeating-linear-gradient(90deg,transparent,transparent 48px,rgba(0,229,255,.018) 48px,rgba(0,229,255,.018) 49px);
}

/* HEADER */
header{
  display:flex;align-items:center;gap:16px;
  padding:0 20px;height:50px;
  background:rgba(8,14,24,.97);
  border-bottom:1px solid var(--b);flex-shrink:0;
}
.logo{font-family:var(--head);font-size:28px;letter-spacing:5px;color:var(--cyan);text-shadow:0 0 24px rgba(0,229,255,.45)}
.pills{display:flex;gap:8px;flex:1}
.pill{background:rgba(0,229,255,.05);border:1px solid var(--b);border-radius:3px;padding:3px 10px;font-size:10px;color:var(--muted)}
.pill b{color:var(--cyan)}
.dot{width:8px;height:8px;border-radius:50%;background:var(--green);box-shadow:0 0 10px var(--green);animation:pulse 1.8s ease infinite;margin-left:auto}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.2}}

/* LAYOUT */
.ws{display:grid;grid-template-columns:230px 1fr 250px;flex:1;overflow:hidden;min-height:0}

/* SIDEBAR */
.sb{background:var(--panel);border-right:1px solid var(--b);display:flex;flex-direction:column;overflow:hidden}
.sh{
  padding:9px 13px;font-size:9px;font-weight:700;letter-spacing:2.5px;
  text-transform:uppercase;color:var(--muted);
  border-bottom:1px solid var(--b);
  display:flex;align-items:center;justify-content:space-between;flex-shrink:0
}
.scan-btn{
  background:transparent;color:var(--cyan);
  border:1px solid rgba(0,229,255,.25);border-radius:3px;
  padding:2px 8px;font-family:var(--mono);font-size:9px;font-weight:700;
  letter-spacing:1px;cursor:pointer;transition:all .15s
}
.scan-btn:hover{background:rgba(0,229,255,.1)}
.scan-btn:disabled{opacity:.35;cursor:not-allowed}
.peers{flex:1;overflow-y:auto;padding:5px}
.pc{
  padding:8px 11px;border-radius:5px;cursor:pointer;
  border:1px solid transparent;transition:all .13s;margin-bottom:3px;
  position:relative;overflow:hidden
}
.pc::before{
  content:'';position:absolute;left:0;top:15%;bottom:15%;
  width:2px;background:var(--cyan);opacity:0;transition:opacity .15s
}
.pc:hover{background:rgba(0,229,255,.04);border-color:var(--b)}
.pc.on{background:rgba(0,229,255,.07);border-color:rgba(0,229,255,.28)}
.pc.on::before{opacity:1}
.pc-ip{font-size:13px;color:var(--cyan);font-weight:600}
.pc-port{font-size:10px;color:var(--muted);margin-top:1px}
.pc-age{font-size:9px;color:var(--muted);float:right;margin-top:1px}
.empty{padding:24px 13px;text-align:center;color:var(--muted);font-size:11px;line-height:2}

/* CHAT */
.chat{display:flex;flex-direction:column;overflow:hidden;min-height:0}
.chat-top{
  padding:10px 18px;border-bottom:1px solid var(--b);
  background:rgba(8,14,24,.8);display:flex;align-items:center;gap:12px;flex-shrink:0
}
.ct-name{font-size:14px;font-weight:600;color:var(--cyan)}
.ct-sub{font-size:10px;color:var(--muted);margin-top:2px}
.enc-badge{
  margin-left:auto;border:1px solid rgba(0,255,157,.25);
  color:var(--green);padding:2px 10px;border-radius:20px;
  font-size:9px;font-weight:700;letter-spacing:1px;
  background:rgba(0,255,157,.04);transition:opacity .2s
}
.msgs{flex:1;overflow-y:auto;padding:14px 18px;display:flex;flex-direction:column;gap:5px;min-height:0}
.msgs::-webkit-scrollbar{width:3px}
.msgs::-webkit-scrollbar-thumb{background:var(--b)}
.bbl{
  max-width:70%;padding:9px 13px 6px;border-radius:9px;
  font-size:12px;line-height:1.6;word-break:break-word;
  animation:pop .17s ease
}
@keyframes pop{from{opacity:0;transform:translateY(5px)}to{opacity:1;transform:translateY(0)}}
.bbl.sent{
  background:linear-gradient(135deg,#0057ff,#0033bb);color:#fff;
  align-self:flex-end;border-bottom-right-radius:2px;
  box-shadow:0 2px 14px rgba(0,87,255,.35)
}
.bbl.recv{
  background:var(--card);border:1px solid var(--b);
  color:var(--text);align-self:flex-start;border-bottom-left-radius:2px
}
.bbl-meta{font-size:9px;opacity:.45;margin-top:3px;text-align:right}
.bbl.recv .bbl-meta{text-align:left}
.chat-empty{
  flex:1;display:flex;flex-direction:column;
  align-items:center;justify-content:center;color:var(--muted);gap:10px
}
.chat-empty-ico{font-size:48px;opacity:.15}
.chat-empty-txt{font-size:11px;letter-spacing:2px}

/* INPUT */
.inp-row{
  display:flex;gap:7px;padding:11px 18px;
  border-top:1px solid var(--b);background:rgba(8,14,24,.8);flex-shrink:0
}
.msg-inp{
  flex:1;background:var(--card);border:1px solid var(--b);
  border-radius:5px;padding:8px 13px;color:var(--text);
  font-family:var(--mono);font-size:12px;outline:none;transition:border-color .15s
}
.msg-inp:focus{border-color:var(--cyan)}
.msg-inp::placeholder{color:var(--muted)}
.msg-inp:disabled{opacity:.35}
.btn-f{
  background:var(--card);border:1px solid var(--b);color:var(--muted);
  border-radius:5px;padding:0 12px;font-size:15px;cursor:pointer;transition:all .15s
}
.btn-f:hover{border-color:var(--cyan);color:var(--cyan)}
.btn-f:disabled{opacity:.35;cursor:not-allowed}
.btn-s{
  background:var(--blue);color:#fff;border:none;border-radius:5px;
  padding:0 16px;font-family:var(--mono);font-size:11px;font-weight:700;
  letter-spacing:2px;cursor:pointer;transition:all .15s
}
.btn-s:hover{background:var(--cyan);color:var(--bg)}
.btn-s:disabled{opacity:.35;cursor:not-allowed}

/* RIGHT */
.rp{background:var(--panel);border-left:1px solid var(--b);display:flex;flex-direction:column;overflow:hidden}
.xfers{padding:7px;border-bottom:1px solid var(--b);flex-shrink:0;min-height:0}
.xi{background:var(--card);border:1px solid var(--b);border-radius:5px;padding:7px 9px;margin-bottom:4px}
.xi-name{font-size:11px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:5px}
.xi-bar{height:3px;background:var(--bg);border-radius:2px;overflow:hidden}
.xi-fill{height:100%;background:linear-gradient(90deg,var(--blue),var(--cyan));border-radius:2px;transition:width .4s}
.xi-meta{font-size:9px;color:var(--muted);margin-top:3px}
.logbox{flex:1;overflow-y:auto;padding:5px 7px;font-size:10px;line-height:1.9}
.logbox::-webkit-scrollbar{width:3px}
.logbox::-webkit-scrollbar-thumb{background:var(--b)}
.ll{padding:1px 4px;border-radius:2px;word-break:break-all}
.ll.info{color:var(--muted)}.ll.ok{color:var(--green)}.ll.error{color:var(--red)}.ll.warn{color:var(--yellow)}

/* MODAL */
.ov{display:none;position:fixed;inset:0;background:rgba(0,0,0,.78);z-index:200;align-items:center;justify-content:center;backdrop-filter:blur(5px)}
.ov.open{display:flex}
.modal{
  background:var(--panel);border:1px solid var(--b);border-radius:10px;
  padding:26px;width:400px;animation:mi .2s ease;
  box-shadow:0 24px 64px rgba(0,0,0,.7)
}
@keyframes mi{from{opacity:0;transform:scale(.93)}to{opacity:1;transform:scale(1)}}
.modal-h{font-family:var(--head);font-size:22px;letter-spacing:3px;color:var(--cyan);margin-bottom:18px}
.dz{
  border:2px dashed var(--b);border-radius:7px;padding:32px;
  text-align:center;cursor:pointer;color:var(--muted);font-size:11px;
  line-height:2.2;transition:all .2s;margin-bottom:14px
}
.dz:hover,.dz.dg{border-color:var(--cyan);color:var(--cyan);background:rgba(0,229,255,.03)}
.dz input{display:none}
.modal-btns{display:flex;gap:9px;justify-content:flex-end}
.btn-cancel{background:transparent;color:var(--muted);border:1px solid var(--b);border-radius:5px;padding:7px 14px;font-family:var(--mono);font-size:11px;cursor:pointer}
.btn-sf{
  background:var(--blue);color:#fff;border:none;border-radius:5px;
  padding:7px 16px;font-family:var(--mono);font-size:11px;font-weight:700;
  letter-spacing:1px;cursor:pointer;transition:background .15s
}
.btn-sf:hover{background:var(--cyan);color:var(--bg)}
.btn-sf:disabled{opacity:.35;cursor:not-allowed}

/* TOAST */
.toast{
  position:fixed;bottom:22px;left:50%;
  transform:translateX(-50%) translateY(70px);
  background:var(--panel);border:1px solid var(--b);
  border-radius:7px;padding:9px 18px;font-size:11px;font-weight:600;
  letter-spacing:1px;z-index:300;transition:transform .28s ease;pointer-events:none;
  box-shadow:0 8px 30px rgba(0,0,0,.55)
}
.toast.show{transform:translateX(-50%) translateY(0)}
.toast.ok{color:var(--green);border-color:rgba(0,255,157,.25)}
.toast.error{color:var(--red);border-color:rgba(255,51,85,.25)}
.toast.warn{color:var(--yellow);border-color:rgba(255,221,0,.25)}
</style>
</head>
<body>

<header>
  <div class="logo">🏝 ARCHIPEL</div>
  <div class="pills">
    <div class="pill">IP <b id="hIp">…</b></div>
    <div class="pill">PORT <b id="hPort">…</b></div>
    <div class="pill">ID <b id="hId">…</b></div>
    <div class="pill">RÉSEAU <b id="hN">0</b> PC</div>
  </div>
  <div class="dot"></div>
</header>

<div class="ws">

  <div class="sb">
    <div class="sh">PAIRS DÉTECTÉS <button class="scan-btn" id="scanBtn" onclick="doScan()">SCAN</button></div>
    <div class="peers" id="peers"><div class="empty">En attente...<br><small>Scan auto dans 4s</small></div></div>
  </div>

  <div class="chat">
    <div class="chat-top">
      <div>
        <div class="ct-name" id="ctName">— Sélectionnez un PC —</div>
        <div class="ct-sub"  id="ctSub">Choisissez un pair à gauche</div>
      </div>
      <div class="enc-badge" id="enc" style="opacity:.25">🔒 AES-256-GCM</div>
    </div>
    <div class="msgs" id="msgs">
      <div class="chat-empty">
        <div class="chat-empty-ico">🏝</div>
        <div class="chat-empty-txt">SÉLECTIONNEZ UN PC POUR COMMENCER</div>
      </div>
    </div>
    <div class="inp-row">
      <button class="btn-f" id="btnF" onclick="openModal()" disabled title="Envoyer un fichier">📎</button>
      <input  class="msg-inp" id="msgIn" placeholder="Message chiffré E2E…" disabled
              onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();doSend()}">
      <button class="btn-s" id="btnS" onclick="doSend()" disabled>ENVOYER</button>
    </div>
  </div>

  <div class="rp">
    <div class="sh">TRANSFERTS</div>
    <div class="xfers" id="xfers"></div>
    <div class="sh">LOGS RÉSEAU</div>
    <div class="logbox" id="logbox"></div>
  </div>

</div>

<div class="ov" id="ov">
  <div class="modal">
    <div class="modal-h">ENVOYER UN FICHIER</div>
    <div class="dz" id="dz"
         onclick="document.getElementById('fi').click()"
         ondragover="dzO(event)" ondragleave="dzL()" ondrop="dzD(event)">
      <div id="dzTxt">⬆ Cliquez ou déposez un fichier<br><small>Tout type · Max 200 Mo</small></div>
      <input type="file" id="fi" onchange="fChosen(this)">
    </div>
    <div class="modal-btns">
      <button class="btn-cancel" onclick="closeModal()">Annuler</button>
      <button class="btn-sf" id="btnSF" onclick="sendFile()" disabled>ENVOYER</button>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
let sel=null, peers={}, msgN=0, logN=0, fdata=null;

async function init(){
  const i=await api('/api/info');if(!i)return;
  g('hIp').textContent=i.ip; g('hPort').textContent=i.port;
  g('hId').textContent=i.node_id.slice(0,14)+'…';
  log('Nœud démarré · '+i.ip+':'+i.port,'ok');
  setInterval(pollPeers,3000);setInterval(pollMsgs,900);
  setInterval(pollLogs,1200);setInterval(pollXfers,1500);
  setTimeout(doScan,4000);
}

async function pollPeers(){
  const d=await api('/api/peers');if(!d)return;
  peers=d.peers||{};renderPeers();
  g('hN').textContent=Object.keys(peers).length;
}
async function pollMsgs(){
  if(!sel)return;
  const d=await api('/api/messages');if(!d)return;
  const m=d.messages||[];if(m.length===msgN)return;
  msgN=m.length;renderMsgs(m);
}
async function pollLogs(){
  const d=await api('/api/logs?since='+logN);if(!d)return;
  (d.logs||[]).forEach(l=>{log(l.msg,l.level);logN++;});
}
async function pollXfers(){
  const d=await api('/api/transfers');if(!d)return;
  renderXfers(d.transfers||[]);
}

function renderPeers(){
  const b=g('peers'),ks=Object.keys(peers);
  if(!ks.length){b.innerHTML='<div class="empty">Aucun PC trouvé<br><small>Cliquez SCAN</small></div>';return;}
  b.innerHTML=ks.map(id=>{
    const p=peers[id],age=Math.round(Date.now()/1000-(p.last_seen||0)),s=sel&&sel.id===id?'on':'';
    return`<div class="pc ${s}" onclick="pick('${id}','${p.ip}',${p.port})">
      <span class="pc-age">${age}s</span>
      <div class="pc-ip">${p.ip}</div>
      <div class="pc-port">PORT ${p.port}</div>
    </div>`;
  }).join('');
}

function pick(id,ip,port){
  sel={id,ip,port};
  g('ctName').textContent=ip+':'+port;
  g('ctSub').textContent='Chiffrement AES-256-GCM · nonce unique/message';
  g('enc').style.opacity='1';
  g('msgIn').disabled=false;g('btnS').disabled=false;g('btnF').disabled=false;
  g('msgIn').focus();renderPeers();msgN=0;pollMsgs();
  log('Chat ouvert avec '+ip,'info');
}

function renderMsgs(msgs){
  const b=g('msgs');
  b.innerHTML=msgs.map(m=>{
    const d=m.direction==='sent'?'sent':'recv';
    const w=m.direction==='sent'?'Vous':(m.from_ip||'Pair');
    return`<div class="bbl ${d}">${esc(m.text)}<div class="bbl-meta">${w} · ${m.timestamp}</div></div>`;
  }).join('');
  b.scrollTop=b.scrollHeight;
}

async function doSend(){
  if(!sel)return;
  const inp=g('msgIn'),txt=inp.value.trim();if(!txt)return;
  inp.value='';g('btnS').disabled=true;
  const d=await api('/api/send',{method:'POST',json:{peer_id:sel.id,peer_ip:sel.ip,peer_port:sel.port,text:txt}});
  g('btnS').disabled=false;inp.focus();
  if(d&&d.ok){toast('Message envoyé','ok');pollMsgs();}
  else toast('Échec envoi','error');
}

async function doScan(){
  const b=g('scanBtn');b.disabled=true;b.textContent='…';
  log('Scan réseau…','info');
  const d=await api('/api/scan',{method:'POST'});
  b.disabled=false;b.textContent='SCAN';
  if(d){toast(d.found+' PC(s) trouvé(s)',d.found>0?'ok':'warn');pollPeers();}
}

function openModal(){if(!sel){toast('Sélectionnez un PC','warn');return;}g('ov').classList.add('open');}
function closeModal(){g('ov').classList.remove('open');fdata=null;g('dzTxt').innerHTML='⬆ Cliquez ou déposez un fichier<br><small>Tout type · Max 200 Mo</small>';g('btnSF').disabled=true;g('fi').value='';}
function fChosen(inp){if(inp.files&&inp.files[0]){fdata=inp.files[0];g('dzTxt').textContent='📄 '+fdata.name+' ('+(fdata.size/1024).toFixed(0)+' Ko)';g('btnSF').disabled=false;}}
function dzO(e){e.preventDefault();g('dz').classList.add('dg');}
function dzL(){g('dz').classList.remove('dg');}
function dzD(e){e.preventDefault();dzL();const f=e.dataTransfer.files[0];if(f){fdata=f;g('dzTxt').textContent='📄 '+f.name;g('btnSF').disabled=false;}}

async function sendFile(){
  if(!sel||!fdata)return;
  const form=new FormData();
  form.append('file',fdata);form.append('peer_id',sel.id);
  form.append('peer_ip',sel.ip);form.append('peer_port',sel.port);
  closeModal();log('Envoi de '+fdata.name+'…','info');toast('Envoi en cours…','ok');
  const d=await fetch('/api/send_file',{method:'POST',body:form}).then(r=>r.json()).catch(()=>null);
  toast(d&&d.ok?'Fichier envoyé !':'Échec envoi fichier',d&&d.ok?'ok':'error');
}

function renderXfers(list){
  const b=g('xfers');
  if(!list.length){b.innerHTML='';return;}
  b.innerHTML=list.map(t=>`
    <div class="xi">
      <div class="xi-name">📄 ${esc(t.name)}</div>
      <div class="xi-bar"><div class="xi-fill" style="width:${t.pct}%"></div></div>
      <div class="xi-meta">${t.done}/${t.total} · ${t.pct}% ${t.completed?'✅':''}</div>
    </div>`).join('');
}

function log(msg,lv='info'){
  const b=g('logbox'),d=document.createElement('div');
  d.className='ll '+lv;d.textContent=new Date().toLocaleTimeString('fr',{hour12:false})+'  '+msg;
  b.appendChild(d);b.scrollTop=b.scrollHeight;
  while(b.children.length>200)b.removeChild(b.firstChild);
}

let _tt=null;
function toast(msg,lv='ok'){
  const t=g('toast');t.textContent=msg;t.className='toast '+lv;
  setTimeout(()=>t.classList.add('show'),10);
  clearTimeout(_tt);_tt=setTimeout(()=>t.classList.remove('show'),2800);
}

    function g(id){return document.getElementById(id);}
    function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
    async function api(url,o={}){
    try{
        const opt={method:o.method||'GET'};
        if(o.json){opt.headers={'Content-Type':'application/json'};opt.body=JSON.stringify(o.json);}
        return await(await fetch(url,opt)).json();
    }catch(e){return null;}
    }
init();
    </script>
    </body>
</html>
"""


# ─────────────────────────────────────────────────────────────────────
#  SERVEUR HTTP
# ─────────────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):

    def log_message(self, *_): pass

    def do_GET(self):
        p = urlparse(self.path).path
        q = parse_qs(urlparse(self.path).query)

        if p == '/':
            return self._ok('text/html; charset=utf-8', HTML.encode())
        if p == '/api/info':
            return self._json({"ip": my_ip, "port": my_port,
                               "node_id": my_node_id or "?",
                               "peers": peer_table.count()})
        if p == '/api/peers':
            return self._json({"peers": peer_table.get_all()})
        if p == '/api/messages':
            return self._json({"messages": list(messages_log)})
        if p == '/api/logs':
            since = int(q.get('since', ['0'])[0])
            with _log_lock:
                batch = list(system_log[since:])
            return self._json({"logs": batch})
        if p == '/api/transfers':
            return self._json({"transfers": get_transfers()})
        self._ok('text/plain', b'Not Found', 404)

    def do_POST(self):
        p = urlparse(self.path).path

        if p == '/api/send':
            b = self._jbody()
            ok = send_message(b.get('peer_ip'), b.get('peer_port'),
                              b.get('peer_id'), b.get('text')) if b else False
            return self._json({"ok": ok})

        if p == '/api/scan':
            n = do_scan()
            return self._json({"found": n})

        if p == '/api/send_file':
            return self._json(self._upload())

        self._ok('text/plain', b'Not Found', 404)

    def _upload(self):
        try:
            ct  = self.headers.get('Content-Type', '')
            ln  = int(self.headers.get('Content-Length', 0))
            raw = self.rfile.read(ln)
            if 'multipart/form-data' not in ct:
                return {"ok": False, "error": "not multipart"}

            bnd   = ct.split('boundary=')[-1].strip().encode()
            parts = raw.split(b'--' + bnd)

            peer_ip = peer_port = peer_id = fname = fdata = None
            for part in parts:
                if b'Content-Disposition' not in part:
                    continue
                hdr, _, body = part.partition(b'\r\n\r\n')
                body   = body.rstrip(b'\r\n')
                hdrstr = hdr.decode('utf-8', errors='ignore')
                if   'name="peer_ip"'   in hdrstr: peer_ip   = body.decode().strip()
                elif 'name="peer_port"' in hdrstr: peer_port = int(body.decode().strip())
                elif 'name="peer_id"'   in hdrstr: peer_id   = body.decode().strip()
                elif 'name="file"'      in hdrstr:
                    for s in hdrstr.split(';'):
                        if 'filename=' in s:
                            fname = s.split('filename=')[-1].strip().strip('"')
                    fdata = body

            if not all([peer_ip, peer_port, peer_id, fname, fdata]):
                return {"ok": False, "error": "données manquantes"}

            base  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            tmpd  = os.path.join(base, 'tmp_uploads')
            os.makedirs(tmpd, exist_ok=True)
            path  = os.path.join(tmpd, fname)
            with open(path, 'wb') as f:
                f.write(fdata)

            syslog(f"Upload reçu : {fname} ({len(fdata)//1024} Ko)", "info")

            if file_transfer:
                threading.Thread(
                    target=send_file_bg,
                    args=(path, fname, peer_ip, peer_port, peer_id),
                    daemon=True
                ).start()
                return {"ok": True}

            return {"ok": False, "error": "service transfert indisponible"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _jbody(self):
        try:
            n = int(self.headers.get('Content-Length', 0))
            return json.loads(self.rfile.read(n))
        except Exception:
            return None

    def _json(self, d):
        b = json.dumps(d, default=str).encode()
        self._ok('application/json', b)

    def _ok(self, ct, body, code=200):
        self.send_response(code)
        self.send_header('Content-Type', ct)
        self.send_header('Content-Length', len(body))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

#  DÉMARRAGE
# ─────────────────────────────────────────────────────────────────────
def start(port=7777, web_port=8080):
    global messaging, file_transfer, my_node_id, my_ip, my_port
    my_port = port

    # Clés dans .archipel/ — hors repo Git (anti-pattern 1)
    signing_key, verify_key = load_identity(port)
    my_node_id = verify_key.encode().hex()
    
    # Corrige la détection d'IP
    my_ip = get_my_ip()
    
    # Affiche un debug
    print(f"\n[DEBUG] IP détectée: {my_ip}")
    
    print()
    print("=" * 55)
    print("  🏝️  ARCHIPEL — Sprint 4 — Zero Day Heroes")
    print("=" * 55)
    print(f"  Mon IP    : {my_ip}")
    print(f"  Port P2P  : {port}")
    print(f"  Interface : http://localhost:{web_port}")
    print("=" * 55)

    # Nonce unique par message — anti-pattern 3 respecté dans messaging.py
    session_manager = SessionManager(signing_key)

    messaging = MessagingService(signing_key, my_node_id, session_manager, port)
    messaging.start_tcp_server(port)
    patch_messaging(messaging)

    from src.network.router import RelayService
    relay = RelayService(my_node_id, peer_table, messaging)
    messaging.set_relay_service(relay)

    file_transfer = FileTransferService(
        my_node_id, my_ip, port,
        messaging.print_lock, session_manager,
        signing_key, peer_table
    )
    file_transfer.start()
    messaging.set_file_transfer(file_transfer)

    discovery = DiscoveryService(peer_table, my_node_id, tcp_port=port)
    discovery.start()

    syslog(f"Nœud P2P démarré sur {my_ip}:{port}", "ok")
    syslog(f"Ce PC est son propre serveur — zéro infrastructure centrale", "info")

    # Serveur web — le PC lui-même héberge l'interface
    srv = HTTPServer(('0.0.0.0', web_port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    syslog(f"Interface web sur http://localhost:{web_port}", "ok")

    # Ouvrir le navigateur automatiquement
    time.sleep(1.2)
    webbrowser.open(f'http://localhost:{web_port}')

    print(f"\n[✅] Navigateur ouvert sur http://localhost:{web_port}")
    print("[INFO] Ctrl+C pour arrêter\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[ARRÊT] Archipel arrêté proprement")
        discovery.stop()


if __name__ == "__main__":
    port     = int(sys.argv[1]) if len(sys.argv) > 1 else 7777
    web_port = int(sys.argv[2]) if len(sys.argv) > 2 else 8080
    start(port, web_port)