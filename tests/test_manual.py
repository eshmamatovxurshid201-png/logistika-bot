import asyncio
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from logistika_bot import ui
from logistika_bot.config import Settings
from logistika_bot.db import Database
from logistika_bot.domain import InputError, add_months
from logistika_bot.service import Application
from logistika_bot.pipeline import Pipeline
from tests.helpers import FakeAPI, sample


class ManualTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.temp.name) / "bot.sqlite3"))
        self.db.initialize()
        self.now = int(datetime(2028, 1, 31, 12, 0, tzinfo=ZoneInfo("Asia/Tashkent")).timestamp())
        self.settings = Settings(database_path=self.db.path, paid_access=True, admin_ids=frozenset({1, 3}),
                                 card_number="0000000000000000", card_holder="DEMO", support_username="support_user",
                                 tariff_prices_uzs=(100, 200, 300, 600))
        self.api = FakeAPI()
        self.app = Application(self.settings, self.db, self.api, clock=lambda: self.now)
        self.db.user(2, self.now)

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def msg(self, text="", uid=2, **extra):
        await self.app.handle("message", {"message_id": 1, "from": {"id": uid}, "chat": {"id": uid, "type": "private"}, "text": text, **extra})

    async def cb(self, data, uid=2):
        await self.app.handle("callback_query", {"id": "callback", "from": {"id": uid}, "data": data,
                              "message": {"message_id": 100, "chat": {"id": uid, "type": "private"}}})

    async def request(self, months=1, uid=2):
        await self.msg("/subscribe", uid)
        await self.cb("accept:" + ui.TERMS_VERSION, uid)
        await self.cb(f"manual:{months}", uid)
        return self.db.manual_open(uid)

    async def submit(self, months=1, uid=2, file="receipt-one", unique="unique-one"):
        request = await self.request(months, uid)
        await self.msg(uid=uid, photo=[{"file_id": file, "file_unique_id": unique, "file_size": 500}])
        return self.db.manual_payment(request["id"])

    async def test_full_receipt_admin_review_and_calendar_month_activation(self):
        payment = await self.submit(3)
        self.assertEqual(payment["status"], "pending")
        self.assertEqual(self.db.user(2, self.now)["subscription_until"], 0)
        await self.cb(f"payview:{payment['id']}", uid=1)
        preview = [p for m, p in self.api.calls if m == "sendPhoto"][-1]
        self.assertEqual(preview["photo"], "receipt-one")
        await self.cb(f"paypick:{payment['id']}:3", uid=1)
        self.assertEqual(self.db.user(2, self.now)["subscription_until"], 0)
        await self.cb(f"payok:{payment['id']}:3", uid=1)
        until = self.db.user(2, self.now)["subscription_until"]
        self.assertEqual(until, add_months(self.now, 3, self.settings.timezone))
        await self.cb(f"payok:{payment['id']}:6", uid=3)
        self.assertEqual(self.db.user(2, self.now)["subscription_until"], until)
        self.assertEqual(self.db.manual_payment(payment["id"])["approved_months"], 3)

    async def test_non_admin_cannot_view_or_approve_receipt(self):
        payment = await self.submit()
        self.api.calls.clear()
        for action in ["payview", "paypick", "payok"]:
            await self.cb(f"{action}:{payment['id']}" + (":6" if action != "payview" else ""), uid=2)
        self.assertFalse(any(m in {"sendPhoto", "sendDocument"} for m, _ in self.api.calls))
        self.assertEqual(self.db.user(2, self.now)["subscription_until"], 0)

    async def test_no_listing_counts_or_previews_before_admin_approval(self):
        self.db.save_listing(sample(description="PRIVATE CARGO"), 99, "sample", self.now, 7)
        await self.msg(ui.QUICK)
        await self.msg(ui.CARGO)
        await self.msg(ui.VEHICLE)
        await self.app.results(2, {"kind": "cargo"})
        await self.app.geography(2, {"kind": "vehicle"})
        self.assertFalse(self.api.buttons("detail:"))
        self.assertFalse(self.api.buttons("geo:"))
        self.assertNotIn("PRIVATE CARGO", self.api.text())
        self.assertNotIn("ta e’lon topildi", self.api.text())
        with self.db.connection() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0)

    async def test_receipt_rejection_has_reason_and_does_not_grant_access(self):
        payment = await self.submit()
        await self.cb(f"payreject:{payment['id']}", uid=1)
        await self.msg("Bankda tushum topilmadi", uid=1)
        self.assertEqual(self.db.manual_payment(payment["id"])["status"], "rejected")
        self.assertIn("Bankda tushum topilmadi", self.api.text())
        self.assertEqual(self.db.user(2, self.now)["subscription_until"], 0)

    async def test_only_one_pending_request_and_duplicate_file_rejected(self):
        payment = await self.submit()
        await self.cb("manual:6")
        self.assertEqual(self.db.manual_open(2)["id"], payment["id"])
        self.db.reject_manual(payment["id"], 1, "Tekshirish kerak", self.now)
        next_request = await self.request(2)
        await self.msg(photo=[{"file_id": "another-file-id", "file_unique_id": "unique-one"}])
        self.assertEqual(self.db.manual_payment(next_request["id"])["status"], "awaiting")
        self.assertIn("avval yuborilgan", self.api.text())

    async def test_pdf_receipt_and_upload_validation(self):
        payment = await self.request()
        await self.msg(document={"file_id": "exe", "file_unique_id": "exe", "mime_type": "application/x-msdownload"})
        self.assertEqual(self.db.manual_payment(payment["id"])["status"], "awaiting")
        await self.msg(document={"file_id": "big", "file_unique_id": "big", "mime_type": "application/pdf", "file_size": 11 * 1024 * 1024})
        self.assertEqual(self.db.manual_payment(payment["id"])["status"], "awaiting")
        await self.msg(document={"file_id": "pdf", "file_unique_id": "pdf", "mime_type": "application/pdf", "file_size": 1000})
        await self.cb(f"payview:{payment['id']}", uid=1)
        self.assertEqual([p for m, p in self.api.calls if m == "sendDocument"][-1]["document"], "pdf")

    async def test_foreign_request_cancel_and_submit_denied(self):
        payment = await self.request()
        self.assertFalse(self.db.manual_cancel(payment["id"], 4))
        with self.assertRaises(InputError):
            self.db.manual_submit(payment["id"], 4, "file", "unique", "photo", self.now)
        with self.assertRaises(InputError):
            self.db.approve_manual(payment["id"], 1, 1, self.now, self.settings.timezone)
        self.assertTrue(self.db.manual_cancel(payment["id"], 2))

    async def test_two_admins_racing_grant_only_once(self):
        payment = await self.submit()
        def approve(admin):
            return self.db.approve_manual(payment["id"], admin, 2, self.now, self.settings.timezone)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(approve, [1, 3]))
        self.assertEqual(sum(fresh for _, fresh in results), 1)
        self.assertEqual(self.db.user(2, self.now)["subscription_until"], add_months(self.now, 2, self.settings.timezone))
        with self.db.connection() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM admin_audit WHERE action='payment_approved'").fetchone()[0], 1)

    async def test_all_four_month_lengths_and_renewal(self):
        for months in (1, 2, 3, 6):
            end = datetime.fromtimestamp(add_months(self.now, months, self.settings.timezone), ZoneInfo(self.settings.timezone))
            self.assertEqual(end.month, 1 + months)
            self.assertEqual(end.day, {1: 29, 2: 31, 3: 30, 6: 31}[months])
        current = self.db.grant_months(2, 1, 1, self.now, self.settings.timezone)
        later = self.db.grant_months(2, 2, 1, self.now, self.settings.timezone)
        self.assertEqual(later, add_months(current, 2, self.settings.timezone))
        with self.assertRaises(InputError):
            add_months(self.now, 4, self.settings.timezone)

    async def test_old_terms_button_and_stars_button_do_not_start_sale(self):
        await self.cb("accept")
        self.assertEqual(self.db.user(2, self.now)["terms_version"], "")
        await self.cb("buy")
        self.assertFalse(any(m == "sendInvoice" for m, _ in self.api.calls))

    async def test_v1_migration_preserves_subscription_and_draft(self):
        path = str(Path(self.temp.name) / "v1.sqlite3")
        with sqlite3.connect(path) as con:
            con.executescript("CREATE TABLE users(id INTEGER PRIMARY KEY,state TEXT NOT NULL DEFAULT 'home',context TEXT NOT NULL DEFAULT '{}',"
                              "vehicle TEXT NOT NULL DEFAULT 'all',subscription_until INTEGER NOT NULL DEFAULT 0,terms_version TEXT NOT NULL DEFAULT '',"
                              "created_at INTEGER NOT NULL); PRAGMA user_version=1;")
            con.execute("INSERT INTO users(id,state,context,subscription_until,created_at) VALUES(1,'post_phone','{\"draft\":true}',?,?)", (self.now + 1000, self.now))
        migrated = Database(path)
        migrated.initialize()
        self.assertEqual(migrated.user(1, self.now)["subscription_until"], self.now + 1000)
        self.assertEqual(migrated.user(1, self.now)["state"], "post_phone")
        self.assertEqual(migrated.operations_stats()["pending_payments"], 0)

    async def test_admin_can_review_and_publish_ambiguous_ad_once(self):
        text = "Toshkent Samarqand\nTent kerak\nTelefon: +998000000000"
        self.db.source_seed([-1001234], self.now)
        self.db.ingest_enqueue(-1001234, 1, text, "https://t.me/c/1234/1", self.now, self.now, self.now)
        Pipeline(self.db, self.settings, lambda: self.now).process_one()
        self.assertEqual(self.db.search({"kind": "cargo"}, self.now, 100)[1], 0)
        await self.cb("reviewqueue:0", uid=1)
        button = self.api.buttons("review:")[-1]["callback_data"]
        self.api.calls.clear()
        await self.cb(button, uid=2)
        self.assertNotIn(text, self.api.text())
        await self.cb(button, uid=1)
        approve = self.api.buttons("reviewok:")[-1]["callback_data"]
        await self.cb(approve, uid=1)
        await self.cb(approve, uid=3)
        self.assertEqual(self.db.search({"kind": "cargo"}, self.now, 100)[1], 1)

    async def test_admin_review_correction_and_stale_revision(self):
        text = "Toshkent Samarqand\nTent kerak\nTelefon: +998000000000"
        self.db.source_seed([-1001234], self.now)
        self.db.ingest_enqueue(-1001234, 1, text, "https://t.me/c/1234/1", self.now, self.now, self.now)
        Pipeline(self.db, self.settings, lambda: self.now).process_one()
        await self.cb("reviewqueue:0", uid=1)
        button = self.api.buttons("review:")[-1]["callback_data"]
        await self.cb(button, uid=1)
        edit = self.api.buttons("reviewedit:")[-1]["callback_data"]
        await self.cb(edit, uid=1)
        self.db.ingest_enqueue(-1001234, 1, text + "\nYangilangan", "https://t.me/c/1234/1", self.now, self.now + 1, self.now)
        await self.msg("#yuk\nJo‘nash: Toshkent\nManzil: Buxoro\nAvto: Tent\nTavsif: Qoplangan ko‘mir\nTelefon: +998000000000", uid=1)
        self.assertEqual(self.db.search({"kind": "cargo"}, self.now, 100)[1], 0)
        Pipeline(self.db, self.settings, lambda: self.now).process_one()
        await self.cb("reviewqueue:0", uid=1)
        await self.cb(self.api.buttons("review:")[-1]["callback_data"], uid=1)
        await self.cb(self.api.buttons("reviewedit:")[-1]["callback_data"], uid=1)
        await self.msg("#yuk\nJo‘nash: Toshkent\nManzil: Buxoro\nAvto: Tent\nTavsif: Qoplangan ko‘mir\nTelefon: +998000000000", uid=1)
        ids, count = self.db.search({"kind": "cargo"}, self.now, 100)
        self.assertEqual(count, 1)
        self.assertEqual(self.db.listing(ids[0])["data"]["destinations"][0]["city"], "Buxoro")

    async def test_old_brief_and_pagination_buttons_are_locked_after_expiry(self):
        self.db.grant_months(2, 1, 1, self.now, self.settings.timezone)
        for i in range(6):
            self.db.save_listing(sample(description="PRIVATE " + str(i)), 99, str(i), self.now, 7)
        await self.app.results(2, {"kind": "cargo"})
        detail = self.api.buttons("detail:")[0]["callback_data"]
        more = self.api.buttons("more:")[-1]["callback_data"]
        self.db.revoke(2)
        self.api.calls.clear()
        for action in ["brief", "detail", "phone", "source"]:
            await self.cb(detail.replace("detail:", action + ":"))
        await self.cb(more)
        await self.msg("/davom")
        self.assertNotIn("PRIVATE", self.api.text())
        self.assertFalse(any(m in {"editMessageText", "sendContact"} for m, _ in self.api.calls))
