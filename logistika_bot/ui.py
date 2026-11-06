from __future__ import annotations

from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from .domain import VEHICLES, mask_contacts

QUICK = "🔍 Tezkor Qidiruv"
MINE = "📢 Mening e’lonlarim"
ADD = "➕ E’lon qo‘shish"
SETTINGS = "⚙️ Sozlamalar"
FAVORITES = "⭐ Tanlanganlar"
CARGO = "📦 Yuk topish"
VEHICLE = "🚚 Moshina topish"
BACK = "⬅️ Orqaga"
CANCEL = "❌ Bekor qilish"
SKIP = "O‘tkazib yuborish"
SUBSCRIBE = "⭐ Obuna"
TERMS_VERSION = "2"


def reply(rows: list[list[str | dict]]) -> dict:
    return {"keyboard": [[{"text": x} if isinstance(x, str) else x for x in row] for row in rows],
            "resize_keyboard": True, "is_persistent": True}


def button(text: str, data: str) -> dict:
    if len(data.encode("utf-8")) > 64:
        raise ValueError("callback_data is longer than Telegram's limit")
    return {"text": text, "callback_data": data}


def inline(rows: list[list[dict]]) -> dict:
    return {"inline_keyboard": rows}


def pairs(items: list) -> list[list]:
    return [items[i:i + 2] for i in range(0, len(items), 2)]


def main_keyboard() -> dict:
    return reply([[QUICK], [FAVORITES], [MINE], [ADD], [SETTINGS]])


def quick_keyboard() -> dict:
    return reply([[CARGO], [VEHICLE], [BACK]])


def vehicle_keyboard() -> dict:
    return reply([["Hammasi"], *pairs(list(VEHICLES.values())[:-1]), ["Sprinter"], [BACK]])


def current_keyboard(vehicle: str) -> dict:
    name = VEHICLES.get(vehicle, "Hammasi")
    return reply([[f"Joriy: 🚚 {name.upper()} 🚚. Avto turini o‘zgartirish"], [BACK]])


def post_vehicles(selected: list[str]) -> dict:
    buttons = [button(("✅ " if key in selected else "") + name, f"draft:{key}")
               for key, name in VEHICLES.items()]
    return inline([*pairs(buttons), [button("Davom etish ➡️", "draft:next")],
                   [button(CANCEL, "draft:cancel")]])


def card_keyboard(session_id: str, listing_id: int, detail: bool = False,
                  more_offset: int | None = None, total: int = 0, saved: bool = False) -> dict:
    suffix = f"{session_id}:{listing_id}"
    rows = ([[button("📞 Telefon raqam", "phone:" + suffix), button("Xabarga o‘tish", "source:" + suffix)],
             [button(BACK, "brief:" + suffix)]] if detail else
            [[button("Batafsil", "detail:" + suffix)]])
    rows.append([button("⭐ Olib tashlash" if saved else "⭐ Saqlash", ("unsave:" if saved else "save:") + suffix),
                 button("🔗 Mos e’lonlar", "match:" + suffix)])
    if more_offset is not None:
        rows.append([button(f"Ko‘proq ko‘rsatish ({more_offset + 1} - {total})",
                            f"more:{session_id}:{more_offset}")])
    return inline(rows)


def geo_keyboard(session: dict, offset: int = 0) -> dict:
    sid = session["id"]
    options = session["data"]["options"]
    rows = pairs([button(f"{x['name']} - {x['count']}", f"geo:{sid}:{i}")
                  for i, x in enumerate(options[offset:offset + 40], offset)])
    navigation = []
    if offset:
        navigation.append(button("◀️ Oldingi", f"geopage:{sid}:{max(0, offset - 40)}"))
    if offset + 40 < len(options):
        navigation.append(button("Keyingi ▶️", f"geopage:{sid}:{offset + 40}"))
    if navigation:
        rows.append(navigation)
    rows.append([button(BACK, f"geoback:{sid}")])
    return inline(rows)


def label(place: dict) -> str:
    return place.get("city") or place["country"]


def age(published_at: int, now: int) -> str:
    seconds = max(0, now - published_at)
    if seconds < 60:
        return "Hozirgina"
    if seconds < 3600:
        return f"{seconds // 60} daqiqa oldin"
    if seconds < 86400:
        return f"{seconds // 3600} soat oldin"
    return f"{seconds // 86400} kun oldin"


def brief(listing: dict, ordinal: int, now: int) -> str:
    data = listing["data"]
    # Previews never expose raw text or a source/contact URL.
    origin = escape(mask_contacts(label(data["origin"])))
    dest = escape(mask_contacts(", ".join(label(x) for x in data["destinations"])))
    vehicle = ", ".join(VEHICLES[x] for x in data["vehicles"])
    source = "Telegram" if data.get("source_url") or data.get("source_chat_id") else "Bot"
    lines = [f"<b>{ordinal}. {origin} → {dest}</b>", f"🔵 {source}", "", f"🚚 {vehicle}"]
    if data["kind"] == "cargo":
        lines.append("📦 " + escape(mask_contacts(data["description"][:180])))
    if data.get("capacity") and data["capacity"] != "—":
        lines.append("↔️ " + escape(mask_contacts(data["capacity"])))
    lines.append("💰 " + escape(mask_contacts(data.get("price", "Kelishiladi"))))
    if data.get("ready_date"):
        lines.append("📅 " + escape(data["ready_date"]))
    if data.get("demo"):
        lines.append("🧪 DEMO — haqiqiy e’lon emas")
    lines.extend(["", age(listing["published_at"], now)])
    if listing.get("match_info"):
        info = listing["match_info"]
        lines.extend([f"🔗 Moslik balli: {info['score']}/100", escape("; ".join(info["reasons"]))])
    return "\n".join(lines)


