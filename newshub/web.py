"""Web kumanda paneli (Flask): sistem sağlığı, ajans kartları, aç/kapat, canlı log."""
from __future__ import annotations

import hmac

from flask import Flask, Response, jsonify, request

from .config_io import apply_and_save, load_editable
from .status import StatusRegistry

PAGE = r"""
<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Haber Toplama Servisi</title>
<style>
  :root{
    --bg:#0b1017; --panel:#131c27; --panel2:#0e1620; --line:#233245;
    --txt:#e8eef5; --mut:#8ba0b6; --acc:#3b82f6;
    --ok:#22c55e; --run:#3b82f6; --err:#ef4444; --off:#64748b; --warn:#f59e0b;
  }
  *{box-sizing:border-box}
  body{margin:0;background:radial-gradient(1200px 600px at 70% -10%,#16212f 0%,var(--bg) 55%);
       color:var(--txt);font:14px/1.5 -apple-system,Segoe UI,Roboto,Arial;min-height:100vh}
  .top{display:flex;align-items:center;justify-content:space-between;gap:14px;
       padding:16px 24px;border-bottom:1px solid var(--line);background:rgba(11,16,23,.6);
       backdrop-filter:blur(6px);position:sticky;top:0;z-index:5}
  .brand{display:flex;align-items:center;gap:12px}
  .brand .logo{font-size:22px}
  .brand h1{font-size:16px;margin:0;font-weight:700;letter-spacing:.2px}
  .brand .sub{color:var(--mut);font-size:12px}
  .health{display:flex;align-items:center;gap:10px;font-weight:600;font-size:13px;
          padding:7px 14px;border-radius:999px;border:1px solid var(--line);background:var(--panel)}
  .health .dot{width:10px;height:10px;border-radius:50%}
  .wrap{padding:22px 24px;max-width:1240px;margin:0 auto}
  .stats{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:22px}
  .stat{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px 18px}
  .stat .k{color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.04em}
  .stat .v{font-size:30px;font-weight:800;margin-top:4px;font-variant-numeric:tabular-nums}
  .cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px}
  .card{background:linear-gradient(180deg,var(--panel),var(--panel2));border:1px solid var(--line);
        border-radius:16px;padding:18px;position:relative;overflow:hidden}
  .card::before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--off)}
  .card.s-idle::before{background:var(--ok)} .card.s-running::before{background:var(--run)}
  .card.s-error::before{background:var(--err)} .card.s-disabled::before{background:var(--off)}
  .card .hd{display:flex;align-items:center;justify-content:space-between;gap:10px}
  .card .nm{display:flex;align-items:center;gap:10px}
  .card .nm b{font-size:17px}
  .badge{font-size:11px;color:var(--mut);border:1px solid var(--line);border-radius:999px;
         padding:2px 9px;white-space:nowrap}
  .pill{display:inline-flex;align-items:center;gap:7px;font-weight:700;font-size:13px;
        padding:5px 12px;border-radius:999px}
  .pill .dot{width:9px;height:9px;border-radius:50%}
  .s-idle .pill{color:var(--ok);background:rgba(34,197,94,.12)} .s-idle .pill .dot{background:var(--ok);box-shadow:0 0 8px var(--ok)}
  .s-running .pill{color:var(--run);background:rgba(59,130,246,.12)} .s-running .pill .dot{background:var(--run);box-shadow:0 0 8px var(--run);animation:pulse 1.2s infinite}
  .s-error .pill{color:var(--err);background:rgba(239,68,68,.12)} .s-error .pill .dot{background:var(--err);box-shadow:0 0 8px var(--err)}
  .s-disabled .pill{color:var(--off);background:rgba(100,116,139,.12)} .s-disabled .pill .dot{background:var(--off)}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
  .flow{margin:14px 0 12px;padding:10px 12px;background:rgba(255,255,255,.03);border-radius:10px;
        font-size:13px;color:#cdd9e6;min-height:38px;display:flex;align-items:center;gap:8px}
  .flow .lbl{color:var(--mut);font-size:11px}
  .grid2{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:6px 0 14px}
  .kv .k{color:var(--mut);font-size:11px} .kv .v{font-weight:700;font-size:15px;font-variant-numeric:tabular-nums}
  .chk{color:var(--ok);font-size:11px;opacity:.75;margin:2px 0 8px}
  .path{color:var(--mut);font-family:ui-monospace,Consolas,monospace;font-size:11px;
        word-break:break-all;margin-bottom:12px}
  .row{display:flex;gap:8px}
  button{flex:1;border:1px solid var(--line);background:#1a2836;color:var(--txt);
         padding:9px;border-radius:9px;cursor:pointer;font-size:13px;font-weight:600;transition:.15s}
  button:hover{border-color:var(--acc);background:#213142}
  button.on{color:var(--ok)} button.off{color:var(--err)}
  .err{color:#fca5a5;font-size:12px;margin-top:2px}
  h3.sec{margin:26px 0 10px;font-size:12px;color:var(--mut);text-transform:uppercase;letter-spacing:.06em}
  #log{background:#080d13;border:1px solid var(--line);border-radius:14px;padding:14px 16px;
       height:280px;overflow:auto;font:12.5px/1.7 ui-monospace,Consolas,monospace}
  #log div{white-space:pre-wrap;word-break:break-word}
  #log .l-ok{color:#7ee0a2} #log .l-warn{color:#fbbf24} #log .l-err{color:#f87171}
  #log .l-sum{color:#8ba0b6} #log .l-dim{color:#6b7d90}
  @media(max-width:680px){.stats{grid-template-columns:1fr}}
  .cfgbtn{border:1px solid var(--line);background:var(--panel);color:var(--txt);padding:8px 14px;
          border-radius:999px;cursor:pointer;font-size:13px;font-weight:600}
  .cfgbtn:hover{border-color:var(--acc)}
  .modal{position:fixed;inset:0;background:rgba(0,0,0,.72);
         display:flex;align-items:flex-start;justify-content:center;padding:40px 16px;z-index:20;overflow:auto}
  .modal-box{background:var(--panel);border:1px solid var(--line);border-radius:16px;
             width:100%;max-width:720px;box-shadow:0 20px 60px rgba(0,0,0,.5)}
  .modal-hd{display:flex;align-items:center;justify-content:space-between;padding:16px 20px;
            border-bottom:1px solid var(--line);font-size:16px}
  .modal-hd .x{border:none;background:none;color:var(--mut);font-size:18px;cursor:pointer}
  #cfgBody{padding:8px 20px;max-height:64vh;overflow:auto}
  .modal-ft{display:flex;align-items:center;gap:10px;padding:14px 20px;border-top:1px solid var(--line)}
  .modal-ft button{border:1px solid var(--line);background:#1a2836;color:var(--txt);
                   padding:9px 16px;border-radius:9px;cursor:pointer;font-weight:600}
  .modal-ft button.primary{background:var(--acc);border-color:var(--acc);color:#fff}
  .cfg-sec{padding:14px 0;border-bottom:1px solid var(--line)}
  .cfg-sec h4{margin:0 0 12px;font-size:14px;display:flex;align-items:center;gap:8px}
  .cfg-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px 16px}
  .fld{display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--mut)}
  .fld span{font-weight:600}
  .fld input[type=text],.fld input[type=password],.fld input[type=number]{
      background:var(--panel2);border:1px solid var(--line);border-radius:8px;
      padding:8px 10px;color:var(--txt);font-size:13px}
  .fld input:focus{outline:none;border-color:var(--acc)}
  .fld.bool{flex-direction:row;align-items:center;gap:8px}
  @media(max-width:560px){.cfg-grid{grid-template-columns:1fr}}
</style></head><body>
<div class="top">
  <div class="brand"><span class="logo">📡</span>
    <div><h1>Haber Toplama Servisi</h1><div class="sub" id="clock">—</div></div>
  </div>
  <div style="display:flex;align-items:center;gap:12px">
    <button class="cfgbtn" onclick="openConfig()">⚙ Ayarlar</button>
    <div class="health" id="health"><span class="dot" style="background:var(--off)"></span><span id="healthTxt">Bağlanıyor…</span></div>
  </div>
</div>
<div class="wrap">
  <div class="stats">
    <div class="stat"><div class="k">Bugün toplanan haber</div><div class="v" id="stTotal">—</div></div>
    <div class="stat"><div class="k">Çalışan ajans</div><div class="v" id="stActive">—</div></div>
    <div class="stat"><div class="k">Sorunlu ajans</div><div class="v" id="stErr">—</div></div>
    <div class="stat"><div class="k">Medyası inmeyen (arıza)</div><div class="v" id="stFail">—</div></div>
  </div>
  <div class="cards" id="cards"></div>
  <h3 class="sec">Canlı Akış / Log</h3>
  <div id="log"></div>
</div>
<div id="cfgModal" class="modal" style="display:none">
  <div class="modal-box">
    <div class="modal-hd"><b>⚙ Ayarlar</b><button class="x" onclick="closeConfig()">✕</button></div>
    <div id="cfgBody">Yükleniyor…</div>
    <div class="modal-ft">
      <span id="cfgMsg" class="muted" style="font-size:12px"></span>
      <div style="flex:1"></div>
      <button onclick="closeConfig()">İptal</button>
      <button class="primary" onclick="saveConfig()">Kaydet ve Uygula</button>
    </div>
  </div>
</div>
<script>
const LBL={running:"Çekiyor",idle:"Canlı",error:"Sorun",disabled:"Kapalı"};
const ICON={"Çekici":"📥","Bekçi":"🐕"};
function esc(s){return (s??'').toString().replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
async function api(u){await fetch(u,{method:'POST'});setTimeout(refresh,150);}
function logClass(l){
  if(l.includes('✓'))return 'l-ok'; if(l.includes('✗')||l.includes('HATA')||l.includes('ERROR'))return 'l-err';
  if(l.includes('⚠'))return 'l-warn'; if(l.includes('↻')||l.includes('●'))return 'l-sum'; return 'l-dim';
}
async function refresh(){
  let r; try{r=await (await fetch('/api/status',{cache:'no-store'})).json();}catch(e){return;}
  document.getElementById('clock').textContent='Sunucu saati: '+r.now;
  const errs=r.agencies.filter(a=>a.state==='error');
  const active=r.agencies.filter(a=>a.enabled&&a.state!=='error'&&a.state!=='disabled');
  const total=r.agencies.reduce((s,a)=>s+(a.written_total||0),0);
  const fails=r.agencies.reduce((s,a)=>s+(a.failures||0),0);
  document.getElementById('stTotal').textContent=total;
  document.getElementById('stActive').textContent=active.length+' / '+r.agencies.length;
  document.getElementById('stErr').textContent=errs.length;
  const sf=document.getElementById('stFail');sf.textContent=fails;sf.style.color=fails?'var(--warn)':'var(--txt)';
  const h=document.getElementById('health'),ht=document.getElementById('healthTxt');
  const hd=h.querySelector('.dot');
  if(errs.length){hd.style.background='var(--err)';ht.textContent=errs.length+' ajansta sorun';}
  else{hd.style.background='var(--ok)';ht.textContent='Sistem sağlıklı';}
  document.getElementById('cards').innerHTML=r.agencies.map(a=>`
    <div class="card s-${a.state}">
      <div class="hd">
        <div class="nm"><span>${ICON[a.kind]||'📡'}</span><b>${esc(a.name)}</b>
          <span class="badge">${esc(a.kind)}</span></div>
        <span class="pill"><span class="dot"></span>${LBL[a.state]||a.state}</span>
      </div>
      <div class="flow"><span class="lbl">SON:</span>${a.last_title?esc(a.last_title):'<span style="color:var(--mut)">—</span>'}</div>
      <div class="grid2">
        <div class="kv"><div class="k">Bugün</div><div class="v">${a.written_total||0}</div></div>
        <div class="kv"><div class="k">Son haber</div><div class="v" style="font-size:12.5px">${esc(a.last_success)||'—'}</div></div>
      </div>
      <div class="chk">⟳ son kontrol: ${a.last_check?esc(a.last_check.slice(11)):'—'}</div>
      <div class="path">📁 ${esc(a.output_dir)}</div>
      ${a.last_error?`<div class="err">⚠ ${esc(a.last_error)}</div>`:''}
      ${a.failures?`<div class="err" style="color:var(--warn)">⚠ ${a.failures} haberde medya inmedi (metin kaydedildi)</div>`:''}
      <div class="row" style="margin-top:12px">
        ${a.enabled
          ?`<button class="off" onclick="api('/api/agency/${encodeURIComponent(a.name)}/disable')">■ Durdur</button>`
          :`<button class="on" onclick="api('/api/agency/${encodeURIComponent(a.name)}/enable')">▶ Başlat</button>`}
        <button onclick="api('/api/agency/${encodeURIComponent(a.name)}/fetch-now')">↻ Şimdi çek</button>
      </div>
    </div>`).join('');
  const log=document.getElementById('log');const bottom=log.scrollTop+log.clientHeight>=log.scrollHeight-40;
  log.innerHTML=r.logs.map(l=>`<div class="${logClass(l)}">${esc(l)}</div>`).join('');
  if(bottom)log.scrollTop=log.scrollHeight;
}
refresh();setInterval(refresh,2000);

let cfgData=null;
function fieldInput(prefix,key,val){
  const id=`f_${prefix}_${key}`;
  if(typeof val==='boolean')
    return `<label class="fld bool"><input type="checkbox" id="${id}" ${val?'checked':''}><span>${esc(key)}</span></label>`;
  const isPw=/pass|şifre|sifre|password/i.test(key);
  const type=isPw?'password':(typeof val==='number'?'number':'text');
  const step=(typeof val==='number')?'step="any"':'';
  return `<label class="fld"><span>${esc(key)}</span><input type="${type}" id="${id}" value="${esc(val)}" ${step} autocomplete="off"></label>`;
}
async function openConfig(){
  const m=document.getElementById('cfgModal');m.style.display='flex';
  document.getElementById('cfgMsg').textContent='';
  const body=document.getElementById('cfgBody');body.innerHTML='Yükleniyor…';
  try{cfgData=await (await fetch('/api/config',{cache:'no-store'})).json();}catch(e){body.innerHTML='Yüklenemedi';return;}
  let html=`<div class="cfg-sec"><h4>⚙ Genel</h4><div class="cfg-grid">`;
  for(const [k,v] of Object.entries(cfgData.global)) html+=fieldInput('g',k,v);
  html+=`</div></div>`;
  cfgData.agencies.forEach((a,i)=>{
    html+=`<div class="cfg-sec"><h4>${esc(a.name)} <span class="badge">${esc(a.type)}</span></h4><div class="cfg-grid">`;
    for(const [k,v] of Object.entries(a.fields)) html+=fieldInput('a'+i,k,v);
    html+=`</div></div>`;
  });
  body.innerHTML=html;
}
function closeConfig(){document.getElementById('cfgModal').style.display='none';}
function collectVal(prefix,key,orig){
  const el=document.getElementById(`f_${prefix}_${key}`);
  if(!el) return orig;
  if(el.type==='checkbox') return el.checked;
  if(el.type==='number') return el.value===''?orig:Number(el.value);
  return el.value;
}
async function saveConfig(){
  if(!cfgData) return;
  const payload={global:{},agencies:[]};
  for(const [k,v] of Object.entries(cfgData.global)) payload.global[k]=collectVal('g',k,v);
  cfgData.agencies.forEach((a,i)=>{
    const fields={};
    for(const [k,v] of Object.entries(a.fields)) fields[k]=collectVal('a'+i,k,v);
    payload.agencies.push({name:a.name,fields});
  });
  const msg=document.getElementById('cfgMsg');msg.textContent='Kaydediliyor…';
  try{
    const r=await (await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})).json();
    if(r.ok){msg.textContent='✓ Kaydedildi ve uygulandı';setTimeout(()=>{closeConfig();refresh();},900);}
    else msg.textContent='Hata: '+(r.error||'?');
  }catch(e){msg.textContent='Hata: '+e;}
}
</script></body></html>
"""


