"""
ARCANE Cloud — Railway deployment
Single file, zero dependencies on static folder, works 100%
"""
import os, json, base64, requests, re, datetime
from flask import Flask, request, jsonify, Response

app = Flask(__name__)

GROQ_KEY    = os.environ.get("GROQ_API_KEY",    "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")
GEM_KEY     = os.environ.get("GEMINI_API_KEY",  "AIzaSyBS3OKamOSz8sWT5DmUmMjT-4P8ZGpbCZA")
EL_KEY      = os.environ.get("ELEVENLABS_KEY",  "sk_2366c420fdd5cc5126322b6c073919fb7a3288073ec40754")
EL_VOICE    = os.environ.get("ELEVENLABS_VOICE","ZT9u07TYPVl83ejeLakq")
SOMTODAY    = "https://api.somtoday.nl/rest/v1/icalendar/stream/16edafe9-0fe3-42cc-8582-e62243b01d5a/10e0526e-0852-4016-b761-49b4ec3504a1"
PORT        = int(os.environ.get("PORT", 8080))

_histories = {}
_memory    = {}

SYSTEM = """You are Arcane — Joey's personal AI assistant. Like F.R.I.D.A.Y. from Iron Man.
Confident, concise, max 2-3 sentences. Match user language (Dutch→Dutch).
Actions — add JSON at END:
{"action":"weather","city":"Leeuwarden"}
{"action":"school_today"} {"action":"school_tomorrow"} {"action":"school_week"}
{"action":"search","query":"terms"}
{"action":"remember","fact":"text"}
{"action":"generate_image","prompt":"description"}
{"action":"news"}
{"action":"translate","text":"...","target":"English"}"""

# ── BRAIN ─────────────────────────────────────────────────
def think(sid, message):
    hist = _histories.get(sid, [])
    mem  = _memory.get(sid, [])
    sys  = SYSTEM + ("\n\nMemory:\n" + "\n".join(mem[-8:]) if mem else "")
    hist.append({"role":"user","content":message})
    if len(hist) > 20: hist = hist[-20:]
    try:
        r = requests.post("https://api.groq.com/openai/v1/chat/completions",
            json={"model":"llama-3.3-70b-versatile",
                  "messages":[{"role":"system","content":sys}]+hist,
                  "max_tokens":512,"temperature":0.7},
            headers={"Authorization":f"Bearer {GROQ_KEY}","Content-Type":"application/json"},
            timeout=30)
        reply = r.json()["choices"][0]["message"]["content"]
        hist.append({"role":"assistant","content":reply})
        _histories[sid] = hist
        action = None
        m = re.search(r'\{[^{}]*"action"[^{}]*\}', reply, re.DOTALL)
        if m:
            try: action = json.loads(m.group())
            except: pass
        if action and action.get("action") == "remember":
            f = _memory.get(sid,[]); f.append(action.get("fact","")); _memory[sid]=f
        clean = re.sub(r'\{[^{}]*"action"[^{}]*\}','',reply,flags=re.DOTALL).strip()
        return clean, action
    except Exception as e:
        return f"Error: {e}", None

