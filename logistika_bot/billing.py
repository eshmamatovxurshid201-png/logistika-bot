from html import escape

from . import ui
from .domain import InputError

MONTHS = (1, 2, 3, 6)


def money(amount: int) -> str:
    return f"{amount:,}".replace(",", " ") + " so‘m"


class BillingFlows:
    async def require_access(self, uid: int) -> bool:
        user = await self.query("user", uid, self.now())
        if (not self.settings.paid_access or uid in self.settings.admin_ids
                or user["subscription_until"] > self.now()):
            return True
        await self.send(uid, "🔒 E’lonlarni ko‘rish va qidirish uchun faol obuna kerak. "
                        "To‘lov cheki admin tomonidan tasdiqlangach kirish ochiladi.",
                        ui.inline([[ui.button("⭐ Tariflar va to‘lov", "plan")]]))
        return False

    async def plan(self, user: dict):
        uid = user["id"]
        if not self.settings.paid_access:
            return await self.send(uid, "Hozir ochiq sinov rejimi yoqilgan.")
        if user["terms_version"] != ui.TERMS_VERSION:
            return await self.send(uid, ui.terms(self.settings.plan_days, self.settings.payment_mode == "manual"),
                                   ui.inline([[ui.button("Shartlarni qabul qilaman", "accept:" + ui.TERMS_VERSION)]]))
        if self.settings.payment_mode == "stars":
            if not self.settings.plan_price_stars:
                return await self.send(uid, "Obuna savdosi hali yoqilmagan. /paysupport")
            return await self.send(uid, f"⭐ {self.settings.plan_days} kun: {self.settings.plan_price_stars} Stars.",
                                   ui.inline([[ui.button("⭐ Sotib olish", "buy")]]))
        existing = await self.query("manual_open", uid)
        if existing:
            return await self.manual_status(existing)
        rows = [[ui.button(f"{months} oy — " + (money(self.settings.tariff_price(months))
                 if self.settings.tariff_price(months) else "narx belgilanmagan"), f"manual:{months}")]
                for months in MONTHS]
        text = "<b>1, 2, 3 yoki 6 oylik tarifni tanlang.</b>\nTo‘lovdan keyin chek yuborasiz. Admin bankdagi tushumni tekshirib kirishni yoqadi."
        if user["subscription_until"] > self.now():
            text += "\nAmaldagi obuna: " + ui.local_date(user["subscription_until"], self.settings.timezone)
        await self.send(uid, text, ui.inline(rows))

    async def manual_status(self, payment: dict):
        uid = payment["user_id"]
        if payment["status"] == "pending":
            return await self.send(uid, f"⏳ Chek #{payment['id']} admin tekshiruvini kutmoqda. "
                                   "Tasdiqlangach xabar beriladi. /paysupport")
        await self.query("set_state", uid, "payment_receipt", {"payment_id": payment["id"]})
        card = self.settings.card_number
        if not card or card[-4:] != payment["card_last4"]:
            return await self.send(uid, "Karta rekvizitlari o‘zgargan. To‘lovdan oldin so‘rovni bekor qilib tarifni qayta tanlang. "
                                   "Avval to‘lagan bo‘lsangiz /paysupport orqali aniqlashtiring.",
                                   ui.inline([[ui.button("So‘rovni bekor qilish", f"paycancel:{payment['id']}")]]))
        grouped = " ".join(card[i:i + 4] for i in range(0, len(card), 4))
        text = (f"<b>To‘lov so‘rovi #{payment['id']}</b>\nTarif: {payment['months']} oy\n"
                f"Summa: <b>{money(payment['amount_uzs'])}</b>\n\n"
                f"Karta: <code>{grouped}</code>\nEgasi: {escape(self.settings.card_holder)}\n\n"
                "To‘lovni amalga oshirgach chekni rasm yoki PDF qilib shu chatga yuboring (10 MB gacha). "
                "Kirish chek yuborilganda emas, admin tasdiqlaganda ochiladi.")
        await self.send(uid, text, ui.inline([[ui.button("To‘lov so‘rovini bekor qilish", f"paycancel:{payment['id']}")]]))

    async def receipt_message(self, event: dict, user: dict):
        request_id = user["context"].get("payment_id")
        if not request_id:
            raise InputError("Avval /subscribe orqali tarif tanlang.")
        kind = "photo"
        photos = event.get("photo", [])
        document = event.get("document")
        if photos:
            file = photos[-1]
        elif document and document.get("mime_type") in {"image/jpeg", "image/png", "application/pdf"}:
            file, kind = document, "document"
        else:
            raise InputError("Chekni rasm yoki PDF fayl sifatida yuboring (10 MB gacha).")
        if file.get("file_size", 0) > 10 * 1024 * 1024:
            raise InputError("Chek fayli 10 MB dan kichik bo‘lsin.")
        await self.query("manual_submit", request_id, user["id"], file.get("file_id", ""),
                         file.get("file_unique_id", ""), kind, self.now())
        await self.query("set_state", user["id"], "home")
        await self.send(user["id"], f"✅ Chek #{request_id} qabul qilindi. Admin tasdiqlashini kuting.", ui.main_keyboard())
        for admin in self.settings.admin_ids:
            try:
                await self.send(admin, f"🧾 Yangi to‘lov cheki #{request_id}.",
                                ui.inline([[ui.button("Chekni tekshirish", f"payview:{request_id}")]]))
            except Exception:
                # Receipt remains in the durable /admin queue if notification fails.
                pass

    async def billing_callback(self, parts: list[str], user: dict) -> bool:
        action, uid = parts[0], user["id"]
        if action == "plan":
            await self.plan(user)
        elif action == "accept":
            if parts != ["accept", ui.TERMS_VERSION]:
                raise InputError("Shartlar yangilangan. /subscribe orqali qayta oching.")
            await self.query("accept_terms", uid, ui.TERMS_VERSION)
            user["terms_version"] = ui.TERMS_VERSION
            await self.plan(user)
        elif action == "manual" and len(parts) == 2 and parts[1].isdigit():
            if self.settings.payment_mode != "manual" or user["terms_version"] != ui.TERMS_VERSION:
                await self.plan(user)
                return True
            months = int(parts[1])
            if (months not in MONTHS or not self.settings.tariff_price(months)
                    or not self.settings.card_number or not self.settings.admin_ids):
                raise InputError("Bu tarif hali sozlanmagan. /paysupport")
            payment = await self.query("manual_create", uid, months, self.settings.tariff_price(months),
                                       self.settings.card_number[-4:], self.now())
            await self.manual_status(payment)
        elif action == "paycancel" and len(parts) == 2 and parts[1].isdigit():
            ok = await self.query("manual_cancel", int(parts[1]), uid)
            if not ok:
                raise InputError("Yuborilgan yoki ko‘rib chiqilgan chek bekor qilinmaydi. /paysupport")
            await self.home(uid)
        elif action == "buy":
            if self.settings.payment_mode != "stars":
                await self.plan(user)
                return True
            await self.buy(user)
        else:
            return False
        return True

    async def buy(self, user: dict):
        if (self.settings.payment_mode != "stars" or not self.settings.paid_access
                or not self.settings.plan_price_stars or user["terms_version"] != ui.TERMS_VERSION):
            return await self.plan(user)
        order = await self.query("order_new", user["id"], self.settings.plan_price_stars,
                                 self.settings.plan_days, self.now())
        await self.api.call("sendInvoice", chat_id=user["id"], title="Logistika obunasi",
                            description=f"{self.settings.plan_days} kunlik e’lonlarga kirish.",
                            payload="access:" + order, currency="XTR", provider_token="",
                            prices=[{"label": "Obuna", "amount": self.settings.plan_price_stars}], start_parameter="access")
