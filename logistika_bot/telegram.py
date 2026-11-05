from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher, Router
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.methods import (AnswerCallbackQuery, AnswerPreCheckoutQuery,
                             EditMessageText, SendContact, SendInvoice, SendMessage)

METHODS = {x.__api_method__: x for x in [SendMessage, EditMessageText, SendContact,
                                      SendInvoice, AnswerCallbackQuery, AnswerPreCheckoutQuery]}


class AiogramTransport:
    def __init__(self, bot: Bot):
        self.bot = bot

    async def call(self, method: str, **params):
        request = METHODS[method].model_validate(params)
        for attempt in range(3):
            try:
                result = await self.bot(request)
                return result.model_dump(mode="json", by_alias=True, exclude_none=True) if hasattr(result, "model_dump") else result
            except TelegramRetryAfter as exc:
                if attempt == 2 or exc.retry_after > 30:
                    raise
                await asyncio.sleep(exc.retry_after)
            except TelegramBadRequest as exc:
                if "message is not modified" in exc.message.lower():
                    return True
                raise


def make_dispatcher(app) -> Dispatcher:
    router = Router()

    def make_handler(kind: str):
        async def handler(event):
            data = event.model_dump(mode="python", by_alias=True, exclude_none=True)
            for field in ["date", "edit_date"]:
                if hasattr(data.get(field), "timestamp"):
                    data[field] = int(data[field].timestamp())
            try:
                await app.handle(kind, data)
            except Exception as exc:
                # No tokens, raw updates, contacts or payment payloads in logs.
                logging.getLogger(__name__).error("Handler failed: %s", type(exc).__name__)
                uid = data.get("from", {}).get("id")
                chat = data.get("chat") or data.get("message", {}).get("chat", {})
                if uid and chat.get("type") == "private" and chat.get("id") == uid:
                    try:
                        await app.send(uid, "So‘rovni yakunlashda xatolik bo‘ldi. Natijalar uchun /davom, "
                                            "to‘lov bo‘yicha /paysupport yozing.")
                    except Exception:
                        pass
        return handler

    for kind in ["message", "callback_query", "pre_checkout_query", "channel_post", "edited_channel_post"]:
        getattr(router, kind).register(make_handler(kind))
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    return dispatcher
