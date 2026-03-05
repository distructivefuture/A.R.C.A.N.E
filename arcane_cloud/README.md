# ARCANE Cloud Server

Deploy once → access from anywhere, no PC needed.

## Deploy to Railway (FREE, recommended)

1. Go to https://railway.app → sign up free
2. Click "New Project" → "Deploy from GitHub repo"
3. Upload this folder OR:
   - Install Railway CLI: `npm install -g @railway/cli`
   - Run: `railway login` then `railway up`
4. Your app is live at `https://arcane-xxx.railway.app`
5. Add to phone home screen → works like a real app!

## Deploy to Render (FREE)

1. Go to https://render.com → sign up free
2. Click "New Web Service" → connect GitHub repo
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn app:app --bind 0.0.0.0:$PORT`
5. Done!

## Environment Variables (already set in render.yaml/railway.json)
- GROQ_API_KEY
- GEMINI_API_KEY  
- ELEVENLABS_KEY
- ELEVENLABS_VOICE

## Features
- Chat with LLaMA 3.3 70B
- ElevenLabs voice responses (plays on phone!)
- School schedule (SOMtoday)
- Weather (Leeuwarden)
- Memory per session
- Image generation (Gemini Imagen 3)
- Colour orb states (red/blue/orange/yellow)
- PWA — add to home screen on iOS/Android