# ── ACTIONS ───────────────────────────────────────────────
def do_action(action):
    if not action: return None
    t = action.get("action","")

    if t == "weather":
        city = action.get("city","Leeuwarden")
        try:
            geo = requests.get(f"https://geocoding-api.open-meteo.com/v1/search?name={requests.utils.quote(city)}&count=1",timeout=8).json()
            if not geo.get("results"): return f"City not found: {city}"
            loc = geo["results"][0]
            wx  = requests.get(
                f"https://api.open-meteo.com/v1/forecast"
                f"?latitude={loc['latitude']}&longitude={loc['longitude']}"
                f"&current=temperature_2m,apparent_temperature,weathercode,windspeed_10m,relativehumidity_2m,precipitation"
                f"&daily=temperature_2m_max,temperature_2m_min,weathercode"
                f"&timezone=auto&forecast_days=3",timeout=8).json()
            cur = wx.get("current",{})
            cond = {0:"Clear ☀️",1:"Clear ☀️",2:"Partly cloudy ⛅",3:"Overcast ☁️",
                    45:"Foggy 🌫️",51:"Drizzle 🌦️",61:"Rain 🌧️",63:"Rain 🌧️",65:"Heavy rain 🌧️",
                    71:"Snow ❄️",80:"Showers 🌦️",95:"Thunderstorm ⛈️"}
            code = cur.get("weathercode",0)
            lines = [
                f"🌡️ {loc['name']}: {cond.get(code,'?')}",
                f"{cur.get('temperature_2m','?')}°C (feels {cur.get('apparent_temperature','?')}°C)",
                f"💧{cur.get('relativehumidity_2m','?')}% 💨{cur.get('windspeed_10m','?')}km/h"
            ]
            daily = wx.get("daily",{})
            for i in range(min(3,len(daily.get("time",[])))):
                lines.append(f"{daily['time'][i]}: {daily['temperature_2m_min'][i]}–{daily['temperature_2m_max'][i]}°C {cond.get(daily['weathercode'][i],'')}")
            return "\n".join(lines)
        except Exception as e: return f"Weather error: {e}"

    elif t in ("school_today","school_tomorrow","school_week"):
        try:
            resp = requests.get(SOMTODAY, timeout=10)
            events, ev = [], {}
            for line in resp.text.split("\n"):
                line = line.strip()
                if line=="BEGIN:VEVENT": ev={}
                elif line=="END:VEVENT" and ev: events.append(ev); ev={}
                elif line.startswith("DTSTART"): ev["start"]=line.split(":",1)[-1]
                elif line.startswith("SUMMARY"): ev["title"]=line.split(":",1)[-1]
                elif line.startswith("LOCATION"): ev["loc"]=line.split(":",1)[-1]
            now = datetime.datetime.now()
            filtered = []
            for ev in events:
                s = ev.get("start","").replace("Z","")
                for fmt in ["%Y%m%dT%H%M%S","%Y%m%d"]:
                    try:
                        dt = datetime.datetime.strptime(s,fmt)
                        if t=="school_today" and dt.date()==now.date(): filtered.append((dt,ev))
                        elif t=="school_tomorrow" and dt.date()==(now+datetime.timedelta(1)).date(): filtered.append((dt,ev))
                        elif t=="school_week" and 0<=(dt.date()-now.date()).days<=7: filtered.append((dt,ev))
                        break
                    except: pass
            filtered.sort(key=lambda x:x[0])
            if not filtered: return "No classes found."
            return "\n".join(f"📚 {dt.strftime('%a %H:%M')} — {ev.get('title','?')}" + (f" ({ev['loc']})" if ev.get("loc") else "") for dt,ev in filtered)
        except Exception as e: return f"School error: {e}"

    elif t == "search":
        try:
            r = requests.get("https://api.duckduckgo.com/",
                params={"q":action.get("query",""),"format":"json","no_html":1},timeout=8).json()
            if r.get("AbstractText"): return r["AbstractText"][:500]
            for topic in r.get("RelatedTopics",[]):
                if isinstance(topic,dict) and topic.get("Text"): return topic["Text"][:400]
            return "No results found."
        except Exception as e: return f"Search error: {e}"

    elif t == "news":
        try:
            r = requests.get("https://api.duckduckgo.com/",
                params={"q":"Netherlands news today","format":"json","no_html":1},timeout=8).json()
            lines = []
            for topic in r.get("RelatedTopics",[])[:5]:
                if isinstance(topic,dict) and topic.get("Text"):
                    lines.append("• " + topic["Text"][:120])
            return "\n".join(lines) if lines else "No news found."
        except Exception as e: return f"News error: {e}"

    elif t == "translate":
        try:
            r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                json={"model":"llama-3.3-70b-versatile",
                      "messages":[{"role":"user","content":f"Translate to {action.get('target','English')}. Reply with ONLY the translation:\n{action.get('text','')}"}],
                      "max_tokens":300,"temperature":0.1},
                headers={"Authorization":f"Bearer {GROQ_KEY}","Content-Type":"application/json"},
                timeout=15)
            return r.json()["choices"][0]["message"]["content"]
        except Exception as e: return f"Translation error: {e}"

    elif t == "generate_image":
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-002:predict?key={GEM_KEY}"
            r = requests.post(url,
                json={"instances":[{"prompt":action.get("prompt","")}],"parameters":{"sampleCount":1}},
                timeout=60)
            if r.status_code==200:
                return "IMAGE_B64:" + r.json()["predictions"][0]["bytesBase64Encoded"]
        except Exception as e: return f"Image error: {e}"

    return None

