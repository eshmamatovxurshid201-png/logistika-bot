from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sqlite3
import time
from pathlib import Path

from .config import Settings, load_dotenv
from .db import Database
from .domain import InputError, validate_listing


async def run(settings: Settings, db: Database):
    from aiogram import Bot
    from aiogram.types import BotCommand
    from .service import Application
    from .telegram import AiogramTransport, make_dispatcher
    from .pipeline import Pipeline

    settings.validate(require_token=True)
    bot = Bot(settings.token)
    app = Application(settings, db, AiogramTransport(bot))
    dispatcher = make_dispatcher(app)
    tasks = []
    try:
        webhook = await bot.get_webhook_info()
        if webhook.url:
            raise RuntimeError("Bu token uchun webhook yoqilgan. Avval oldingi xizmatni to‘xtatib, webhookni o‘chiring.")
        await bot.set_my_commands([
            BotCommand(command="start", description="Bosh menyu"),
            BotCommand(command="help", description="Foydalanish tartibi"),
            BotCommand(command="id", description="Telegram ID"),
            BotCommand(command="subscribe", description="Obuna"),
            BotCommand(command="davom", description="Qidiruvni davom ettirish"),
            BotCommand(command="cancel", description="Jarayonni bekor qilish"),
            BotCommand(command="terms", description="Xizmat shartlari"),
            BotCommand(command="paysupport", description="Yordam va to‘lov"),
        ])
        tasks = [asyncio.create_task(Pipeline(db, settings).run()),
                 asyncio.create_task(dispatcher.start_polling(bot, handle_as_tasks=True, tasks_concurrency_limit=64,
                                                             allowed_updates=dispatcher.resolve_used_update_types()))]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            await task
    finally:
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await bot.session.close()


def main():
    parser = argparse.ArgumentParser(description="Logistika Telegram boti")
    parser.add_argument("command", choices=["run", "check", "init-db", "seed-demo", "import", "backup",
                                           "collector-login", "collector-dialogs", "collect", "process-queue", "sources-import"])
    parser.add_argument("file", nargs="?")
    args = parser.parse_args()
    load_dotenv()
    settings = Settings.from_env()
    if args.command == "check":
        print(f"Sozlamalar to‘g‘ri. Token kiritilgan: {bool(settings.token)}. "
              f"Pullik kirish: {settings.paid_access}. To‘lov: {settings.payment_mode}. Guruh limiti: {settings.source_limit}.")
        return
    db = Database(settings.database_path)
    db.initialize()
    now = int(time.time())
    db.source_seed(settings.source_chat_ids, now, settings.source_limit)
    if args.command == "init-db":
        print("Baza tayyor.")
    elif args.command == "seed-demo":
        from .seed import seed_demo
        print(f"{seed_demo(db, now, settings.listing_ttl_days)} ta DEMO namunasi tayyor.")
    elif args.command == "import":
        if not args.file:
            parser.error("Import uchun JSON fayl yo‘lini kiriting.")
        path = Path(args.file)
        if path.stat().st_size > 2_000_000:
            parser.error("JSON 2 MB dan kichik bo‘lsin.")
        rows = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(rows, list) or len(rows) > 1000:
            parser.error("JSON ichida ko‘pi bilan 1000 e’lonli ro‘yxat bo‘lsin.")
        # Validate the whole batch before the first write.
        validated = []
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("external_key"), str) or not row["external_key"]:
                parser.error("Har bir e’lon uchun external_key matni kerak.")
            validated.append((validate_listing(row), row["external_key"]))
        for data, key in validated:
            db.save_listing(data, 0, "import:" + key, now, settings.listing_ttl_days, update=True)
        print(f"{len(rows)} ta e’lon import qilindi.")
    elif args.command == "sources-import":
        if not args.file or Path(args.file).stat().st_size > 2_000_000:
            parser.error("2 MB dan kichik guruhlar JSON faylini kiriting.")
        rows = json.loads(Path(args.file).read_text(encoding="utf-8"))
        from .domain import clean_text
        if not isinstance(rows, list) or len(rows) > settings.source_limit:
            parser.error("Guruhlar ro‘yxati SOURCE_LIMIT chegarasidan oshmasin.")
        validated = []
        for row in rows:
            if not isinstance(row, dict) or type(row.get("chat_id")) is not int or row["chat_id"] >= 0:
                parser.error("Har bir guruhda manfiy chat_id va title bo‘lsin.")
            validated.append((row["chat_id"], clean_text(row.get("title", str(row["chat_id"])), 100)))
        db.source_seed([x[0] for x in validated], now, settings.source_limit)
        for chat_id, title in validated:
            db.source_put(chat_id, title, now, settings.source_limit)
        print(f"{len(validated)} ta manba ro‘yxatga kiritildi.")
    elif args.command in {"collector-login", "collector-dialogs", "collect", "process-queue"}:
        logging.basicConfig(level=logging.WARNING)
        if args.command == "process-queue":
            from .pipeline import Pipeline
            pipeline, count = Pipeline(db, settings), 0
            while pipeline.process_one():
                count += 1
            print(f"{count} ta xabar qayta ishlandi.")
        else:
            from .collector import login, list_dialogs, run_collector
            functions = {"collector-login": lambda: login(settings), "collector-dialogs": lambda: list_dialogs(settings),
                         "collect": lambda: run_collector(settings, db)}
            asyncio.run(functions[args.command]())
    elif args.command == "backup":
        if not args.file or Path(args.file).exists():
            parser.error("Zaxira uchun mavjud bo‘lmagan yangi fayl yo‘lini kiriting.")
        target = Path(args.file)
        target.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db.path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
        print("Baza zaxirasi tayyor.")
    else:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        asyncio.run(run(settings, db))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, InputError) as exc:
        raise SystemExit(str(exc)) from None
