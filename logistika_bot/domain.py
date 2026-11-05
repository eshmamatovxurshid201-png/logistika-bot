from __future__ import annotations

import re
import calendar
import unicodedata
from datetime import datetime, timedelta
from urllib.parse import urlparse
from zoneinfo import ZoneInfo


class InputError(ValueError):
    """An invalid user input that may safely be shown to the user."""


VEHICLES = {
    "tent": "Tent", "ref": "Ref", "ref_off": "Ref rejimsiz", "isotherm": "Izoterma",
    "isuzu_small": "Kichkina Isuzu", "isuzu_large": "Katta Isuzu",
    "chakman": "Chakman", "kamaz": "Kamaz", "mega": "Mega",
    "flatbed": "Ploshadka", "roadtrain": "Parovoz", "lowbed": "Tral",
    "labo": "Labo", "partial": "Dagruz", "sprinter": "Sprinter",
}
CYRILLIC = dict(zip(
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюяқғўҳ",
    ["a", "b", "v", "g", "d", "e", "yo", "j", "z", "i", "y", "k", "l", "m",
     "n", "o", "p", "r", "s", "t", "u", "f", "x", "ts", "ch", "sh", "sh", "", "i",
     "", "e", "yu", "ya", "q", "g", "o", "h"], strict=True,
))


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    text = "".join(CYRILLIC.get(c, c) for c in text)
    text = re.sub(r"['‘’ʻʼ`ʼ]", "", text)
    return " ".join(re.sub(r"[^a-z0-9\s]", " ", text).split())


_COUNTRIES = {
    "O‘zbekiston": ["uz", "uzbekiston", "uzbekistan", "o'zbekiston", "узбекистан"],
    "Rossiya": ["ru", "russia", "rossiya", "россия"],
    "Qozog‘iston": ["kz", "kazakhstan", "kazahstan", "qozogiston", "казахстан"],
    "Qirg‘iziston": ["kg", "kyrgyzstan", "kirgiziya", "qirgiziston", "киргизия"],
    "Turkiya": ["tr", "turkey", "turkiye", "turkiya", "турция"],
    "Xitoy": ["cn", "china", "xitoy", "китай"],
    "Litva": ["lt", "lithuania", "litva"], "Polsha": ["pl", "poland", "polsha", "польша"],
    "Tojikiston": ["tj", "tajikistan", "tojikiston", "таджикистан"],
    "Turkmaniston": ["tm", "turkmenistan", "turkmaniston"],
}
COUNTRY_ALIASES = {normalize(alias): name for name, aliases in _COUNTRIES.items()
                   for alias in [name, *aliases]}
_CITIES = {
    "Toshkent": ["tashkent", "toshkent", "ташкент"],
    "Samarqand": ["samarkand", "samarqand", "самарканд"],
    "Andijon": ["andijan", "andizhan", "андижан"],
    "Farg‘ona": ["fergana", "fargona", "фергана"],
    "Buxoro": ["bukhara", "buxoro", "buhara", "бухара"],
    "Qo‘qon": ["kokand", "qoqon", "коканд"],
    "Navoiy": ["navoi", "navoiy", "навои"],
    "Xorazm": ["khorezm", "xorazm", "хорезм"],
}
for _city in ["Angren", "Asaka", "Chinoz", "Gijduvon", "Jizzax", "Kattaqo‘rg‘on",
              "Marg‘ilon", "Namangan", "Nazarbek", "Ohangaron", "Olmaliq", "Qarshi",
              "Qashqadaryo", "Quva", "Shahrihon", "Sirdaryo", "Urganch", "Urgut",
              "Vodiy", "Zarafshon", "Nukus", "Qoraqalpog‘iston", "Termiz", "Denov"]:
    _CITIES.setdefault(_city, [])
PLACE_ALIASES: dict[str, dict] = {}
for _name, _aliases in _CITIES.items():
    for _alias in [_name, *_aliases]:
        PLACE_ALIASES[normalize(_alias)] = {"country": "O‘zbekiston", "city": _name}
for _country, _name, _aliases in [
    ("Rossiya", "Moskva", ["moscow", "москва"]),
    ("Qozog‘iston", "Olmaota", ["almaty", "almata", "olmata", "алматы"]),
    ("Turkiya", "Istanbul", ["istambul", "stambul", "istanbul", "стамбул"]),
    ("Turkiya", "Chorlu", ["corlu", "чорлу"]),
    ("Qirg‘iziston", "Bishkek", ["bishkek", "бишкек"]),
    ("Tojikiston", "Dushanbe", ["душанбе"]),
]:
    for _alias in [_name, *_aliases]:
        PLACE_ALIASES[normalize(_alias)] = {"country": _country, "city": _name}


