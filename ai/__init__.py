"""
ai/__init__.py — AI module exports
Wraps Groq AI functions as async-compatible for handlers.
"""

import asyncio
from ai.groq_ai import chat as _chat_sync, get_financial_advice as _advice_sync, is_configured
from ai.image_gen import generate_image, upscale_image


async def chat(user_id: int, message: str) -> tuple[str | None, str | None]:
    """Async wrapper for Groq chat."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _chat_sync, user_id, message)


async def get_financial_advice(user_id: int, summary: str, language: str = "km") -> tuple[str | None, str | None]:
    """Async wrapper for Groq financial advice."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _advice_sync, user_id, summary, language)


__all__ = ["chat", "get_financial_advice", "generate_image", "upscale_image", "is_configured"]