# ── TTS ───────────────────────────────────────────────────
def tts(text):
    try:
        r = requests.post(f"https://api.elevenlabs.io/v1/text-to-speech/{EL_VOICE}",
            json={"text":text[:500],"model_id":"eleven_turbo_v2",
                  "voice_settings":{"stability":0.5,"similarity_boost":0.8}},
            headers={"xi-api-key":EL_KEY,"Content-Type":"application/json"},timeout=20)
        if r.status_code==200: return base64.b64encode(r.content).decode()
    except: pass
    return None

# ── HTML (full PWA UI embedded) ───────────────────────────
HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="theme-color" content="#000000">
<title>ARCANE</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{background:#000;color:#ffcccc;font-family:'Courier New',monospace;height:100dvh;display:flex;flex-direction:column;overflow:hidden;user-select:none}
#header{padding:12px 16px;border-bottom:1px solid #3a0404;display:flex;align-items:center;justify-content:space-between;flex-shrink:0}
#header h1{font-size:18px;color:#ff2020;letter-spacing:4px}
#status{font-size:10px;color:#660808}
#orb-wrap{display:flex;justify-content:center;align-items:center;padding:16px 0;flex-shrink:0}
#orb-canvas{border-radius:50%;cursor:pointer}
#caption{text-align:center;font-size:11px;color:#880808;min-height:18px;padding:0 16px;flex-shrink:0;letter-spacing:1px}
#chat{flex:1;overflow-y:auto;padding:10px 12px;display:flex;flex-direction:column;gap:6px;min-height:0}
#chat::-webkit-scrollbar{width:3px}
#chat::-webkit-scrollbar-thumb{background:#3a0404;border-radius:2px}
.msg{max-width:88%;padding:10px 14px;border-radius:12px;font-size:13px;line-height:1.5;word-break:break-word}
.user{align-self:flex-end;background:#120000;border:1px solid #3a0404;color:#ffaaaa}
.arcane{align-self:flex-start;background:#0a0000;border:1px solid #550404;color:#ffcccc}
.system{align-self:center;color:#880808;font-size:11px;font-style:italic;border:none;background:transparent}
.action{align-self:flex-start;color:#ff6600;font-size:12px;background:#0a0000;border:1px solid #332200;white-space:pre-wrap}
#input-row{display:flex;gap:8px;padding:10px 12px;border-top:1px solid #3a0404;flex-shrink:0}
#inp{flex:1;background:#080000;border:1px solid #550404;color:#ffcccc;padding:10px 14px;border-radius:20px;font-family:'Courier New',monospace;font-size:14px;outline:none}
#inp::placeholder{color:#440404}
#inp:focus{border-color:#880808}
#send-btn{background:#1a0000;border:1px solid #880808;color:#ff2020;width:44px;height:44px;border-radius:50%;cursor:pointer;font-size:18px;display:flex;align-items:center;justify-content:center}
#mic-btn{background:#1a0000;border:1px solid #880808;color:#ff2020;width:44px;height:44px;border-radius:50%;cursor:pointer;font-size:18px;display:flex;align-items:center;justify-content:center}
#mic-btn.active{background:#3a0000;border-color:#ff2020;animation:pulse 1s infinite}
@keyframes pulse{0%,100%{box-shadow:0 0 0 0 rgba(255,32,32,0.4)}50%{box-shadow:0 0 0 8px rgba(255,32,32,0)}}
#tabs{display:flex;border-bottom:1px solid #3a0404;flex-shrink:0}
.tab{flex:1;padding:8px;font-size:10px;text-align:center;cursor:pointer;color:#440404;letter-spacing:1px;transition:all 0.2s}
.tab.active{color:#ff2020;border-bottom:1px solid #ff2020}
.tab:hover{color:#880808}
</style>
</head>
<body>
<div id="header">
  <h1>◈ ARCANE</h1>
  <div id="status">● ONLINE</div>
</div>
<div id="orb-wrap"><canvas id="orb-canvas" width="180" height="180"></canvas></div>
<div id="caption">ADAPTIVE RUNTIME COMPUTING & AUTONOMOUS NEURAL ENGINE</div>
<div id="tabs">
  <div class="tab active" onclick="setTab('chat')">CHAT</div>
  <div class="tab" onclick="setTab('school')">SCHOOL</div>
  <div class="tab" onclick="setTab('weather')">WEATHER</div>
  <div class="tab" onclick="setTab('memory')">MEMORY</div>
</div>
<div id="chat"></div>
<div id="input-row">
  <button id="mic-btn" onclick="toggleMic()">🎙</button>
  <input id="inp" placeholder="Message Arcane..." onkeydown="if(event.key==='Enter')send()">
  <button id="send-btn" onclick="send()">▶</button>
</div>

<script>
const SESSION = 'arcane_' + Math.random().toString(36).slice(2);
let listening = false, recognition = null, orbState = 'idle';
let orbAngle = 0, orbAngle2 = 0, orbPulse = 0, orbPulseDir = 1;

// ── ORB ──────────────────────────────────────────────────
const canvas = document.getElementById('orb-canvas');
const ctx    = canvas.getContext('2d');
const S      = 180, CX = S/2, CY = S/2, R = 72;

const STATE_COLORS = {
  idle:      [180,8,8],    listening: [255,20,20],
  thinking:  [20,80,255],  speaking:  [220,80,10],
  alert:     [255,200,0],  observing: [0,200,180],
  resting:   [40,4,4],
};
let curColor = [180,8,8], tgtColor = [180,8,8];

function setOrbState(state) {
  orbState = state;
  tgtColor = STATE_COLORS[state] || [180,8,8];
}

function drawOrb() {
  ctx.clearRect(0,0,S,S);
  // blend color
  curColor = curColor.map((c,i) => c + (tgtColor[i]-c)*0.08);
  const [cr,cg,cb] = curColor;

  orbAngle  = (orbAngle  + 1.4) % 360;
  orbAngle2 = (orbAngle2 + 1.0) % 360;
  orbPulse += 0.05 * orbPulseDir;
  if(orbPulse>1){orbPulseDir=-1} if(orbPulse<0){orbPulseDir=1}

  const a = orbAngle * Math.PI/180;
  const a2= orbAngle2* Math.PI/180;
  const p = orbPulse;
  const rr=cr/255,rg=cg/255,rb=cb/255;

  // outer glow
  const og = ctx.createRadialGradient(CX,CY,R*0.6,CX,CY,R*1.4);
  og.addColorStop(0,`rgba(${cr},${cg},${cb},${0.12+p*0.06})`);
  og.addColorStop(1,'rgba(0,0,0,0)');
  ctx.beginPath(); ctx.arc(CX,CY,R*1.4,0,Math.PI*2);
  ctx.fillStyle=og; ctx.fill();

  // sphere body
  const sg = ctx.createRadialGradient(CX-R*0.3,CY-R*0.3,2,CX,CY,R);
  sg.addColorStop(0,`rgba(${Math.min(255,cr+40)},${cg},${cb},0.15)`);
  sg.addColorStop(0.5,`rgba(${cr},${cg},${cb},0.08)`);
  sg.addColorStop(1,`rgba(${cr},${cg},${cb},0.25)`);
  ctx.beginPath(); ctx.arc(CX,CY,R,0,Math.PI*2);
  ctx.fillStyle=sg; ctx.fill();

  // rim glow
  for(let i=0;i<5;i++){
    ctx.beginPath(); ctx.arc(CX,CY,R-i*0.8,0,Math.PI*2);
    ctx.strokeStyle=`rgba(${cr},${cg},${cb},${(0.6-i*0.1)*(0.7+p*0.3)})`;
    ctx.lineWidth=0.8; ctx.stroke();
  }

  // orbital rings
  function ring(rx,ry,rot,speed,alpha){
    ctx.save(); ctx.translate(CX,CY); ctx.rotate(rot);
    ctx.scale(1,ry/rx);
    ctx.beginPath(); ctx.arc(0,0,rx,0,Math.PI*2);
    ctx.strokeStyle=`rgba(${cr},${cg},${cb},${alpha*(0.6+p*0.4)})`;
    ctx.lineWidth=1.2; ctx.stroke(); ctx.restore();
  }
  ring(R*0.85,R*0.25, a,  1.4, 0.6);
  ring(R*0.80,R*0.22, a2, 1.0, 0.45);
  ring(R*0.90,R*0.18, a+1.2, 0.8, 0.3);

  // core
  const cg2 = ctx.createRadialGradient(CX,CY,0,CX,CY,R*0.35);
  cg2.addColorStop(0,`rgba(255,220,200,${0.9+p*0.1})`);
  cg2.addColorStop(0.4,`rgba(${cr},${Math.min(255,cg+60)},${cb},0.7)`);
  cg2.addColorStop(1,`rgba(${cr},${cg},${cb},0)`);
  ctx.beginPath(); ctx.arc(CX,CY,R*0.35,0,Math.PI*2);
  ctx.fillStyle=cg2; ctx.fill();

  // scanline
  const scanY = CY - R + ((orbAngle/360)*R*2);
  const sl = ctx.createLinearGradient(CX-R,scanY,CX+R,scanY);
  sl.addColorStop(0,'rgba(0,0,0,0)');
  sl.addColorStop(0.5,`rgba(${cr},${cg},${cb},0.25)`);
  sl.addColorStop(1,'rgba(0,0,0,0)');
  ctx.beginPath(); ctx.ellipse(CX,scanY,R*0.95,2,0,0,Math.PI*2);
  ctx.fillStyle=sl; ctx.fill();

  // label
  ctx.fillStyle=`rgba(${cr},${cg},${cb},0.7)`;
  ctx.font='bold 9px Courier New';
  ctx.textAlign='center';
  ctx.letterSpacing='3px';
  ctx.fillText('ARCANE',CX,CY+R+16);

  requestAnimationFrame(drawOrb);
}
drawOrb();

// ── CHAT ─────────────────────────────────────────────────
function addMsg(text, type) {
  const chat = document.getElementById('chat');
  const d = document.createElement('div');
  d.className = 'msg ' + type;
  d.textContent = text;
  chat.appendChild(d);
  chat.scrollTop = chat.scrollHeight;
  return d;
}

function setCaption(t) {
  document.getElementById('caption').textContent = t || '';
}

async function send() {
  const inp = document.getElementById('inp');
  const text = inp.value.trim();
  if(!text) return;
  inp.value = '';
  addMsg(text, 'user');
  setOrbState('thinking');
  setCaption('◈ Processing...');
  document.getElementById('status').textContent = '● THINKING';

  try {
    const r = await fetch('/chat', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({message:text, session:SESSION})
    });
    const data = await r.json();

    setOrbState('speaking');
    if(data.text) addMsg(data.text, 'arcane');
    if(data.action_result && !data.action_result.startsWith('Remembered:'))
      addMsg('⚡ ' + data.action_result, 'action');
    if(data.image_b64) {
      const img = document.createElement('img');
      img.src = 'data:image/png;base64,' + data.image_b64;
      img.style.cssText = 'max-width:280px;border-radius:8px;border:1px solid #550404;margin:4px';
      const d = document.createElement('div'); d.className='msg arcane'; d.appendChild(img);
      document.getElementById('chat').appendChild(d);
    }
    if(data.audio) playAudio(data.audio);
    else setTimeout(()=>setOrbState('idle'), 2000);

    setCaption('');
    document.getElementById('status').textContent = '● ONLINE';
  } catch(e) {
    addMsg('Connection error: '+e, 'system');
    setOrbState('idle');
  }
}

function playAudio(b64) {
  const audio = new Audio('data:audio/mpeg;base64,' + b64);
  audio.onended = () => setOrbState('idle');
  audio.play().catch(()=>setOrbState('idle'));
}

// ── TABS ─────────────────────────────────────────────────
function setTab(tab) {
  document.querySelectorAll('.tab').forEach((t,i)=>{
    t.classList.toggle('active', ['chat','school','weather','memory'][i]===tab);
  });
  const chat = document.getElementById('chat');
  chat.innerHTML = '';
  if(tab==='chat') return;
  setOrbState('thinking');
  const endpoints = {school:'/school?period=today',weather:'/weather',memory:'/memory?session='+SESSION};
  fetch(endpoints[tab]).then(r=>r.json()).then(data=>{
    addMsg(data.result || 'No data.', 'action');
    setOrbState('idle');
  }).catch(()=>setOrbState('idle'));
}

// ── MIC ──────────────────────────────────────────────────
function toggleMic() {
  if(listening) { stopMic(); return; }
  if(!('webkitSpeechRecognition' in window||'SpeechRecognition' in window)) {
    addMsg('Speech recognition not supported in this browser. Use Chrome.','system'); return;
  }
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  recognition = new SR();
  recognition.lang = 'nl-NL';
  recognition.interimResults = true;
  recognition.continuous = false;
  recognition.onstart = () => { listening=true; setOrbState('listening'); document.getElementById('mic-btn').classList.add('active'); };
  recognition.onresult = e => {
    const t = Array.from(e.results).map(r=>r[0].transcript).join('');
    document.getElementById('inp').value = t;
    setCaption(t);
    if(e.results[e.results.length-1].isFinal) { stopMic(); send(); }
  };
  recognition.onerror = recognition.onend = () => { stopMic(); };
  recognition.start();
}

function stopMic() {
  listening = false;
  document.getElementById('mic-btn').classList.remove('active');
  setOrbState('idle');
  if(recognition) { try{recognition.stop()}catch(e){} recognition=null; }
}

// ── INIT ─────────────────────────────────────────────────
addMsg('◈ ARCANE online. How can I help?', 'arcane');
</script>
</body>
</html>"""

# ── ROUTES ───────────────────────────────────────────────
@app.route("/")
def index(): return Response(HTML, mimetype="text/html")

@app.route("/health")
def health(): return jsonify({"status":"ok","service":"arcane"})

@app.route("/chat", methods=["POST"])
def chat():
    data   = request.json or {}
    text, action = think(data.get("session","x"), data.get("message",""))
    result = do_action(action)
    audio  = tts(text) if text else None
    resp   = {"text":text, "action_result":result, "audio":audio}
    if result and result.startswith("IMAGE_B64:"):
        resp["image_b64"]    = result[10:]
        resp["action_result"] = "Image generated!"
    return jsonify(resp)

@app.route("/weather")
def weather(): return jsonify({"result": do_action({"action":"weather","city":"Leeuwarden"})})

@app.route("/school")
def school():
    period = request.args.get("period","today")
    return jsonify({"result": do_action({"action":f"school_{period}"})})

@app.route("/memory")
def memory():
    sid   = request.args.get("session","x")
    facts = _memory.get(sid,[])
    return jsonify({"result": "\n".join(facts) if facts else "No memories this session."})

@app.route("/news")
def news(): return jsonify({"result": do_action({"action":"news"})})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
