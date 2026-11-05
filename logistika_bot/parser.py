"""Conservative local extraction. Uncertain routes/types require a human review."""
from __future__ import annotations

import hashlib
import json
import re

from .domain import (COUNTRY_ALIASES, PLACE_ALIASES, VEHICLES, InputError,
                     date_input, normalize, parse_channel, phone, validate_listing)


def trim_units(text: str, units: int) -> str:
    return text.encode("utf-16-le")[:units * 2].decode("utf-16-le", errors="ignore")


def places(text: str) -> list[dict]:
    text = normalize(text)
    matches = []
    for alias, value in PLACE_ALIASES.items():
        for match in re.finditer(r"(?<![a-z0-9])" + re.escape(alias) + r"(?P<suffix>dan|ga|дан|га|a|u|e)?(?![a-z0-9])", text):
            matches.append((match.start(), match.end(), value, match.group("suffix") or ""))
    # Prefer the longest alias at any overlapping position.
    selected = []
    for start, end, value, suffix in sorted(matches, key=lambda x: (x[0], -(x[1] - x[0]))):
        if any(start < other[1] and end > other[0] for other in selected):
            continue
        selected.append((start, end, value, suffix))
    if selected:
        return [dict(value, suffix=suffix) for _, _, value, suffix in selected]
    for alias, country in sorted(COUNTRY_ALIASES.items(), key=lambda x: -len(x[0])):
        if len(alias) > 2 and re.search(r"(?<![a-z])" + re.escape(alias) + r"(?![a-z])", text):
            return [{"country": country, "city": "", "suffix": ""}]
    return []


def point(item: dict) -> dict:
    return {"country": item["country"], "city": item["city"]}


def extract_vehicles(text: str) -> list[str]:
    text = normalize(text)
    aliases = {key: [normalize(name)] for key, name in VEHICLES.items()}
    aliases["tent"] += ["tentovka", "tentli"]
    aliases["ref"] += ["refrijerator", "refrijirator", "refrejerator", "refrizherator"]
    aliases["ref_off"] += ["ref bez rezhima", "ref bez rejima"]
    aliases["flatbed"] += ["ploshchadka", "platforma"]
    aliases["partial"] += ["dogruz", "dagruz"]
    aliases["isotherm"] += ["izoterm"]
    result = [key for key, names in aliases.items()
              if any(re.search(r"(?<![a-z])" + re.escape(x) + r"(?![a-z])", text) for x in names)]
    if "ref_off" in result and "ref" in result:
        result.remove("ref")
    return result


def extract_phone(text: str) -> str:
    candidates = re.findall(r"(?<!\w)(?:\+\d|998)[\d ()-]{6,22}\d(?!\w)", text)
    for candidate in candidates:
        try:
            return phone(candidate)
        except InputError:
            pass
    if re.search(r"(?i)(telefon|tel\b|телефон|☎|📞)", text):
        for candidate in re.findall(r"(?<!\d)\d[\d ()-]{7,16}\d(?!\d)", text):
            try:
                return phone(candidate)
            except InputError:
                pass
    return ""


