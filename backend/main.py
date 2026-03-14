from __future__ import annotations

import os
import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import BackgroundTasks, Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from pydantic import BaseModel
from supabase import Client, create_client

from services.ai_generation import AIGenerationService
from services.pro_explore_ranking import ProExploreRanking
from services.tts_generator import generate_audio


load_dotenv()

app = FastAPI(title="StoryPod AI Backend", default_response_class=ORJSONResponse)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set in environment")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
ai_service = AIGenerationService()


class GenerateStoryBody(BaseModel):
    """Optional request body for POST /api/generate-story. No body is valid."""

    target_words: Optional[List[str]] = None

    model_config = {"json_schema_extra": {"examples": [{"target_words": ["airport"]}]}}


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
    try:
        audio_dir = os.getenv("AUDIO_OUTPUT_DIR", "stories")
        os.makedirs(audio_dir, exist_ok=True)
        path_str = os.path.join(audio_dir, f"{user_id or 'anon'}_{int(datetime.now().timestamp())}.mp3")
        await generate_audio(content, path_str, language=language)  # type: ignore[arg-type]
        audio_path = path_str
    except Exception as e:
        print("TTS generation failed (background):", e)
    try:
        await ai_service.generate_quiz(
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
    raw = body.target_words if body and body.target_words else []
    if not isinstance(raw, list):
        raw = []
    request_target_words = [w.strip() for w in raw if isinstance(w, str) and w.strip()]
    target_words = await _get_adaptive_target_words(user_id, language, request_target_words)
    if target_words is None:
        target_words = []
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
    existing = (
        supabase.table("user_words")
        .select("*")
        .eq("user_id", user_id)
        .eq("word", word)
        .eq("target_language", target_language)
        .execute()
    )

    today_iso = date.today().isoformat()

    if existing.data:
        current = existing.data[0]
        updates: Dict[str, Any] = {
            "times_encountered": (current.get("times_encountered") or 0) + 1,
            "last_encountered_date": today_iso,
        }
        if action == "learned":
            updates["status"] = "mastered"
            updates["last_review_date"] = today_iso
        elif action == "clicked":
            updates["times_clicked"] = (current.get("times_clicked") or 0) + 1

        (
            supabase.table("user_words")
            .update(updates)
            .eq("user_id", user_id)
            .eq("word", word)
            .eq("target_language", target_language)
            .execute()
        )
    else:
        supabase.table("user_words").insert(
            {
                "user_id": user_id,
                "word": word,
                "target_language": target_language,
                "status": "learning" if action == "learned" else "new",
                "times_encountered": 1,
                "last_encountered_date": today_iso,
            }
        ).execute()

    # Log into word_learning_history (omit story_id from payload when None)
    history_payload: Dict[str, Any] = {
        "user_id": user_id,
        "word": word,
        "target_language": target_language,
        "event_type": "clicked" if action == "clicked" else "encountered",
        "context_data": {"action": action},
    }
    if story_id is not None:
        history_payload["context_data"]["story_id"] = story_id
    try:
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


@app.post("/api/track-interaction")
async def track_interaction(
    user_id: str,
    story_id: str,
    action: str,
    result: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Track story interaction (play, complete, like, quiz) in public.story_interactions
    and update public.stories / public.daily_progress where relevant.
    """
    supabase.table("story_interactions").insert(
        {
            "user_id": user_id,
            "story_id": story_id,
            "action": action,
            "result": result,
        }
    ).execute()

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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=True)

