from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo


def load_dotenv(path: str = ".env") -> None:
    """Read simple KEY=value files without executing their contents."""
    if not Path(path).is_file():
        return
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or not key.strip().replace("_", "").isalnum():
            raise ValueError(".env ichida KEY=value shaklida yozing.")
        value = value.strip()
        if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


def _bool(value: str) -> bool:
    if value.lower() not in {"true", "false"}:
        raise ValueError("PAID_ACCESS faqat true yoki false bo‘lishi kerak.")
    return value.lower() == "true"


@dataclass(frozen=True)
class Settings:
    token: str = field(default="", repr=False)
    database_path: str = "data/bot.sqlite3"
    bot_name: str = "Logistika Bot"
    timezone: str = "Asia/Tashkent"
    admin_ids: frozenset[int] = frozenset()
    source_chat_ids: frozenset[int] = frozenset()
    paid_access: bool = True
    payment_mode: str = "manual"
    card_number: str = field(default="", repr=False)
    card_holder: str = ""
    tariff_prices_uzs: tuple[int, int, int, int] = (0, 0, 0, 0)
    plan_price_stars: int = 0
    plan_days: int = 30
    support_username: str = ""
    listing_ttl_days: int = 7
    page_size: int = 5
    search_limit: int = 5000
    session_hours: int = 24
    source_limit: int = 500
    telegram_api_id: int = 0
    telegram_api_hash: str = field(default="", repr=False)
    collector_session: str = "data/collector"

    def tariff_price(self, months: int) -> int:
        return dict(zip((1, 2, 3, 6), self.tariff_prices_uzs, strict=True)).get(months, 0)

    def validate_collector(self) -> None:
        import re
        if self.telegram_api_id <= 0 or not re.fullmatch(r"[a-fA-F0-9]{32}", self.telegram_api_hash):
            raise ValueError("TELEGRAM_API_ID va TELEGRAM_API_HASH sozlamalarini kiriting.")

    def validate(self, require_token: bool = False) -> None:
        ZoneInfo(self.timezone)
        if require_token and not self.token:
            raise ValueError(".env ichiga BOT_TOKEN kiriting.")
        if self.payment_mode not in {"manual", "stars"}:
            raise ValueError("PAYMENT_MODE manual yoki stars bo‘lsin.")
        if len(self.tariff_prices_uzs) != 4 or any(x < 0 for x in self.tariff_prices_uzs):
            raise ValueError("1, 2, 3 va 6 oylik tarif narxlari manfiy bo‘lmasin.")
        if self.card_number and (not self.card_number.isascii() or not self.card_number.isdigit()
                                 or not 16 <= len(self.card_number) <= 19):
            raise ValueError("PAYMENT_CARD_NUMBER 16–19 ta raqam bo‘lsin.")
        if self.payment_mode == "manual" and any(self.tariff_prices_uzs):
            if not self.card_number or not self.card_holder or not self.admin_ids or not self.support_username:
                raise ValueError("Karta to‘lovi uchun karta, egasi, ADMIN_IDS va SUPPORT_USERNAME kerak.")
        if not 1 <= self.source_limit <= 2000 or len(self.source_chat_ids) > self.source_limit:
            raise ValueError("Guruhlar soni SOURCE_LIMIT chegarasidan oshmasin (1–2000).")
        if any(x >= 0 for x in self.source_chat_ids):
            raise ValueError("SOURCE_CHAT_IDS faqat guruh/kanalning manfiy ID’laridan iborat bo‘lsin.")
        if not 1 <= self.page_size <= 10:
            raise ValueError("PAGE_SIZE 1–10 oralig‘ida bo‘lsin.")
        if not 1 <= self.search_limit <= 10000:
            raise ValueError("SEARCH_LIMIT 1–10000 oralig‘ida bo‘lsin.")
        if not 1 <= self.plan_days <= 365 or self.plan_price_stars < 0:
            raise ValueError("PLAN_DAYS 1–365 va PLAN_PRICE_STARS >= 0 bo‘lsin.")
        if not 1 <= self.listing_ttl_days <= 365 or not 1 <= self.session_hours <= 168:
            raise ValueError("E’lon yoki qidiruv amal muddati noto‘g‘ri.")
        if self.plan_price_stars and not self.support_username:
            raise ValueError("Sotuv uchun SUPPORT_USERNAME kiriting.")
        if self.support_username:
            import re
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,31}", self.support_username):
                raise ValueError("SUPPORT_USERNAME havola emas, Telegram username bo‘lsin.")
        if any(x <= 0 for x in self.admin_ids):
            raise ValueError("ADMIN_IDS musbat foydalanuvchi ID’laridan iborat bo‘lsin.")

    @classmethod
    def from_env(cls) -> Settings:
        def ids(name: str) -> frozenset[int]:
            return frozenset(int(x.strip()) for x in os.getenv(name, "").split(",") if x.strip())
        settings = cls(
            token=os.getenv("BOT_TOKEN", "").strip(),
            database_path=os.getenv("DATABASE_PATH", "data/bot.sqlite3"),
            bot_name=os.getenv("BOT_NAME", "Logistika Bot"),
            timezone=os.getenv("TIMEZONE", "Asia/Tashkent"),
            admin_ids=ids("ADMIN_IDS"), source_chat_ids=ids("SOURCE_CHAT_IDS"),
            paid_access=_bool(os.getenv("PAID_ACCESS", "true")),
            payment_mode=os.getenv("PAYMENT_MODE", "manual").strip().lower(),
            card_number="".join(os.getenv("PAYMENT_CARD_NUMBER", "").split()),
            card_holder=os.getenv("PAYMENT_CARD_HOLDER", "").strip(),
            tariff_prices_uzs=tuple(int(os.getenv(f"TARIFF_{m}_MONTH_UZS", "0")) for m in (1, 2, 3, 6)),
            plan_price_stars=int(os.getenv("PLAN_PRICE_STARS", "0")),
            plan_days=int(os.getenv("PLAN_DAYS", "30")),
            support_username=os.getenv("SUPPORT_USERNAME", "").strip().lstrip("@"),
            listing_ttl_days=int(os.getenv("LISTING_TTL_DAYS", "7")),
            page_size=int(os.getenv("PAGE_SIZE", "5")),
            search_limit=int(os.getenv("SEARCH_LIMIT", "5000")),
            session_hours=int(os.getenv("SESSION_HOURS", "24")),
            source_limit=int(os.getenv("SOURCE_LIMIT", "500")),
            telegram_api_id=int(os.getenv("TELEGRAM_API_ID", "0")),
            telegram_api_hash=os.getenv("TELEGRAM_API_HASH", "").strip(),
            collector_session=os.getenv("COLLECTOR_SESSION", "data/collector"),
        )
        settings.validate()
        return settings
