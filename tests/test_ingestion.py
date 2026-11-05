import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from logistika_bot.collector import GroupCollector, make_client, run_collector
from logistika_bot.config import Settings
from logistika_bot.db import Database
from logistika_bot.domain import InputError
from logistika_bot.parser import parse_message
from logistika_bot.pipeline import Pipeline

TEXT = "Toshkent → Samarqand\nTent kerak\nYuk: qoplangan mahsulot\n20 t\nNarx: 2000000 so‘m\nTelefon: +998000000000"


class IngestionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.temp.name) / "bot.sqlite3"))
        self.db.initialize()
        self.now = 1793980800
        self.settings = Settings(database_path=self.db.path)
        self.db.source_put(-1001234, "Test group", self.now, 500)
        self.pipeline = Pipeline(self.db, self.settings, lambda: self.now)

    def tearDown(self):
        self.temp.cleanup()

    def enqueue(self, text=TEXT, mid=1, chat=-1001234, revision=None, deleted=False):
        return self.db.ingest_enqueue(chat, mid, text, f"https://t.me/c/{str(chat)[4:]}/{mid}", self.now,
                                      self.now if revision is None else revision, self.now, deleted)

    def test_known_latin_cyrillic_and_directional_suffixes(self):
        for text in [TEXT, "Ташкент - Самарканд\nТент керак\n20 т\n+998000000000",
                     "Toshkentdan Samarqandga\nTent kerak\n+998000000000"]:
            decision = parse_message(text, None, self.now, self.settings.timezone)
            self.assertEqual(decision["status"], "accepted", decision)
            self.assertEqual(decision["data"]["origin"]["city"], "Toshkent")
            self.assertEqual(decision["data"]["destinations"][0]["city"], "Samarqand")

    def test_vehicle_ad_and_ambiguous_or_spam_posts(self):
        result = parse_message("Toshkent → Moskva\nBo‘sh Tent bor\nYuk kerak\n96 m3\n+998000000000", None, self.now, self.settings.timezone)
        self.assertEqual((result["status"], result["data"]["kind"]), ("accepted", "vehicle"))
        result = parse_message("Toshkent Samarqand\nTent kerak\n+998000000000", None, self.now, self.settings.timezone)
        self.assertEqual(result["status"], "review")
        self.assertEqual(parse_message("Oddiy guruh suhbati", None, self.now, self.settings.timezone)["status"], "discarded")
        self.assertEqual(parse_message("Kazino o‘ynang yuk tent", None, self.now, self.settings.timezone)["status"], "discarded")

    def test_allowlist_and_duplicate_update(self):
        self.assertFalse(self.enqueue(chat=-1009999))
        self.assertTrue(self.enqueue())
        self.assertFalse(self.enqueue())
        self.pipeline.process_one()
        self.assertEqual(self.db.search({"kind": "cargo"}, self.now, 100)[1], 1)
        job = self.db.ingest_job("group:-1001234:1")
        self.assertEqual(job["status"], "accepted")

    def test_newer_edit_wins_and_stale_parser_result_cannot_publish(self):
        self.enqueue()
        old = self.db.next_job(self.now)
        self.enqueue(TEXT.replace("mahsulot", "yangi mahsulot"), revision=self.now + 1)
        result = self.db.ingest_finish(old["key"], old["digest"], parse_message(TEXT, old["source_url"], self.now, self.settings.timezone), self.now, 7)
        self.assertIsNone(result)
        self.assertFalse(self.enqueue(revision=self.now - 1))
        self.pipeline.process_one()
        ids, total = self.db.search({"kind": "cargo"}, self.now, 100)
        self.assertEqual(total, 1)
        self.assertIn("yangi mahsulot", self.db.listing(ids[0])["data"]["description"])

    def test_duplicate_across_500_configured_groups_is_one_listing(self):
        chats = [-1001000000 - i for i in range(500)]
        self.db.source_seed(chats[:499], self.now, 500)  # plus the source created in setUp
        with self.assertRaises(InputError):
            self.db.source_put(chats[499], "501st", self.now, 500)
        for chat in [-1001234, *chats[:499]]:
            self.enqueue(chat=chat)
        count = 0
        while self.pipeline.process_one():
            count += 1
        self.assertEqual(count, 500)
        self.assertEqual(self.db.operations_stats()["duplicates"], 499)
        self.assertEqual(self.db.search({"kind": "cargo"}, self.now, 100)[1], 1)

    def test_deletion_and_disabling_source_hide_results(self):
        self.enqueue()
        self.pipeline.process_one()
        self.enqueue("", revision=self.now + 1, deleted=True)
        self.pipeline.process_one()
        self.assertEqual(self.db.search({"kind": "cargo"}, self.now, 100)[1], 0)
        self.assertFalse(self.enqueue(revision=self.now))
        self.enqueue(mid=2)
        in_flight = self.db.next_job(self.now)
        self.db.source_toggle(-1001234, False, 1, self.now)
        result = self.db.ingest_finish(in_flight["key"], in_flight["digest"], parse_message(TEXT, in_flight["source_url"], self.now, self.settings.timezone), self.now, 7)
        self.assertIsNone(result)
        self.assertFalse(self.enqueue(mid=3))

    def test_repeated_parser_error_becomes_durable_review(self):
        self.enqueue()
        with patch("logistika_bot.pipeline.parse_message", side_effect=RuntimeError("test")):
            for i in range(5):
                self.pipeline.process_one()
                self.now += 2 ** (i + 1)
        self.assertEqual(self.db.ingest_job("group:-1001234:1")["status"], "review")

    def test_moderator_hidden_listing_is_not_reopened_by_edit(self):
        self.enqueue()
        self.pipeline.process_one()
        lid = self.db.search({"kind": "cargo"}, self.now, 100)[0][0]
        self.db.close_listing(lid, 1, admin=True)
        self.enqueue(TEXT.replace("mahsulot", "yangisi"), revision=self.now + 1)
        self.pipeline.process_one()
        self.assertEqual(self.db.listing(lid)["status"], "closed")


class CollectorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.temp.name) / "bot.sqlite3"))
        self.db.initialize()
        self.now = 1793980800
        self.settings = Settings(database_path=self.db.path, telegram_api_id=12345, telegram_api_hash="0" * 32,
                                 collector_session=str(Path(self.temp.name) / "collector"))

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def test_collector_only_records_selected_groups_without_entity_calls(self):
        self.db.source_seed([-1001234], self.now)
        collector = GroupCollector(self.db, self.settings, lambda: self.now)
        event = SimpleNamespace(chat_id=-1009999, id=1, raw_text=TEXT,
                                message=SimpleNamespace(date=datetime.fromtimestamp(self.now, timezone.utc), edit_date=None))
        await collector.receive(event)
        self.assertIsNone(self.db.next_job(self.now))
        event.chat_id = -1001234
        await collector.receive(event)
        self.assertEqual(self.db.next_job(self.now)["chat_id"], -1001234)

    async def test_actual_telethon_constructor_without_network(self):
        client = make_client(self.settings)
        await client.disconnect()

    async def test_collect_does_not_prompt_for_credentials_when_unauthorized(self):
        class Client:
            disconnected = False
            def add_event_handler(self, *args): pass
            async def connect(self): pass
            async def is_user_authorized(self): return False
            async def disconnect(self): self.disconnected = True
        client = Client()
        with patch("logistika_bot.collector.make_client", return_value=client), self.assertRaises(ValueError):
            await run_collector(self.settings, self.db)
        self.assertTrue(client.disconnected)
