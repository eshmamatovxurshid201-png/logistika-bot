import copy
import io
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from logistika_bot import ui
from logistika_bot.config import Settings
from logistika_bot.db import Database
from logistika_bot.domain import InputError, place
from logistika_bot.matching import rank_pair
from logistika_bot.parser import parse_message
from logistika_bot.pipeline import Pipeline
from logistika_bot.semantic import OpenAIExtractor, SemanticAssistant, verify_proposal
from logistika_bot.service import Application
from tests.helpers import FakeAPI, sample

TEXT = "Toshkent Samarqand\nTent kerak\nYuk: ko‘mir\n20 t\nTelefon: +998000000000"


def proposal():
    return {"kind": "cargo", "origin_text": "Toshkent", "destination_text": "Samarqand",
            "intent_quote": "Tent kerak", "route_quote": "Toshkent Samarqand", "vehicle_quote": "Tent",
            "vehicles": ["tent"], "cargo_text": "ko‘mir", "capacity_text": "20 t", "price_text": "",
            "ready_date_text": "", "uncertainties": ["Yo‘nalishni admin tasdiqlasin"]}


class Extractor:
    def __init__(self, result=None, fail=False):
        self.inputs, self.result, self.fail = [], result or proposal(), fail
    def extract(self, text):
        self.inputs.append(text)
        if self.fail:
            raise TimeoutError()
        return copy.deepcopy(self.result)


class SemanticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.temp.name) / "test.sqlite3"))
        self.db.initialize()
        self.now = 1793980800
        self.settings = Settings(ai_enabled=True, openai_api_key="test-only", ai_model="test-model", ai_daily_limit=1)
        self.job = {"raw_text": TEXT, "published_at": self.now, "source_url": "https://t.me/example/1"}
        self.decision = parse_message(TEXT, self.job["source_url"], self.now, "Asia/Tashkent")

    def tearDown(self):
        self.temp.cleanup()

    def test_disabled_ai_makes_zero_requests(self):
        extractor = Extractor(fail=True)
        assistant = SemanticAssistant(self.db, replace(self.settings, ai_enabled=False), extractor)
        self.assertEqual(assistant.enrich(self.job, self.decision, self.now), self.decision)
        self.assertEqual(extractor.inputs, [])

    def test_ai_proposal_remains_in_review_and_phone_stays_local(self):
        extractor = Extractor()
        assistant = SemanticAssistant(self.db, self.settings, extractor)
        result = assistant.enrich(self.job, self.decision, self.now)
        self.assertEqual(result["status"], "review")
        self.assertEqual(result["data"]["phone"], "+998000000000")
        self.assertNotIn("+998000000000", extractor.inputs[0])
        self.assertEqual(result["data"]["extraction_method"], "ai_proposal")
        summary = ui.extraction_summary(result["data"])
        self.assertIn("Taklif qilingan maydonlar", summary)
        self.assertIn("Jo‘nash: Toshkent", summary)
        self.assertIn("AI noaniqligi", summary)

    def test_same_redacted_text_uses_cache_with_current_contact(self):
        extractor = Extractor()
        assistant = SemanticAssistant(self.db, self.settings, extractor)
        assistant.enrich(self.job, self.decision, self.now)
        other = dict(self.job, raw_text=TEXT.replace("000000000", "000000001"))
        result = assistant.enrich(other, self.decision, self.now)
        self.assertEqual(len(extractor.inputs), 1)
        self.assertEqual(result["data"]["phone"], "+998000000001")

    def test_daily_limit_and_error_do_not_publish_or_retry_unbounded(self):
        extractor = Extractor(fail=True)
        assistant = SemanticAssistant(self.db, self.settings, extractor)
        self.assertEqual(assistant.enrich(self.job, self.decision, self.now)["status"], "review")
        assistant.enrich(self.job, self.decision, self.now)
        assistant.enrich(dict(self.job, raw_text=TEXT + "\nYangi matn"), self.decision, self.now)
        self.assertEqual(len(extractor.inputs), 1)

    def test_hallucinated_location_number_vehicle_or_extra_action_is_rejected(self):
        for key, value in [("origin_text", "Moskva"), ("capacity_text", "100 t"), ("vehicles", ["kamaz"]),
                           ("kind", "vehicle"), ("price_text", "90000000 so‘m")]:
            with self.subTest(key=key), self.assertRaises(InputError):
                verify_proposal(dict(proposal(), **{key: value}), self.job, "Asia/Tashkent")
        with self.assertRaises(InputError):
            verify_proposal(dict(proposal(), action="approve_payment"), self.job, "Asia/Tashkent")

    def test_busy_cache_defers_job_without_publishing(self):
        self.db.source_seed([-1001234], self.now)
        self.db.ingest_enqueue(-1001234, 1, TEXT, self.job["source_url"], self.now, self.now, self.now)
        class Busy:
            def enrich(self, *args): return None
        Pipeline(self.db, self.settings, lambda: self.now, Busy()).process_one()
        self.assertIsNone(self.db.next_job(self.now))
        self.assertEqual(self.db.search({"kind": "cargo"}, self.now, 100)[1], 0)

    def test_responses_request_uses_strict_schema_and_handles_refusal(self):
        captured = []
        def opener(request, timeout):
            captured.append(json.loads(request.data))
            return io.BytesIO(json.dumps({"status": "completed", "output": [{"type": "message", "content": [
                {"type": "output_text", "text": json.dumps(proposal())}]}]}).encode())
        result = OpenAIExtractor(self.settings, opener).extract("REDACTED DATA")
        self.assertEqual(result["kind"], "cargo")
        self.assertFalse(captured[0]["store"])
        self.assertTrue(captured[0]["text"]["format"]["strict"])
        self.assertNotIn("tools", captured[0])
        def refused(*args, **kwargs):
            return io.BytesIO(b'{"status":"completed","output":[{"type":"message","content":[{"type":"refusal"}]}]}')
        with self.assertRaises(InputError):
            OpenAIExtractor(self.settings, refused).extract("data")

    def test_negation_multiple_ads_and_russian_intents(self):
        cases = [
            ("Ташкент → Самарканд\nНужен тент\n+998000000000", "accepted", "cargo"),
            ("Ташкент → Самарканд\nПустой тент, нужен груз\n+998000000000", "accepted", "vehicle"),
            ("Toshkent → Samarqand\nYuk yo‘q, tent kerak emas\n+998000000000", "review", None),
            ("Toshkent → Samarqand\nBuxoro → Farg‘ona\nTent kerak\n+998000000000", "review", None),
        ]
        for text, status, kind in cases:
            with self.subTest(text=text):
                result = parse_message(text, self.job["source_url"], self.now, "Asia/Tashkent")
                self.assertEqual(result["status"], status)
                if kind:
                    self.assertEqual(result["data"]["kind"], kind)