def create_app(service) -> Flask:
    app = Flask(__name__)
    registry = service.registry

    @app.before_request
    def _require_auth():
        if not service.web_user:   # web_user boşsa panel açık, değilse giriş ister
            return None
        auth = request.authorization
        ok = (auth is not None
              and hmac.compare_digest(auth.username or "", service.web_user)
              and hmac.compare_digest(auth.password or "", service.web_password))
        if not ok:
            return Response("Giriş gerekli", 401,
                            {"WWW-Authenticate": 'Basic realm="Haber Servisi"'})
        return None

    @app.get("/")
    def index():
        return PAGE

    @app.get("/api/status")
    def status():
        resp = jsonify({
            "now": _clock(),
            "agencies": registry.snapshot(),
            "logs": registry.recent_logs(200),
        })
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return resp

    @app.post("/api/agency/<name>/enable")
    def enable(name):
        if name in service.workers:
            registry.update(name, enabled=True, state="idle")
            service.workers[name].fetch_now()
        return jsonify(ok=True)

    @app.post("/api/agency/<name>/disable")
    def disable(name):
        if name in service.workers:
            registry.update(name, enabled=False)
        return jsonify(ok=True)

    @app.post("/api/agency/<name>/fetch-now")
    def fetch_now(name):
        if name in service.workers:
            service.workers[name].fetch_now()
        return jsonify(ok=True)

    @app.get("/api/config")
    def get_config():
        return jsonify(load_editable(service.config_path))

    @app.post("/api/config")
    def save_config():
        data = request.get_json(force=True) or {}
        try:
            apply_and_save(service.config_path, data)
            service.reload()
            return jsonify(ok=True)
        except Exception as e:
            return jsonify(ok=False, error=str(e)), 400

    return app


def _clock() -> str:
    import datetime as _dt
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
