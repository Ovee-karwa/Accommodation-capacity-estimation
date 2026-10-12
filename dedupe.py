"""Entity resolution: merge the same property seen on several sources.

A pair is a duplicate when (distance, name similarity) passes any rule in
config.DEDUP_RULES, or when they share a phone number that is not a call-centre
number. Records without coordinates are matched on near-identical names only.
Matches are grouped with union-find; every matched pair is written out for audit.
"""
import math
import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher

import config

STOP = set("""hotel hotels the and & n nashik nasik by a an of in at near new pvt ltd private limited
lodge lodging resort resorts spa inn stay stays rooms room residency residence grand
oyo collection o townhouse flagship capital super spot on silverkey palette sunday
treebo fab fabhotel itsy premium boutique luxury trimbak trimbakeshwar road rd""".split())

SOURCE_RANK = {"google": 0, "osm": 1, "easemytrip": 2, "oyo": 3, "cleartrip": 4}


def aliases(name: str) -> list[str]:
    """Normalised name variants. OYO keeps old names as 'X formerly Y'."""
    parts = re.split(r"\bformerly\b|\(|\)", name.lower())
    out = []
    for p in parts:
        p = re.sub(r"\boyo\s*\d+\b|\b\d{3,}\b", " ", p)
        p = re.sub(r"[^a-z0-9ऀ-ॿ ]", " ", p)
        toks = [t for t in p.split() if t not in STOP and len(t) > 1]
        if toks:
            out.append(" ".join(sorted(toks)))
    return out or [re.sub(r"\W+", " ", name.lower()).strip()]


def name_sim(a: list[str], b: list[str]) -> float:
    best = 0.0
    for x in a:
        for y in b:
            if not x or not y:
                continue
            s = SequenceMatcher(None, x, y).ratio()
            xs, ys = set(x.split()), set(y.split())
            if xs <= ys or ys <= xs:  # one name is a subset of the other ("radhika" vs "radhika palace")
                s = max(s, 0.88 if min(len(xs), len(ys)) >= 1 and min(len(x), len(y)) >= 5 else s)
            best = max(best, s)
    return best


def haversine(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def norm_phone(p):
    if not p:
        return None
    d = re.sub(r"\D", "", str(p))[-10:]
    return d if len(d) == 10 else None


def dedupe(records):
    n = len(records)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for r in records:
        r["_al"] = aliases(r["name"])
        r["_ph"] = norm_phone(r.get("phone"))
    phone_freq = Counter(r["_ph"] for r in records if r["_ph"])
    max_d = max(d for d, _ in config.DEDUP_RULES)

    # spatial bucketing (~0.025 deg cells) to avoid O(n^2) over everything
    cells = defaultdict(list)
    for i, r in enumerate(records):
        if r["lat"] is not None:
            cells[(int(r["lat"] / 0.025), int(r["lon"] / 0.025))].append(i)

    pairs = []

    def consider(i, j, dist):
        a, b = records[i], records[j]
        if a["source"] == b["source"] and a["source"] != "osm":
            return  # one OTA does not list the same hotel twice under different ids (OSM can: node + way)
        s = name_sim(a["_al"], b["_al"])
        why = None
        if dist is not None:
            for d, t in config.DEDUP_RULES:
                if dist <= d and s >= t:
                    why = f"dist {dist:.0f}m, name {s:.2f}"
                    break
        elif re.sub(r"\W+", "", a["name"].lower()) == re.sub(r"\W+", "", b["name"].lower()):
            why = "no coords, identical name"
        if not why and a["_ph"] and a["_ph"] == b["_ph"] and phone_freq[a["_ph"]] <= 3:
            why = f"same phone {a['_ph']}"
        if why:
            pairs.append((a["source"], a["name"], b["source"], b["name"], why))
            parent[find(i)] = find(j)

    reach = int(max_d / 2700) + 1
    for (cx, cy), idx in cells.items():
        near = [j for dx in range(-reach, reach + 1) for dy in range(-reach, reach + 1)
                for j in cells.get((cx + dx, cy + dy), [])]
        for i in idx:
            for j in near:
                if j > i:
                    dist = haversine((records[i]["lat"], records[i]["lon"]), (records[j]["lat"], records[j]["lon"]))
                    if dist <= max_d:
                        consider(i, j, dist)
    nocoord = [i for i, r in enumerate(records) if r["lat"] is None]
    for i in nocoord:
        for j in range(n):
            if j != i and (records[j]["lat"] is not None or j > i):
                consider(i, j, None)

    groups = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(records[i])
    return [merge(g) for g in groups.values()], pairs


def merge(group):
    group = sorted(group, key=lambda r: SOURCE_RANK.get(r["source"], 9))
    with_xy = [r for r in group if r["lat"] is not None]
    first = lambda k: next((r[k] for r in group if r.get(k) not in (None, "")), None)
    stars = [r["stars"] for r in group if r.get("stars")]
    return {
        "name": max((r["name"] for r in group if r["source"] != "oyo"), key=len, default=group[0]["name"]),
        "all_names": " | ".join(sorted({r["name"] for r in group})),
        "sources": ",".join(sorted({r["source"] for r in group})),
        "n_sources": len({r["source"] for r in group}),
        "kinds": ",".join(sorted({str(r["kind"]) for r in group if r["kind"]})),
        "stars": max(stars) if stars else None,
        "lat": with_xy[0]["lat"] if with_xy else None,
        "lon": with_xy[0]["lon"] if with_xy else None,
        "address": first("address"),
        "locality": first("locality"),
        "phone": first("phone"),
        "rooms_reported": first("rooms"),
        "beds_reported": first("beds"),
        "urls": " ".join(r["url"] for r in group if r.get("url")),
    }