class MatchTests(unittest.TestCase):
    def pair(self, **changes):
        cargo = {"data": sample(capacity="20 t", ready_date="2026-11-08")}
        truck = {"data": sample(kind="vehicle", capacity="25 t", phone="+998000000001", ready_date="2026-11-07", **changes)}
        return cargo, truck

    def test_matching_route_capacity_and_dates(self):
        a, b = self.pair()
        self.assertEqual(rank_pair(a, b)["score"], 100)
        self.assertIsNone(rank_pair(a, {"data": dict(b["data"], capacity="10 t")}))
        self.assertIsNone(rank_pair(a, {"data": dict(b["data"], ready_date="2026-11-09")}))
        self.assertIsNone(rank_pair(a, {"data": dict(b["data"], origin=place("Samarqand"), destinations=[place("Toshkent")])}))
        self.assertIsNone(rank_pair(a, {"data": dict(b["data"], phone=a["data"]["phone"])}))

    def test_unknown_capacity_is_not_claimed_as_verified(self):
        a, b = self.pair()
        result = rank_pair(a, {"data": dict(b["data"], capacity="—", ready_date="")})
        self.assertLess(result["score"], 100)
        self.assertIn("Tonnajni aniqlashtiring", result["reasons"])


class DispatcherTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.temp.name) / "test.sqlite3"))
        self.db.initialize()
        self.now = 1793980800
        self.settings = Settings(database_path=self.db.path, paid_access=False)
        self.api = FakeAPI()
        self.app = Application(self.settings, self.db, self.api, lambda: self.now)
        self.db.user(2, self.now)
        self.lid = self.db.save_listing(sample(capacity="20 t"), 99, "cargo", self.now, 7)

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def cb(self, data, message_id, uid=2):
        await self.app.handle("callback_query", {"id": "cb", "from": {"id": uid}, "data": data,
            "message": {"message_id": message_id, "chat": {"id": uid, "type": "private"}}})

    async def source_card(self):
        await self.app.results(2, {"kind": "cargo"})
        data = self.api.buttons("detail:")[0]["callback_data"]
        _, sid, lid = data.split(":")
        return data, self.db.card(sid, int(lid))["message_id"]

    async def test_private_favorites_idempotency_and_removal(self):
        callback, mid = await self.source_card()
        await self.cb(callback.replace("detail:", "save:"), mid)
        await self.cb(callback.replace("detail:", "save:"), mid)
        self.assertEqual(self.db.favorites(2, self.now), [self.lid])
        self.assertEqual(self.db.favorites(3, self.now), [])
        await self.app.show_favorites(2)
        self.assertTrue(self.api.buttons("unsave:"))
        await self.cb(callback.replace("detail:", "unsave:"), mid)
        self.assertEqual(self.db.favorites(2, self.now), [])

    async def test_find_matching_vehicle_and_subscription_guard(self):
        truck_id = self.db.save_listing(sample(kind="vehicle", phone="+998000000001", capacity="30 t"), 98, "truck", self.now, 7)
        callback, mid = await self.source_card()
        await self.cb(callback.replace("detail:", "match:"), mid)
        self.assertIn("Moslik balli", self.api.text())
        self.assertEqual(self.db.matching(self.lid, self.now)[0]["id"], truck_id)
        self.app.settings = replace(self.settings, paid_access=True)
        self.api.calls.clear()
        await self.cb(callback.replace("detail:", "save:"), mid)
        await self.cb(callback.replace("detail:", "match:"), mid)
        await self.app.show_favorites(2)
        self.assertFalse(self.api.buttons("detail:"))
        self.assertEqual(self.db.favorites(2, self.now), [])
