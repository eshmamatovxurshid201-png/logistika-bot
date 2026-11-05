import asyncio
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from logistika_bot import ui
from logistika_bot.config import Settings
from logistika_bot.db import Database
from logistika_bot.service import Application
from tests.helpers import FakeAPI, sample


class ApplicationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.now = 1793894400
        self.db = Database(str(Path(self.temp.name) / "test.sqlite3"))
        self.db.initialize()
        self.db.user(2, self.now)
        self.api = FakeAPI()
        self.settings = Settings(database_path=self.db.path, paid_access=False, admin_ids=frozenset({1}))
        self.app = Application(self.settings, self.db, self.api, clock=lambda: self.now)

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def msg(self, text="", uid=2, **extra):
        await self.app.handle("message", {"message_id": 1, "from": {"id": uid},
                              "chat": {"id": uid, "type": "private"}, "text": text, **extra})

    async def cb(self, data, message_id=100, uid=2):
        await self.app.handle("callback_query", {"id": "cb", "from": {"id": uid}, "data": data,
                              "message": {"message_id": message_id, "chat": {"id": uid, "type": "private"}}})

    def add(self, key="one", **changes):
        return self.db.save_listing(sample(**changes), 99, key, self.now, 7)

    async def search(self):
        await self.msg("/start")
        await self.msg(ui.QUICK)
        await self.msg(ui.CARGO)
        await self.msg("Tent")
        await self.msg("Ташкент Самарканд")

    def card(self, index=0):
        callback = self.api.buttons("detail:")[index]["callback_data"]
        _, sid, lid = callback.split(":")
        stored = self.db.card(sid, int(lid))
        return callback, stored

    async def test_search_detail_phone_source_and_back(self):
        self.add(source_url="https://t.me/example/123", raw_text="Angren\nSamarqand\nTent kerak")
        await self.search()
        callback, card = self.card()
        await self.cb(callback, card["message_id"])
        self.assertIn("Tent kerak", self.api.calls[-1][1]["text"])
        self.assertIn("👀 1", self.api.calls[-1][1]["text"])
        await self.cb(callback.replace("detail:", "phone:"), card["message_id"])
        contacts = [p for m, p in self.api.calls if m == "sendContact"]
        self.assertEqual(contacts[0]["phone_number"], "+998000000000")
        await self.cb(callback.replace("detail:", "source:"), card["message_id"])
        self.assertEqual(self.api.calls[-1][1]["reply_markup"]["inline_keyboard"][0][0]["url"], "https://t.me/example/123")
        await self.cb(callback.replace("detail:", "brief:"), card["message_id"])
        self.assertNotIn("Tent kerak", self.api.calls[-1][1]["text"])
        self.assertEqual(self.db.user(2, self.now)["vehicle"], "tent")

    async def test_paid_gate_covers_detail_phone_and_source_even_old_buttons(self):
        self.add(source_url="https://t.me/example/123", raw_text="PRIVATE CONTACT TEXT")
        await self.search()
        callback, card = self.card()
        self.app.settings = replace(self.settings, paid_access=True)
        self.api.calls.clear()
        for action in ["detail", "phone", "source"]:
            await self.cb(callback.replace("detail:", action + ":"), card["message_id"])
        self.assertNotIn("PRIVATE CONTACT TEXT", self.api.text())
        self.assertFalse(any(m == "sendContact" for m, _ in self.api.calls))
        self.assertFalse(any(b.get("url") for _, p in self.api.calls for row in p.get("reply_markup", {}).get("inline_keyboard", []) for b in row))
        self.db.grant(2, 1, self.now)
        await self.cb(callback, card["message_id"])
        self.assertIn("PRIVATE CONTACT TEXT", self.api.calls[-1][1]["text"])
        self.db.revoke(2)
        self.api.calls.clear()
        await self.cb(callback.replace("detail:", "phone:"), card["message_id"])
        self.assertFalse(any(m == "sendContact" for m, _ in self.api.calls))

    async def test_session_cannot_be_used_by_another_user_or_message(self):
        self.add(raw_text="PRIVATE")
        await self.search()
        callback, card = self.card()
        self.api.calls.clear()
        await self.cb(callback, card["message_id"], uid=3)
        await self.cb(callback, card["message_id"] + 999)
        self.assertNotIn("PRIVATE", self.api.text())

    async def test_pagination_has_stable_snapshot_and_repeated_click_is_safe(self):
        for i in range(12):
            self.add(str(i))
        await self.search()
        first = self.api.buttons("detail:")
        self.assertEqual(len(first), 5)
        next_button = self.api.buttons("more:")[-1]["callback_data"]
        self.add("new-after-snapshot")
        await self.cb(next_button)
        self.assertEqual(len(self.api.buttons("detail:")), 10)
        await self.cb(next_button)
        self.assertEqual(len(self.api.buttons("detail:")), 10)
        await self.cb(self.api.buttons("more:")[-1]["callback_data"])
        ids = [b["callback_data"].split(":")[-1] for b in self.api.buttons("detail:")]
        self.assertEqual(len(ids), 12)
        self.assertEqual(len(set(ids)), 12)

    async def test_interrupted_page_can_resume_without_resending_saved_cards(self):
        for i in range(7):
            self.add(str(i))
        # The header and two cards succeed; the third card's send fails.
        self.api.fail_send_at = self.api.send_count + 4
        with self.assertRaises(RuntimeError):
            await self.app.results(2, {"kind": "cargo", "vehicle": "tent"})
        self.assertEqual(len(self.api.buttons("detail:")), 2)
        self.api.fail_send_at = None
        await self.msg("/davom")
        self.assertEqual(len(self.api.buttons("detail:")), 5)
        self.assertEqual(len({b["callback_data"] for b in self.api.buttons("detail:")}), 5)

    async def test_geo_navigation_filters_origin(self):
        lid = self.add(kind="vehicle")
        await self.msg(ui.VEHICLE)
        country = self.api.buttons("geo:")[-1]["callback_data"]
        await self.cb(country)
        city = self.api.buttons("geo:")[-1]["callback_data"]
        await self.cb(city)
        self.assertEqual(int(self.api.buttons("detail:")[-1]["callback_data"].split(":")[-1]), lid)

    async def test_posting_survives_restart_and_double_publish_does_not_duplicate(self):
        await self.msg(ui.ADD)
        await self.msg("📦 Yuk e’loni")
        await self.cb("draft:tent")
        await self.cb("draft:ref")
        await self.cb("draft:next")
        for text in ["Toshkent", "Samarqand; Buxoro", "Qadoqlangan mahsulot", "20 t", "Bugun", "Kelishiladi"]:
            await self.msg(text)
        self.app = Application(self.settings, Database(self.db.path), self.api, clock=lambda: self.now)
        await self.msg("+998000000000")
        publish = self.api.buttons("publish:")[-1]["callback_data"]
        await self.cb(publish)
        await self.cb(publish)
        listings = self.db.mine(2, self.now)
        self.assertEqual(len(listings), 1)
        self.assertEqual(listings[0]["data"]["vehicles"], ["tent", "ref"])
        self.assertEqual(len(listings[0]["data"]["destinations"]), 2)

    async def test_close_ownership_and_expired_listing(self):
        lid = self.add()
        await self.cb(f"close:{lid}")
        self.assertEqual(self.db.listing(lid)["status"], "active")
        await self.cb(f"close:{lid}", uid=1)
        self.assertEqual(self.db.listing(lid)["status"], "closed")
        self.add("new")
        await self.search()
        callback, card = self.card()
        self.now += 8 * 86400
        self.api.calls.clear()
        await self.cb(callback, card["message_id"])
        self.assertFalse(any(m == "sendContact" for m, _ in self.api.calls))

    async def test_admin_authorization(self):
        await self.msg("/grant 2 30", uid=2)
        self.assertEqual(self.db.user(2, self.now)["subscription_until"], 0)
        await self.msg("/grant 2 30", uid=1)
        self.assertEqual(self.db.user(2, self.now)["subscription_until"], self.now + 30 * 86400)
        await self.msg("/revoke 2", uid=1)
        self.assertEqual(self.db.user(2, self.now)["subscription_until"], 0)

    async def test_payment_from_invoice_through_receipt_is_idempotent(self):
        self.app.settings = replace(self.settings, paid_access=True, payment_mode="stars", plan_price_stars=100,
                                    plan_days=30, support_username="support_user")
        await self.msg(ui.SUBSCRIBE)
        await self.cb("accept:" + ui.TERMS_VERSION)
        await self.cb("buy")
        invoice = [p for m, p in self.api.calls if m == "sendInvoice"][-1]
        checkout = {"id": "checkout", "from": {"id": 2}, "invoice_payload": invoice["payload"],
                    "total_amount": 100, "currency": "XTR"}
        await self.app.handle("pre_checkout_query", checkout)
        self.assertTrue(self.api.calls[-1][1]["ok"])
        self.assertEqual(self.db.user(2, self.now)["subscription_until"], 0)
        bad = dict(checkout, total_amount=1)
        await self.app.handle("pre_checkout_query", bad)
        self.assertFalse(self.api.calls[-1][1]["ok"])
        receipt = {"invoice_payload": invoice["payload"], "total_amount": 100,
                   "currency": "XTR", "telegram_payment_charge_id": "charge-1"}
        await self.msg(successful_payment=receipt)
        until = self.db.user(2, self.now)["subscription_until"]
        await self.msg(successful_payment=receipt)
        self.assertEqual(until, self.now + 30 * 86400)
        self.assertEqual(self.db.user(2, self.now)["subscription_until"], until)

    async def test_checkout_does_not_wait_for_user_search_lock(self):
        self.app.settings = replace(self.settings, payment_mode="stars")
        order = self.db.order_new(2, 100, 30, self.now)
        lock = asyncio.Lock()
        self.app.locks[2] = lock
        await lock.acquire()
        try:
            await asyncio.wait_for(self.app.handle("pre_checkout_query", {
                "id": "checkout", "from": {"id": 2}, "invoice_payload": "access:" + order,
                "total_amount": 100, "currency": "XTR"}), timeout=1)
        finally:
            lock.release()
        self.assertTrue(self.api.calls[-1][1]["ok"])

    async def test_only_approved_channel_is_imported_and_edits_are_upserted(self):
        channel = -10012345
        self.app.settings = replace(self.settings, source_chat_ids=frozenset({channel}))
        text = "#yuk\nJo‘nash: Toshkent\nManzil: Samarqand\nAvto: Tent\nTavsif: Qoplangan mahsulot\nTelefon: +998000000000"
        event = {"chat": {"id": -10099999, "type": "channel"}, "message_id": 10, "text": text, "date": self.now}
        await self.app.handle("channel_post", event)
        self.assertEqual(self.db.search({"kind": "cargo"}, self.now, 100)[1], 0)
        event["chat"]["id"] = channel
        await self.app.handle("channel_post", event)
        event["text"] = text.replace("Qoplangan mahsulot", "Yangilangan mahsulot")
        await self.app.handle("edited_channel_post", event)
        ids, count = self.db.search({"kind": "cargo"}, self.now, 100)
        self.assertEqual(count, 1)
        self.assertEqual(self.db.listing(ids[0])["data"]["description"], "Yangilangan mahsulot")
        event["text"] = "#yopildi"
        await self.app.handle("edited_channel_post", event)
        self.assertEqual(self.db.search({"kind": "cargo"}, self.now, 100)[1], 0)

    async def test_real_aiogram_dispatcher_routes_without_network(self):
        from aiogram import Bot
        from aiogram.types import Update
        from logistika_bot.telegram import make_dispatcher
        bot = Bot("123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
        dispatcher = make_dispatcher(self.app)
        try:
            update = Update.model_validate({"update_id": 1, "message": {"message_id": 1, "date": self.now,
                                            "from": {"id": 2, "is_bot": False, "first_name": "Tester"},
                                            "chat": {"id": 2, "type": "private"}, "text": "/start"}})
            await dispatcher.feed_update(bot, update)
        finally:
            await bot.session.close()
        self.assertIn("Xush kelibsiz", self.api.text())

    async def test_group_message_does_not_create_private_response(self):
        await self.app.handle("message", {"from": {"id": 2}, "chat": {"id": -100, "type": "group"}, "text": "/start"})
        self.assertEqual(self.api.calls, [])
