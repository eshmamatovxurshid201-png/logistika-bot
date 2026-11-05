from __future__ import annotations

import json
import hashlib
import sqlite3

from .domain import InputError, add_months, clean_text, validate_listing

SCHEMA = """
CREATE TABLE IF NOT EXISTS manual_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id),
    months INTEGER NOT NULL CHECK(months IN (1,2,3,6)), amount_uzs INTEGER NOT NULL,
    card_last4 TEXT NOT NULL, created_at INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'awaiting' CHECK(status IN ('awaiting','pending','approved','rejected','cancelled')),
    receipt_file_id TEXT, receipt_unique_id TEXT UNIQUE, receipt_kind TEXT,
    submitted_at INTEGER, reviewed_at INTEGER, admin_id INTEGER, approved_months INTEGER,
    fulfilled_until INTEGER, reason TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS one_open_payment ON manual_payments(user_id) WHERE status IN ('awaiting','pending');
CREATE INDEX IF NOT EXISTS pending_payments ON manual_payments(status,submitted_at);
CREATE TABLE IF NOT EXISTS admin_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT, admin_id INTEGER NOT NULL, action TEXT NOT NULL,
    target TEXT NOT NULL, data TEXT NOT NULL, created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sources (
    chat_id INTEGER PRIMARY KEY CHECK(chat_id<0), title TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL, last_seen INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS ingest_jobs (
    key TEXT PRIMARY KEY, chat_id INTEGER NOT NULL REFERENCES sources(chat_id), message_id INTEGER NOT NULL,
    raw_text TEXT NOT NULL, source_url TEXT, published_at INTEGER NOT NULL, revision INTEGER NOT NULL,
    digest TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued', parsed TEXT NOT NULL DEFAULT '{}',
    reason TEXT NOT NULL DEFAULT '', listing_id INTEGER REFERENCES listings(id),
    attempts INTEGER NOT NULL DEFAULT 0, retry_at INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL, deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ingest_status ON ingest_jobs(status,retry_at,updated_at);
CREATE INDEX IF NOT EXISTS ingest_source ON ingest_jobs(chat_id,message_id);
CREATE TABLE IF NOT EXISTS fingerprints (
    listing_id INTEGER PRIMARY KEY REFERENCES listings(id), fingerprint TEXT NOT NULL, updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS duplicate_search ON fingerprints(fingerprint,updated_at);
"""