def fingerprint(data: dict) -> str:
    description = re.sub(r"(?i)(?:https?://|t\.me/)\S+|@[\w]+", "", data["description"])
    content = {"kind": data["kind"], "origin": data["origin"],
               "destinations": sorted(data["destinations"], key=lambda x: (x["country"], x["city"])),
               "vehicles": sorted(data["vehicles"]), "description": normalize(description),
               "phone": data.get("phone", ""), "price": normalize(data.get("price", "")),
               "capacity": normalize(data.get("capacity", "")), "date": data.get("ready_date", "")}
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def parse_message(text: str, source_url: str | None, published_at: int, timezone: str) -> dict:
    normalized = normalize(text)
    if text.strip().lower() == "#yopildi":
        return {"status": "closed", "reason": "Manbada yopilgan"}
    if re.search(r"(.)\1{20,}", normalized) or re.search(r"\b(kazino|casino|bukmeker|betting)\b", normalized):
        return {"status": "discarded", "reason": "Spam yoki logistika bo‘lmagan reklama"}
    if not re.search(r"\b(yuk|gruz|mashina|tent|fura|ref|isuzu|kamaz|transport|yuklanadi)\b", normalized):
        return {"status": "discarded", "reason": "Logistika e’loni belgisi yo‘q"}
    raw = trim_units(text, 3200)
    if text.strip().lower().startswith(("#yuk", "#transport")):
        try:
            data = parse_channel(raw)
            data.update(source_url=source_url, normalized=True)
            return {"status": "accepted", "data": validate_listing(data), "reason": "Kelishilgan shablon"}
        except InputError:
            return {"status": "review", "reason": "Shablon maydonlarini tuzatish kerak", "data": {}}

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    fields = {}
    for line in lines:
        key, sep, value = line.partition(":")
        if sep:
            fields[normalize(key)] = value.strip()
    cargo = bool(re.search(r"\b(yuk bor|gruz est|yuklanadi|mashina kerak|fura kerak|nuzhen tent|nuzhna mashina)\b", normalized)
                 or re.search(r"\b(tent|ref|kamaz|isuzu|transport) (?:\d+ ta )?kerak\b", normalized))
    vehicle = bool(re.search(r"\b(yuk kerak|gruz nuzhen|gruz nuzhna|yuk qidiraman|mashina bosh|svobodnaya mashina|pustaya fura)\b", normalized)
                   or re.search(r"\bbosh\b.{0,25}\b(mashina|tent|ref|fura|isuzu|kamaz)\b", normalized))
    kind = "cargo" if cargo and not vehicle else "vehicle" if vehicle and not cargo else ""
    origin, dests, directed = None, [], False
    for key in ["jonash", "qayerdan", "otkuda", "yuklash joyi"]:
        if key in fields and places(fields[key]):
            origin = point(places(fields[key])[0])
    for key in ["manzil", "qayerga", "kuda", "yetib borish"]:
        if key in fields:
            dests = [point(x) for x in places(fields[key])]
    directed = bool(origin and dests)
    if not directed:
        for line in lines:
            halves = re.split(r"\s*(?:→|➡\ufe0f?|➜|->|=>|\s[-–—]\s)\s*", line, maxsplit=1)
            if len(halves) == 2:
                a, b = places(halves[0]), places(halves[1])
                if len(a) == 1 and b:
                    origin, dests, directed = point(a[0]), [point(x) for x in b], True
                    break
    detected = places(text)
    if not directed:
        starts = [x for x in detected if x["suffix"] == "dan"]
        ends = [x for x in detected if x["suffix"] == "ga"]
        if len(starts) == 1 and ends:
            origin, dests, directed = point(starts[0]), [point(x) for x in ends], True
        elif len(detected) >= 2:
            origin, dests = point(detected[0]), [point(detected[1])]

    description = fields.get("tavsif") or fields.get("gruz") or fields.get("yuk") or text
    description = trim_units(description, 1800)
    capacity = fields.get("hajm", "")
    if not capacity:
        capacity = ", ".join(dict.fromkeys(re.findall(r"\d+(?:[.,]\d+)?\s*(?:tonna|тонн[аы]?|т\b|t\b|m[³3]|м[³3])", text, re.I)))[:80]
    price = fields.get("narx") or fields.get("tsena") or fields.get("stavka") or ""
    if not price:
        match = re.search(r"[\d][\d .,]{0,18}\s*(?:so[‘’']?m|сум|uzs|usd|dollar|руб|rubl|\$)", text, re.I)
        price = match.group() if match else "Kelishiladi"
    ready_date = ""
    match = re.search(r"\b\d{4}-\d{2}-\d{2}\b|\b(?:bugun|ertaga)\b", text, re.I)
    if match:
        try:
            ready_date = date_input(match.group(), published_at, timezone)
        except InputError:
            pass
    data = {"kind": kind, "origin": origin or {}, "destinations": dests[:5],
            "vehicles": extract_vehicles(text), "description": description, "capacity": capacity,
            "price": trim_units(price, 80), "phone": extract_phone(text), "source_url": source_url,
            "raw_text": raw, "ready_date": ready_date, "normalized": True}
    reasons = []
    if not kind:
        reasons.append("yuk yoki transport turi noaniq")
    if not directed:
        reasons.append("yo‘nalish tartibi noaniq")
    if not data["vehicles"]:
        reasons.append("avto turi topilmadi")
    if not data["phone"] and not source_url:
        reasons.append("aloqa ma’lumoti yo‘q")
    if reasons:
        return {"status": "review", "data": data, "reason": "; ".join(reasons)}
    try:
        return {"status": "accepted", "data": validate_listing(data), "reason": "Aniq yo‘nalish va tur"}
    except InputError:
        return {"status": "review", "data": data, "reason": "Ajratilgan maydonlarni tekshirish kerak"}
