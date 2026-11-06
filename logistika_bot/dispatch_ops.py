import json

from .domain import InputError

SCHEMA = """
CREATE TABLE IF NOT EXISTS favorites (
    user_id INTEGER NOT NULL REFERENCES users(id), listing_id INTEGER NOT NULL REFERENCES listings(id),
    created_at INTEGER NOT NULL, PRIMARY KEY(user_id,listing_id)
);
CREATE TABLE IF NOT EXISTS ai_cache (
    cache_key TEXT PRIMARY KEY, state TEXT NOT NULL, data TEXT,
    lease_until INTEGER NOT NULL, updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_usage(day INTEGER PRIMARY KEY, requests INTEGER NOT NULL);
"""


class DispatcherOperations:
    def favorite_has(self, user_id: int, listing_id: int) -> bool:
        with self.connection() as con:
            return con.execute("SELECT 1 FROM favorites WHERE user_id=? AND listing_id=?", (user_id, listing_id)).fetchone() is not None

    def favorite_set(self, user_id: int, listing_id: int, saved: bool, now: int) -> None:
        with self.connection(write=True) as con:
            if not saved:
                con.execute("DELETE FROM favorites WHERE user_id=? AND listing_id=?", (user_id, listing_id))
                return
            if not con.execute("SELECT 1 FROM listings WHERE id=? AND status='active' AND expires_at>?", (listing_id, now)).fetchone():
                raise InputError("E’lon faol emas.")
            if con.execute("SELECT COUNT(*) FROM favorites WHERE user_id=?", (user_id,)).fetchone()[0] >= 500:
                if not con.execute("SELECT 1 FROM favorites WHERE user_id=? AND listing_id=?", (user_id, listing_id)).fetchone():
                    raise InputError("Tanlanganlar 500 ta bilan cheklangan. Keraksizlarini olib tashlang.")
            con.execute("INSERT OR IGNORE INTO favorites VALUES(?,?,?)", (user_id, listing_id, now))

    def favorites(self, user_id: int, now: int) -> list[int]:
        with self.connection() as con:
            return [row[0] for row in con.execute("SELECT l.id FROM favorites f JOIN listings l ON l.id=f.listing_id "
                "WHERE f.user_id=? AND l.status='active' AND l.expires_at>? ORDER BY f.created_at DESC,l.id DESC LIMIT 500", (user_id, now))]

    def matching(self, listing_id: int, now: int) -> list[dict]:
        from .matching import rank_pair
        source = self.listing(listing_id)
        if not source or source["status"] != "active" or source["expires_at"] <= now:
            return []
        other = "vehicle" if source["data"]["kind"] == "cargo" else "cargo"
        ids, _ = self.search({"kind": other}, now, 500)
        rows = []
        for candidate in self.listings(ids).values():
            info = rank_pair(source, candidate)
            if info:
                rows.append({"id": candidate["id"], **info, "published_at": candidate["published_at"]})
        return sorted(rows, key=lambda x: (-x["score"], -x["published_at"], -x["id"]))

    def ai_reserve(self, key: str, day: int, now: int, limit: int) -> tuple[str, dict | None]:
        with self.connection(write=True) as con:
            row = con.execute("SELECT * FROM ai_cache WHERE cache_key=?", (key,)).fetchone()
            if row and row["lease_until"] > now:
                if row["state"] == "done":
                    return "cached", json.loads(row["data"])
                return ("busy" if row["state"] == "pending" else "error"), None
            count = con.execute("SELECT requests FROM ai_usage WHERE day=?", (day,)).fetchone()
            if count and count[0] >= limit:
                return "limit", None
            con.execute("INSERT INTO ai_usage VALUES(?,1) ON CONFLICT(day) DO UPDATE SET requests=requests+1", (day,))
            con.execute("INSERT INTO ai_cache VALUES(?,'pending',NULL,?,?) ON CONFLICT(cache_key) DO UPDATE SET state='pending',data=NULL,lease_until=excluded.lease_until,updated_at=excluded.updated_at", (key, now + 60, now))
            con.execute("DELETE FROM ai_cache WHERE lease_until<?", (now - 7 * 86400,))
            con.execute("DELETE FROM ai_usage WHERE day<?", (day - 30 * 86400,))
            return "reserved", None

    def ai_finish(self, key: str, data: dict | None, now: int):
        with self.connection(write=True) as con:
            con.execute("UPDATE ai_cache SET state=?,data=?,lease_until=?,updated_at=? WHERE cache_key=?",
                        ("done" if data is not None else "error", json.dumps(data, ensure_ascii=False),
                         now + (86400 if data is not None else 300), now, key))

    def ingest_defer(self, key: str, digest: str, now: int):
        with self.connection(write=True) as con:
            con.execute("UPDATE ingest_jobs SET retry_at=? WHERE key=? AND digest=? AND status='queued'", (now + 2, key, digest))
