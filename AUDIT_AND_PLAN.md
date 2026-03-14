# StoryPod AI — Audit and Implementation Plan

## PHASE 1 — AUDIT SUMMARY

### 1. Backend folder structure
```
backend/
├── main.py                 # FastAPI app, all 7 endpoints
├── requirements.txt        # fastapi, uvicorn, dotenv, supabase, orjson, anyio, groq, edge-tts
├── migrations/
│   └── 001_init.sql       # profiles + stories tables; optional alter for word_list, target_words
└── services/
    ├── ai_generation.py   # Groq story + quiz generation; quiz JSON repair + fallback
    ├── tts_generator.py    # Edge-TTS chunked streaming (3500 chars)
    └── pro_explore_ranking.py  # Personalized story scoring (linguistic + marketing)
```
No `__init__.py` in services (Python still loads it when run from backend root).

### 2. Frontend folder structure
**No frontend exists.** No `package.json`, `index.html`, `.tsx`, or Vite/React app under project root. Frontend must be created from scratch.

### 3. Current routes / pages / components
- **Backend routes only.** All 7 endpoints live in `main.py`:
  - `GET /health`
  - `GET /api/stories` (query: level, topic, language, limit)
  - `POST /api/generate-story` (query: topic, duration, level, language, user_id; body: optional `{ target_words }`)
  - `POST /api/track-word` (user_id, word, action, story_id?, target_language)
  - `GET /api/user-words/{user_id}` (query: status?, target_language)
  - `POST /api/track-interaction` (user_id, story_id, action, result?)
  - `GET /api/explore/pro` (user_id, limit?, min_score?, language?)
- **No frontend routes or pages yet.**

### 4. Current API client usage
- None. No frontend and no shared API client.

### 5. Supabase-related backend schema assumptions
- **Tables used by backend:**
  - `public.profiles` — FK for stories.user_id; ProExplore reads it.
  - `public.stories` — canonical columns in 001_init.sql; insert payload matches.
  - `public.user_words` — track-word, get user-words, ProExplore.
  - `public.word_learning_history` — track-word inserts events.
  - `public.story_interactions` — track-interaction inserts; play/completion updates stories + daily_progress.
  - `public.daily_progress` — track-interaction (complete) upserts.
  - `public.user_interests` — ProExplore only.
- **Migration 001_init.sql** only creates `profiles` and `stories` (and optional alters for word_list, target_words). Tables `user_words`, `word_learning_history`, `story_interactions`, `daily_progress`, `user_interests` are **not** created in this file; they are assumed to exist (manually or elsewhere). **Do not drop or rename these.**

### 6. What is already working
- Backend runs (FastAPI + Supabase client + env vars).
- `/api/generate-story`: TTS failure → audio_url null; quiz parse failure → fallback quiz; optional body with `target_words`.
- Stories insert payload matches 001_init `stories` columns.
- Swagger: POST generate-story has optional body model `{ "target_words": ["airport"] }`.
- CORS allows localhost:3000, 5173, 127.0.0.1:5173.

### 7. What is missing
- **Frontend:** no app, no pages, no API client.
- **Explore page** — list stories, filters, generate entry, optional personalized feed.
- **Generate story page** — form (topic, duration, level, language, target_words), submit, loading, redirect to reader.
- **Story reader page** — title, metadata, content/transcript, audio (or fallback if null), word click → tooltip, track clicked/learned.
- **User vocabulary page** — list user words, filter by status.
- **Personalized explore** — call explore/pro when user_id present; fallback to stories.
- **Single API client** — base URL, getStories, generateStory, trackWord, getUserWords, trackInteraction, explorePro; loading/empty/error/success states.
- **Resilience** — null audio_url, malformed transcript/vocabulary, empty explore/pro, no duplicate submit, defensive types.

---

## IMPLEMENTATION PLAN

