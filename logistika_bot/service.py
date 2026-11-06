from __future__ import annotations

import asyncio
import logging
import secrets
import time
import weakref
from html import escape
from typing import Protocol

from . import ui
from .config import Settings
from .db import Database
from .billing import BillingFlows
from .admin import AdminFlows
from .dispatcher import DispatcherFlows
from .domain import (InputError, VEHICLES, clean_text, date_input, destinations,
                     normalize, parse_channel, parse_query, phone, place, validate_listing)

log = logging.getLogger(__name__)


class Transport(Protocol):
    async def call(self, method: str, **params): ...


class Application(BillingFlows, AdminFlows, DispatcherFlows):
    def __init__(self, settings: Settings, db: Database, api: Transport, clock=time.time):
        self.settings, self.db, self.api, self.clock = settings, db, api, clock
        self.locks: weakref.WeakValueDictionary[int, asyncio.Lock] = weakref.WeakValueDictionary()

    def now(self) -> int:
        return int(self.clock())

    async def query(self, name: str, *args, **kwargs):
        return await asyncio.to_thread(getattr(self.db, name), *args, **kwargs)

    async def send(self, chat_id: int, text: str, keyboard: dict | None = None):
        params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                  "link_preview_options": {"is_disabled": True}}
        if keyboard is not None:
            params["reply_markup"] = keyboard
        return await self.api.call("sendMessage", **params)

    async def edit(self, chat_id: int, message_id: int, text: str, keyboard: dict):
        return await self.api.call("editMessageText", chat_id=chat_id, message_id=message_id,
                                   text=text, parse_mode="HTML", reply_markup=keyboard,
                                   link_preview_options={"is_disabled": True})

    async def handle(self, event_type: str, event: dict):
        if event_type in {"channel_post", "edited_channel_post"}:
            channel_id = event.get("chat", {}).get("id", 0)
            lock = self.locks.setdefault(channel_id, asyncio.Lock())
            async with lock:
                return await self.channel(event)
        user_id = event.get("from", {}).get("id")
        if not isinstance(user_id, int) or user_id <= 0:
            return
        # Checkout must not wait behind a multi-message search response (<10s).
        if event_type == "pre_checkout_query":
            return await self.checkout(event)
        if event_type == "callback_query":
            await self.api.call("answerCallbackQuery", callback_query_id=event["id"])
            chat = event.get("message", {}).get("chat", {})
        else:
            chat = event.get("chat", {})
        if chat.get("type") != "private" or chat.get("id") != user_id:
            return
        lock = self.locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            user = await self.query("user", user_id, self.now())
            try:
                if event_type == "message":
                    await self.message(event, user)
                elif event_type == "callback_query":
                    await self.callback(event, user)
            except InputError as exc:
                await self.send(user_id, escape(str(exc)))

    async def home(self, user_id: int):
        await self.query("set_state", user_id, "home")
        await self.send(user_id, "📦 Yuk va transport qidirish uchun bot. Xush kelibsiz!", ui.main_keyboard())

    async def quick(self, user_id: int):
        if not await self.require_access(user_id):
            return
        await self.query("set_state", user_id, "quick")
        await self.send(user_id, "Kerakli qidiruv bo‘limini tanlang", ui.quick_keyboard())

    async def support(self, user_id: int):
        name = self.settings.support_username
        await self.send(user_id, "Yordam va to‘lov masalalari: " +
                        (f"@{escape(name)}" if name else "bot egasiga murojaat qiling. "
                         "Admin SUPPORT_USERNAME sozlamasini to‘ldirishi kerak."))

    async def message(self, event: dict, user: dict):
        uid = user["id"]
        if event.get("successful_payment"):
            payment = event["successful_payment"]
            payload = payment.get("invoice_payload", "")
            if not payload.startswith("access:"):
                raise InputError("To‘lov turi tanilmadi. /paysupport")
            until, fresh = await self.query("payment", payload[7:], uid, payment["total_amount"],
                                             payment["currency"], payment["telegram_payment_charge_id"], self.now())
            await self.send(uid, ("✅ To‘lov qabul qilindi." if fresh else "✅ Bu to‘lov avval hisoblangan.") +
                            " Obuna: " + ui.local_date(until, self.settings.timezone))
            return
        text = (event.get("text") or "").strip()
        command = text.split(maxsplit=1)[0].split("@")[0] if text else ""
        if command in {"/start", "/cancel"} or text == ui.CANCEL:
            return await self.home(uid)
        if command == "/id":
            return await self.send(uid, f"Sizning Telegram ID: <code>{uid}</code>")
        if command in {"/paysupport", "/support"}:
            return await self.support(uid)
        if command == "/terms":
            return await self.send(uid, ui.terms(self.settings.plan_days, self.settings.payment_mode == "manual"))
        if command == "/help":
            return await self.send(uid, "Tezkor Qidiruv orqali yuk yoki mashina tanlang.\n"
                                   "Bitta joy ikki tomondan qidiriladi; ikki joy yo‘nalishni belgilaydi.\n"
                                   "Misol: Toshkent → Samarqand. Kirill yozuvi ham taniladi.\n"
                                   "/start — menyu; /cancel — bekor qilish; /davom — natijani davom ettirish; "
                                   "/id — ID; /terms — shartlar; /paysupport — yordam.")
        if command in {"/admin", "/stats", "/grant", "/grant_months", "/revoke", "/hide", "/template", "/sources"}:
            return await self.admin(uid, text)
        if command == "/davom":
            sid = user["context"].get("last_session", "")
            session = await self.query("session", sid, uid, self.now())
            if not session or session["data"].get("mode") != "results":
                raise InputError("Davom ettirish uchun avval qidiruv qiling.")
            return await self.show_page(session, session["next_offset"])
        if text == ui.QUICK:
            return await self.quick(uid)
        if text == ui.BACK:
            if user["state"] in {"search", "choose_vehicle"}:
                return await self.quick(uid)
            return await self.home(uid)
        if text == ui.CARGO:
            if not await self.require_access(uid):
                return
            await self.query("set_state", uid, "choose_vehicle", {"kind": "cargo"})
            return await self.send(uid, "🚙 Avto turini o‘zgartirish", ui.vehicle_keyboard())
        if text == ui.VEHICLE:
            return await self.start_search(uid, {"kind": "vehicle", "vehicle": user["vehicle"]})
        if text == ui.ADD:
            await self.query("set_state", uid, "post_kind")
            return await self.send(uid, "Qanday e’lon qo‘shamiz?", ui.reply([["📦 Yuk e’loni"], ["🚚 Transport e’loni"], [ui.CANCEL]]))
        if text == ui.MINE:
            return await self.mine(uid)
        if text == ui.FAVORITES:
            return await self.show_favorites(uid)
        if text == ui.SETTINGS:
            await self.query("set_state", uid, "settings")
            until = user["subscription_until"]
            status = ui.local_date(until, self.settings.timezone) if until > self.now() else "Faol emas"
            access = "Obuna bilan" if self.settings.paid_access else "Ochiq sinov rejimi"
            return await self.send(uid, f"⚙️ Sozlamalar\nKirish: {access}\nObuna: {status}\n"
                                   "Til: O‘zbekcha\nYordam: /paysupport", ui.reply([[ui.SUBSCRIBE], [ui.BACK]]))
        if text == ui.SUBSCRIBE or command == "/subscribe":
            return await self.plan(user)
        if user["state"] == "payment_receipt":
            return await self.receipt_message(event, user)
        if user["state"].startswith("admin_"):
            return await self.admin_message(event, user)
        if user["state"] == "choose_vehicle":
            names = {normalize(v): k for k, v in VEHICLES.items()}
            vehicle = "all" if normalize(text) == "hammasi" else names.get(normalize(text))
            if not vehicle:
                raise InputError("Avto turini pastdagi tugmalardan tanlang.")
            await self.query("set_vehicle", uid, vehicle)
            return await self.start_search(uid, {"kind": user["context"].get("kind", "cargo"), "vehicle": vehicle})
        if user["state"].startswith("post_"):
            return await self.post_message(event, user, text)
        if user["state"] == "search":
            if text.startswith("Joriy:"):
                await self.query("set_state", uid, "choose_vehicle", user["context"])
                return await self.send(uid, "🚙 Avto turini o‘zgartirish", ui.vehicle_keyboard())
            filters = {k: v for k, v in user["context"].items() if k in {"kind", "vehicle"}}
            filters["query"] = parse_query(text)
            return await self.results(uid, filters)
        await self.send(uid, "Boshlash uchun menyudan bo‘lim tanlang yoki /start yozing.", ui.main_keyboard())

    async def start_search(self, uid: int, filters: dict):
        if not await self.require_access(uid):
            return
        await self.query("set_state", uid, "search", filters)
        if filters["kind"] == "cargo":
            text = ("Yuklarni topish uchun jo‘nash va yetib borish shahar yoki mamlakatini kiriting.\n\n"
                    "Misollar:\n🔘 Toshkent\n🔘 Toshkent Samarqand\n🔘 Стамбул Olmata\n\n"
                    "Bitta joy yo‘nalishning ikkala tomonidan qidiriladi.")
            await self.send(uid, text, ui.current_keyboard(filters["vehicle"]))
        else:
            await self.send(uid, "🚚 Transport qidiruvi", ui.current_keyboard(filters["vehicle"]))
            await self.geography(uid, filters)

    async def geography(self, uid: int, filters: dict, message_id: int | None = None):
        if not await self.require_access(uid):
            return
        data = await self.query("geography", filters, self.now(), self.settings.timezone)
        session = await self.query("session_new", uid, data, self.now(), self.settings.session_hours)
        title = filters.get("country") or "Mamlakatni tanlang"
        text = f"🚚 {data['total']} ta e’lon topildi, {data['today']} tasi bugungi\n{escape(title)}"
        if not data["total"]:
            text += "\nHozircha mos transport yo‘q. Boshqa avto turi yoki yo‘nalishni sinang."
        if message_id is None:
            await self.send(uid, text, ui.geo_keyboard(session))
        else:
            await self.edit(uid, message_id, text, ui.geo_keyboard(session))

    async def results(self, uid: int, filters: dict):
        if not await self.require_access(uid):
            return
        ids, total = await self.query("search", filters, self.now(), self.settings.search_limit)
        if not ids:
            return await self.send(uid, "Mos e’lon topilmadi. Boshqa joy yoki avto turini tanlang.")
        data = {"mode": "results", "ids": ids, "total": total, "filters": filters}
        session = await self.query("session_new", uid, data, self.now(), self.settings.session_hours)
        await self.query("set_state", uid, "search", {"kind": filters["kind"],
                         "vehicle": filters.get("vehicle", "all"), "last_session": session["id"]})
        text = f"🔎 {total} ta e’lon topildi."
        if total > len(ids):
            text += f" Dastlabki {len(ids)} tasi ko‘rsatiladi; qidiruvni toraytirishingiz mumkin."
        await self.send(uid, text)
        await self.show_page(session, 0)

    async def show_page(self, session: dict, expected: int):
        uid, sid = session["user_id"], session["id"]
        if not await self.require_access(uid):
            return
        if expected != session["next_offset"]:
            return await self.send(uid, "Bu sahifa avval ochilgan. /davom bilan keyingisini oching.")
        ids = session["data"]["ids"]
        offset = expected
        while offset < len(ids):
            end = min(offset + self.settings.page_size, len(ids))
            listings = await self.query("listings", ids[offset:end])
            live = [(i, listings[lid]) for i, lid in enumerate(ids[offset:end], offset)
                    if lid in listings and listings[lid]["status"] == "active" and listings[lid]["expires_at"] > self.now()]
            for index, listing in live:
                lid = listing["id"]
                if await self.query("card", sid, lid):
                    continue  # A previous partial page was already sent.
                more = end if index == live[-1][0] and end < len(ids) else None
                if str(lid) in session["data"].get("match_info", {}):
                    listing = dict(listing, match_info=session["data"]["match_info"][str(lid)])
                saved = await self.query("favorite_has", uid, lid)
                result = await self.send(uid, ui.brief(listing, index + 1, self.now()),
                                         ui.card_keyboard(sid, lid, more_offset=more, total=len(ids), saved=saved))
                await self.query("card_save", sid, lid, result["message_id"], index + 1, more)
            await self.query("page_done", sid, offset, end)
            if live:
                return
            offset = end
        await self.send(uid, "Natijalar tugadi. Yangi yo‘nalish yozishingiz mumkin.")

    def accessible(self, user: dict, listing: dict) -> bool:
        return (not self.settings.paid_access or user["id"] in self.settings.admin_ids
                or listing["owner_id"] == user["id"] or user["subscription_until"] > self.now())

    async def callback(self, event: dict, user: dict):
        uid = user["id"]
        parts = event.get("data", "").split(":")
        action = parts[0]
        message_id = event.get("message", {}).get("message_id")
        if await self.billing_callback(parts, user):
            return
        if await self.admin_callback(parts, user):
            return
        if action == "draft" and len(parts) == 2:
            if parts[1] == "cancel":
                return await self.home(uid)
            if user["state"] != "post_vehicles":
                raise InputError("Bu tanlov eskirgan. Yangi e’lonni menyudan boshlang.")
            draft = user["context"]
            if parts[1] == "next":
                if not draft["vehicles"]:
                    raise InputError("Kamida bitta transport tanlang.")
                await self.query("set_state", uid, "post_origin", draft)
                return await self.send(uid, "Jo‘nash joyini yozing. Masalan: Toshkent yoki Turkiya / Chorlu.",
                                       ui.reply([[ui.CANCEL]]))
            if parts[1] not in VEHICLES:
                raise InputError("Transport turi tanilmadi.")
            selected = draft["vehicles"]
            selected.remove(parts[1]) if parts[1] in selected else selected.append(parts[1])
            await self.query("set_state", uid, "post_vehicles", draft)
            return await self.edit(uid, message_id, "Bir yoki bir nechta avto turini tanlang:", ui.post_vehicles(selected))
        if action == "publish" and len(parts) == 2:
            draft = user["context"]
            if user["state"] != "post_confirm" or draft.get("draft_id") != parts[1]:
                raise InputError("E’lon avval saqlangan yoki tanlov eskirgan.")
            lid = await self.query("save_listing", draft, uid, f"post:{uid}:{parts[1]}", self.now(), self.settings.listing_ttl_days)
            await self.query("set_state", uid, "home")
            return await self.send(uid, f"✅ E’lon #{lid} chop etildi.", ui.main_keyboard())
        if action == "close" and len(parts) == 2 and parts[1].isdigit():
            closed = await self.query("close_listing", int(parts[1]), uid, uid in self.settings.admin_ids)
            if not closed:
                raise InputError("Bu e’lon sizga tegishli emas.")
            return await self.edit(uid, message_id, "🛑 E’lon yopildi.", ui.inline([]))
        if len(parts) < 2:
            raise InputError("Tugma tanilmadi. /start bilan boshlang.")
        if not await self.require_access(uid):
            return
        session = await self.query("session", parts[1], uid, self.now())
        if not session:
            raise InputError("Qidiruv muddati tugagan. Yangi qidiruvni boshlang.")
        data = session["data"]
        if action in {"geo", "geoback", "geopage"} and data.get("mode") == "geo":
            if action == "geoback":
                if data["cities"]:
                    filters = {k: v for k, v in data["filters"].items() if k != "country"}
                    return await self.geography(uid, filters, message_id)
                return await self.quick(uid)
            if len(parts) != 3 or not parts[2].isdigit():
                raise InputError("Hudud tugmasi noto‘g‘ri.")
            index = int(parts[2])
            if action == "geopage":
                if index % 40 or not 0 <= index < max(1, len(data["options"])):
                    raise InputError("Hudud sahifasi noto‘g‘ri.")
                return await self.edit(uid, message_id, f"🚚 {data['total']} ta e’lon, {data['today']} tasi bugungi",
                                       ui.geo_keyboard(session, index))
            if not 0 <= index < len(data["options"]):
                raise InputError("Hudud tugmasi eskirgan.")
            filters = dict(data["filters"])
            filters["city" if data["cities"] else "country"] = data["options"][index][
                "key" if data["cities"] else "name"]
            if data["cities"]:
                return await self.results(uid, filters)
            return await self.geography(uid, filters, message_id)
        if data.get("mode") != "results" or len(parts) != 3 or not parts[2].isdigit():
            raise InputError("Tugma tanilmadi.")
        if action == "more":
            return await self.show_page(session, int(parts[2]))
        lid = int(parts[2])
        card = await self.query("card", session["id"], lid)
        if not card or card["message_id"] != message_id:
            raise InputError("E’lon ushbu qidiruvga tegishli emas.")
        listing = await self.query("listing", lid)
        if not listing or listing["status"] != "active" or listing["expires_at"] <= self.now():
            return await self.edit(uid, message_id, "Bu e’lon yopilgan yoki amal muddati tugagan.", ui.inline([]))
        if action not in {"detail", "brief", "phone", "source", "save", "unsave", "match"}:
            raise InputError("Tugma tanilmadi.")
        if action != "brief" and not self.accessible(user, listing):
            return await self.send(uid, "🔒 Batafsil ma’lumot va kontaktlar uchun faol obuna kerak.",
                                   ui.inline([[ui.button("⭐ Obunani ko‘rish", "plan")]]))
        if action in {"save", "unsave"}:
            await self.query("favorite_set", uid, lid, action == "save", self.now())
            return await self.send(uid, "⭐ Tanlanganlarga saqlandi." if action == "save" else "Tanlanganlardan olib tashlandi.")
        if action == "match":
            return await self.show_matches(uid, listing)
        saved = await self.query("favorite_has", uid, lid)
        keyboard = ui.card_keyboard(session["id"], lid, detail=action != "brief",
                                    more_offset=card["more_offset"], total=len(data["ids"]), saved=saved)
        if action == "brief":
            return await self.edit(uid, message_id, ui.brief(listing, card["ordinal"], self.now()), keyboard)
        if action == "source":
            url = listing["data"].get("source_url")
            if not url:
                return await self.send(uid, "Bu e’lon bot orqali qo‘shilgan; tashqi xabar havolasi yo‘q.")
            return await self.send(uid, "E’lonning asl xabari. Yopiq kanal bo‘lsa a’zolik talab qilinishi mumkin.",
                                   ui.inline([[{"text": "Xabarni ochish ↗️", "url": url}]]))
        if action == "phone":
            if not listing["data"].get("phone"):
                return await self.send(uid, "E’londa telefon ko‘rsatilmagan. Mavjud bo‘lsa Xabarga o‘tish tugmasidan foydalaning.")
            await self.api.call("sendContact", chat_id=uid, phone_number=listing["data"]["phone"],
                                first_name=f"E’lon #{lid}")
        counts = await self.query("event", uid, lid, "phone" if action == "phone" else "view", self.now())
        return await self.edit(uid, message_id, ui.detail(listing, counts), keyboard)

    async def post_message(self, event: dict, user: dict, text: str):
        uid, state, draft = user["id"], user["state"], dict(user["context"])
        if state == "post_kind":
            kind = {"📦 Yuk e’loni": "cargo", "🚚 Transport e’loni": "vehicle"}.get(text)
            if not kind:
                raise InputError("E’lon turini pastdagi tugmadan tanlang.")
            draft = {"kind": kind, "vehicles": [], "draft_id": secrets.token_hex(8)}
            await self.query("set_state", uid, "post_vehicles", draft)
            await self.send(uid, "E’lon qo‘shish boshlandi.", ui.reply([[ui.CANCEL]]))
            return await self.send(uid, "Bir yoki bir nechta avto turini tanlang:", ui.post_vehicles([]))
        transitions = {
            "post_origin": ("origin", "post_destination", "Yetib borish joyi. Bir nechta manzilni ; bilan ajrating."),
            "post_destination": ("destinations", "post_description", "Yuk yoki transport haqida tavsif yozing (3–1800 belgi)."),
            "post_description": ("description", "post_capacity", "Og‘irlik / hajm. Masalan: 20 t, 96 m³."),
            "post_capacity": ("capacity", "post_date", "Yuklash yoki bo‘sh bo‘lish sanasi: Bugun, Ertaga yoki YYYY-MM-DD."),
            "post_date": ("ready_date", "post_price", "Narxni yozing. Masalan: 2 000 000 so‘m yoki Kelishiladi."),
            "post_price": ("price", "post_phone", "Telefon raqamingizni yuboring yoki +998901234567 shaklida yozing."),
        }
        if state in transitions:
            field, next_state, prompt = transitions[state]
            if state == "post_origin":
                value = place(text)
            elif state == "post_destination":
                value = destinations(text)
            elif state == "post_date":
                value = date_input(text, self.now(), self.settings.timezone)
            elif text == ui.SKIP and state in {"post_capacity", "post_price"}:
                value = "—" if state == "post_capacity" else "Kelishiladi"
            else:
                value = clean_text(text, 1800 if state == "post_description" else 80,
                                   3 if state == "post_description" else 1)
            draft[field] = value
            await self.query("set_state", uid, next_state, draft)
            rows = [[ui.CANCEL]]
            if next_state in {"post_capacity", "post_date", "post_price"}:
                rows.insert(0, [ui.SKIP])
            if next_state == "post_date":
                rows.insert(0, ["Bugun", "Ertaga"])
            if next_state == "post_phone":
                rows.insert(0, [{"text": "📞 Raqamimni yuborish", "request_contact": True}])
            return await self.send(uid, prompt, ui.reply(rows))
        if state == "post_phone":
            contact = event.get("contact")
            if contact:
                if contact.get("user_id") != uid:
                    raise InputError("O‘z kontaktingizni yuboring yoki raqamni matn bilan kiriting.")
                text = contact["phone_number"]
            draft["phone"] = phone(text)
            draft = validate_listing(draft)
            await self.query("set_state", uid, "post_confirm", draft)
            await self.send(uid, "E’lonni tekshiring:", ui.reply([[ui.CANCEL]]))
            return await self.send(uid, escape(ui.raw_text(draft)), ui.inline([
                [ui.button("✅ Chop etish", "publish:" + draft["draft_id"])],
                [ui.button(ui.CANCEL, "draft:cancel")]]))
        raise InputError("Tanlovni xabardagi tugmalar orqali davom ettiring yoki /cancel yozing.")

    async def mine(self, uid: int):
        await self.query("set_state", uid, "home")
        listings = await self.query("mine", uid, self.now())
        if not listings:
            return await self.send(uid, "Sizda faol e’lon yo‘q.", ui.main_keyboard())
        await self.send(uid, "Sizning faol e’lonlaringiz (eng so‘nggi 30 ta):", ui.main_keyboard())
        for i, listing in enumerate(listings, 1):
            await self.send(uid, ui.brief(listing, i, self.now()),
                            ui.inline([[ui.button("🛑 E’lonni yopish", f"close:{listing['id']}")]]))

    async def checkout(self, event: dict):
        payload = event.get("invoice_payload", "")
        ok = self.settings.payment_mode == "stars" and payload.startswith("access:") and await self.query(
            "order_check", payload[7:], event["from"]["id"], event["total_amount"], event["currency"], self.now())
        params = {"pre_checkout_query_id": event["id"], "ok": bool(ok)}
        if not ok:
            params["error_message"] = "Buyurtma eskirgan yoki sizga tegishli emas. Yangi hisob yarating: /subscribe"
        await self.api.call("answerPreCheckoutQuery", **params)


    async def channel(self, event: dict):
        from .pipeline import Pipeline
        chat = event.get("chat", {})
        chat_id = chat.get("id")
        source = await self.query("source", chat_id)
        if source is None and chat_id in self.settings.source_chat_ids:
            await self.query("source_put", chat_id, chat.get("title", str(chat_id)), self.now(), self.settings.source_limit)
            source = await self.query("source", chat_id)
        if not source or not source["enabled"]:
            return
        text = event.get("text") or event.get("caption") or ""
        username = chat.get("username")
        link = f"https://t.me/{username}/{event['message_id']}" if username else (
            f"https://t.me/c/{str(chat_id)[4:]}/{event['message_id']}" if str(chat_id).startswith("-100") else None)
        await self.query("ingest_enqueue", chat_id, event["message_id"], text, link,
                         event.get("date", self.now()), event.get("edit_date", event.get("date", self.now())), self.now())
        await asyncio.to_thread(Pipeline(self.db, self.settings, self.clock).process_one)