class Operations:
    def ingest_enqueue(self, chat_id: int, message_id: int, text: str, source_url: str | None,
                       published_at: int, revision: int, now: int, deleted: bool = False) -> bool:
        if message_id <= 0 or not 0 <= published_at <= now + 60 or revision > now + 60:
            raise InputError("Xabar vaqti yoki ID noto‘g‘ri.")
        if not isinstance(text, str) or len(text.encode("utf-8")) > 50000:
            raise InputError("Xabar hajmi juda katta.")
        key = f"group:{chat_id}:{message_id}"
        digest = hashlib.sha256((text + ("\0deleted" if deleted else "")).encode()).hexdigest()
        with self.connection(write=True) as con:
            source = con.execute("SELECT enabled FROM sources WHERE chat_id=?", (chat_id,)).fetchone()
            if not source or not source[0]:
                return False
            old = con.execute("SELECT * FROM ingest_jobs WHERE key=?", (key,)).fetchone()
            if old and (old["revision"] > revision or (old["deleted"] and revision <= old["revision"])
                        or (old["revision"] == revision and old["digest"] == digest)):
                return False
            con.execute("INSERT INTO ingest_jobs(key,chat_id,message_id,raw_text,source_url,published_at,revision,digest,updated_at,deleted) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET raw_text=excluded.raw_text,source_url=excluded.source_url,"
                        "revision=excluded.revision,digest=excluded.digest,status='queued',reason='',attempts=0,retry_at=0,"
                        "updated_at=excluded.updated_at,deleted=excluded.deleted",
                        (key, chat_id, message_id, text, source_url, published_at, revision, digest, now, int(deleted)))
            con.execute("UPDATE sources SET last_seen=? WHERE chat_id=?", (now, chat_id))
        return True

    @staticmethod
    def _job(row) -> dict | None:
        if not row:
            return None
        data = dict(row)
        data["parsed"] = json.loads(data["parsed"])
        return data

    def next_job(self, now: int) -> dict | None:
        with self.connection() as con:
            return self._job(con.execute("SELECT * FROM ingest_jobs WHERE status='queued' AND retry_at<=? ORDER BY updated_at,key LIMIT 1", (now,)).fetchone())

    def ingest_job(self, key: str) -> dict | None:
        with self.connection() as con:
            return self._job(con.execute("SELECT * FROM ingest_jobs WHERE key=?", (key,)).fetchone())

    def review_queue(self, offset: int = 0) -> tuple[list[dict], int]:
        with self.connection() as con:
            total = con.execute("SELECT COUNT(*) FROM ingest_jobs WHERE status='review'").fetchone()[0]
            rows = con.execute("SELECT * FROM ingest_jobs WHERE status='review' ORDER BY updated_at,key LIMIT 10 OFFSET ?", (offset,))
            return [self._job(x) for x in rows], total

    def ingest_finish(self, key: str, digest: str, decision: dict, now: int, ttl_days: int,
                      admin_id: int | None = None) -> dict | None:
        status = decision["status"]
        if status not in {"accepted", "review", "discarded", "closed"}:
            raise InputError("Saralash holati noto‘g‘ri.")
        data = decision.get("data", {})
        if status == "accepted":
            data = validate_listing(data)
        with self.connection(write=True) as con:
            row = con.execute("SELECT * FROM ingest_jobs WHERE key=? AND digest=?", (key, digest)).fetchone()
            if not row or row["status"] != ("review" if admin_id is not None else "queued"):
                return None  # A newer edit or another reviewer won.
            source = con.execute("SELECT enabled FROM sources WHERE chat_id=?", (row["chat_id"],)).fetchone()
            if not source or not source[0]:
                con.execute("UPDATE ingest_jobs SET status='ignored' WHERE key=?", (key,))
                return None
            listing_id = row["listing_id"]
            if status == "accepted":
                from .parser import fingerprint
                data.update(source_chat_id=row["chat_id"], source_url=row["source_url"], raw_text=row["raw_text"])
                # Truncate only the display copy; the complete original stays in ingest_jobs.
                data["raw_text"] = data["raw_text"].encode("utf-16-le")[:6400].decode("utf-16-le", errors="ignore")
                fp = fingerprint(data)
                duplicate = con.execute("SELECT f.listing_id FROM fingerprints f JOIN listings l ON l.id=f.listing_id "
                                        "WHERE f.fingerprint=? AND l.external_key<>? AND l.status='active' AND l.expires_at>? "
                                        "AND f.updated_at>? LIMIT 1", (fp, key, now, now - 86400)).fetchone()
                if duplicate:
                    listing_id, status = duplicate[0], "duplicate"
                    con.execute("UPDATE listings SET status='closed' WHERE external_key=? AND id<>?", (key, listing_id))
                else:
                    listing_id = self._save_listing_row(con, data, 0, key, row["published_at"], ttl_days, reopen=True)
                    con.execute("INSERT INTO fingerprints VALUES(?,?,?) ON CONFLICT(listing_id) DO UPDATE SET "
                                "fingerprint=excluded.fingerprint,updated_at=excluded.updated_at", (listing_id, fp, now))
            if status in {"review", "discarded", "closed"}:
                con.execute("UPDATE listings SET status='closed' WHERE external_key=?", (key,))
            con.execute("UPDATE ingest_jobs SET status=?,parsed=?,reason=?,listing_id=?,updated_at=? WHERE key=?",
                        (status, json.dumps(data, ensure_ascii=False), decision.get("reason", ""), listing_id, now, key))
            if admin_id is not None:
                self._audit(con, admin_id, "ad_" + status, key, {"listing_id": listing_id}, now)
            return {"status": status, "listing_id": listing_id}

    def ingest_retry(self, key: str, digest: str, now: int):
        with self.connection(write=True) as con:
            row = con.execute("SELECT attempts FROM ingest_jobs WHERE key=? AND digest=?", (key, digest)).fetchone()
            if not row:
                return
            attempts = row[0] + 1
            con.execute("UPDATE ingest_jobs SET attempts=?,retry_at=?,status=?,reason=? WHERE key=? AND digest=?",
                        (attempts, now + min(2 ** attempts, 300), "review" if attempts >= 5 else "queued",
                         "Parserni qo‘lda tekshirish kerak" if attempts >= 5 else "Vaqtincha qayta urinish", key, digest))

    @staticmethod
    def _audit(con, admin_id: int, action: str, target: str, data: dict, now: int):
        con.execute("INSERT INTO admin_audit(admin_id,action,target,data,created_at) VALUES(?,?,?,?,?)",
                    (admin_id, action, target, json.dumps(data, ensure_ascii=False), now))

    def manual_create(self, user_id: int, months: int, amount: int, card_last4: str, now: int) -> dict:
        if months not in {1, 2, 3, 6} or amount <= 0:
            raise InputError("Bu tarif hali sotuvga qo‘yilmagan.")
        with self.connection(write=True) as con:
            con.execute("UPDATE manual_payments SET status='cancelled' WHERE user_id=? AND status='awaiting' AND created_at<?",
                        (user_id, now - 3 * 86400))
            row = con.execute("SELECT * FROM manual_payments WHERE user_id=? AND status IN ('awaiting','pending')", (user_id,)).fetchone()
            if row:
                return dict(row)
            cur = con.execute("INSERT INTO manual_payments(user_id,months,amount_uzs,card_last4,created_at) VALUES(?,?,?,?,?)",
                              (user_id, months, amount, card_last4, now))
            return dict(con.execute("SELECT * FROM manual_payments WHERE id=?", (cur.lastrowid,)).fetchone())

    def manual_payment(self, request_id: int) -> dict | None:
        with self.connection() as con:
            row = con.execute("SELECT * FROM manual_payments WHERE id=?", (request_id,)).fetchone()
            return dict(row) if row else None

    def manual_open(self, user_id: int) -> dict | None:
        with self.connection() as con:
            row = con.execute("SELECT * FROM manual_payments WHERE user_id=? AND status IN ('awaiting','pending')", (user_id,)).fetchone()
            return dict(row) if row else None

    def manual_submit(self, request_id: int, user_id: int, file_id: str, unique_id: str, kind: str, now: int) -> bool:
        if kind not in {"photo", "document"} or not file_id or not unique_id:
            raise InputError("Chekni rasm yoki PDF fayl sifatida yuboring.")
        with self.connection(write=True) as con:
            row = con.execute("SELECT * FROM manual_payments WHERE id=? AND user_id=?", (request_id, user_id)).fetchone()
            if not row or row["status"] != "awaiting":
                raise InputError("Chek allaqachon yuborilgan yoki buyurtma yopilgan. /subscribe")
            try:
                con.execute("UPDATE manual_payments SET status='pending',receipt_file_id=?,receipt_unique_id=?,"
                            "receipt_kind=?,submitted_at=? WHERE id=?", (file_id, unique_id, kind, now, request_id))
            except sqlite3.IntegrityError as exc:
                raise InputError("Bu chek avval yuborilgan. Yordam uchun /paysupport yozing.") from exc
            return True

    def manual_cancel(self, request_id: int, user_id: int) -> bool:
        with self.connection(write=True) as con:
            cur = con.execute("UPDATE manual_payments SET status='cancelled' WHERE id=? AND user_id=? AND status='awaiting'",
                              (request_id, user_id))
            return cur.rowcount > 0

    def manual_queue(self, offset: int = 0) -> tuple[list[dict], int]:
        with self.connection() as con:
            total = con.execute("SELECT COUNT(*) FROM manual_payments WHERE status='pending'").fetchone()[0]
            rows = con.execute("SELECT * FROM manual_payments WHERE status='pending' ORDER BY submitted_at,id LIMIT 10 OFFSET ?", (offset,))
            return [dict(x) for x in rows], total

    def approve_manual(self, request_id: int, admin_id: int, months: int, now: int, timezone: str) -> tuple[dict, bool]:
        if months not in {1, 2, 3, 6}:
            raise InputError("1, 2, 3 yoki 6 oyni tanlang.")
        with self.connection(write=True) as con:
            row = con.execute("SELECT * FROM manual_payments WHERE id=?", (request_id,)).fetchone()
            if not row:
                raise InputError("To‘lov so‘rovi topilmadi.")
            if row["status"] == "approved":
                return dict(row), False
            if row["status"] != "pending":
                raise InputError("Faqat tekshirishni kutayotgan chek tasdiqlanadi.")
            current = con.execute("SELECT subscription_until FROM users WHERE id=?", (row["user_id"],)).fetchone()[0]
            until = add_months(max(now, current), months, timezone)
            con.execute("UPDATE users SET subscription_until=? WHERE id=?", (until, row["user_id"]))
            con.execute("UPDATE manual_payments SET status='approved',reviewed_at=?,admin_id=?,approved_months=?,fulfilled_until=? WHERE id=?",
                        (now, admin_id, months, until, request_id))
            self._audit(con, admin_id, "payment_approved", str(request_id), {"user_id": row["user_id"], "months": months, "until": until}, now)
            return dict(con.execute("SELECT * FROM manual_payments WHERE id=?", (request_id,)).fetchone()), True

    def reject_manual(self, request_id: int, admin_id: int, reason: str, now: int) -> dict:
        reason = clean_text(reason, 300, 3)
        with self.connection(write=True) as con:
            row = con.execute("SELECT * FROM manual_payments WHERE id=?", (request_id,)).fetchone()
            if not row or row["status"] != "pending":
                raise InputError("Bu chek avval ko‘rib chiqilgan.")
            con.execute("UPDATE manual_payments SET status='rejected',reason=?,reviewed_at=?,admin_id=? WHERE id=?",
                        (reason, now, admin_id, request_id))
            self._audit(con, admin_id, "payment_rejected", str(request_id), {"reason": reason}, now)
            return dict(con.execute("SELECT * FROM manual_payments WHERE id=?", (request_id,)).fetchone())

    def grant_months(self, user_id: int, months: int, admin_id: int, now: int, timezone: str) -> int:
        if user_id <= 0:
            raise InputError("Foydalanuvchi ID noto‘g‘ri.")
        with self.connection(write=True) as con:
            con.execute("INSERT OR IGNORE INTO users(id,created_at) VALUES(?,?)", (user_id, now))
            current = con.execute("SELECT subscription_until FROM users WHERE id=?", (user_id,)).fetchone()[0]
            until = add_months(max(current, now), months, timezone)
            con.execute("UPDATE users SET subscription_until=? WHERE id=?", (until, user_id))
            self._audit(con, admin_id, "months_granted", str(user_id), {"months": months, "until": until}, now)
            return until

    def source_seed(self, ids, now: int, limit: int = 500):
        with self.connection(write=True) as con:
            existing = {r[0] for r in con.execute("SELECT chat_id FROM sources")}
            new = set(ids) - existing
            if len(existing) + len(new) > limit:
                raise InputError("Guruhlar SOURCE_LIMIT chegarasidan oshdi.")
            con.executemany("INSERT OR IGNORE INTO sources(chat_id,title,created_at) VALUES(?,?,?)",
                            [(chat_id, str(chat_id), now) for chat_id in new])

    def source_put(self, chat_id: int, title: str, now: int, limit: int, admin_id: int = 0):
        if not isinstance(chat_id, int) or chat_id >= 0:
            raise InputError("Guruh/kanalning manfiy raqamli ID’sini yozing.")
        title = clean_text(title or str(chat_id), 100)
        with self.connection(write=True) as con:
            exists = con.execute("SELECT 1 FROM sources WHERE chat_id=?", (chat_id,)).fetchone()
            count = con.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
            if not exists and count >= limit:
                raise InputError("Guruhlar SOURCE_LIMIT chegarasidan oshdi.")
            con.execute("INSERT INTO sources(chat_id,title,created_at) VALUES(?,?,?) ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title",
                        (chat_id, title, now))
            self._audit(con, admin_id, "source_saved", str(chat_id), {"title": title}, now)

    def source_list(self, offset: int = 0, limit: int = 10) -> tuple[list[dict], int]:
        with self.connection() as con:
            total = con.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
            rows = con.execute("SELECT * FROM sources ORDER BY chat_id LIMIT ? OFFSET ?", (limit, offset))
            return [dict(x) for x in rows], total

    def enabled_sources(self) -> set[int]:
        with self.connection() as con:
            return {r[0] for r in con.execute("SELECT chat_id FROM sources WHERE enabled=1")}

    def source(self, chat_id: int) -> dict | None:
        with self.connection() as con:
            row = con.execute("SELECT * FROM sources WHERE chat_id=?", (chat_id,)).fetchone()
            return dict(row) if row else None

    def source_toggle(self, chat_id: int, enabled: bool, admin_id: int, now: int):
        with self.connection(write=True) as con:
            if not con.execute("UPDATE sources SET enabled=? WHERE chat_id=?", (int(enabled), chat_id)).rowcount:
                raise InputError("Guruh topilmadi.")
            if not enabled:
                con.execute("UPDATE ingest_jobs SET status='ignored' WHERE chat_id=? AND status IN ('queued','review')", (chat_id,))
                con.execute("UPDATE listings SET status='closed' WHERE json_extract(data,'$.source_chat_id')=?", (chat_id,))
            self._audit(con, admin_id, "source_enabled" if enabled else "source_disabled", str(chat_id), {}, now)

    def operations_stats(self) -> dict:
        with self.connection() as con:
            return {"pending_payments": con.execute("SELECT COUNT(*) FROM manual_payments WHERE status='pending'").fetchone()[0],
                    "sources": con.execute("SELECT COUNT(*) FROM sources WHERE enabled=1").fetchone()[0],
                    "queued": con.execute("SELECT COUNT(*) FROM ingest_jobs WHERE status='queued'").fetchone()[0],
                    "review": con.execute("SELECT COUNT(*) FROM ingest_jobs WHERE status='review'").fetchone()[0],
                    "duplicates": con.execute("SELECT COUNT(*) FROM ingest_jobs WHERE status='duplicate'").fetchone()[0]}
