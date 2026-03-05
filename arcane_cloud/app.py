"""
ARCANE Cloud Server
Deploys to Railway / Render / Fly.io — runs 24/7, no PC needed.
"""
import os, json, base64, requests, re, datetime
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__, static_folder="static")

# ── Config from environment variables ─────────────────────────
GROQ_API_KEY    = os.environ.get("GROQ_API_KEY",    "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")
GEMINI_API_KEY  = os.environ.get("GEMINI_API_KEY",  "AIzaSyBS3OKamOSz8sWT5DmUmMjT-4P8ZGpbCZA")
ELEVENLABS_KEY  = os.environ.get("ELEVENLABS_KEY",  "sk_2366c420fdd5cc5126322b6c073919fb7a3288073ec40754")
ELEVENLABS_VOICE= os.environ.get("ELEVENLABS_VOICE","ZT9u07TYPVl83ejeLakq")
SOMTODAY_URL    = os.environ.get("SOMTODAY_URL",
    "https://api.somtoday.nl/rest/v1/icalendar/stream/16edafe9-0fe3-42cc-8582-e62243b01d5a/10e0526e-0852-4016-b761-49b4ec3504a1")

# In-memory conversation history per session
_histories = {}
_memory    = {}

SYSTEM = """You are Arcane — Adaptive Runtime Computing & Autonomous Neural Engine.
You are an intelligent AI assistant. Speak concisely, confidently, and with a calm futuristic tone like F.R.I.D.A.Y.
Keep responses SHORT — 2-3 sentences max unless more detail is needed.
Always respond in the same language as the user (Dutch→Dutch, English→English).

For actions include a JSON block at the END of your message:
Web search:      {"action":"search","query":"terms"}
Weather:         {"action":"weather","city":"name"}
School today:    {"action":"school_today"}
School tomorrow: {"action":"school_tomorrow"}
School week:     {"action":"school_week"}
Remember:        {"action":"remember","fact":"text"}
Generate image:  {"action":"generate_image","prompt":"description"}
"""

# ── Brain ──────────────────────────────────────────────────────
def think(session_id, message):
    hist = _histories.get(session_id, [])
    mem  = _memory.get(session_id, [])
    mem_txt = "\n".join(mem[-10:]) if mem else ""
    sys_prompt = SYSTEM + (f"\n\nMemory about user:\n{mem_txt}" if mem_txt else "")

    hist.append({"role":"user","content":message})
    if len(hist) > 30: hist = hist[-30:]

    msgs = [{"role":"system","content":sys_prompt}] + hist
    headers = {"Authorization":f"Bearer {GROQ_API_KEY}","Content-Type":"application/json"}
    try:
        resp = requests.post("https://api.groq.com/openai/v1/chat/completions",
            json={"model":"llama-3.3-70b-versatile","messages":msgs,
                  "max_tokens":512,"temperature":0.7},
            headers=headers, timeout=30)
        data  = resp.json()
        reply = data["choices"][0]["message"]["content"]
        hist.append({"role":"assistant","content":reply})
        _histories[session_id] = hist

        # extract action
        action = None
        m = re.search(r'\{[^{}]*"action"[^{}]*\}', reply, re.DOTALL)
        if m:
            try: action = json.loads(m.group())
            except: pass
        # handle remember
        if action and action.get("action")=="remember":
            facts = _memory.get(session_id,[])
            facts.append(action.get("fact",""))
            _memory[session_id] = facts

        clean = re.sub(r'\{[^{}]*"action"[^{}]*\}','',reply,flags=re.DOTALL).strip()
        return clean, action
    except Exception as e:
        return f"Error: {e}", None

