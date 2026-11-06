from html import escape

from . import ui
from .billing import MONTHS, money
from .domain import InputError, clean_text, parse_channel, validate_listing


def job_suffix(job: dict) -> str:
    return f"{job['chat_id']}:{job['message_id']}:{job['digest'][:12]}"


class AdminFlows:
    def require_admin(self, uid: int):
        if uid not in self.settings.admin_ids:
            raise InputError("Bu bo‘lim faqat admin uchun.")

    async def admin(self, uid: int, text: str):
        self.require_admin(uid)
        parts = text.split()
        command = parts[0].split("@")[0]
        if command in {"/admin", "/stats"}:
            stats = await self.query("stats", self.now())
            extra = await self.query("operations_stats")
            return await self.send(uid, f"<b>Admin panel</b>\n👥 Foydalanuvchi: {stats['users']}\n"
                                   f"⭐ Faol obuna: {stats['subscribers']}\n📦 Faol e’lon: {stats['active']}\n"
                                   f"🧾 Kutilayotgan chek: {extra['pending_payments']}\n"
                                   f"👥 Kuzatuv ro‘yxatidagi guruh: {extra['sources']}\n"
                                   f"📥 Navbat: {extra['queued']} · Tekshiruv: {extra['review']}\n"
                                   f"♻️ Takroriy e’lon: {extra['duplicates']}\n\n"
                                   "/grant_months ID 1|2|3|6 — oy berish\n/revoke ID — obunani yopish\n/hide ELON_ID — e’lonni yopish",
                                   ui.inline([[ui.button("🧾 To‘lov cheklari", "payqueue:0")],
                                              [ui.button("🔎 Saralash navbati", "reviewqueue:0")],
                                              [ui.button("👥 Guruhlar", "sources:0")],
                                              [ui.button("➕ Guruh qo‘shish", "sourceadd")]]))
        if command == "/sources":
            return await self.admin_sources(uid, 0)
        if command == "/template":
            return await self.send(uid, "<pre>#yuk\nJo‘nash: Toshkent\nManzil: Samarqand\nAvto: Tent, Ref\n"
                                   "Tavsif: Qoplangan yuk\nHajm: 20 t\nNarx: Kelishiladi\nTelefon: +998000000000</pre>")
        try:
            if command == "/grant_months" and len(parts) == 3:
                until = await self.query("grant_months", int(parts[1]), int(parts[2]), uid, self.now(), self.settings.timezone)
                return await self.send(uid, "✅ Obuna: " + ui.local_date(until, self.settings.timezone))
            if command == "/grant" and len(parts) == 3:
                until = await self.query("grant", int(parts[1]), int(parts[2]), self.now())
                return await self.send(uid, "✅ Kun bilan berilgan obuna: " + ui.local_date(until, self.settings.timezone))
            if command == "/revoke" and len(parts) == 2 and int(parts[1]) > 0:
                await self.query("revoke", int(parts[1]))
                return await self.send(uid, "Obuna bekor qilindi.")
            if command == "/hide" and len(parts) == 2:
                ok = await self.query("close_listing", int(parts[1]), uid, True)
                return await self.send(uid, "E’lon yopildi." if ok else "E’lon topilmadi.")
        except ValueError as exc:
            raise InputError("ID va muddatni raqam bilan yozing. /admin") from exc
        raise InputError("Buyruq shakli noto‘g‘ri. /admin")

    async def admin_payments(self, uid: int, offset: int):
        rows, total = await self.query("manual_queue", offset)
        keyboard = [[ui.button(f"#{r['id']} · {r['months']} oy · {money(r['amount_uzs'])}", f"payview:{r['id']}")] for r in rows]
        if offset:
            keyboard.append([ui.button("◀️ Oldingi", f"payqueue:{max(0, offset - 10)}")])
        if offset + 10 < total:
            keyboard.append([ui.button("Keyingi ▶️", f"payqueue:{offset + 10}")])
        await self.send(uid, f"🧾 Tasdiqlashni kutayotgan cheklar: {total}", ui.inline(keyboard))

    async def admin_payment_view(self, uid: int, request_id: int):
        payment = await self.query("manual_payment", request_id)
        if not payment:
            raise InputError("Chek topilmadi.")
        text = (f"<b>Chek #{request_id}</b>\nFoydalanuvchi: <code>{payment['user_id']}</code>\n"
                f"So‘ralgan tarif: {payment['months']} oy\nSumma: {money(payment['amount_uzs'])}\n"
                f"Holat: {escape(payment['status'])}\nKarta oxiri: {payment['card_last4']}\n"
                "Bankdagi haqiqiy tushumni tekshirib, yoqiladigan muddatni tanlang.")
        keyboard = []
        if payment["status"] == "pending":
            keyboard = ui.pairs([ui.button(f"{m} oy yoqish", f"paypick:{request_id}:{m}") for m in MONTHS])
            keyboard.append([ui.button("❌ Rad etish", f"payreject:{request_id}")])
        keyboard.append([ui.button("🧾 Cheklar navbati", "payqueue:0")])
        markup = ui.inline(keyboard)
        if payment["receipt_file_id"]:
            method, field = ("sendPhoto", "photo") if payment["receipt_kind"] == "photo" else ("sendDocument", "document")
            await self.api.call(method, chat_id=uid, **{field: payment["receipt_file_id"]}, caption=text,
                                parse_mode="HTML", reply_markup=markup)
        else:
            await self.send(uid, text, markup)

    async def admin_sources(self, uid: int, offset: int):
        rows, total = await self.query("source_list", offset, 10)
        keyboard = []
        for row in rows:
            state = "🟢" if row["enabled"] else "⚪"
            keyboard.append([ui.button(f"{state} {row['title'][:45]} ({row['chat_id']})", f"adm_source:{row['chat_id']}:{0 if row['enabled'] else 1}")])
        if offset:
            keyboard.append([ui.button("◀️ Oldingi", f"sources:{max(0, offset - 10)}")])
        if offset + 10 < total:
            keyboard.append([ui.button("Keyingi ▶️", f"sources:{offset + 10}")])
        keyboard.append([ui.button("➕ Guruh qo‘shish", "sourceadd")])
        await self.send(uid, f"👥 Guruhlar: {total}/{self.settings.source_limit}. Tugma holatni almashtiradi.\n"
                        "Bu ro‘yxat kuzatishga ruxsat beradi; akkauntning guruhga a’zoligini alohida tekshiring.", ui.inline(keyboard))

    async def admin_review_queue(self, uid: int, offset: int):
        rows, total = await self.query("review_queue", offset)
        keyboard = [[ui.button(f"{r['chat_id']} / {r['message_id']} — {r['reason'][:35]}",
                               f"review:{job_suffix(r)}")] for r in rows]
        if offset:
            keyboard.append([ui.button("◀️ Oldingi", f"reviewqueue:{max(0, offset - 10)}")])
        if offset + 10 < total:
            keyboard.append([ui.button("Keyingi ▶️", f"reviewqueue:{offset + 10}")])
        await self.send(uid, f"🔎 Qo‘lda tekshirish kerak bo‘lgan e’lonlar: {total}", ui.inline(keyboard))

    async def admin_job(self, parts: list[str]) -> dict:
        if len(parts) != 4:
            raise InputError("Saralash tugmasi noto‘g‘ri.")
        try:
            key = f"group:{int(parts[1])}:{int(parts[2])}"
        except ValueError as exc:
            raise InputError("E’lon identifikatori noto‘g‘ri.") from exc
        job = await self.query("ingest_job", key)
        if not job or job["status"] != "review" or not job["digest"].startswith(parts[3]):
            raise InputError("E’lon tahrirlangan yoki avval ko‘rib chiqilgan. Navbatni yangilang.")
        return job

    async def admin_callback(self, parts: list[str], user: dict) -> bool:
        action, uid = parts[0], user["id"]
        actions = {"payqueue", "payview", "paypick", "payok", "payreject", "sources", "adm_source", "sourceadd",
                   "reviewqueue", "review", "reviewok", "reviewdrop", "reviewedit"}
        if action not in actions:
            return False
        self.require_admin(uid)
        if action == "sourceadd":
            await self.query("set_state", uid, "admin_source")
            await self.send(uid, "Guruhning raqamli ID va nomini yuboring: -1001234567890 | Guruh nomi. /cancel — bekor qilish.")
            return True
        if action in {"review", "reviewok", "reviewdrop", "reviewedit"}:
            job = await self.admin_job(parts)
            suffix = job_suffix(job)
            if action == "review":
                from .parser import trim_units
                await self.send(uid, "<b>Saralash</b>\nSabab: " + escape(trim_units(job["reason"], 400)) + "\n\n" +
                                ui.extraction_summary(job["parsed"]) + "\n\n<b>Asl matn</b>\n" + escape(trim_units(job["raw_text"], 1400)),
                                ui.inline([[ui.button("✅ Chop etish", "reviewok:" + suffix)],
                                           [ui.button("📝 Tuzatib chop etish", "reviewedit:" + suffix)],
                                           [ui.button("🗑 O‘tkazish", "reviewdrop:" + suffix)]]))
            elif action == "reviewedit":
                await self.query("set_state", uid, "admin_review", {"key": job["key"], "digest": job["digest"]})
                await self.send(uid, "Tuzatilgan matnni /template shaklida #yuk yoki #transport bilan yuboring. "
                                "Jo‘nash, Manzil, Avto va Tavsif qatorlari kerak. /cancel — bekor qilish.")
            else:
                decision = {"status": "discarded", "reason": "Admin o‘tkazdi"}
                if action == "reviewok":
                    try:
                        data = validate_listing(job["parsed"])
                    except InputError as exc:
                        raise InputError("Maydonlar to‘liq emas. Tuzatib chop etish tugmasidan foydalaning.") from exc
                    decision = {"status": "accepted", "data": data}
                result = await self.query("ingest_finish", job["key"], job["digest"], decision, self.now(), self.settings.listing_ttl_days, uid)
                await self.send(uid, "✅ Natija: " + result["status"] if result else "E’lon yangilangan. Navbatni qayta oching.")
            return True
        if len(parts) < 2:
            raise InputError("Admin tugmasi noto‘g‘ri.")
        try:
            value = int(parts[1])
        except ValueError as exc:
            raise InputError("Identifikator noto‘g‘ri.") from exc
        if action in {"payqueue", "sources", "reviewqueue"} and not 0 <= value <= 100000:
            raise InputError("Sahifa noto‘g‘ri.")
        if action == "payqueue":
            await self.admin_payments(uid, value)
        elif action == "payview":
            await self.admin_payment_view(uid, value)
        elif action == "paypick":
            if len(parts) != 3 or not parts[2].isdigit() or int(parts[2]) not in MONTHS:
                raise InputError("1, 2, 3 yoki 6 oyni tanlang.")
            payment = await self.query("manual_payment", value)
            if not payment or payment["status"] != "pending":
                raise InputError("Bu chek tasdiqlash navbatida emas.")
            await self.send(uid, f"Chek #{value}: so‘ralgan {payment['months']} oy, {money(payment['amount_uzs'])}.\n"
                            f"Bankdagi tushumni tekshirdingizmi? <b>{parts[2]} oy</b> kirishni tasdiqlaysiz.",
                            ui.inline([[ui.button("✅ Tasdiqlayman", f"payok:{value}:{parts[2]}")],
                                       [ui.button("Chekka qaytish", f"payview:{value}")]]))
        elif action == "payok":
            if len(parts) != 3 or not parts[2].isdigit():
                raise InputError("Muddat noto‘g‘ri.")
            payment, fresh = await self.query("approve_manual", value, uid, int(parts[2]), self.now(), self.settings.timezone)
            until = ui.local_date(payment["fulfilled_until"], self.settings.timezone)
            await self.send(uid, f"✅ Chek #{value}: {payment['approved_months']} oy. Obuna: {until}." + ("" if fresh else " Avval tasdiqlangan."))
            if fresh:
                try:
                    await self.send(payment["user_id"], f"✅ Chekingiz tasdiqlandi. {payment['approved_months']} oylik obuna {until} gacha faol.", ui.main_keyboard())
                except Exception:
                    pass
        elif action == "payreject":
            payment = await self.query("manual_payment", value)
            if not payment or payment["status"] != "pending":
                raise InputError("Bu chek avval ko‘rib chiqilgan.")
            await self.query("set_state", uid, "admin_reject", {"payment_id": value})
            await self.send(uid, "Rad etish sababini yozing (3–300 belgi). /cancel — bekor qilish.")
        elif action == "sources":
            await self.admin_sources(uid, value)
        elif action == "adm_source":
            if len(parts) != 3 or parts[2] not in {"0", "1"}:
                raise InputError("Guruh tugmasi noto‘g‘ri.")
            await self.query("source_toggle", value, parts[2] == "1", uid, self.now())
            await self.admin_sources(uid, 0)
        elif action == "reviewqueue":
            await self.admin_review_queue(uid, value)
        return True

    async def admin_message(self, event: dict, user: dict):
        uid, context = user["id"], user["context"]
        self.require_admin(uid)
        text = (event.get("text") or "").strip()
        if user["state"] == "admin_reject":
            payment = await self.query("reject_manual", context["payment_id"], uid, text, self.now())
            await self.query("set_state", uid, "home")
            await self.send(uid, "Chek rad etildi.")
            try:
                await self.send(payment["user_id"], "❌ Chek tasdiqlanmadi. Sabab: " + escape(payment["reason"]) + "\n/subscribe orqali qayta boshlashingiz mumkin.")
            except Exception:
                pass
        elif user["state"] == "admin_source":
            number, _, title = text.partition("|")
            try:
                chat_id = int(number.strip())
            except ValueError as exc:
                raise InputError("Masalan: -1001234567890 | Guruh nomi") from exc
            await self.query("source_put", chat_id, clean_text(title.strip() or number, 100), self.now(), self.settings.source_limit, uid)
            await self.query("set_state", uid, "home")
            await self.admin_sources(uid, 0)
        elif user["state"] == "admin_review":
            data = parse_channel(text)
            result = await self.query("ingest_finish", context["key"], context["digest"], {"status": "accepted", "data": data},
                                      self.now(), self.settings.listing_ttl_days, uid)
            await self.query("set_state", uid, "home")
            await self.send(uid, "✅ E’lon: " + result["status"] if result else "E’lon yangilangan. Navbatni qayta oching.")