def clean_text(value: str, limit: int, minimum: int = 1) -> str:
    if not isinstance(value, str):
        raise InputError("Matn maydoni oddiy matn bo‘lishi kerak.")
    value = value.strip()
    if not minimum <= len(value.encode("utf-16-le")) // 2 <= limit:
        raise InputError(f"Matn {minimum}–{limit} belgidan iborat bo‘lsin.")
    if any(unicodedata.category(c) == "Cc" and c not in "\n\t" for c in value):
        raise InputError("Matnda yaroqsiz boshqaruv belgisi bor.")
    return value


def place(text: str) -> dict:
    text = clean_text(text, 100, 2)
    if "/" in text:
        country, city = [x.strip() for x in text.split("/", 1)]
        country = COUNTRY_ALIASES.get(normalize(country), clean_text(country, 50, 2))
        city = clean_text(city, 50, 2)
        known = PLACE_ALIASES.get(normalize(city))
        if known and known["country"] == country:
            city = known["city"]
        return {"country": country, "city": city}
    key = normalize(text)
    if key in PLACE_ALIASES:
        return dict(PLACE_ALIASES[key])
    if key in COUNTRY_ALIASES:
        return {"country": COUNTRY_ALIASES[key], "city": ""}
    raise InputError("Joy tanilmadi. Masalan: Toshkent yoki Turkiya / Chorlu.")


def destinations(text: str) -> list[dict]:
    parts = text.split(";")
    if not 1 <= len(parts) <= 5:
        raise InputError("Ko‘pi bilan 5 manzilni ; bilan ajrating.")
    result = []
    for part in parts:
        item = place(part)
        if item not in result:
            result.append(item)
    return result


def parse_query(text: str) -> dict:
    """One place matches either endpoint; two places preserve direction."""
    parts = re.split(r"\s*(?:→|->|—|;)\s*", text.strip())
    if len(parts) == 2:
        return {"origin": place(parts[0]), "destination": place(parts[1])}
    if len(parts) > 2:
        raise InputError("Bitta joy yoki 'Toshkent → Samarqand' yozing.")
    try:
        return {"either": place(text)}
    except InputError:
        pass
    words = normalize(clean_text(text, 150)).split()
    candidates = []
    for split in range(1, len(words)):
        try:
            candidate = {"origin": place(" ".join(words[:split])),
                         "destination": place(" ".join(words[split:]))}
            if candidate not in candidates:
                candidates.append(candidate)
        except InputError:
            continue
    if len(candidates) == 1:
        return candidates[0]
    raise InputError("Yo‘nalish tanilmadi. Masalan: Toshkent → Samarqand. "
                     "Noma’lum shahar uchun: Turkiya / Chorlu.")


def phone(text: str) -> str:
    text = text.strip()
    if not re.fullmatch(r"\+?[0-9 ()-]{8,25}", text):
        raise InputError("Telefonni +998901234567 shaklida kiriting.")
    digits = re.sub(r"\D", "", text)
    if len(digits) == 9 and not text.startswith("+"):
        digits = "998" + digits
    if not 8 <= len(digits) <= 15:
        raise InputError("Telefon raqami 8–15 ta raqamdan iborat bo‘lsin.")
    return "+" + digits


def telegram_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    if (parsed.scheme != "https" or parsed.netloc != "t.me" or parsed.query
            or parsed.fragment or not re.fullmatch(r"/(?:[A-Za-z0-9_]+|c/\d+)/\d+", parsed.path)):
        raise InputError("Manba Telegram xabarining https://t.me/kanal/123 havolasi bo‘lsin.")
    return value


def mask_contacts(text: str) -> str:
    text = re.sub(r"(?i)(?:https?://|tg://|www\.|t\.me/|telegram\.me/)\S+", "[havola]", text)
    text = re.sub(r"@[\w]{3,}", "[kontakt]", text)
    return re.sub(r"(?<!\w)\+?\d[\d ()-]{6,}\d(?!\w)", "[telefon]", text)


def day_start(now: int, timezone: str) -> int:
    return int(datetime.fromtimestamp(now, ZoneInfo(timezone)).replace(
        hour=0, minute=0, second=0, microsecond=0).timestamp())


