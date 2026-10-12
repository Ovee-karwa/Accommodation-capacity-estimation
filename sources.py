"""Collectors. Each returns a list of dicts in the common record schema:

source, source_id, name, kind, stars, lat, lon, address, locality, phone,
rooms, beds, url
"""
import json
import os
import time
import re
from collections import deque
from urllib.parse import urljoin, urlparse

import config
import fetch

LAT0, LON0 = config.CENTER
RADIUS_M = config.RADIUS_KM * 1000


def rec(**kw):
    base = dict(source=None, source_id=None, name=None, kind=None, stars=None, lat=None,
                lon=None, address=None, locality=None, phone=None, rooms=None, beds=None,
                url=None)
    base.update(kw)
    return base


def _num(v):
    try:
        f = float(str(v).strip())
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _ld_json(html):
    out = []
    for block in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S):
        try:
            j = json.loads(block)
        except json.JSONDecodeError:
            continue
        stack = [j]
        while stack:  # flatten ItemList / @graph / lists
            o = stack.pop()
            if isinstance(o, list):
                stack.extend(o)
            elif isinstance(o, dict):
                t = o.get("@type")
                t = t if isinstance(t, list) else [t]
                if any(x in ("Hotel", "LodgingBusiness", "Hostel", "Motel", "Resort", "BedAndBreakfast")
                       for x in t):
                    out.append(o)
                stack.extend(v for k, v in o.items() if k in ("itemListElement", "@graph", "item"))
    return out


def _js_state(html, var):
    m = re.search(r'window\.' + re.escape(var) + r'\s*=\s*', html)
    if not m:
        return None
    try:
        return json.JSONDecoder().raw_decode(html[m.end():])[0]
    except json.JSONDecodeError:
        return None


def _crawl(seeds, listing_re, max_pages=config.MAX_PAGES_PER_SITE):
    """BFS over a site's own city/locality listing pages. Yields (url, html)."""
    seen, q, n = set(), deque(seeds), 0
    while q and n < max_pages:
        url = q.popleft().split("#")[0]
        if url in seen:
            continue
        seen.add(url)
        html = fetch.get(url)
        n += 1
        if not html:
            continue
        yield url, html
        for href in re.findall(r'href="([^"#?]+)', html):
            u = urljoin(url, href.replace("&amp;", "&"))
            if urlparse(u).netloc == urlparse(url).netloc and listing_re.search(u) and u not in seen:
                q.append(u)


# ---------------------------------------------------------------- OpenStreetMap
def osm():
    """OpenStreetMap via Overpass: hotels, lodges, guest houses, hostels, dharamshalas, ashrams."""
    lat, lon, r = LAT0, LON0, RADIUS_M
    name_re = ("dharm?a?sh?ala|dharmshala|bhakt[a]? ?niwas|bhakt[a]? ?nivas|yatri ?ni[wv]as|"
               "lodge|lodging|guest ?house|ashram|math |mutt|akhada|hostel|hotel|homestay|resort")
    dlat, dlon = config.RADIUS_KM / 111.0, config.RADIUS_KM / 104.0
    bbox = f"{lat - dlat},{lon - dlon},{lat + dlat},{lon + dlon}"
    queries = [
        f'nwr["tourism"~"^(hotel|motel|guest_house|hostel|apartment|chalet|camp_site|resort)$"]({bbox});'
        f'nwr["amenity"~"^(dharamshala|dharmashala|shelter_lodging)$"]({bbox});'
        f'nwr["building"~"^(hotel|dormitory)$"]["name"]({bbox});',
        # name search restricted to named buildings/amenities to keep it light
        f'nwr["building"]["name"~"{name_re}",i]({bbox});'
        f'nwr["amenity"~"^(place_of_worship|community_centre|social_facility)$"]["name"~"dharm|niwas|nivas|ashram|bhavan",i]({bbox});',
    ]
    elements = {}
    for body in queries:
        q = f"[out:json][timeout:170];({body});out tags center;"
        txt = None
        for attempt in range(4):  # public Overpass servers are often busy (HTTP 504/429)
            for ep in ("https://overpass-api.de/api/interpreter",
                       "https://maps.mail.ru/osm/tools/overpass/api/interpreter"):
                txt = fetch.get(ep, method="POST", data={"data": q}, check_robots=False,
                                headers={"User-Agent": "NashikBedCensus/0.1", "Accept": "application/json"})
                if txt and txt.lstrip().startswith("{"):
                    break
                txt = None
            if txt:
                break
            time.sleep(20 * (attempt + 1))
        if txt:
            for e in json.loads(txt)["elements"]:
                elements[(e["type"], e["id"])] = e
    out = []
    for e in elements.values():
        t = e.get("tags", {})
        name = t.get("name:en") or t.get("name") or t.get("name:mr")
        if not name:
            continue
        lat_ = e.get("lat") or e.get("center", {}).get("lat")
        lon_ = e.get("lon") or e.get("center", {}).get("lon")
        kind = t.get("tourism") or t.get("amenity") or t.get("building") or ""
        # In India "Hotel X" is very often an eatery: drop anything mapped as one
        if t.get("amenity") in ("restaurant", "cafe", "fast_food", "bar", "food_court"):
            continue
        if kind == "place_of_worship" and not re.search(name_re, name, re.I):
            continue
        # student / PG hostels and anonymous hostel blocks are not pilgrim accommodation
        if re.search(r"boys|girls|ladies|college|collage|\bpg\b|student|hostel block|vidyarthi|mess", name, re.I) \
                or len(name.strip()) <= 3:
            continue
        out.append(rec(
            source="osm", source_id=f"{e['type']}/{e['id']}", name=name, kind=kind,
            stars=_num(t.get("stars")), lat=lat_, lon=lon_,
            address=" ".join(filter(None, [t.get("addr:housenumber"), t.get("addr:street"),
                                           t.get("addr:suburb"), t.get("addr:city")])) or None,
            locality=t.get("addr:suburb"), phone=t.get("phone") or t.get("contact:phone"),
            rooms=_num(t.get("rooms")), beds=_num(t.get("beds")),
            url=f"https://www.openstreetmap.org/{e['type']}/{e['id']}"))
    return out


