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


# Words that describe a type of stay rather than identify one. Two names that share
# only these ("Ambient Homestay" / "Asmita Homestay") are not the same place.
GENERIC = set("""homestay homestays home homes stay stays villa villas apartment apartments apt flat
guest house houses bungalow bunglow cottage cottages farm farmstay farmhouse room rooms suite suites
service serviced inn palace comfort serene premium deluxe luxury luxe private family view mountain
lake pool infinity 1bhk 2bhk 3bhk 4bhk 5bhk bhk bedroom bed beds city centre center near road
retreat nature green express boutique heritage regency plaza elite classic international sai shree
shri sri new hostel lodging boarding restaurant banquets spa vistas stayvista saffronstays veo
nest cozy peaceful entire floor with by at in nasik""".split())


def _core(x):
    return {t for t in x.split() if t not in GENERIC}


def name_sim(a: list[str], b: list[str]) -> float:
    best = 0.0
    for x in a:
        for y in b:
            if not x or not y:
                continue
            s = SequenceMatcher(None, x, y).ratio()
            cx, cy = _core(x), _core(y)
            if cx and cy and not (cx & cy):
                s = min(s, 0.6)  # no distinctive word in common
            elif cx and cy and (cx <= cy or cy <= cx) and min(len(" ".join(cx)), len(" ".join(cy))) >= 4:
                s = max(s, 0.88)  # distinctive words of one name contained in the other
            elif not cx or not cy:
                s = min(s, 0.8)  # one name is only generic words: never enough on its own
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
    max_d = max([d for d, _ in config.DEDUP_RULES] + [4000])

    # spatial bucketing (~0.025 deg cells) to avoid O(n^2) over everything
    cells = defaultdict(list)
    for i, r in enumerate(records):
        if r["lat"] is not None:
            cells[(int(r["lat"] / 0.025), int(r["lon"] / 0.025))].append(i)

    pairs, cand = [], []

    def consider(i, j, dist):
        a, b = records[i], records[j]
        same_listing_site = a["source"] == b["source"] and a["source"] != "osm" \
            and a["source_id"] != b["source_id"] and not (a.get("approx") or b.get("approx"))  # one OTA does not list the same hotel twice under different ids (OSM can: node + way)
        s = name_sim(a["_al"], b["_al"])
        why = None
        rules = config.DEDUP_RULES
        if a.get("approx") or b.get("approx"):  # locality-level coordinates: wider radius, stricter names
            rules = [(4000, 0.85)]
        if same_listing_site:  # one site listing a property twice: only near-identical pins and names
            rules = [(150, 0.95)]
        if dist is not None:
            for d, t in rules:
                if dist <= d and s >= t:
                    why = f"dist {dist:.0f}m, name {s:.2f}"
                    break
        else:
            # no coordinates (e.g. Booking.com): Booking gives distance from the centre,
            # so the other record must sit on roughly the same ring around the city
            ring = a.get("ring_km") if a.get("ring_km") is not None else b.get("ring_km")
            other = b if a.get("lat") is None else a
            if re.sub(r"\W+", "", a["name"].lower()) == re.sub(r"\W+", "", b["name"].lower()):
                why = "no coords, identical name"
            elif ring is not None and other.get("lat") is not None and s >= 0.88 \
                    and abs(haversine((other["lat"], other["lon"]), config.CENTER) / 1000 - ring) <= 3:
                why = f"no coords, name {s:.2f}, ~{ring:g} km from centre"
            elif other.get("lat") is None and s >= 0.97:
                why = f"no coords on either, name {s:.2f}"
            elif ring is None and (s >= 0.97 or (s >= 0.92 and min(len(x) for x in a["_al"] + b["_al"]) >= 8)
                                   or (s >= 0.88 and min(len(_core(x)) for x in a["_al"] + b["_al"]) >= 2)):
                why = f"no coords, name {s:.2f}"
        if not why and a["_ph"] and a["_ph"] == b["_ph"] and phone_freq[a["_ph"]] <= 3:
            why = f"same phone {a['_ph']}"
        if why:
            cand.append((s, -(dist or 0), i, j, why))

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
    # Records without coordinates (Booking, Agoda, Yatra, Goibibo): compare only with
    # records sharing a distinctive name token, then apply the name rules in consider().
    tok_count = Counter(t for r in records for t in set(" ".join(r["_al"]).split()))
    index = defaultdict(set)
    for j, r in enumerate(records):
        for t in set(" ".join(r["_al"]).split()):
            if tok_count[t] < 60:
                index[t].add(j)
    for i, r in enumerate(records):
        if r["lat"] is not None:
            continue
        cands = set().union(*[index[t] for t in set(" ".join(r["_al"]).split()) if t in index] or [set()])
        for j in cands:
            if j != i and (records[j]["lat"] is not None or j > i):
                consider(i, j, None)

    # Strongest matches first. A cluster may not hold two *different* listings from the
    # same booking site unless their names are near-identical: sites rarely list one
    # hotel twice, so such a merge almost always means two neighbouring places chained.
    members = {i: [i] for i in range(n)}
    for s, _, i, j, why in sorted(cand, reverse=True):
        ri, rj = find(i), find(j)
        if ri == rj:
            continue
        ok = True
        for x in members[ri]:
            for y in members[rj]:
                a, b = records[x], records[y]
                if a["source"] == b["source"] and a["source"] != "osm" and a["source_id"] != b["source_id"] \
                        and name_sim(a["_al"], b["_al"]) < 0.95:
                    ok = False
                    break
            if not ok:
                break
        if not ok:
            continue
        parent[ri] = rj
        members[rj] += members.pop(ri)
        a, b = records[i], records[j]
        pairs.append((a["source"], a["name"], b["source"], b["name"], why))

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
