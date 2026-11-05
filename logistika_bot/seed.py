from .db import Database
from .domain import place


def seed_demo(db: Database, now: int, ttl_days: int) -> int:
    """Explicit demo only; uses non-operational placeholder contact numbers."""
    rows = [
        ("cargo", "Toshkent", "Samarqand", ["tent", "ref"], "DEMO: qoplangan mahsulot"),
        ("cargo", "Angren", "Samarqand", ["tent"], "DEMO: qoplangan ko‘mir"),
        ("cargo", "Namangan", "Toshkent", ["isuzu_large"], "DEMO: qutilar"),
        ("cargo", "Toshkent", "Buxoro", ["tent"], "DEMO: qurilish materiali"),
        ("cargo", "Toshkent", "Samarqand", ["tent"], "DEMO: oziq-ovqat"),
        ("cargo", "Toshkent", "Samarqand", ["tent"], "DEMO: qadoqlangan yuk"),
        ("vehicle", "Toshkent", "Moskva", ["tent"], "DEMO: bo‘sh transport"),
        ("vehicle", "Toshkent", "Xorazm", ["kamaz"], "DEMO: bo‘sh Kamaz"),
        ("vehicle", "Samarqand", "Toshkent", ["ref"], "DEMO: bo‘sh refrijerator"),
    ]
    for i, (kind, origin, dest, vehicles, description) in enumerate(rows):
        db.save_listing({"kind": kind, "origin": place(origin), "destinations": [place(dest)],
                         "vehicles": vehicles, "description": description, "capacity": "96 m³",
                         "price": "Kelishiladi", "phone": "+998000000000", "demo": True},
                        owner_id=0, key=f"demo:{i}", now=now, ttl_days=ttl_days)
    return len(rows)
