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
    plan_price_stars: int = 0
    plan_days: int = 30
    support_username: str = ""
    listing_ttl_days: int = 7
    page_size: int = 5
    search_limit: int = 5000
    session_hours: int = 24

    def validate(self, require_token: bool = False) -> None:
        ZoneInfo(self.timezone)
        if require_token and not self.token:
            raise ValueError(".env ichiga BOT_TOKEN kiriting.")
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
            plan_price_stars=int(os.getenv("PLAN_PRICE_STARS", "0")),
            plan_days=int(os.getenv("PLAN_DAYS", "30")),
            support_username=os.getenv("SUPPORT_USERNAME", "").strip().lstrip("@"),
            listing_ttl_days=int(os.getenv("LISTING_TTL_DAYS", "7")),
            page_size=int(os.getenv("PAGE_SIZE", "5")),
            search_limit=int(os.getenv("SEARCH_LIMIT", "5000")),
            session_hours=int(os.getenv("SESSION_HOURS", "24")),
        )
        settings.validate()
        return settings
