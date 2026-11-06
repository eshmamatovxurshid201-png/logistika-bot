import asyncio
import logging
import time

from .parser import parse_message

log = logging.getLogger(__name__)


class Pipeline:
    def __init__(self, db, settings, clock=time.time, semantic=None):
        self.db, self.settings, self.clock = db, settings, clock
        from .semantic import SemanticAssistant
        self.semantic = semantic or SemanticAssistant(db, settings)

    def process_one(self) -> bool:
        now = int(self.clock())
        job = self.db.next_job(now)
        if not job:
            return False
        try:
            decision = ({"status": "closed", "reason": "Manba xabari o‘chirilgan"} if job["deleted"] else
                        parse_message(job["raw_text"], job["source_url"], job["published_at"], self.settings.timezone))
            decision = self.semantic.enrich(job, decision, now)
            if decision is None:
                self.db.ingest_defer(job["key"], job["digest"], now)
                return True
            self.db.ingest_finish(job["key"], job["digest"], decision, now, self.settings.listing_ttl_days)
        except Exception as exc:
            log.error("Ingestion failed: %s", type(exc).__name__)
            self.db.ingest_retry(job["key"], job["digest"], now)
        return True

    async def run(self):
        while True:
            processed = await asyncio.to_thread(self.process_one)
            if not processed:
                await asyncio.sleep(1)
