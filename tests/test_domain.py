import unittest
from dataclasses import replace

from logistika_bot import ui
from logistika_bot.config import Settings
from logistika_bot.domain import (InputError, VEHICLES, clean_text, date_input,
                                  mask_contacts, normalize, parse_channel,
                                  parse_query, phone, place, telegram_url, validate_listing)
from tests.helpers import sample


class DomainTests(unittest.TestCase):
    def test_latin_cyrillic_and_apostrophe_aliases(self):
        for text in ["Ташкент Самарканд", "toshkent → SAMARQAND", "Toshkent Samarqand"]:
            query = parse_query(text)
            self.assertEqual(query["origin"], place("Toshkent"))
            self.assertEqual(query["destination"], place("Samarqand"))
        self.assertEqual(normalize("Qo‘qon"), normalize("Qo'qon"))
        self.assertEqual(place("Фергана"), place("Farg‘ona"))

    def test_single_place_has_explicit_either_semantics(self):
        self.assertEqual(parse_query("Ташкент"), {"either": place("Toshkent")})
        self.assertNotEqual(parse_query("Toshkent Samarqand"), parse_query("Samarqand Toshkent"))

    def test_explicit_unknown_city_and_country(self):
        result = parse_query("Turkiya / Gebze → O‘zbekiston / Toshkent")
        self.assertEqual(result["origin"]["city"], "Gebze")
        self.assertEqual(place("uz / ташкент"), place("Toshkent"))

    def test_ambiguous_or_invalid_route_is_rejected(self):
        for value in ["", "noma’lum joy", "Toshkent → Samarqand → Buxoro"]:
            with self.subTest(value=value), self.assertRaises(InputError):
                parse_query(value)

    def test_phones_and_public_contact_redaction(self):
        self.assertEqual(phone("90 123-45-67"), "+998901234567")
        for value in ["hello", "123", "+abc000000000"]:
            with self.assertRaises(InputError):
                phone(value)
        raw = "+998 (90) 123-45-67 https://t.me/foo/123 @contact t.me/foo/123"
        masked = mask_contacts(raw)
        self.assertNotIn("123-45-67", masked)
        self.assertNotIn("t.me", masked)
        self.assertNotIn("@contact", masked)

    def test_source_links_are_restricted_to_message_urls(self):
        for link in ["https://t.me/example/123", "https://t.me/c/12345/678"]:
            self.assertEqual(telegram_url(link), link)
        for link in ["http://t.me/test/1", "https://evil.test/1", "https://t.me@evil.test/1", "https://t.me/foo", "https://t.me/foo/1?x=1"]:
            with self.subTest(link=link), self.assertRaises(InputError):
                telegram_url(link)

    def test_public_card_escapes_html_and_hides_raw_data(self):
        listing = {"data": validate_listing(sample(description="<b>x</b> +998000000000 @secret",
                                                     source_url="https://t.me/example/123", raw_text="PRIVATE RAW")),
                   "published_at": 100, "id": 1}
        preview = ui.brief(listing, 1, 200)
        self.assertIn("&lt;b&gt;", preview)
        for private in ["PRIVATE RAW", "+998000000000", "@secret", "https://t.me"]:
            self.assertNotIn(private, preview)

    def test_all_vehicle_options_and_geo_pagination(self):
        rows = ui.vehicle_keyboard()["keyboard"]
        self.assertEqual(len(VEHICLES), 15)
        self.assertEqual(len([button for row in rows for button in row]), 17)
        session = {"id": "abc", "data": {"options": [{"name": str(i), "count": 1} for i in range(90)]}}
        buttons = [b for row in ui.geo_keyboard(session)["inline_keyboard"] for b in row]
        self.assertLessEqual(len(buttons), 42)
        self.assertIn("geopage:abc:40", [b["callback_data"] for b in buttons])

    def test_channel_template_and_invalid_data(self):
        post = "#yuk\nJo‘nash: Toshkent\nManzil: Samarqand; Buxoro\nAvto: Tent, Ref\nTavsif: Mahsulot\nTelefon: +998000000000"
        data = parse_channel(post)
        self.assertEqual(data["vehicles"], ["tent", "ref"])
        self.assertEqual(len(data["destinations"]), 2)
        self.assertEqual(data["raw_text"], post)
        with self.assertRaises(InputError):
            parse_channel("Oddiy va noma’lum matn")
        with self.assertRaises(InputError):
            validate_listing(sample(description=123))

    def test_date_and_unicode_limits(self):
        now = 1793894400
        self.assertTrue(date_input("Bugun", now, "Asia/Tashkent"))
        with self.assertRaises(InputError):
            date_input("2000-01-01", now, "Asia/Tashkent")
        with self.assertRaises(InputError):
            clean_text("🚚" * 2000, 3300)

    def test_sales_cannot_start_without_support(self):
        with self.assertRaises(ValueError):
            replace(Settings(), plan_price_stars=100).validate()
        replace(Settings(), plan_price_stars=100, support_username="support_user").validate()
