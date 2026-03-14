from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

from groq import Groq


STORY_GENERATION_PROMPT = """
You are a professional language learning content creator. Write a story in {language} at CEFR level {level}.

REQUIREMENTS:
1. Length: Exactly {word_count} words (±5%). Count carefully.
2. Topic: {topic}
3. Include these target words naturally: {target_words}
4. For Korean A1/A2: Include Romanization for EVERY sentence:
   "Annyeonghaseyo (안녕하세요) - Hello"
5. Sentence structure: Simple for A1/A2, complex for C1.
6. Include cultural context where appropriate.
7. End with a moral or reflection.

OUTPUT FORMAT (JSON):
{{
  "title": "...",
  "content": "...",
  "transcript_json": [
    {{"sentence": "...", "romanization": "...", "translation": "...", "words": [{{"text": "...", "pos": "..."}}]}}
  ],
  "vocabulary": [
    {{"word": "...", "definition": "...", "translation": "...", "example": "...", "pos": "..."}}
  ],
  "target_words_used": ["..."],
  "cef_level_verified": "..."
}}
IMPORTANT: Verify word count before outputting. If not {word_count} words, regenerate.
"""


QUIZ_GENERATION_PROMPT = """
Analyze this transcript in {language} (Level {level}). Generate exactly 3 quiz questions:

1. CONTEXT INFERENCE: Why did the character use [specific word]? (Multiple choice, 4 options)
2. CLOZE TEST: Remove a key word/particle from a sentence. (Fill blank, 4 options)
3. SHADOWING TARGET: Select one full sentence for pronunciation practice.

For Korean A1/A2: ALL options MUST include Romanization.
Example: "Gamsahamnida (감사합니다)" not just "감사합니다"

OUTPUT FORMAT (JSON):
{{
  "questions": [
    {{"type": "context", "question": "...", "options": ["A", "B", "C", "D"], "correct": 0, "explanation": "..."}},
    {{"type": "cloze", "question": "...", "options": ["A", "B", "C", "D"], "correct": 0, "explanation": "..."}},
    {{"type": "shadowing", "sentence": "...", "romanization": "...", "difficulty": "medium"}}
  ]
}}
"""


def _extract_json_substring(text: str) -> str:
    """Extract the first {...} substring from response text."""
    start = text.find("{")
    if start == -1:
        return "{}"
    end = text.rfind("}") + 1
    return text[start:end] if end > start else "{}"


def _repair_quiz_json(raw: str) -> str:
    """Apply common repairs to malformed quiz JSON from LLM output."""
    s = raw.strip()
    if not s.startswith("{"):
        s = "{" + s
    if not s.endswith("}"):
        s = s + "}"
    s = s.replace("options=[", '"options": [')
    s = s.replace("= [", ": [")
    s = s.replace("= {", ": {")
    s = re.sub(r",\s*]", "]", s)
    s = re.sub(r",\s*}", "}", s)
    return s


def _fallback_quiz() -> Dict[str, Any]:
    """Return a generic quiz so the endpoint never fails on parse errors."""
    return {
        "questions": [
            {
                "type": "context",
                "question": "What did you understand from the story?",
                "options": ["A", "B", "C", "D"],
                "correct": 0,
                "explanation": "Review the story again.",
            },
            {
                "type": "cloze",
                "question": "Choose the best word to complete the sentence.",
                "options": ["A", "B", "C", "D"],
                "correct": 0,
                "explanation": "Check the transcript.",
            },
            {
                "type": "shadowing",
                "sentence": "Repeat the sentence after listening.",
                "romanization": "",
                "difficulty": "medium",
            },
        ]
    }


class AIGenerationService:
    """
    Thin wrapper around Groq's Chat Completion API for stories and quizzes.
    """

    def __init__(self, client: Optional[Groq] = None, model: str = "llama-3.3-70b-versatile") -> None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key and not client:
            raise RuntimeError("GROQ_API_KEY is required for AI generation")
        self.client = client or Groq(api_key=api_key)
        self.model = model

    async def generate_story_text(
        self,
        topic: str,
        duration_minutes: int,
        level: str,
        language: str,
        target_words: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        # Rough heuristic: 130 wpm listening speed
        word_count = max(80, int(duration_minutes * 130))
        target_words = target_words or []

        prompt = STORY_GENERATION_PROMPT.format(
            language=language,
            level=level,
            word_count=word_count,
            topic=topic,
            target_words=", ".join(target_words) if isinstance(target_words, list) and target_words else "[]",
        )

        completion = self.client.chat.completions.create(
            model=self.model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "You are a precise language-learning content generator."},
                {"role": "user", "content": prompt},
            ],
        )

        content = completion.choices[0].message.content

        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            # best-effort: extract JSON substring
            start = content.find("{")
            end = content.rfind("}") + 1
            data = json.loads(content[start:end])

        return data

    async def generate_quiz(
        self,
        transcript_json: List[Dict[str, Any]],
        level: str,
        language: str,
    ) -> Dict[str, Any]:
        prompt = QUIZ_GENERATION_PROMPT.format(language=language, level=level)
        transcript_text = json.dumps(transcript_json, ensure_ascii=False)

        completion = self.client.chat.completions.create(
            model=self.model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "You generate high-quality quizzes for language learners."},
                {
                    "role": "user",
                    "content": f"{prompt}\n\nTRANSCRIPT JSON:\n{transcript_text}",
                },
            ],
        )

        content = completion.choices[0].message.content
        json_str = _extract_json_substring(content)
        try:
            data = json.loads(json_str)
            if isinstance(data, dict) and "questions" in data:
                return data
        except json.JSONDecodeError:
            pass
        try:
            repaired = _repair_quiz_json(json_str)
            data = json.loads(repaired)
            if isinstance(data, dict) and "questions" in data:
                return data
        except json.JSONDecodeError:
            pass
        return _fallback_quiz()

