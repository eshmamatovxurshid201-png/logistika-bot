import re

from .domain import normalize


def tonnes(data: dict) -> float | None:
    match = re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(?:tonna|тонн[аы]?|t|т)\b", data.get("capacity", ""), re.I)
    return float(match[1].replace(",", ".")) if match else None


def compatible_place(a: dict, b: dict) -> tuple[bool, bool]:
    if normalize(a["country"]) != normalize(b["country"]):
        return False, False
    if a.get("city") and b.get("city"):
        exact = normalize(a["city"]) == normalize(b["city"])
        return exact, exact
    return True, False


def rank_pair(source: dict, candidate: dict) -> dict | None:
    a, b = source["data"], candidate["data"]
    if a["kind"] == b["kind"]:
        return None
    if a.get("phone") and a.get("phone") == b.get("phone"):
        return None  # Avoid offering a caller their own repost as a counterpart.
    origin_ok, origin_exact = compatible_place(a["origin"], b["origin"])
    destinations = [compatible_place(x, y) for x in a["destinations"] for y in b["destinations"]]
    if not origin_ok or not any(ok for ok, _ in destinations) or not set(a["vehicles"]) & set(b["vehicles"]):
        return None
    destination_exact = any(exact for ok, exact in destinations if ok)
    cargo, truck = (a, b) if a["kind"] == "cargo" else (b, a)
    cargo_weight, capacity = tonnes(cargo), tonnes(truck)
    if cargo_weight is not None and capacity is not None and cargo_weight > capacity:
        return None
    if cargo.get("ready_date") and truck.get("ready_date") and truck["ready_date"] > cargo["ready_date"]:
        return None
    score = 20 + (30 if origin_exact else 10) + (30 if destination_exact else 10)
    reasons = ["Avto turi mos", "Yo‘nalish mos" if origin_exact and destination_exact else "Hudud mos; shaharni aniqlashtiring"]
    if cargo_weight is not None and capacity is not None:
        score += 10
        reasons.append("Ko‘rsatilgan tonnaj yetarli")
    else:
        reasons.append("Tonnajni aniqlashtiring")
    if cargo.get("ready_date") and truck.get("ready_date"):
        score += 10
        reasons.append("Ko‘rsatilgan sana mos")
    else:
        reasons.append("Sanani aniqlashtiring")
    return {"score": score, "reasons": reasons}