def add_months(timestamp: int, months: int, timezone: str) -> int:
    if months not in {1, 2, 3, 6}:
        raise InputError("Tarif 1, 2, 3 yoki 6 oy bo‘lsin.")
    value = datetime.fromtimestamp(timestamp, ZoneInfo(timezone))
    serial = value.year * 12 + value.month - 1 + months
    year, month = divmod(serial, 12)
    month += 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return int(value.replace(year=year, month=month, day=day).timestamp())


def date_input(text: str, now: int, timezone: str) -> str:
    today = datetime.fromtimestamp(now, ZoneInfo(timezone)).date()
    key = normalize(text)
    if key in {"bugun", "ertaga"}:
        return (today + timedelta(days=key == "ertaga")).isoformat()
    if text == "O‘tkazib yuborish":
        return ""
    try:
        value = datetime.strptime(text.strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise InputError("Sana: 2026-11-05, Bugun yoki Ertaga shaklida bo‘lsin.") from exc
    if value < today or value > today + timedelta(days=365):
        raise InputError("Bugundan boshlab bir yil ichidagi sanani kiriting.")
    return value.isoformat()


def validate_listing(data: dict) -> dict:
    if data.get("kind") not in {"cargo", "vehicle"}:
        raise InputError("E’lon turi cargo yoki vehicle bo‘lsin.")
    selected = data.get("vehicles", [])
    if not isinstance(selected, list) or not selected or any(x not in VEHICLES for x in selected):
        raise InputError("Kamida bitta to‘g‘ri transport turi kerak.")
    origin = data.get("origin", {})
    dests = data.get("destinations", [])
    if not isinstance(origin, dict) or not isinstance(dests, list) or not 1 <= len(dests) <= 5:
        raise InputError("Jo‘nash joyi va 1–5 manzil kerak.")
    for item in [origin, *dests]:
        if not isinstance(item, dict):
            raise InputError("Joy country va city maydonlaridan iborat bo‘lsin.")
        clean_text(item.get("country", ""), 50, 2)
        if item.get("city"):
            clean_text(item["city"], 50, 2)
    result = dict(data)
    def canonical(item: dict) -> dict:
        country = COUNTRY_ALIASES.get(normalize(item["country"]), item["country"].strip())
        city = item.get("city", "").strip()
        known = PLACE_ALIASES.get(normalize(city))
        if known and known["country"] == country:
            city = known["city"]
        return {"country": country, "city": city}
    result.update(vehicles=list(dict.fromkeys(selected)), origin=canonical(origin),
                  destinations=[canonical(x) for x in dests],
                  description=clean_text(data.get("description", ""), 1800, 3),
                  capacity=clean_text(data.get("capacity", "") or "—", 80),
                  price=clean_text(data.get("price", "") or "Kelishiladi", 80),
                  phone=phone(data["phone"]) if data.get("phone") else "",
                  source_url=telegram_url(data.get("source_url")))
    # Keep the complete detailed message within Telegram's 4096 character limit.
    if result.get("raw_text"):
        result["raw_text"] = clean_text(result["raw_text"], 3300)
    ready = result.get("ready_date", "")
    if ready:
        try:
            datetime.strptime(ready, "%Y-%m-%d")
        except ValueError as exc:
            raise InputError("ready_date YYYY-MM-DD shaklida bo‘lsin.") from exc
    result["ready_date"] = ready
    return result


def parse_channel(text: str) -> dict:
    lines = text.strip().splitlines()
    if not lines or lines[0].strip().lower() not in {"#yuk", "#transport"}:
        raise InputError("Kanal posti #yuk yoki #transport bilan boshlansin.")
    fields = {}
    for line in lines[1:]:
        key, sep, value = line.partition(":")
        if sep:
            fields[normalize(key)] = value.strip()
    names = {normalize(v): k for k, v in VEHICLES.items()}
    selected = [names.get(normalize(x), "") for x in fields.get("avto", "").split(",")]
    return validate_listing({
        "kind": "cargo" if lines[0].strip().lower() == "#yuk" else "vehicle",
        "origin": place(fields.get("jonash", "")),
        "destinations": destinations(fields.get("manzil", "")), "vehicles": selected,
        "description": fields.get("tavsif", ""), "phone": fields.get("telefon", ""),
        "capacity": fields.get("hajm", ""), "price": fields.get("narx", ""),
        "ready_date": fields.get("sana", ""), "raw_text": text,
    })
