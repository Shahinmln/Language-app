from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Literal

import edge_tts


LanguageCode = Literal["en", "es", "ko"]


VOICE_MAP: dict[LanguageCode, str] = {
    "en": "en-US-GuyNeural",
    "es": "es-ES-ElviraNeural",
    "ko": "ko-KR-InJoonNeural",
}


async def generate_audio(text: str, output_path: str, language: LanguageCode = "en") -> str:
    """
    Generate audio using Microsoft's free edge-tts.

    Long text is split into chunks (~3500 chars) and streamed via Communicate.stream()
    into a single output file to avoid 403 / connection issues with very long payloads.
    """
    voice = VOICE_MAP.get(language, VOICE_MAP["en"])

    # Basic markdown cleanup to avoid reading formatting
    clean_text = text.replace("**", "").replace("*", "")

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    max_chars = 3500
    chunks = [clean_text[i : i + max_chars] for i in range(0, len(clean_text), max_chars)]

    with open(path, "wb") as out:
        for chunk in chunks:
            communicate = edge_tts.Communicate(chunk, voice)
            async for data in communicate.stream():
                if data["type"] == "audio":
                    out.write(data["data"])

    return str(path)


def generate_audio_sync(text: str, output_path: str, language: LanguageCode = "en") -> str:
    """
    Synchronous wrapper for environments where you cannot easily await.
    """
    return asyncio.run(generate_audio(text, output_path, language))

