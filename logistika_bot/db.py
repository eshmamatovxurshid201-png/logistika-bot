from __future__ import annotations

import json
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .domain import InputError, day_start, normalize, validate_listing


class Database:
    """Short per-operation connections; safe to call through asyncio.to_thread."""

    def __init__(self, path: str):
        self.path = path

    @contextmanager
    def connection(self, write: bool = False):
        con = sqlite3.connect(self.path, timeout=15)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        try:
            if write:
                con.execute("BEGIN IMMEDIATE")
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    def initialize(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as con:
            if con.execute("PRAGMA user_version").fetchone()[0] > 1:
                raise RuntimeError("Baza versiyasi dasturdan yangi; avval kodni yangilang.")
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY, state TEXT NOT NULL DEFAULT 'home',
                    context TEXT NOT NULL DEFAULT '{}', vehicle TEXT NOT NULL DEFAULT 'all',
                    subscription_until INTEGER NOT NULL DEFAULT 0,
                    terms_version TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS listings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER NOT NULL,
                    external_key TEXT UNIQUE, kind TEXT NOT NULL CHECK(kind IN ('cargo','vehicle')),
                    origin_country TEXT NOT NULL, country_key TEXT NOT NULL,
                    city_key TEXT NOT NULL, data TEXT NOT NULL,
                    published_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','closed'))
                );
                CREATE INDEX IF NOT EXISTS listings_search ON listings(kind,status,expires_at,published_at);
                CREATE INDEX IF NOT EXISTS listings_geo ON listings(country_key,city_key);
                CREATE TABLE IF NOT EXISTS vehicles (
                    listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
                    vehicle TEXT NOT NULL, PRIMARY KEY(listing_id,vehicle)
                );
                CREATE INDEX IF NOT EXISTS vehicle_search ON vehicles(vehicle,listing_id);
                CREATE TABLE IF NOT EXISTS destinations (
                    listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
                    country_key TEXT NOT NULL, city_key TEXT NOT NULL,
                    PRIMARY KEY(listing_id,country_key,city_key)
                );
                CREATE INDEX IF NOT EXISTS destination_search ON destinations(country_key,city_key,listing_id);
                CREATE TABLE IF NOT EXISTS events (
                    user_id INTEGER NOT NULL, listing_id INTEGER NOT NULL REFERENCES listings(id),
                    kind TEXT NOT NULL CHECK(kind IN ('view','phone')), created_at INTEGER NOT NULL,
                    PRIMARY KEY(user_id,listing_id,kind)
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
                    data TEXT NOT NULL, next_offset INTEGER NOT NULL DEFAULT 0,
                    expires_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS session_expiry ON sessions(expires_at);
                CREATE TABLE IF NOT EXISTS cards (
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    listing_id INTEGER NOT NULL REFERENCES listings(id), message_id INTEGER NOT NULL,
                    ordinal INTEGER NOT NULL, more_offset INTEGER,
                    PRIMARY KEY(session_id,listing_id)
                );
                CREATE TABLE IF NOT EXISTS orders (
                    id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
                    stars INTEGER NOT NULL, days INTEGER NOT NULL, created_at INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending', charge_id TEXT UNIQUE,
                    fulfilled_until INTEGER
                );
                PRAGMA user_version=1;
            """)

    def user(self, user_id: int, now: int) -> dict:
        with self.connection(write=True) as con:
            con.execute("INSERT OR IGNORE INTO users(id,created_at) VALUES(?,?)", (user_id, now))
            row = dict(con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())
        row["context"] = json.loads(row["context"])
        return row

    def set_state(self, user_id: int, state: str, context: dict | None = None) -> None:
        with self.connection(write=True) as con:
            con.execute("UPDATE users SET state=?,context=? WHERE id=?",
                        (state, json.dumps(context or {}, ensure_ascii=False), user_id))

    def set_vehicle(self, user_id: int, vehicle: str) -> None:
        with self.connection(write=True) as con:
            con.execute("UPDATE users SET vehicle=? WHERE id=?", (vehicle, user_id))

    def accept_terms(self, user_id: int, version: str) -> None:
        with self.connection(write=True) as con:
            con.execute("UPDATE users SET terms_version=? WHERE id=?", (version, user_id))

    def grant(self, user_id: int, days: int, now: int) -> int:
        if user_id <= 0 or not 1 <= days <= 365:
            raise InputError("Foydalanuvchi ID yoki kun soni noto‘g‘ri.")
        with self.connection(write=True) as con:
            con.execute("INSERT OR IGNORE INTO users(id,created_at) VALUES(?,?)", (user_id, now))
            until = con.execute("SELECT subscription_until FROM users WHERE id=?", (user_id,)).fetchone()[0]
            until = max(until, now) + days * 86400
            con.execute("UPDATE users SET subscription_until=? WHERE id=?", (until, user_id))
        return until

    def revoke(self, user_id: int) -> None:
        with self.connection(write=True) as con:
            con.execute("UPDATE users SET subscription_until=0 WHERE id=?", (user_id,))

    def save_listing(self, data: dict, owner_id: int, key: str, now: int, ttl_days: int,
                     update: bool = False, published_at: int | None = None) -> int:
        data = validate_listing(data)
        published_at = now if published_at is None else published_at
        if not isinstance(published_at, int) or published_at > now + 60 or published_at < 0:
            raise InputError("E’lon vaqti noto‘g‘ri.")
        with self.connection(write=True) as con:
            old = con.execute("SELECT id FROM listings WHERE external_key=?", (key,)).fetchone()
            if old and not update:
                return old[0]
            values = (owner_id, data["kind"], data["origin"]["country"],
                      normalize(data["origin"]["country"]), normalize(data["origin"]["city"]),
                      json.dumps(data, ensure_ascii=False), published_at, published_at + ttl_days * 86400)
            if old:
                listing_id = old[0]
                con.execute("UPDATE listings SET owner_id=?,kind=?,origin_country=?,country_key=?,"
                            "city_key=?,data=?,published_at=?,expires_at=? WHERE id=?", (*values, listing_id))
                con.execute("DELETE FROM vehicles WHERE listing_id=?", (listing_id,))
                con.execute("DELETE FROM destinations WHERE listing_id=?", (listing_id,))
            else:
                cur = con.execute("INSERT INTO listings(owner_id,kind,origin_country,country_key,city_key,"
                                  "data,published_at,expires_at,external_key) VALUES(?,?,?,?,?,?,?,?,?)",
                                  (*values, key))
                listing_id = cur.lastrowid
            con.executemany("INSERT INTO vehicles VALUES(?,?)", [(listing_id, x) for x in data["vehicles"]])
            con.executemany("INSERT OR IGNORE INTO destinations VALUES(?,?,?)",
                            [(listing_id, normalize(x["country"]), normalize(x["city"]))
                             for x in data["destinations"]])
        return listing_id

    @staticmethod
    def _listing(row) -> dict | None:
        if row is None:
            return None
        result = dict(row)
        result["data"] = json.loads(result["data"])
        return result

    def listing(self, listing_id: int) -> dict | None:
        with self.connection() as con:
            return self._listing(con.execute("SELECT * FROM listings WHERE id=?", (listing_id,)).fetchone())

    def listings(self, ids: list[int]) -> dict[int, dict]:
        if not ids:
            return {}
        with self.connection() as con:
            rows = con.execute("SELECT * FROM listings WHERE id IN (" + ",".join("?" for _ in ids) + ")", ids)
            return {r["id"]: self._listing(r) for r in rows}

    def close_listing(self, listing_id: int, user_id: int, admin: bool = False) -> bool:
        with self.connection(write=True) as con:
            cur = con.execute("UPDATE listings SET status='closed' WHERE id=? AND (owner_id=? OR ?)",
                              (listing_id, user_id, int(admin)))
            return cur.rowcount > 0

    def close_source(self, key: str) -> None:
        with self.connection(write=True) as con:
            con.execute("UPDATE listings SET status='closed' WHERE external_key=?", (key,))

    def mine(self, user_id: int, now: int) -> list[dict]:
        with self.connection() as con:
            rows = con.execute("SELECT * FROM listings WHERE owner_id=? AND status='active' "
                               "AND expires_at>? ORDER BY id DESC LIMIT 30", (user_id, now))
            return [self._listing(x) for x in rows]

    @staticmethod
    def _where(filters: dict, now: int) -> tuple[str, list]:
        clauses = ["l.status='active'", "l.expires_at>?", "l.kind=?"]
        params: list = [now, filters["kind"]]
        if filters.get("vehicle", "all") != "all":
            clauses.append("EXISTS(SELECT 1 FROM vehicles v WHERE v.listing_id=l.id AND v.vehicle=?)")
            params.append(filters["vehicle"])
        for field, column in [("country", "country_key"), ("city", "city_key")]:
            if filters.get(field) is not None:
                clauses.append(f"l.{column}=?")
                params.append(normalize(filters[field]))

        def endpoint(point: dict, destination: bool) -> tuple[str, list]:
            prefix = "d" if destination else "l"
            cond = [f"{prefix}.country_key=?"]
            args = [normalize(point["country"])]
            if point.get("city"):
                cond.append(f"{prefix}.city_key=?")
                args.append(normalize(point["city"]))
            sql = " AND ".join(cond)
            if destination:
                sql = "EXISTS(SELECT 1 FROM destinations d WHERE d.listing_id=l.id AND " + sql + ")"
            return "(" + sql + ")", args

        query = filters.get("query", {})
        for field, dest in [("origin", False), ("destination", True)]:
            if field in query:
                sql, args = endpoint(query[field], dest)
                clauses.append(sql)
                params.extend(args)
        if "either" in query:
            a, ap = endpoint(query["either"], False)
            b, bp = endpoint(query["either"], True)
            clauses.append(f"({a} OR {b})")
            params.extend([*ap, *bp])
        return " AND ".join(clauses), params

    def search(self, filters: dict, now: int, limit: int) -> tuple[list[int], int]:
        where, params = self._where(filters, now)
        with self.connection() as con:
            con.execute("BEGIN")  # count and IDs share one snapshot
            total = con.execute("SELECT COUNT(*) FROM listings l WHERE " + where, params).fetchone()[0]
            ids = [r[0] for r in con.execute("SELECT l.id FROM listings l WHERE " + where +
                                            " ORDER BY l.published_at DESC,l.id DESC LIMIT ?", (*params, limit))]
        return ids, total

    def geography(self, filters: dict, now: int, timezone: str) -> dict:
        where, params = self._where(filters, now)
        cities = filters.get("country") is not None
        column = "city_key" if cities else "country_key"
        label = "json_extract(l.data,'$.origin.city')" if cities else "l.origin_country"
        with self.connection() as con:
            rows = con.execute(f"SELECT l.{column} AS key,{label} AS name,COUNT(*) AS count,"
                               "SUM(l.published_at>=?) AS today FROM listings l WHERE " + where +
                               f" GROUP BY l.{column} ORDER BY count DESC,key", (day_start(now, timezone), *params))
            options = [dict(x) for x in rows]
        for item in options:
            item["name"] = item["name"] or "boshqa"
        return {"mode": "geo", "filters": filters, "cities": cities, "options": options,
                "total": sum(x["count"] for x in options), "today": sum(x["today"] for x in options)}

    def session_new(self, user_id: int, data: dict, now: int, hours: int) -> dict:
        session_id = secrets.token_hex(6)
        with self.connection(write=True) as con:
            con.execute("DELETE FROM sessions WHERE expires_at<=?", (now,))
            con.execute("INSERT INTO sessions(id,user_id,data,expires_at) VALUES(?,?,?,?)",
                        (session_id, user_id, json.dumps(data, ensure_ascii=False), now + hours * 3600))
        return {"id": session_id, "user_id": user_id, "data": data, "next_offset": 0}

    def session(self, session_id: str, user_id: int, now: int) -> dict | None:
        with self.connection() as con:
            row = con.execute("SELECT * FROM sessions WHERE id=? AND user_id=? AND expires_at>?",
                              (session_id, user_id, now)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["data"] = json.loads(result["data"])
        return result

    def page_done(self, session_id: str, old: int, new: int) -> None:
        with self.connection(write=True) as con:
            con.execute("UPDATE sessions SET next_offset=? WHERE id=? AND next_offset=?", (new, session_id, old))

    def card(self, session_id: str, listing_id: int) -> dict | None:
        with self.connection() as con:
            row = con.execute("SELECT * FROM cards WHERE session_id=? AND listing_id=?", (session_id, listing_id)).fetchone()
            return dict(row) if row else None

    def card_save(self, session_id: str, listing_id: int, message_id: int, ordinal: int,
                  more_offset: int | None) -> None:
        with self.connection(write=True) as con:
            con.execute("INSERT OR REPLACE INTO cards VALUES(?,?,?,?,?)",
                        (session_id, listing_id, message_id, ordinal, more_offset))

    def event(self, user_id: int, listing_id: int, kind: str, now: int) -> dict:
        with self.connection(write=True) as con:
            con.execute("INSERT OR IGNORE INTO events VALUES(?,?,?,?)", (user_id, listing_id, kind, now))
            result = dict(con.execute("SELECT kind,COUNT(*) AS n FROM events WHERE listing_id=? GROUP BY kind",
                                      (listing_id,)).fetchall())
        return {"view": result.get("view", 0), "phone": result.get("phone", 0)}

    def order_new(self, user_id: int, stars: int, days: int, now: int) -> str:
        order_id = secrets.token_hex(16)
        with self.connection(write=True) as con:
            con.execute("INSERT INTO orders(id,user_id,stars,days,created_at) VALUES(?,?,?,?,?)",
                        (order_id, user_id, stars, days, now))
        return order_id

    def order_check(self, order_id: str, user_id: int, stars: int, currency: str, now: int) -> bool:
        with self.connection() as con:
            row = con.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        return bool(row and row["user_id"] == user_id and row["stars"] == stars and currency == "XTR"
                    and row["status"] == "pending" and row["created_at"] + 86400 > now)

    def payment(self, order_id: str, user_id: int, stars: int, currency: str, charge: str, now: int) -> tuple[int, bool]:
        with self.connection(write=True) as con:
            order = con.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
            if not order or order["user_id"] != user_id or order["stars"] != stars or currency != "XTR" or not charge:
                raise InputError("To‘lov buyurtmaga mos emas. /paysupport orqali murojaat qiling.")
            if order["status"] == "paid":
                if order["charge_id"] != charge:
                    raise InputError("Buyurtma oldin to‘langan. /paysupport orqali murojaat qiling.")
                return order["fulfilled_until"], False
            if con.execute("SELECT 1 FROM orders WHERE charge_id=?", (charge,)).fetchone():
                raise InputError("Bu to‘lov boshqa buyurtmada hisoblangan. /paysupport")
            current = con.execute("SELECT subscription_until FROM users WHERE id=?", (user_id,)).fetchone()[0]
            until = max(now, current) + order["days"] * 86400
            con.execute("UPDATE users SET subscription_until=? WHERE id=?", (until, user_id))
            con.execute("UPDATE orders SET status='paid',charge_id=?,fulfilled_until=? WHERE id=?", (charge, until, order_id))
        return until, True

    def stats(self, now: int) -> dict:
        with self.connection() as con:
            return {
                "users": con.execute("SELECT COUNT(*) FROM users").fetchone()[0],
                "subscribers": con.execute("SELECT COUNT(*) FROM users WHERE subscription_until>?", (now,)).fetchone()[0],
                "active": con.execute("SELECT COUNT(*) FROM listings WHERE status='active' AND expires_at>?", (now,)).fetchone()[0],
                "payments": con.execute("SELECT COUNT(*) FROM orders WHERE status='paid'").fetchone()[0],
            }
