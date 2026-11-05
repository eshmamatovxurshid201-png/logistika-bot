"""One authorized MTProto session; receive updates only from an explicit allowlist."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path

from .pipeline import Pipeline

log = logging.getLogger(__name__)


def make_client(settings):
    from telethon import TelegramClient
    settings.validate_collector()
    Path(settings.collector_session).parent.mkdir(parents=True, exist_ok=True)
    return TelegramClient(settings.collector_session, settings.telegram_api_id, settings.telegram_api_hash,
                          sequential_updates=True, catch_up=True, auto_reconnect=True, flood_sleep_threshold=60)


class GroupCollector:
    def __init__(self, db, settings, clock=time.time):
        self.db, self.settings, self.clock = db, settings, clock
        self.allowed: set[int] = set()
        self.refreshed_at = -1000.0

    async def allowed_chat(self, chat_id: int | None) -> bool:
        if time.monotonic() - self.refreshed_at > 30:
            self.allowed = await asyncio.to_thread(self.db.enabled_sources)
            self.refreshed_at = time.monotonic()
        return chat_id in self.allowed

    async def receive(self, event):
        chat_id = event.chat_id
        if not await self.allowed_chat(chat_id):
            return
        text = event.raw_text or ""
        if not text:
            return
        # ID-based message links avoid per-message entity/history requests.
        link = f"https://t.me/c/{str(chat_id)[4:]}/{event.id}" if str(chat_id).startswith("-100") else None
        published_at = int(event.message.date.timestamp())
        revision = int((event.message.edit_date or event.message.date).timestamp())
        await asyncio.to_thread(self.db.ingest_enqueue, chat_id, event.id, text, link,
                                published_at, revision, int(self.clock()))

    async def deleted(self, event):
        chat_id = event.chat_id
        if not await self.allowed_chat(chat_id):
            return
        now = int(self.clock())
        for message_id in event.deleted_ids:
            old = await asyncio.to_thread(self.db.ingest_job, f"group:{chat_id}:{message_id}")
            await asyncio.to_thread(self.db.ingest_enqueue, chat_id, message_id, "", None,
                                    old["published_at"] if old else now, now, now, True)


async def login(settings):
    client = make_client(settings)
    try:
        # This command is explicitly run interactively by the account owner.
        await client.start()
        path = Path(settings.collector_session + ".session")
        if path.exists() and os.name != "nt":
            path.chmod(0o600)
        print("Yig‘uvchi akkaunt sessiyasi tayyor. Guruhlar ro‘yxatini sozlab collect buyrug‘ini ishlating.")
    finally:
        await client.disconnect()


async def list_dialogs(settings):
    client = make_client(settings)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            raise ValueError("Avval collector-login buyrug‘ini o‘z terminalingizda bajaring.")
        groups = []
        async for dialog in client.iter_dialogs():
            if dialog.is_group or dialog.is_channel:
                groups.append({"chat_id": dialog.id, "title": dialog.name})
        print(json.dumps(groups, ensure_ascii=False, indent=2))
    finally:
        await client.disconnect()


async def run_collector(settings, db):
    from telethon import events
    client = make_client(settings)
    collector = GroupCollector(db, settings)
    tasks = []
    try:
        client.add_event_handler(collector.receive, events.NewMessage())
        client.add_event_handler(collector.receive, events.MessageEdited())
        client.add_event_handler(collector.deleted, events.MessageDeleted())
        await client.connect()
        if not await client.is_user_authorized():
            raise ValueError("Sessiya yo‘q. Avval collector-login buyrug‘ini bajaring.")
        await client.catch_up()
        tasks = [asyncio.create_task(client.run_until_disconnected()),
                 asyncio.create_task(Pipeline(db, settings).run())]
        log.info("Collector started with %s configured sources", len(await asyncio.to_thread(db.enabled_sources)))
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            await task
    finally:
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await client.disconnect()