# ── Skills ─────────────────────────────────────────────────────
def do_action(action):
    if not action: return None
    t = action.get("action","")

    if t == "weather":
        city = action.get("city","Leeuwarden")
        try:
            geo = requests.get(
                f"https://geocoding-api.open-meteo.com/v1/search?name={requests.utils.quote(city)}&count=1",
                timeout=8).json()
            if not geo.get("results"): return f"City not found: {city}"
            loc = geo["results"][0]
            wx = requests.get(
                f"https://api.open-meteo.com/v1/forecast"
                f"?latitude={loc['latitude']}&longitude={loc['longitude']}"
                f"&current=temperature_2m,apparent_temperature,weathercode,windspeed_10m,relativehumidity_2m"
                f"&timezone=auto", timeout=8).json()
            cur = wx.get("current",{})
            cond = {0:"Clear",1:"Clear",2:"Partly cloudy",3:"Overcast",45:"Fog",
                    61:"Rain",63:"Rain",65:"Heavy rain",71:"Snow",80:"Showers",95:"Thunderstorm"}
            code = cur.get("weathercode",0)
            return (f"🌡️ {loc['name']}: {cond.get(code,str(code))}, "
                    f"{cur.get('temperature_2m','?')}°C "
                    f"(feels {cur.get('apparent_temperature','?')}°C), "
                    f"💨 {cur.get('windspeed_10m','?')} km/h, "
                    f"💧 {cur.get('relativehumidity_2m','?')}%")
        except Exception as e: return f"Weather error: {e}"

    elif t in ("school_today","school_tomorrow","school_week"):
        try:
            resp = requests.get(SOMTODAY_URL, timeout=10)
            lines = resp.text.split("\n")
            events = []
            ev = {}
            for line in lines:
                line = line.strip()
                if line == "BEGIN:VEVENT": ev = {}
                elif line == "END:VEVENT" and ev:
                    events.append(ev)
                    ev = {}
                elif line.startswith("DTSTART"): ev["start"] = line.split(":",1)[-1]
                elif line.startswith("DTEND"):   ev["end"]   = line.split(":",1)[-1]
                elif line.startswith("SUMMARY"): ev["title"] = line.split(":",1)[-1]
                elif line.startswith("LOCATION"):ev["loc"]   = line.split(":",1)[-1]

            now  = datetime.datetime.now()
            def parse(s):
                s = s.replace("Z","")
                for fmt in ["%Y%m%dT%H%M%S","%Y%m%d"]:
                    try: return datetime.datetime.strptime(s,fmt)
                    except: pass
                return None

            filtered = []
            for ev in events:
                start = parse(ev.get("start",""))
                if not start: continue
                if t=="school_today" and start.date()==now.date(): filtered.append((start,ev))
                elif t=="school_tomorrow" and start.date()==(now+datetime.timedelta(1)).date(): filtered.append((start,ev))
                elif t=="school_week":
                    days = (start.date()-now.date()).days
                    if 0 <= days <= 7: filtered.append((start,ev))

            filtered.sort(key=lambda x:x[0])
            if not filtered: return "No classes found."
            lines2 = []
            for start,ev in filtered:
                lines2.append(f"📚 {start.strftime('%a %H:%M')} — {ev.get('title','?')}"
                              + (f" ({ev['loc']})" if ev.get('loc') else ""))
            return "\n".join(lines2)
        except Exception as e: return f"School error: {e}"

    elif t == "search":
        query = action.get("query","")
        try:
            r = requests.get("https://api.duckduckgo.com/",
                params={"q":query,"format":"json","no_html":1},timeout=8).json()
            if r.get("AbstractText"): return r["AbstractText"][:400]
            topics = r.get("RelatedTopics",[])
            if topics and isinstance(topics[0],dict):
                return topics[0].get("Text","No results found.")[:300]
            return f"No results for: {query}"
        except: return f"Search failed for: {query}"

    elif t == "generate_image":
        prompt = action.get("prompt","")
        try:
            url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
                   f"imagen-3.0-generate-002:predict?key={GEMINI_API_KEY}")
            resp = requests.post(url,
                json={"instances":[{"prompt":prompt}],
                      "parameters":{"sampleCount":1,"aspectRatio":"1:1"}},
                timeout=60)
            if resp.status_code==200:
                b64 = resp.json()["predictions"][0]["bytesBase64Encoded"]
                return f"IMAGE_B64:{b64}"
            return "Image generation failed."
        except Exception as e: return f"Image error: {e}"

    return None

# ── ElevenLabs TTS ─────────────────────────────────────────────
def text_to_speech(text):
    try:
        url  = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE}"
        headers = {
            "xi-api-key": ELEVENLABS_KEY,
            "Content-Type": "application/json"
        }
        payload = {
            "text": text,
            "model_id": "eleven_turbo_v2",
            "voice_settings": {"stability":0.5,"similarity_boost":0.8,"style":0.3}
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=20)
        if resp.status_code == 200:
            return base64.b64encode(resp.content).decode()
    except Exception: pass
    return None

# ── Routes ─────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/chat", methods=["POST"])
def chat():
    data    = request.json
    message = data.get("message","")
    sid     = data.get("session","default")

    text, action = think(sid, message)
    result       = do_action(action)

    # generate speech via ElevenLabs
    audio_b64 = text_to_speech(text) if text else None

    resp = {"text": text, "action_result": result, "audio": audio_b64}
    if result and result.startswith("IMAGE_B64:"):
        resp["image_b64"]   = result[10:]
        resp["action_result"] = "Image generated!"
    return jsonify(resp)

@app.route("/weather")
def weather():
    result = do_action({"action":"weather","city":"Leeuwarden"})
    return jsonify({"result": result})

@app.route("/school")
def school():
    period = request.args.get("period","today")
    result = do_action({"action":f"school_{period}"})
    return jsonify({"result": result})

@app.route("/memory")
def memory():
    sid  = request.args.get("session","default")
    facts = _memory.get(sid,[])
    return jsonify({"result": "\n".join(facts) if facts else "No memories yet."})

@app.route("/remember", methods=["POST"])
def remember():
    data = request.json
    sid  = data.get("session","default")
    fact = data.get("fact","")
    facts = _memory.get(sid,[])
    facts.append(fact)
    _memory[sid] = facts
    return jsonify({"ok":True})

@app.route("/health")
def health():
    return jsonify({"status":"online","name":"ARCANE"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