# ---------------------------------------------------------------- EaseMyTrip
def easemytrip():
    seeds = ["https://www.easemytrip.com/hotels/hotels-in-nashik/",
             "https://www.easemytrip.com/hotels/hotels-in-trimbakeshwar/",
             "https://www.easemytrip.com/hotels/hotels-in-trimbak/"]
    listing = re.compile(r"easemytrip\.com/hotels/hotels-in-[a-z0-9-]*(nashik|trimbak|panchavati|deolali)[a-z0-9-]*/?$")
    out = {}
    for url, html in _crawl(seeds, listing):
        for h in _ld_json(html):
            geo = h.get("geo") or {}
            addr = h.get("address") or {}
            name = h.get("name")
            if not name:
                continue
            out[name + str(geo.get("latitude"))] = rec(
                source="easemytrip", source_id=h.get("url") or name, name=name, kind="hotel",
                stars=_num((h.get("starRating") or {}).get("ratingValue")),
                lat=_num(geo.get("latitude")), lon=_num(geo.get("longitude")),
                address=(addr.get("streetAddress") or "").replace(">", ", ") or None,
                locality=addr.get("addressLocality"), phone=h.get("telephone"), url=url)
    return list(out.values())


# ---------------------------------------------------------------- Cleartrip
def cleartrip():
    seeds = ["https://www.cleartrip.com/hotels/india/nashik/",
             "https://www.cleartrip.com/hotels/3-star-hotels-in-nashik",
             "https://www.cleartrip.com/hotels/4-star-hotels-in-nashik",
             "https://www.cleartrip.com/hotels/5-star-hotels-in-nashik",
             "https://www.cleartrip.com/hotels/india/trimbakeshwar/"]
    listing = re.compile(r"cleartrip\.com/hotels/(india/(nashik|trimbak[a-z]*)/?$|"
                         r"[a-z0-9-]*hotels-in-[a-z0-9-]*(nashik|trimbak)[a-z0-9-]*/?$)")
    found = {}
    for url, html in _crawl(seeds, listing):
        for h in _ld_json(html):
            m = re.search(r"/hotels/details/(?:[a-z0-9-]*-)?(\d+)", h.get("url", ""))
            if not m or not h.get("name"):
                continue
            found[m.group(1)] = (h, h["url"].split("?")[0])
    out = []
    print(f"  cleartrip: {len(found)} hotels in listings; fetching detail pages for coordinates")
    for hid, (h, durl) in found.items():
        lat = lon = None
        html = fetch.get(durl)
        if html:
            m = re.search(r'"latLong":\{"lat":(-?[\d.]+),"lng":(-?[\d.]+)', html)
            if m:
                lat, lon = float(m.group(1)), float(m.group(2))
        addr = h.get("address") or {}
        out.append(rec(source="cleartrip", source_id=hid, name=h["name"], kind="hotel",
                       stars=_num((h.get("starRating") or {}).get("ratingValue")),
                       lat=lat, lon=lon, locality=addr.get("addressLocality"),
                       address=addr.get("streetAddress"), url=durl))
    return out


