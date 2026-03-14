# TaleTalk

Language learning app: explore stories, generate AI stories, read/listen, track vocabulary, personalized recommendations.

## Run locally

### Backend
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
set SUPABASE_URL=...
set SUPABASE_KEY=...
set GROQ_API_KEY=...

# Development
uvicorn main:app --reload --port 8000

# Production (Gunicorn + UvicornWorker)
gunicorn --bind=0.0.0.0:5000 --reuse-port -k uvicorn.workers.UvicornWorker main:app
```
API (dev): http://localhost:8000  
Swagger (dev): http://localhost:8000/docs

### Frontend
```bash
cd frontend
npm install
cp .env.example .env   # set VITE_API_URL=http://localhost:8000 if needed
npm run dev
```
App: http://localhost:5173

## Flows to test
- **Explore** — list stories, filters, "Generate a story" link.
- **Generate** — form (topic, duration, level, language, optional target words) → redirect to reader.
- **Story reader** — title, metadata, content, audio (or "No audio"), click words → tooltip, track clicked/learned.
- **Vocabulary** — list tracked words (demo user: `demo-user`).
- **Personalized** — on Explore, set User ID to see explore/pro feed (fallback to stories if empty).
