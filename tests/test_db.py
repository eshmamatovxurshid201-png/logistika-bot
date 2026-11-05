import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from logistika_bot.db import Database
from logistika_bot.domain import InputError, parse_query, place
from tests.helpers import sample


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.temp.name) / "test.sqlite3"))
        self.db.initialize()
        self.now = int(datetime(2026, 11, 5, 0, 30, tzinfo=ZoneInfo("Asia/Tashkent")).timestamp())
        self.db.user(1, self.now)

    def tearDown(self):
        self.temp.cleanup()

    def add(self, key, **changes):
        return self.db.save_listing(sample(**changes), 99, key, self.now, 7)

    def test_multi_vehicle_and_destination_matches_are_not_duplicated(self):
        lid = self.add("one", destinations=[place("Samarqand"), place("Buxoro")])
        ids, total = self.db.search({"kind": "cargo", "vehicle": "tent", "query": parse_query("Toshkent")}, self.now, 100)
        self.assertEqual((ids, total), ([lid], 1))
        ids, total = self.db.search({"kind": "cargo", "query": parse_query("Toshkent Buxoro")}, self.now, 100)
        self.assertEqual(total, 1)

    def test_direction_and_listing_kind(self):
        forward = self.add("forward")
        reverse = self.add("reverse", origin=place("Samarqand"), destinations=[place("Toshkent")])
        self.add("vehicle", kind="vehicle")
        ids, _ = self.db.search({"kind": "cargo", "query": parse_query("Toshkent Samarqand")}, self.now, 100)
        self.assertEqual(ids, [forward])
        ids, _ = self.db.search({"kind": "cargo", "query": parse_query("Samarqand")}, self.now, 100)
        self.assertEqual(set(ids), {forward, reverse})

    def test_geo_totals_today_and_expired_closed_rows(self):
        today = self.add("today", kind="vehicle")
        self.db.save_listing(sample(kind="vehicle", origin=place("Samarqand")), 99, "yesterday", self.now, 7,
                             published_at=self.now - 3600)
        closed = self.add("closed", kind="vehicle")
        self.db.close_listing(closed, 99)
        self.db.save_listing(sample(kind="vehicle"), 99, "expired", self.now - 9 * 86400, 7)
        geo = self.db.geography({"kind": "vehicle"}, self.now, "Asia/Tashkent")
        self.assertEqual((geo["total"], geo["today"]), (2, 1))
        cities = self.db.geography({"kind": "vehicle", "country": "O‘zbekiston"}, self.now, "Asia/Tashkent")
        self.assertEqual(sum(x["count"] for x in cities["options"]), geo["total"])
        self.assertFalse(self.db.close_listing(today, 123))

    def test_import_idempotency_and_update(self):
        lid = self.add("same")
        again = self.db.save_listing(sample(description="Yangilangan tavsif"), 99, "same", self.now, 7, update=True)
        self.assertEqual(lid, again)
        self.assertEqual(self.db.listing(lid)["data"]["description"], "Yangilangan tavsif")
        self.assertEqual(self.db.search({"kind": "cargo"}, self.now, 100)[1], 1)

    def test_stable_snapshot_ownership_expiry_and_persistent_state(self):
        one = self.add("one")
        session = self.db.session_new(1, {"mode": "results", "ids": [one]}, self.now, 1)
        self.add("new")
        self.db.set_state(1, "post_phone", {"description": "Draft"})
        reopened = Database(self.db.path)
        self.assertEqual(reopened.user(1, self.now)["state"], "post_phone")
        self.assertEqual(reopened.session(session["id"], 1, self.now)["data"]["ids"], [one])
        self.assertIsNone(reopened.session(session["id"], 2, self.now))
        self.assertIsNone(reopened.session(session["id"], 1, self.now + 3600))

    def test_payment_validation_and_atomic_idempotency(self):
        order = self.db.order_new(1, 100, 30, self.now)
        self.assertFalse(self.db.order_check(order, 2, 100, "XTR", self.now))
        self.assertFalse(self.db.order_check(order, 1, 99, "XTR", self.now))
        self.assertFalse(self.db.order_check(order, 1, 100, "USD", self.now))
        self.assertFalse(self.db.order_check(order, 1, 100, "XTR", self.now + 86400))
        self.assertTrue(self.db.order_check(order, 1, 100, "XTR", self.now))
        def deliver(_):
            return self.db.payment(order, 1, 100, "XTR", "charge-one", self.now)
        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(deliver, [1, 2]))
        self.assertEqual(sum(fresh for _, fresh in replies), 1)
        self.assertEqual(self.db.user(1, self.now)["subscription_until"], self.now + 30 * 86400)
        other = self.db.order_new(1, 100, 30, self.now)
        with self.assertRaises(InputError):
            self.db.payment(other, 1, 100, "XTR", "charge-one", self.now)
        self.db.payment(other, 1, 100, "XTR", "charge-two", self.now)
        self.assertEqual(self.db.user(1, self.now)["subscription_until"], self.now + 60 * 86400)

    def test_events_count_unique_users_and_subscription_revocation(self):
        lid = self.add("one")
        self.db.event(1, lid, "view", self.now)
        counts = self.db.event(1, lid, "view", self.now)
        self.assertEqual(counts["view"], 1)
        self.db.event(2, lid, "view", self.now)
        counts = self.db.event(1, lid, "phone", self.now)
        self.assertEqual(counts, {"view": 2, "phone": 1})
        self.db.grant(1, 1, self.now)
        self.db.revoke(1)
        self.assertEqual(self.db.user(1, self.now)["subscription_until"], 0)