# ---------------------------------------------------------------- OYO
def oyo():
    seeds = ["https://www.oyorooms.com/hotels-in-nashik/",
             "https://www.oyorooms.com/hotels-in-trimbakeshwar/"]
    listing = re.compile(r"oyorooms\.com/(hotels-in-[a-z0-9-]*(nashik|trimbak)[a-z0-9-]*|"
                         r"[a-z-]+-hotels-in-nashik)/?$")
    out = {}
    for url, html in _crawl(seeds, listing):
        st = _js_state(html, "__PRELOADED_STATE__") or {}
        for h in (st.get("listing") or {}).get("hotels") or []:
            lat = lon = None
            if h.get("geo_location"):
                lat, lon = (float(x) for x in h["geo_location"].split(","))
            out[h["id"]] = rec(source="oyo", source_id=h["id"], name=h.get("name"),
                               kind="budget_branded", lat=lat, lon=lon,
                               address=h.get("address"), url="https://www.oyorooms.com" + h.get("url", ""))
    return list(out.values())


# ---------------------------------------------------------------- Google Places (optional)
def google_places():
    """Google Places API (New) Text Search over a grid. Needs GOOGLE_MAPS_API_KEY.

    Cost guide: ~25 tiles x 8 queries x up to 3 pages ≈ 600 requests (a few USD at current pricing).
    """
    key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not key:
        print("  google: GOOGLE_MAPS_API_KEY not set -> skipped (biggest coverage gain if enabled)")
        return []
    queries = ["hotel", "lodge", "dharamshala", "bhakta niwas", "guest house", "homestay",
               "hostel", "ashram rooms"]
    step = 0.06  # ~6.5 km tiles
    lat_min, lat_max = LAT0 - 0.32, LAT0 + 0.32
    lon_min, lon_max = LON0 - 0.34, LON0 + 0.34
    hdr = {"X-Goog-Api-Key": key, "Content-Type": "application/json",
           "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.location,"
                               "places.types,places.primaryType,places.nationalPhoneNumber,nextPageToken"}
    out = {}
    lat = lat_min
    while lat < lat_max:
        lon = lon_min
        while lon < lon_max:
            for q in queries:
                token = None
                for _ in range(3):
                    body = {"textQuery": q, "pageSize": 20, "locationRestriction": {"rectangle": {
                        "low": {"latitude": lat, "longitude": lon},
                        "high": {"latitude": lat + step, "longitude": lon + step}}}}
                    if token:
                        body["pageToken"] = token
                    txt = fetch.get("https://places.googleapis.com/v1/places:searchText", method="POST",
                                    json_body=body, headers=hdr, check_robots=False)
                    if not txt:
                        break
                    j = json.loads(txt)
                    for p in j.get("places", []):
                        types = p.get("types", [])
                        if not ({"lodging", "hotel", "motel", "hostel", "guest_house", "bed_and_breakfast",
                                 "resort_hotel", "inn", "campground", "extended_stay_hotel",
                                 "budget_japanese_inn", "cottage", "private_guest_room"} & set(types)
                                or re.search(r"dharm|niwas|nivas|ashram|lodge", p["displayName"]["text"], re.I)):
                            continue
                        out[p["id"]] = rec(source="google", source_id=p["id"], name=p["displayName"]["text"],
                                           kind=p.get("primaryType") or "lodging",
                                           lat=p["location"]["latitude"], lon=p["location"]["longitude"],
                                           address=p.get("formattedAddress"), phone=p.get("nationalPhoneNumber"),
                                           url=f"https://www.google.com/maps/place/?q=place_id:{p['id']}")
                    token = j.get("nextPageToken")
                    if not token:
                        break
            lon += step
        lat += step
    return list(out.values())


ALL = {"osm": osm, "easemytrip": easemytrip, "cleartrip": cleartrip, "oyo": oyo,
       "google": google_places}
