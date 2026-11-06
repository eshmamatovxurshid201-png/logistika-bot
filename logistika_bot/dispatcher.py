from . import ui


class DispatcherFlows:
    async def result_set(self, uid: int, ids: list[int], title: str, filters: dict, match_info: dict | None = None):
        if not await self.require_access(uid):
            return
        if not ids:
            return await self.send(uid, title + "\nHozircha faol natija yo‘q.")
        data = {"mode": "results", "ids": ids, "total": len(ids), "filters": filters,
                "match_info": match_info or {}}
        session = await self.query("session_new", uid, data, self.now(), self.settings.session_hours)
        await self.query("set_state", uid, "search", {"kind": filters["kind"], "vehicle": "all", "last_session": session["id"]})
        await self.send(uid, title)
        await self.show_page(session, 0)

    async def show_favorites(self, uid: int):
        if not await self.require_access(uid):
            return
        ids = await self.query("favorites", uid, self.now())
        await self.result_set(uid, ids, "⭐ Tanlangan e’lonlar", {"kind": "cargo"})

    async def show_matches(self, uid: int, listing: dict):
        if not await self.require_access(uid):
            return
        matches = await self.query("matching", listing["id"], self.now())
        kind = "vehicle" if listing["data"]["kind"] == "cargo" else "cargo"
        await self.result_set(uid, [x["id"] for x in matches], "🔗 Mos e’lonlar. Ball kelishuv kafolati emas; "
                              "narx, vaqt va sig‘imni tomonlar bilan tasdiqlang.", {"kind": kind},
                              {str(x["id"]): {"score": x["score"], "reasons": x["reasons"]} for x in matches})