- **Step 1:** Phase 2 — Stabilize backend (verify insert payload vs schema; add brief comments for TTS/quiz fragility; no behavior change).
- **Step 2:** Create frontend scaffold (Vite + React + TypeScript, one API client, env for API URL).
- **Step 3:** Explore page (fetch stories, filters, cards, “Generate story” entry; optional explore/pro when user_id set).
- **Step 4:** Generate-story page (form, submit, loading, redirect to reader with new story_id).
- **Step 5:** Story reader page (content/transcript, audio or fallback, word tooltip, track clicked/learned).
- **Step 6:** User vocabulary page (user-words list, optional status filter).
- **Step 7:** Wire explore/pro and fallback; ensure loading/empty/error states everywhere.
- **Step 8:** UX resilience (null audio, bad transcript/vocabulary, no duplicate submit, defensive types); quick verification flows.

---

## FILE-BY-FILE CHANGES (this session)

### Phase 2 — Backend (minimal)
- **backend/main.py**: Added docstring note that TTS/quiz failures are non-fatal; clarified comment that insert keys must match 001_init.sql. No logic changes.

### Phase 3–5 — Frontend (new)
- **frontend/package.json**: New. React 18, react-router-dom 6, Vite 5, TypeScript 5.
- **frontend/vite.config.ts**, **tsconfig.json**, **index.html**: New. Vite + React + TS setup.
- **frontend/src/main.tsx**: New. React root + BrowserRouter.
- **frontend/src/index.css**: New. CSS variables (dark theme, blue/teal), base styles.
- **frontend/src/App.tsx**: New. Nav (Explore, Generate, Vocabulary) + Routes.
- **frontend/src/api/client.ts**: New. Single API layer: BASE from VITE_API_URL; getStories, generateStory, trackWord, getUserWords, trackInteraction, explorePro. Types for Story, params, body.
- **frontend/src/pages/Explore.tsx**: New. Fetches stories (or explorePro when user_id set); fallback to getStories if explore/pro empty; filters level/language; link to Generate; list of story cards with link to Reader (state passed).
- **frontend/src/pages/GenerateStory.tsx**: New. Form topic, duration, level, language, optional target words; submit → generateStory; loading + error; on success navigate to /story/:id with state { story, storyId }.
- **frontend/src/pages/StoryReader.tsx**: New. Load story from state or fetch getStories and find by id; skip fetch when state has storyId; title, metadata, audio (or “No audio”), content/transcript; clickable words → WordTooltip (definition, translation, example, pos); Track clicked / I know it → trackWord; trackInteraction(play) on mount.
- **frontend/src/pages/Vocabulary.tsx**: New. getUserWords(demo-user); status filter; list words.
- **frontend/.env.example**: New. VITE_API_URL.
- **frontend/src/vite-env.d.ts**: New. ImportMetaEnv for VITE_API_URL.
- **README.md**: New. How to run backend and frontend; flows to test.

---

## HOW TO RUN LOCALLY

1. **Backend**  
   `cd backend` → activate venv → `pip install -r requirements.txt` → set SUPABASE_URL, SUPABASE_KEY, GROQ_API_KEY → `uvicorn main:app --reload --port 8000`.

2. **Frontend**  
   `cd frontend` → `npm install` → optional `cp .env.example .env` and set VITE_API_URL → `npm run dev`. Open http://localhost:5173.

---

## WHAT TO TEST NEXT

- **Flow A**: Open app → Explore → stories load (or “No stories yet”).
- **Flow B**: Generate a story → success → redirect to reader; new story visible in feed after refresh.
- **Flow C**: Open story → read content; if audio exists play it; if not, “No audio” shown.
- **Flow D**: Click word → tooltip → Track clicked / I know it → Vocabulary page shows word (user demo-user).
- **Flow E**: On Explore, set User ID → personalized feed or fallback to stories.

---

## REMAINING ISSUES / NOTES

- **No auth**: All track calls use `demo-user`. Backend accepts any user_id string.
- **Single story fetch**: Direct open of /story/:id with no state triggers getStories(100) and find by id; if the story is not in the first 100, it won’t be found. Passing state from Explore/Generate avoids this.
- **Backend**: No GET /api/stories/:id; do not add unless required later.
- **Migration**: 001_init.sql only ensures profiles + stories; user_words, word_learning_history, story_interactions, daily_progress, user_interests must exist in Supabase (do not drop).