def raw_text(data: dict) -> str:
    if data.get("raw_text"):
        return data["raw_text"]
    return "\n".join([
        label(data["origin"]), ", ".join(label(x) for x in data["destinations"]),
        data["description"], "", "🚚 " + ", ".join(VEHICLES[x] for x in data["vehicles"]),
        "Hajm: " + data.get("capacity", "—"), "Narx: " + data.get("price", "Kelishiladi"),
        "Sana: " + (data.get("ready_date") or "Kelishiladi"), "📞 " + data["phone"],
    ])


def detail(listing: dict, counts: dict) -> str:
    if listing["data"].get("normalized"):
        from .parser import trim_units
        data = listing["data"]
        title = "📦 YUK E’LONI" if data["kind"] == "cargo" else "🚚 TRANSPORT E’LONI"
        lines = [f"<b>{title} #{listing['id']}</b>",
                 "📍 Jo‘nash: " + escape(label(data["origin"])),
                 "🏁 Manzil: " + escape("; ".join(label(x) for x in data["destinations"])),
                 "🚛 Avto: " + ", ".join(VEHICLES[x] for x in data["vehicles"]),
                 "📦 Tavsif: " + escape(trim_units(data["description"], 350)),
                 "⚖️ Hajm: " + escape(data.get("capacity", "—")),
                 "💰 Narx: " + escape(data.get("price", "Kelishiladi"))]
        if data.get("ready_date"):
            lines.append("📅 Sana: " + escape(data["ready_date"]))
        if data.get("phone"):
            lines.append("📞 " + escape(data["phone"]))
        if data.get("extraction_method"):
            lines.append("🔎 Ajratish: " + ("AI taklifi, admin tasdiqlagan" if data["extraction_method"] == "ai_proposal" else "Matn qoidalari"))
        raw = trim_units(raw_text(data), 1200)
        lines.extend(["", "<b>Asl matn" + (" (qisqartirilgan)" if raw != raw_text(data) else "") + "</b>", escape(raw),
                      f"\n👀 {counts['view']}   📞 {counts['phone']}"])
        return "\n".join(lines)
    return escape(raw_text(listing["data"])) + f"\n\n👀 {counts['view']}   📞 {counts['phone']}"


def local_date(timestamp: int, timezone: str) -> str:
    return datetime.fromtimestamp(timestamp, ZoneInfo(timezone)).strftime("%Y-%m-%d %H:%M")


def extraction_summary(data: dict) -> str:
    from .parser import trim_units
    def location(value):
        return value.get("city") or value.get("country") or "Aniqlanmagan"
    kind = {"cargo": "Yuk", "vehicle": "Transport"}.get(data.get("kind"), "Aniqlanmagan")
    lines = ["Taklif qilingan maydonlar:", "Tur: " + kind,
             "Jo‘nash: " + location(data.get("origin") or {}),
             "Manzil: " + ("; ".join(location(x) for x in data.get("destinations", [])) or "Aniqlanmagan"),
             "Avto: " + (", ".join(VEHICLES[x] for x in data.get("vehicles", []) if x in VEHICLES) or "Aniqlanmagan"),
             "Hajm: " + data.get("capacity", "Aniqlanmagan"),
             "Narx: " + data.get("price", "Aniqlanmagan")]
    if data.get("extraction_method") == "ai_proposal":
        lines.append("Usul: AI taklifi — admin tekshirishi kerak")
        lines.extend("AI noaniqligi: " + x for x in data.get("ai_uncertainties", []))
        lines.extend("Dalil (" + k + "): " + v for k, v in data.get("ai_evidence", {}).items())
    return escape(trim_units("\n".join(lines), 1100))


def terms(days: int, manual: bool = True) -> str:
    payment = ("1, 2, 3 yoki 6 kalendar oylik tarif tanlanadi. Karta to‘lovi va chekni admin bankdagi tushum "
               "bilan tekshirgandan keyin obuna yoqiladi. Chek yuborishning o‘zi kirishni ochmaydi. "
               if manual else f"Tasdiqlangan to‘lov {days} kunlik kirish beradi. ")
    return (f"<b>Xizmat shartlari — v{TERMS_VERSION}</b>\n\n"
            "Bot yuk va transport e’lonlarini qidirish va e’lon berish uchun xizmat qiladi. "
            "Yo‘nalish, yuk holati, narx va transportni e’lon muallifi bilan aniqlashtiring.\n\n" +
            payment +
            "Avtomatik uzaytirish yo‘q.\n\n"
            "Bot Telegram ID, e’lon, chek fayli identifikatori va tasdiqlash tarixini saqlaydi. "
            "Siz qo‘shgan telefon e’lon bilan birga tegishli foydalanuvchilarga ko‘rsatiladi.\n\n"
            "To‘lov, qaytarish yoki shaxsiy ma’lumot bo‘yicha yordam: /paysupport.")
