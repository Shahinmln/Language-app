from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict

from dotenv import load_dotenv
from fastapi import BackgroundTasks, Body, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from pydantic import BaseModel
from supabase import Client, create_client

from services.ai_generation import AIGenerationService
from services.pro_explore_ranking import ProExploreRanking
from services.tts_generator import generate_audio
from settings import get_settings
import stripe


load_dotenv()

app = FastAPI(title="TaleTalk Backend", default_response_class=ORJSONResponse)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# These are initialized during the FastAPI startup event after configuration
# has been validated via the centralized settings module.
supabase: Client
app.state.ai_service = None  # type: ignore[attr-defined]


def _log_analytics_event(
    event_name: str,
    user_id: Optional[str] = None,
    story_id: Optional[str] = None,
    story_duration_minutes: Optional[int] = None,
    quiz_type: Optional[str] = None,
    progress_percent: Optional[float] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Best-effort fire-and-forget analytics logger.

    Intentionally low-granularity and pseudo-anonymized: we only store user_id
    (no emails), high-level event name, and coarse metadata needed for tuning
    defaults. Failures must never break user flows.
    """
    try:
        payload: Dict[str, Any] = {
            "event_name": event_name,
            "metadata": metadata or {},
        }
        if user_id:
            payload["user_id"] = user_id
        if story_id:
            payload["story_id"] = story_id
        if story_duration_minutes is not None:
            payload["story_duration_minutes"] = story_duration_minutes
        if quiz_type is not None:
            payload["quiz_type"] = quiz_type
        if progress_percent is not None:
            payload["progress_percent"] = progress_percent

        supabase.table("analytics_events").insert(payload).execute()
    except Exception as e:
        # Never raise from analytics; just log.
        print("analytics: failed to log event", event_name, e)


@app.on_event("startup")
async def on_startup() -> None:
    """
    Validate configuration and initialize external services once at startup.
    """
    settings = get_settings()

    # Initialize Supabase client using validated settings.
    global supabase
    supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)

    # Lazily initialize AI generation service so that it does not run at
    # import-time and only after configuration has been validated.
    app.state.ai_service = AIGenerationService(api_key=os.getenv("GROQ_API_KEY"))
    
    # Configure Stripe if credentials are present.
    if settings.STRIPE_SECRET_KEY:
        stripe.api_key = settings.STRIPE_SECRET_KEY


class GenerateStoryBody(BaseModel):
    """Optional request body for POST /api/generate-story. No body is valid."""

    target_words: Optional[List[str]] = None

    model_config = {"json_schema_extra": {"examples": [{"target_words": ["airport"]}]}}


@app.get("/")
def root_health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/api/stories")
async def get_stories(
    level: Optional[str] = None,
    topic: Optional[str] = None,
    language: Optional[str] = None,
    limit: int = 20,
) -> Dict[str, Any]:
    """
    Get list of stories with optional filters.
    Backed by the public.stories table.
    """
    query = supabase.table("stories").select("*").eq("visibility", "public")

    if level:
        query = query.eq("cefr_level", level)
    if topic:
        query = query.eq("topic", topic)
    if language:
        query = query.eq("target_language", language)

    response = query.order("plays_count", desc=True).limit(limit).execute()
    return {"stories": response.data or []}


@app.get("/api/stories/{story_id}")
async def get_story_by_id(story_id: str) -> Dict[str, Any]:
    """
    Get a single story by id. Returns 400 if story_id is not a valid UUID, 404 if not found.
    """
    try:
        uuid.UUID(story_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid story id")
    response = supabase.table("stories").select("*").eq("id", story_id).limit(1).execute()
    if not response.data or len(response.data) == 0:
        raise HTTPException(status_code=404, detail="Story not found")
    return {"story": response.data[0]}


@app.post("/api/stories/{story_id}/simplify")
async def simplify_story_endpoint(story_id: str) -> Dict[str, Any]:
    """
    Generate a shorter / simpler version of an existing story.

    - Uses the stored story JSON (content, transcript_json, vocabulary) as input.
    - Calls the AI service to simplify it (roughly one CEFR level down, shorter, clearer).
    - Does NOT overwrite the original story; returns the simplified version only.
    """
    try:
        uuid.UUID(story_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid story id")

    # Load the base story.
    resp = (
        supabase.table("stories")
        .select("id, title, content, transcript_json, vocabulary, cefr_level, target_language")
        .eq("id", story_id)
        .limit(1)
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=404, detail="Story not found")
    row = resp.data[0]

    level = row.get("cefr_level") or "A2"
    language = row.get("target_language") or "the target language"

    try:
        simplified = await app.state.ai_service.simplify_story(
            {
                "title": row.get("title"),
                "content": row.get("content"),
                "transcript_json": row.get("transcript_json") or [],
                "vocabulary": row.get("vocabulary") or [],
            },
            level=level,
            language=language,
        )
    except Exception as e:
        print("simplify_story_endpoint failed:", e)
        raise HTTPException(status_code=500, detail="Could not simplify story")

    return {"story": simplified}


@app.get("/api/stories/{story_id}/quiz")
async def get_story_quiz(story_id: str) -> Dict[str, Any]:
    """
    Return quiz for a story.
    - If a quiz JSON is already stored on the story row, return it.
    - Otherwise, generate a quiz from transcript_json and (best-effort) store it.
    - Critically, this must NOT fail if the `quiz` column does not exist yet
      in Supabase; in that case we still generate and return a quiz, but skip storing.
    """
    try:
        uuid.UUID(story_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid story id")

    base_columns = "id, transcript_json, cefr_level, target_language"
    full_columns = base_columns + ", quiz"

    row: Optional[Dict[str, Any]] = None
    quiz_from_db: Optional[Dict[str, Any]] = None

    # First attempt: select including quiz column.
    try:
        res = (
            supabase.table("stories")
            .select(full_columns)
            .eq("id", story_id)
            .limit(1)
            .execute()
        )
        if res.data:
            row = res.data[0]
            maybe_quiz = row.get("quiz")
            if isinstance(maybe_quiz, dict):
                quiz_from_db = maybe_quiz
    except Exception as e:
        # If the `quiz` column does not exist, fall back to selecting without it.
        print("get_story_quiz: select with quiz column failed, retrying without quiz:", e)
        try:
            res = (
                supabase.table("stories")
                .select(base_columns)
                .eq("id", story_id)
                .limit(1)
                .execute()
            )
            if res.data:
                row = res.data[0]
        except Exception as inner:
            print("get_story_quiz: select without quiz column also failed:", inner)
            raise HTTPException(status_code=500, detail="Unable to load story for quiz")

    if not row:
        raise HTTPException(status_code=404, detail="Story not found")

    # If quiz already stored, just return it.
    if quiz_from_db is not None:
        return {"quiz": quiz_from_db}

    transcript = row.get("transcript_json") or []
    level = (row.get("cefr_level") or "A1") if isinstance(row, dict) else "A1"
    language = (row.get("target_language") or "en") if isinstance(row, dict) else "en"

    if not isinstance(transcript, list):
        transcript = []

    # Generate a fresh quiz via AI (this handles its own fallbacks).
    # AI service is initialized during app startup; if it's missing, this is a
    # programming/configuration error and we surface a 500.
    ai_service: Optional[AIGenerationService] = getattr(app.state, "ai_service", None)  # type: ignore[attr-defined]
    if ai_service is None:
        raise HTTPException(status_code=500, detail="AI service is not initialized")

    try:
        quiz = await ai_service.generate_quiz(
            transcript_json=transcript,
            level=str(level),
            language=str(language),
        )
    except Exception as e:
        print("get_story_quiz: AI quiz generation failed, returning generic quiz:", e)
        # Last-resort fallback: simple static quiz structure.
        quiz = {
            "questions": [
                {
                    "type": "context",
                    "question": "What is the main idea of this story?",
                    "options": ["A", "B", "C", "D"],
                    "correct": 0,
                    "explanation": "Review the story and pick the closest summary.",
                }
            ]
        }

    # Best-effort: store quiz back onto the story row if the column exists.
    try:
        supabase.table("stories").update({"quiz": quiz}).eq("id", story_id).execute()
    except Exception as e:
        # If the `quiz` column is missing, log and continue without failing.
        print("get_story_quiz: update quiz column failed; continuing without storing:", e)

    return {"quiz": quiz}


async def _get_adaptive_target_words(
    user_id: Optional[str],
    target_language: str,
    request_target_words: List[str],
) -> List[str]:
    """
    Merge request target_words with up to 5 words from user_words (reviewing > want_to_learn > learning).
    Used for adaptive vocabulary injection in story generation.
    """
    if not user_id:
        return request_target_words
    try:
        res = (
            supabase.table("user_words")
            .select("word, status")
            .eq("user_id", user_id)
            .eq("target_language", target_language)
            .in_("status", ["reviewing", "want_to_learn", "learning"])
            .execute()
        )
    except Exception as e:
        print("Adaptive vocab fetch failed:", e)
        return request_target_words
    rows = res.data or []
    priority = {"reviewing": 0, "want_to_learn": 1, "learning": 2}
    rows.sort(key=lambda r: priority.get((r.get("status") or ""), 99))
    request_target_words = request_target_words or []
    seen = {w.lower() for w in request_target_words}
    injected: List[str] = []
    for r in rows:
        word = (r.get("word") or "").strip()
        if not word or word.lower() in seen:
            continue
        seen.add(word.lower())
        injected.append(word)
        if len(injected) >= 5:
            break
    final = request_target_words + injected
    if injected:
        print("Adaptive vocabulary injection:", injected)
    return final


async def _run_story_background_tasks(
    story_id: str,
    content: str,
    language: str,
    level: str,
    transcript_json: List[Dict[str, Any]],
    user_id: Optional[str],
) -> None:
    """
    Run TTS and quiz generation in background; update story row with audio_url and completion_rate.
    On failure: log and leave fields null. Must not raise.
    """
    audio_path = None
    quiz_data: Optional[Dict[str, Any]] = None
    try:
        audio_dir = os.getenv("AUDIO_OUTPUT_DIR", "stories")
        os.makedirs(audio_dir, exist_ok=True)
        path_str = os.path.join(audio_dir, f"{user_id or 'anon'}_{int(datetime.now().timestamp())}.mp3")
        await generate_audio(content, path_str, language=language)  # type: ignore[arg-type]
        audio_path = path_str
    except Exception as e:
        print("TTS generation failed (background):", e)
    # AI service is initialized during app startup; if it's missing, treat this
    # as a configuration error.
    ai_service: Optional[AIGenerationService] = getattr(app.state, "ai_service", None)  # type: ignore[attr-defined]
    if ai_service is None:
        print("Quiz generation skipped: AI service not initialized")
    else:
        try:
            quiz_data = await ai_service.generate_quiz(
                transcript_json=transcript_json,
                level=level,
                language=language,
            )
        except Exception as e:
            print("Quiz generation failed (background):", e)
    update: Dict[str, Any] = {}
    if audio_path is not None:
        update["audio_url"] = audio_path
    update["completion_rate"] = 0.75
    if quiz_data is not None:
        # Store quiz JSON when the column exists; if the column is missing,
        # the update below will fail and we log it without breaking the flow.
        update["quiz"] = quiz_data
    if update:
        try:
            supabase.table("stories").update(update).eq("id", story_id).execute()
        except Exception as e:
            print("Background story update failed:", e)


@app.post("/api/generate-story")
async def generate_story(
    background_tasks: BackgroundTasks,
    topic: str,
    duration: int,
    level: str,
    language: str = "en",
    user_id: Optional[str] = None,
    body: Optional[GenerateStoryBody] = Body(None),
) -> Dict[str, Any]:
    """
    Generate new story with AI; insert immediately; return story_id and story.
    TTS and quiz run in background; story row is updated with audio_url and completion_rate when done.
    """
    if not user_id:
        # For the subscription model we require a signed-in user so we can enforce
        # free vs. paid limits in a clear way.
        raise HTTPException(status_code=401, detail="Please sign in to generate stories.")

    # Enforce simple subscription limits: free users can generate up to 2 stories,
    # paid users (monthly/annual) are unlimited.
    try:
        profile_res = (
            supabase.table("profiles")
            .select("plan")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        plan = (profile_res.data[0].get("plan") if profile_res.data else "free") or "free"
    except Exception as e:
        print("generate_story: failed to load profile, assuming free plan:", e)
        plan = "free"

    if plan == "free":
        try:
            # Count how many stories this user has ever generated.
            # For a production app you might want a time-based limit instead.
            res = (
                supabase.table("stories")
                .select("id", count="exact")  # type: ignore[arg-type]
                .eq("user_id", user_id)
                .execute()
            )
            used = res.count or 0  # type: ignore[union-attr]
            if used >= 2:
                raise HTTPException(
                    status_code=403,
                    detail="Free plan is limited to 2 generated stories. Upgrade to monthly ($5) or annual ($50) for unlimited stories.",
                )
        except HTTPException:
            raise
        except Exception as e:
            # If counting fails, log but do not block generation.
            print("generate_story: failed to count user stories, skipping quota check:", e)

    raw = body.target_words if body and body.target_words else []
    if not isinstance(raw, list):
        raw = []
    request_target_words = [w.strip() for w in raw if isinstance(w, str) and w.strip()]
    target_words = await _get_adaptive_target_words(user_id, language, request_target_words)
    if target_words is None:
        target_words = []
    # AI service is initialized during app startup; if it's missing, this is a
    # configuration error and we surface a 500.
    ai_service: Optional[AIGenerationService] = getattr(app.state, "ai_service", None)  # type: ignore[attr-defined]
    if ai_service is None:
        raise HTTPException(status_code=500, detail="AI service is not initialized")

    try:
        story_data = await ai_service.generate_story_text(
            topic=topic,
            duration_minutes=duration,
            level=level,
            language=language,
            target_words=target_words,
        )

        vocab_list = story_data.get("vocabulary") or []
        insert_payload: Dict[str, Any] = {
            "user_id": user_id,
            "title": story_data.get("title") or "Untitled",
            "topic": topic,
            "target_language": language,
            "cefr_level": level,
            "duration_minutes": duration,
            "content": story_data.get("content"),
            "audio_url": None,
            "transcript_json": story_data.get("transcript_json"),
            "vocabulary": story_data.get("vocabulary"),
            "patterns": story_data.get("patterns"),
            "visibility": "public",
            "target_words": story_data.get("target_words_used") or (target_words or []),
            "word_list": [w.get("word") for w in vocab_list if isinstance(w, dict) and w.get("word")],
        }

        result = supabase.table("stories").insert(insert_payload).execute()
        story_row = result.data[0]
        story_id = story_row["id"]

        content_for_tts = story_data.get("content") or ""
        transcript_for_quiz = story_data.get("transcript_json") or []
        if not isinstance(transcript_for_quiz, list):
            transcript_for_quiz = []

        background_tasks.add_task(
            _run_story_background_tasks,
            story_id=story_id,
            content=content_for_tts,
            language=language,
            level=level,
            transcript_json=transcript_for_quiz,
            user_id=user_id,
        )

        return {
            "success": True,
            "story_id": story_id,
            "story": story_data,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/track-word")
async def track_word(
    user_id: str,
    word: str,
    action: str,
    story_id: Optional[str] = None,
    target_language: str = "en",
) -> Dict[str, Any]:
    """
    Track word interaction (clicked, learned, added) against:
      - public.user_words
      - public.word_learning_history
    """
    if action not in ("clicked", "learned", "added"):
        raise HTTPException(status_code=400, detail="Invalid action")
    try:
        existing = (
            supabase.table("user_words")
            .select("*")
            .eq("user_id", user_id)
            .eq("word", word)
            .eq("target_language", target_language)
            .execute()
        )
    except Exception as e:
        # If the user_words table or columns are missing, log and continue without failing the request.
        print("track-word: user_words select failed; skipping vocabulary update:", e)
        existing = None

    today_iso = date.today().isoformat()

    if existing and existing.data:
        current = existing.data[0]
        updates: Dict[str, Any] = {
            "times_encountered": (current.get("times_encountered") or 0) + 1,
        }
        # Only set columns that are likely to exist; extra fields like last_encountered_date / last_review_date
        # are helpful but optional in case the migration has not been applied yet.
        try:
            updates["last_encountered_date"] = today_iso
        except Exception:
            pass
        if action == "learned":
            updates["status"] = "mastered"
            try:
                updates["last_review_date"] = today_iso
            except Exception:
                pass
        elif action == "clicked":
            updates["times_clicked"] = (current.get("times_clicked") or 0) + 1

        try:
            (
                supabase.table("user_words")
                .update(updates)
                .eq("user_id", user_id)
                .eq("word", word)
                .eq("target_language", target_language)
                .execute()
            )
        except Exception as e:
            print("track-word: user_words update failed; continuing without raising:", e)
    else:
        try:
            payload: Dict[str, Any] = {
                "user_id": user_id,
                "word": word,
                "target_language": target_language,
                "status": "learning" if action == "learned" else "new",
                "times_encountered": 1,
            }
            # Optional columns
            payload["last_encountered_date"] = today_iso
            supabase.table("user_words").insert(payload).execute()
        except Exception as e:
            print("track-word: user_words insert failed; continuing without raising:", e)

    # Log into word_learning_history (omit story_id from payload when None)
    try:
        history_payload: Dict[str, Any] = {
            "user_id": user_id,
            "word": word,
            "target_language": target_language,
            "event_type": "clicked" if action == "clicked" else "encountered",
            "context_data": {"action": action},
        }
        if story_id is not None:
            history_payload["context_data"]["story_id"] = story_id
        supabase.table("word_learning_history").insert(history_payload).execute()
    except Exception as e:
        print("track-word: word_learning_history insert failed:", e)

    return {"success": True}


@app.get("/api/user-words/{user_id}")
async def get_user_words(
    user_id: str,
    status: Optional[str] = None,
    target_language: str = "en",
) -> Dict[str, Any]:
    """
    Get user's vocabulary list from public.user_words.
    """
    query = (
        supabase.table("user_words")
        .select("*")
        .eq("user_id", user_id)
        .eq("target_language", target_language)
    )
    if status:
        query = query.eq("status", status)
    response = query.order("created_at", desc=True).execute()
    return {"words": response.data or []}


@app.get("/api/stories/{story_id}/word-bank")
async def get_story_word_bank(
    story_id: str,
    user_id: str,
    target_language: str = "en",
) -> Dict[str, Any]:
    """
    Return a compact word bank for a story:
      - key words from the story's vocabulary list or word_list
      - merged with the user's current status from user_words
    """
    try:
        uuid.UUID(story_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid story id")

    # Load story vocabulary / word list.
    story_resp = (
        supabase.table("stories")
        .select("id, vocabulary, word_list")
        .eq("id", story_id)
        .limit(1)
        .execute()
    )
    if not story_resp.data:
        raise HTTPException(status_code=404, detail="Story not found")
    story_row = story_resp.data[0]

    vocab_entries = story_row.get("vocabulary") or []
    word_list = story_row.get("word_list") or []

    # Normalize into a dict keyed by word.
    words_by_key: Dict[str, Dict[str, Any]] = {}
    if isinstance(vocab_entries, list):
        for v in vocab_entries:
            w = (v.get("word") or "").strip()
            if not w:
                continue
            key = w.lower()
            if key not in words_by_key:
                words_by_key[key] = {
                    "word": w,
                    "definition": v.get("definition"),
                    "translation": v.get("translation"),
                    "example": v.get("example"),
                    "pos": v.get("pos"),
                }
    if isinstance(word_list, list):
        for w in word_list:
            if not isinstance(w, str):
                continue
            key = w.strip().lower()
            if key and key not in words_by_key:
                words_by_key[key] = {"word": w}

    # Load user's statuses for these words.
    keys = list(words_by_key.keys())
    statuses: Dict[str, str] = {}
    if keys:
        try:
            res = (
                supabase.table("user_words")
                .select("word,status")
                .eq("user_id", user_id)
                .eq("target_language", target_language)
                .in_("word", [words_by_key[k]["word"] for k in keys])
                .execute()
            )
            for row in res.data or []:
                w = (row.get("word") or "").strip().lower()
                if not w:
                    continue
                statuses[w] = row.get("status") or "new"
        except Exception as e:
            print("word-bank: failed to load user_words:", e)

    items: List[Dict[str, Any]] = []
    for key, info in words_by_key.items():
        status = statuses.get(key, "new")
        items.append(
            {
                **info,
                "status": status,
            }
        )

    # Sort by status then alphabetically to make scanning easy.
    order = {"new": 0, "want_to_learn": 1, "learning": 2, "reviewing": 3, "mastered": 4}
    items.sort(key=lambda r: (order.get(str(r.get("status")), 99), str(r.get("word") or "").lower()))

    return {"words": items}


@app.post("/api/track-interaction")
async def track_interaction(
    user_id: str,
    story_id: str,
    action: str,
    result: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Track story interaction (play, complete, like, quiz, abandon) in public.story_interactions
    and update public.stories / public.daily_progress where relevant.

    Also logs a lightweight analytics event so we can understand drop-off and
    completion patterns per story duration and topic.
    """
    try:
        supabase.table("story_interactions").insert(
            {
                "user_id": user_id,
                "story_id": story_id,
                "action": action,
                "result": result,
            }
        ).execute()
    except Exception as e:
        # If the story_interactions table or action column is missing, log and continue without failing the request.
        print("track-interaction: story_interactions insert failed; skipping interaction log:", e)

    # Best-effort analytics logging.
    try:
        # Fetch duration for this story for analytics purposes.
        story_meta = (
            supabase.table("stories")
            .select("duration_minutes")
            .eq("id", story_id)
            .limit(1)
            .execute()
        )
        duration_minutes = None
        if story_meta.data:
            duration_minutes = story_meta.data[0].get("duration_minutes")

        progress_percent = None
        if isinstance(result, dict):
            raw = result.get("progress_percent")
            try:
                if raw is not None:
                    progress_percent = float(raw)
            except (TypeError, ValueError):
                progress_percent = None

        if action == "play":
            _log_analytics_event(
                "story_started",
                user_id=user_id,
                story_id=story_id,
                story_duration_minutes=duration_minutes,
                metadata={},
            )
        elif action == "complete":
            _log_analytics_event(
                "story_completed",
                user_id=user_id,
                story_id=story_id,
                story_duration_minutes=duration_minutes,
                progress_percent=progress_percent,
                metadata={},
            )
        elif action == "abandon":
            _log_analytics_event(
                "story_abandoned",
                user_id=user_id,
                story_id=story_id,
                story_duration_minutes=duration_minutes,
                progress_percent=progress_percent,
                metadata={},
            )
    except Exception as e:
        print("analytics: track_interaction analytics failed:", e)

    if action == "play":
        # Try RPC increment_plays if you've created it; fallback to manual update.
        try:
            supabase.rpc("increment_plays", {"story_id": story_id}).execute()
        except Exception:
            story = (
                supabase.table("stories")
                .select("plays_count")
                .eq("id", story_id)
                .limit(1)
                .execute()
            )
            if story.data:
                plays = (story.data[0].get("plays_count") or 0) + 1
                supabase.table("stories").update({"plays_count": plays}).eq("id", story_id).execute()

    if action == "complete":
        today = date.today().isoformat()
        try:
            progress = (
                supabase.table("daily_progress")
                .select("*")
                .eq("user_id", user_id)
                .eq("date", today)
                .limit(1)
                .execute()
            )
            if progress.data:
                row = progress.data[0]
                supabase.table("daily_progress").update(
                    {"stories_completed": (row.get("stories_completed") or 0) + 1}
                ).eq("id", row["id"]).execute()
            else:
                supabase.table("daily_progress").insert(
                    {"user_id": user_id, "date": today, "stories_completed": 1}
                ).execute()
        except Exception as e:
            print("track-interaction: daily_progress upsert failed; continuing without raising:", e)

    return {"success": True}


@app.get("/api/explore/pro")
async def get_personalized_explore(
    user_id: str,
    limit: int = 20,
    min_score: float = 60,
    language: str = "en",
) -> Dict[str, Any]:
    """
    Get personalized story feed using ProExploreRanking and public.stories.
    """
    stories_resp = (
        supabase.table("stories")
        .select("*")
        .eq("visibility", "public")
        .eq("target_language", language)
        .order("plays_count", desc=True)
        .limit(limit * 2)
        .execute()
    )
    stories = stories_resp.data or []

    ranking = ProExploreRanking(supabase)
    scored_stories: List[Dict[str, Any]] = []

    for story in stories:
        score_data = await ranking.calculate_story_score(user_id, story["id"])
        if score_data["total_score"] >= min_score:
            enriched = {**story, **score_data}
            scored_stories.append(enriched)

    scored_stories.sort(key=lambda x: x["total_score"], reverse=True)
    return {"stories": scored_stories[:limit]}


@app.post("/api/profile")
async def upsert_profile(
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Create or update a user's profile with language preferences and about text.
    Expects:
      - user_id (uuid string)
      - native_language (string)
      - learning_languages (list of strings)
      - about (string)
    """
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")

    native_language = payload.get("native_language")
    learning_languages = payload.get("learning_languages") or []
    about = payload.get("about") or ""
    plan = payload.get("plan") or "free"
    plan_renewal_date = payload.get("plan_renewal_date")
    public_profile = bool(payload.get("public_profile")) if "public_profile" in payload else None
    display_name = payload.get("display_name") or None

    try:
        existing = (
            supabase.table("profiles")
            .select("*")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        if existing.data:
            updates: Dict[str, Any] = {
                "native_language": native_language,
                "learning_languages": learning_languages,
                "about": about,
                "plan": plan,
            }
            if plan_renewal_date is not None:
                updates["plan_renewal_date"] = plan_renewal_date
            if public_profile is not None:
                updates["public_profile"] = public_profile
            if display_name is not None:
                updates["display_name"] = display_name
            supabase.table("profiles").update(updates).eq("id", user_id).execute()
        else:
            create_payload: Dict[str, Any] = {
                "id": user_id,
                "native_language": native_language,
                "learning_languages": learning_languages,
                "about": about,
                "plan": plan,
            }
            if plan_renewal_date is not None:
                create_payload["plan_renewal_date"] = plan_renewal_date
            if public_profile is not None:
                create_payload["public_profile"] = public_profile
            if display_name:
                create_payload["display_name"] = display_name
            supabase.table("profiles").insert(create_payload).execute()
    except Exception as e:
        print("upsert_profile failed:", type(e).__name__, str(e))
        raise HTTPException(status_code=500, detail="Could not save profile")

    return {"success": True}


@app.get("/api/profile/{user_id}")
async def get_profile(user_id: str) -> Dict[str, Any]:
    """
    Return a user's profile, including subscription plan, languages and about text.
    """
    try:
        res = (
            supabase.table("profiles")
            .select("*")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        if not res.data:
            return {"profile": None}
        profile = res.data[0]

        # Compute lightweight stats on the fly.
        try:
            words_resp = (
                supabase.table("user_words")
                .select("id")
                .eq("user_id", user_id)
                .eq("status", "mastered")
                .execute()
            )
            words_learned = len(words_resp.data or [])
        except Exception as e:
            print("get_profile: failed to load words_learned:", e)
            words_learned = 0

        try:
            progress_resp = (
                supabase.table("daily_progress")
                .select("stories_completed")
                .eq("user_id", user_id)
                .execute()
            )
            stories_completed = sum(
                int(row.get("stories_completed") or 0) for row in (progress_resp.data or [])
            )
        except Exception as e:
            print("get_profile: failed to load stories_completed:", e)
            stories_completed = 0

        profile_with_stats = {
            **profile,
            "words_learned": words_learned,
            "stories_completed": stories_completed,
        }
        return {"profile": profile_with_stats}
    except Exception as e:
        print("get_profile failed:", e)
        raise HTTPException(status_code=500, detail="Could not load profile")


@app.get("/api/my-stories")
async def get_my_stories(user_id: str) -> Dict[str, Any]:
    """
    Return all stories generated by a specific user (for history view).
    """
    try:
        res = (
            supabase.table("stories")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        return {"stories": res.data or []}
    except Exception as e:
        print("get_my_stories failed:", e)
        raise HTTPException(status_code=500, detail="Could not load story history")


@app.post("/api/tests")
async def save_test_result(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Save a quiz/test result.
    Expects:
      - user_id
      - story_id
      - score
      - max_score
      - details (JSON with per-question results)
    """
    user_id = payload.get("user_id")
    story_id = payload.get("story_id")
    if not user_id or not story_id:
        raise HTTPException(status_code=400, detail="user_id and story_id are required")

    # Normalize details so each entry has clear fields for later review.
    details = payload.get("details") or []
    normalized_details: List[Dict[str, Any]] = []
    if isinstance(details, list):
        for item in details:
            if not isinstance(item, dict):
                continue
            normalized_details.append(
                {
                    # generic flags
                    "correct": bool(item.get("correct")),
                    # richer quiz info if present
                    "question": item.get("question"),
                    "user_answer": item.get("user_answer"),
                    "correct_answer": item.get("correct_answer"),
                    "target_words": item.get("target_words") or [],
                    # allow carrying through any other custom fields
                    **{k: v for k, v in item.items() if k not in {"correct", "question", "user_answer", "correct_answer", "target_words"}},
                }
            )
    else:
        normalized_details = details

    to_insert = {**payload, "details": normalized_details}

    try:
        supabase.table("tests").insert(to_insert).execute()

        # Analytics: quiz completed.
        try:
            max_score = float(payload.get("max_score") or 0)
            score = float(payload.get("score") or 0)
            ratio = score / max_score if max_score > 0 else 0.0
            # Infer question types from details, if present.
            type_counts: Dict[str, int] = {}
            for item in normalized_details:
                t = str(item.get("type") or "unknown")
                type_counts[t] = type_counts.get(t, 0) + 1

            _log_analytics_event(
                "quiz_completed",
                user_id=user_id,
                story_id=story_id,
                metadata={
                    "score_ratio": ratio,
                    "score": score,
                    "max_score": max_score,
                    "question_types": type_counts,
                    "num_questions": len(normalized_details),
                },
            )
        except Exception as inner:
            print("analytics: quiz_completed logging failed:", inner)
    except Exception as e:
        print("save_test_result failed:", e)
        raise HTTPException(status_code=500, detail="Could not save test result")

    return {"success": True}


@app.get("/api/tests/{user_id}")
async def get_test_history(user_id: str) -> Dict[str, Any]:
    """
    Return a user's test history with scores and details.
    """
    try:
        res = (
            supabase.table("tests")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        return {"tests": res.data or []}
    except Exception as e:
        print("get_test_history failed:", e)
        raise HTTPException(status_code=500, detail="Could not load tests")


@app.get("/api/dashboard-summary")
async def get_dashboard_summary(user_id: str) -> Dict[str, Any]:
    """
    Lightweight personalization summary for the Dashboard.

    Uses recent tests + story_interactions to:
      - infer strengths/weaknesses per (language, level, topic)
      - compute simple weekly goals + streaks from daily_progress
    """
    # --- Pull recent tests for this user ---
    try:
        tests_resp = (
            supabase.table("tests")
            .select("id,story_id,score,max_score,details,created_at")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(200)
            .execute()
        )
        tests = tests_resp.data or []
    except Exception as e:
        print("dashboard-summary: failed to load tests:", e)
        tests = []

    # Map stories to language/level/topic so we can interpret scores.
    story_ids = {t.get("story_id") for t in tests if t.get("story_id")}
    stories_by_id: Dict[str, Dict[str, Any]] = {}
    if story_ids:
        try:
            stories_resp = (
                supabase.table("stories")
                .select("id, topic, cefr_level, target_language")
                .in_("id", list(story_ids))
                .execute()
            )
            for row in stories_resp.data or []:
                sid = row.get("id")
                if sid:
                    stories_by_id[str(sid)] = row
        except Exception as e:
            print("dashboard-summary: failed to load stories for tests:", e)

    # Aggregate scores per (language, level, topic).
    buckets: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for t in tests:
        story_id = t.get("story_id")
        if not story_id:
            continue
        s_meta = stories_by_id.get(str(story_id))
        if not s_meta:
            continue
        lang = s_meta.get("target_language") or "unknown"
        level = s_meta.get("cefr_level") or "unknown"
        topic = s_meta.get("topic") or "general"
        key = (str(lang), str(level), str(topic))

        score = float(t.get("score") or 0.0)
        max_score = float(t.get("max_score") or 0.0)
        if max_score <= 0:
            continue

        bucket = buckets.setdefault(
            key,
            {"total_score": 0.0, "total_max": 0.0, "tests": 0},
        )
        bucket["total_score"] += score
        bucket["total_max"] += max_score
        bucket["tests"] += 1

    strengths: List[Dict[str, Any]] = []
    weaknesses: List[Dict[str, Any]] = []

    for (lang, level, topic), agg in buckets.items():
        if agg["total_max"] <= 0:
            continue
        avg = agg["total_score"] / agg["total_max"]
        record = {
            "language": lang,
            "level": level,
            "topic": topic,
            "avg_score": avg,
            "tests": agg["tests"],
        }
        # Require a minimum number of tests before making claims.
        if agg["tests"] >= 3:
            if avg >= 0.75:
                strengths.append(record)
            elif avg <= 0.6:
                weaknesses.append(record)

    # Sort by average score (descending for strengths, ascending for weaknesses).
    strengths.sort(key=lambda r: r["avg_score"], reverse=True)
    weaknesses.sort(key=lambda r: r["avg_score"])

    # --- Compute simple study goals + streaks from daily_progress ---
    today = date.today()
    seven_days_ago = today - timedelta(days=6)
    weekly_goal = 3  # "3 sessions/week" as a simple, friendly default.

    try:
        progress_resp = (
            supabase.table("daily_progress")
            .select("date,stories_completed")
            .eq("user_id", user_id)
            .order("date", desc=True)
            .limit(90)
            .execute()
        )
        progress_rows = progress_resp.data or []
    except Exception as e:
        print("dashboard-summary: failed to load daily_progress:", e)
        progress_rows = []

    # Normalize dates and build a set for quick streak checks.
    dates_with_activity = set()
    weekly_sessions = 0
    for row in progress_rows:
        raw_date = row.get("date")
        if not raw_date:
            continue
        try:
            if isinstance(raw_date, str):
                d = datetime.fromisoformat(raw_date).date()
            else:
                d = raw_date
        except Exception:
            continue

        if (row.get("stories_completed") or 0) > 0:
            dates_with_activity.add(d)
            if seven_days_ago <= d <= today:
                weekly_sessions += 1

    # Current streak: how many consecutive days up to today have activity.
    current_streak = 0
    cursor = today
    while cursor in dates_with_activity:
        current_streak += 1
        cursor = cursor - timedelta(days=1)

    # Longest streak over the fetched window.
    longest_streak = 0
    if dates_with_activity:
        sorted_days = sorted(dates_with_activity)
        streak = 1
        for prev, cur in zip(sorted_days, sorted_days[1:]):
            if cur == prev + timedelta(days=1):
                streak += 1
            else:
                longest_streak = max(longest_streak, streak)
                streak = 1
        longest_streak = max(longest_streak, streak)

    goals = {
        "weekly_goal": weekly_goal,
        "weekly_sessions": weekly_sessions,
        "weekly_goal_met": weekly_sessions >= weekly_goal,
        "current_streak_days": current_streak,
        "longest_streak_days": longest_streak,
    }

    # --- Human-friendly suggestions based on strengths/weaknesses ---
    suggestions: List[str] = []
    cefr_order = ["A1", "A2", "B1", "B2", "C1", "C2"]

    if strengths:
        best = strengths[0]
        level = best["level"]
        try:
            idx = cefr_order.index(level)
            next_level = cefr_order[min(idx + 1, len(cefr_order) - 1)]
        except ValueError:
            next_level = level
        suggestions.append(
            f"You're strong in {best['topic']} stories at {level}; let's push you into {next_level} next."
        )

    if weaknesses:
        weak = weaknesses[0]
        suggestions.append(
            f"You often miss {weak['topic']} vocabulary; try a focused unit with shorter stories and extra review."
        )

    return {
        "strengths": strengths,
        "weaknesses": weaknesses,
        "goals": goals,
        "suggestions": suggestions,
    }


def _compute_next_review(current: Optional[date], correct: bool) -> date:
  today = date.today()
  if not correct:
      return today + timedelta(days=1)
  # Simple increasing intervals: 3, 7, 14 days
  if not current or current <= today:
      return today + timedelta(days=3)
  delta = (current - today).days
  if delta < 5:
      return today + timedelta(days=7)
  return today + timedelta(days=14)


@app.get("/api/review-words")
async def get_review_words(user_id: str, target_language: str = "en", limit: int = 10) -> Dict[str, Any]:
    """
    Return a small batch of words that are due for review for a user,
    mixing truly-due items with a few recent/new items to strengthen retention.
    """
    today_iso = date.today().isoformat()
    try:
        # First: words that are due now (or overdue)
        due_res = (
            supabase.table("user_words")
            .select("*")
            .eq("user_id", user_id)
            .eq("target_language", target_language)
            .or_(f"next_review_date.lte.{today_iso},next_review_date.is.null")  # type: ignore[attr-defined]
            .order("next_review_date", desc=False)
            .execute()
        )
        due_words = due_res.data or []

        remaining = max(0, limit - len(due_words))
        extra_words: List[Dict[str, Any]] = []

        if remaining > 0:
            # Second: mix in some recent "new" / "learning" words as top-ups
            extra_res = (
                supabase.table("user_words")
                .select("*")
                .eq("user_id", user_id)
                .eq("target_language", target_language)
                .in_("status", ["new", "learning"])
                .order("created_at", desc=True)
                .limit(remaining)
                .execute()
            )
            extra_words = extra_res.data or []

        # Simple concatenation; front-end randomization not strictly necessary,
        # but can be added later.
        combined = due_words + extra_words
        return {"words": combined[:limit]}
    except Exception as e:
        print("get_review_words failed:", e)
        raise HTTPException(status_code=500, detail="Could not load review words")


@app.post("/api/review-words")
async def submit_review_results(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Update review scheduling for a batch of words and record a test summary.

    Expects:
      - user_id
      - target_language (optional, defaults to 'en')
      - items: [{ word: str, correct: bool }]
    """
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")

    target_language = payload.get("target_language") or "en"
    items = payload.get("items") or []
    if not isinstance(items, list) or not items:
        raise HTTPException(status_code=400, detail="items array is required")

    today = date.today()
    correct_count = 0
    total = 0
    details: List[Dict[str, Any]] = []

    for item in items:
        word = item.get("word")
        correct = bool(item.get("correct"))
        if not word:
            continue
        total += 1
        if correct:
            correct_count += 1
        details.append(
            {
                "type": "vocab_review",
                "word": word,
                "correct": correct,
            }
        )
        try:
            # Fetch existing row to get current next_review_date
            existing = (
                supabase.table("user_words")
                .select("next_review_date,times_encountered,status")
                .eq("user_id", user_id)
                .eq("word", word)
                .eq("target_language", target_language)
                .limit(1)
                .execute()
            )
            current_row = existing.data[0] if existing.data else {}
            current_next = current_row.get("next_review_date")
            if isinstance(current_next, str):
                try:
                    current_next_date = datetime.fromisoformat(current_next).date()
                except Exception:
                    current_next_date = None
            else:
                current_next_date = None
            next_date = _compute_next_review(current_next_date, correct)
            new_status = current_row.get("status") or "learning"
            if correct and new_status == "learning":
                new_status = "reviewing"
            elif correct and new_status == "reviewing":
                new_status = "mastered"

            supabase.table("user_words").update(
                {
                    "times_encountered": (current_row.get("times_encountered") or 0) + 1,
                    "last_review_date": today.isoformat(),
                    "next_review_date": next_date.isoformat(),
                    "status": new_status,
                }
            ).eq("user_id", user_id).eq("word", word).eq("target_language", target_language).execute()
        except Exception as e:
            print("submit_review_results: failed to update word", word, e)

    # Save a summary test row (story_id is null for generic review sessions)
    try:
        if total > 0:
            supabase.table("tests").insert(
                {
                    "user_id": user_id,
                    "story_id": None,
                    "score": correct_count,
                    "max_score": total,
                    "details": details,
                }
            ).execute()

            # Analytics: review session completed.
            try:
                ratio = correct_count / total if total > 0 else 0.0
                _log_analytics_event(
                    "review_session_completed",
                    user_id=user_id,
                    metadata={
                        "score_ratio": ratio,
                        "score": correct_count,
                        "max_score": total,
                        "num_items": total,
                    },
                )
            except Exception as inner:
                print("analytics: review_session_completed logging failed:", inner)
    except Exception as e:
        print("submit_review_results: failed to save test summary:", e)

    return {"success": True, "score": correct_count, "max_score": total}


@app.post("/api/tests/{test_id}/practice-again")
async def practice_test_again(test_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Push wrong-answer words from a specific test into immediate SRS review.

    - Reads the test's details to find items with correct == False.
    - Extracts target words for those questions.
    - For each word, upserts/updates user_words as "reviewing" with a near-term next_review_date.
    - Returns the list of affected words so the frontend can show a quick confirmation.
    """
    user_id = payload.get("user_id")
    target_language = payload.get("target_language") or "en"
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")

    try:
        res = (
            supabase.table("tests")
            .select("details,user_id,story_id")
            .eq("id", test_id)
            .limit(1)
            .execute()
        )
    except Exception as e:
        print("practice-again: failed to load test:", e)
        raise HTTPException(status_code=500, detail="Could not load test")

    if not res.data:
        raise HTTPException(status_code=404, detail="Test not found")

    row = res.data[0]
    if row.get("user_id") != user_id:
        # Simple safety check: users can only trigger practice for their own tests.
        raise HTTPException(status_code=403, detail="Forbidden")

    details = row.get("details") or []
    wrong_words: List[str] = []

    if isinstance(details, list):
        for item in details:
            if not isinstance(item, dict):
                continue
            if bool(item.get("correct")):
                continue
            target_words = item.get("target_words") or []
            if isinstance(target_words, list):
                for w in target_words:
                    if isinstance(w, str):
                        w_clean = w.strip()
                        if w_clean and w_clean not in wrong_words:
                            wrong_words.append(w_clean)

    if not wrong_words:
        return {"success": True, "words": []}

    today = date.today().isoformat()
    soon = (date.today() + timedelta(days=1)).isoformat()

    # Upsert/update each wrong word into user_words as reviewing, due soon.
    for w in wrong_words:
        try:
            existing = (
                supabase.table("user_words")
                .select("id,status")
                .eq("user_id", user_id)
                .eq("word", w)
                .eq("target_language", target_language)
                .limit(1)
                .execute()
            )
            if existing.data:
                row0 = existing.data[0]
                supabase.table("user_words").update(
                    {
                        "status": "reviewing",
                        "next_review_date": today,
                    }
                ).eq("id", row0.get("id")).execute()
            else:
                supabase.table("user_words").insert(
                    {
                        "user_id": user_id,
                        "word": w,
                        "target_language": target_language,
                        "status": "reviewing",
                        "next_review_date": today,
                    }
                ).execute()
        except Exception as e:
            print("practice-again: failed to upsert word", w, e)

    return {"success": True, "words": wrong_words}


@app.get("/api/leaderboard/weekly")
async def get_weekly_leaderboard(limit: int = 10) -> Dict[str, Any]:
    """
    Return an anonymized weekly leaderboard for users who have opted in.

    - Only includes profiles with public_profile = true.
    - Weekly XP is based on number of stories completed in the last 7 days.
    - Weekly sessions is the number of days with at least one completed story.
    """
    seven_days_ago = date.today() - timedelta(days=6)

    try:
        profiles_resp = (
            supabase.table("profiles")
            .select("id,display_name,public_profile")
            .eq("public_profile", True)
            .execute()
        )
    except Exception as e:
        print("leaderboard: failed to load profiles:", e)
        return {"entries": []}

    profiles = profiles_resp.data or []
    if not profiles:
        return {"entries": []}

    user_ids = [p["id"] for p in profiles if p.get("id")]

    try:
        progress_resp = (
            supabase.table("daily_progress")
            .select("user_id,date,stories_completed")
            .in_("user_id", user_ids)
            .gte("date", seven_days_ago.isoformat())
            .execute()
        )
        progress_rows = progress_resp.data or []
    except Exception as e:
        print("leaderboard: failed to load progress:", e)
        progress_rows = []

    # Aggregate XP and sessions per user.
    stats: Dict[str, Dict[str, Any]] = {}
    for row in progress_rows:
        uid = row.get("user_id")
        if not uid:
            continue
        uid_str = str(uid)
        user_stats = stats.setdefault(uid_str, {"xp": 0, "sessions_days": set()})
        stories_completed = int(row.get("stories_completed") or 0)
        user_stats["xp"] += stories_completed  # simple 1 XP per story
        try:
            d_raw = row.get("date")
            if isinstance(d_raw, str):
                d = datetime.fromisoformat(d_raw).date()
            else:
                d = d_raw
            if stories_completed > 0 and d is not None:
                user_stats["sessions_days"].add(d)
        except Exception:
            continue

    entries: List[Dict[str, Any]] = []
    for p in profiles:
        uid = str(p.get("id"))
        s = stats.get(uid) or {"xp": 0, "sessions_days": set()}
        xp = int(s.get("xp") or 0)
        sessions = len(s.get("sessions_days") or [])
        # Anonymized display name: use display_name when present, otherwise a generic label.
        raw_name = (p.get("display_name") or "").strip()
        if raw_name:
            name = raw_name
        else:
            suffix = uid.replace("-", "")[-4:]
            name = f"Learner #{suffix}"
        entries.append(
            {
                "name": name,
                "weekly_xp": xp,
                "weekly_sessions": sessions,
            }
        )

    entries.sort(key=lambda e: (e["weekly_xp"], e["weekly_sessions"]), reverse=True)

    return {"entries": entries[:limit]}


@app.get("/api/analytics/summary")
async def get_analytics_summary() -> Dict[str, Any]:
    """
    High-level analytics used to help tune:
      - default story duration
      - quiz difficulty
      - review session length

    This endpoint is meant for internal dashboards or admin tools rather than
    direct end-user display.
    """
    # Story completion vs abandonment by duration
    try:
        story_events = (
            supabase.table("analytics_events")
            .select("event_name,story_duration_minutes")
            .in_("event_name", ["story_started", "story_completed", "story_abandoned"])
            .order("created_at", desc=True)
            .limit(2000)
            .execute()
        )
        story_rows = story_events.data or []
    except Exception as e:
        print("analytics: failed to load story events:", e)
        story_rows = []

    duration_stats: Dict[int, Dict[str, int]] = {}
    for row in story_rows:
        dur = row.get("story_duration_minutes")
        if not isinstance(dur, int):
            continue
        bucket = duration_stats.setdefault(dur, {"started": 0, "completed": 0, "abandoned": 0})
        name = row.get("event_name")
        if name == "story_started":
            bucket["started"] += 1
        elif name == "story_completed":
            bucket["completed"] += 1
        elif name == "story_abandoned":
            bucket["abandoned"] += 1

    # Choose a recommended default duration: duration with highest completion / started ratio.
    recommended_duration = None
    best_ratio = -1.0
    for dur, s in duration_stats.items():
        started = s["started"] or (s["completed"] + s["abandoned"])
        if started <= 0:
            continue
        ratio = s["completed"] / started
        if ratio > best_ratio:
            best_ratio = ratio
            recommended_duration = dur

    # Quiz difficulty: look at score distributions from quiz_completed events.
    try:
        quiz_events = (
            supabase.table("analytics_events")
            .select("metadata")
            .eq("event_name", "quiz_completed")
            .order("created_at", desc=True)
            .limit(1000)
            .execute()
        )
        quiz_rows = quiz_events.data or []
    except Exception as e:
        print("analytics: failed to load quiz events:", e)
        quiz_rows = []

    ratios: List[float] = []
    for row in quiz_rows:
        meta = row.get("metadata") or {}
        try:
            r = float(meta.get("score_ratio") or 0.0)
            ratios.append(r)
        except (TypeError, ValueError):
            continue

    avg_quiz_ratio = sum(ratios) / len(ratios) if ratios else 0.0
    if avg_quiz_ratio >= 0.85:
        quiz_recommendation = "harder"
    elif avg_quiz_ratio <= 0.6:
        quiz_recommendation = "easier"
    else:
        quiz_recommendation = "about_right"

    # Review session length: from review_session_completed events.
    try:
        review_events = (
            supabase.table("analytics_events")
            .select("metadata")
            .eq("event_name", "review_session_completed")
            .order("created_at", desc=True)
            .limit(1000)
            .execute()
        )
        review_rows = review_events.data or []
    except Exception as e:
        print("analytics: failed to load review events:", e)
        review_rows = []

    lengths: List[int] = []
    for row in review_rows:
        meta = row.get("metadata") or {}
        try:
            n = int(meta.get("num_items") or 0)
            if n > 0:
                lengths.append(n)
        except (TypeError, ValueError):
            continue

    avg_session_length = int(round(sum(lengths) / len(lengths))) if lengths else 10

    return {
        "story_duration": {
            "per_duration": duration_stats,
            "recommended_default_minutes": recommended_duration,
        },
        "quiz_difficulty": {
            "average_score_ratio": avg_quiz_ratio,
            "recommendation": quiz_recommendation,
        },
        "review_session": {
            "average_items": avg_session_length,
        },
    }


@app.post("/api/billing/checkout")
async def create_checkout_session(payload: Dict[str, Any], request: Request) -> Dict[str, Any]:
    """
    Create a Stripe Checkout session for monthly or annual subscription.

    Expects:
      - user_id (string)
      - plan: "monthly" | "annual"

    Returns:
      - checkout_url: string (Stripe-hosted URL to redirect the user to)
    """
    settings = get_settings()
    if not settings.STRIPE_SECRET_KEY or not settings.STRIPE_PRICE_MONTHLY or not settings.STRIPE_PRICE_ANNUAL:
        raise HTTPException(
            status_code=500,
            detail="Stripe is not configured. Set STRIPE_SECRET_KEY, STRIPE_PRICE_MONTHLY, and STRIPE_PRICE_ANNUAL.",
        )

    user_id = payload.get("user_id")
    plan = payload.get("plan")
    if not user_id or plan not in ("monthly", "annual"):
        raise HTTPException(status_code=400, detail="user_id and valid plan are required")

    price_id = settings.STRIPE_PRICE_MONTHLY if plan == "monthly" else settings.STRIPE_PRICE_ANNUAL

    origin = request.headers.get("origin") or "http://localhost:5173"
    success_url = f"{origin}/dashboard?billing=success"
    cancel_url = f"{origin}/dashboard?billing=cancel"

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            client_reference_id=user_id,
        )
    except Exception as e:
        print("create_checkout_session failed:", e)
        raise HTTPException(status_code=500, detail="Unable to create checkout session")

    return {"checkout_url": session.url}


@app.post("/api/billing/webhook")
async def stripe_webhook(request: Request) -> ORJSONResponse:
    """
    Handle Stripe webhooks to keep subscription status in sync.

    Updates the user's plan and plan_renewal_date in public.profiles based on subscription events.
    """
    settings = get_settings()
    if not settings.STRIPE_WEBHOOK_SECRET:
        return ORJSONResponse({"received": True})

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        print("stripe_webhook: signature verification failed:", e)
        raise HTTPException(status_code=400, detail="Invalid payload")

    event_type = event.get("type")
    data = event.get("data", {}).get("object", {})

    def _plan_from_price_id(price_id: str | None) -> Optional[str]:
        if not price_id:
            return None
        if price_id == settings.STRIPE_PRICE_MONTHLY:
            return "monthly"
        if price_id == settings.STRIPE_PRICE_ANNUAL:
            return "annual"
        return None

    try:
        if event_type in ("customer.subscription.created", "customer.subscription.updated"):
            subscription = data
            client_ref = subscription.get("client_reference_id")
            items = subscription.get("items", {}).get("data", [])
            price = items[0]["price"]["id"] if items else None
            plan = _plan_from_price_id(price)
            current_period_end = subscription.get("current_period_end")
            renewal_date: Optional[date] = None
            if isinstance(current_period_end, int):
                renewal_date = datetime.utcfromtimestamp(current_period_end).date()

            if client_ref and plan:
                supabase.table("profiles").update(
                    {
                        "plan": plan,
                        "plan_renewal_date": renewal_date.isoformat() if renewal_date else None,
                    }
                ).eq("id", client_ref).execute()
        elif event_type == "checkout.session.completed":
            session = data
            client_ref = session.get("client_reference_id")
            subscription_id = session.get("subscription")
            if client_ref and subscription_id:
                sub = stripe.Subscription.retrieve(subscription_id)
                items = sub.get("items", {}).get("data", [])
                price = items[0]["price"]["id"] if items else None
                plan = _plan_from_price_id(price)
                current_period_end = sub.get("current_period_end")
                renewal_date: Optional[date] = None
                if isinstance(current_period_end, int):
                    renewal_date = datetime.utcfromtimestamp(current_period_end).date()
                if plan:
                    supabase.table("profiles").update(
                        {
                            "plan": plan,
                            "plan_renewal_date": renewal_date.isoformat() if renewal_date else None,
                        }
                    ).eq("id", client_ref).execute()
    except Exception as e:
        print("stripe_webhook handler failed:", e)

    return ORJSONResponse({"received": True})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=True)

