"""Classify each property and estimate rooms and beds (low / central / high)."""
import re

import config
from dedupe import haversine


def classify(p) -> str:
    n = p["all_names"].lower()
    k = p["kinds"]
    s = p["stars"] or 0
    if re.search(r"dharm?a?sh?ala|dharmshala|bhakt[a]? ?ni[wv]as|yatri ?ni[wv]as|धर्मशाळा|धर्मशाला|भक्त ?निवास", n) \
            or "dharamshala" in k:
        return "dharamshala / bhakta niwas"
    if re.search(r"ashram|\bmath\b|\bmutt\b|akhada|आश्रम", n):
        return "ashram / math"
    if "hostel" in k or re.search(r"hostel|dorm", n):
        return "hostel"
    if "camp" in k or re.search(r"\bcamp|tent", n):
        return "campsite / tents"
    if re.search(r"home ?stay|guest ?house|bungalow|cottage|villa|stayvista|apartment|\bbnb\b|b ?& ?b", n) \
            or any(x in k for x in ("guest_house", "apartment", "chalet", "bed_and_breakfast", "private_guest_room", "cottage")):
        return "guest house / homestay"
    if "oyo" in p["sources"] or re.search(r"\boyo\b|super hotel o\b|collection o\b|townhouse|capital o\b", n):
        return "budget hotel (0-2 star)"  # OYO-branded: economy whatever an OTA star tag says
    if s >= 4:
        return "upscale (4-5 star)"
    if re.search(r"resort|vineyard|farm ?stay|retreat", n) or "resort" in k:
        return "resort"
    if s >= 3:
        return "midscale (3 star)"
    if re.search(r"home ?stay|guest ?house|bungalow|cottage|apartment|\bbnb\b|b ?& ?b", n) \
            or any(x in k for x in ("guest_house", "apartment", "chalet", "bed_and_breakfast", "private_guest_room", "cottage")):
        return "guest house / homestay"
    if re.search(r"\blodg", n):
        return "lodge"
    return "budget hotel (0-2 star)"


def zone(p):
    if p["lat"] is None:
        return "Unknown (no coordinates)"
    return min(config.ZONES, key=lambda z: haversine((p["lat"], p["lon"]), config.ZONES[z]))


def estimate(p):
    cat = classify(p)
    pri = config.CATEGORY_PRIORS[cat]
    p["category"] = cat
    p["zone"] = zone(p)
    p["dist_km_from_ramkund"] = (round(haversine((p["lat"], p["lon"]), config.CENTER) / 1000, 1)
                                 if p["lat"] is not None else None)
    if p.get("beds_reported"):
        b = float(p["beds_reported"])
        p.update(beds_low=b, beds_mid=b, beds_high=b, rooms_mid=p.get("rooms_reported"), basis="reported beds")
    elif p.get("rooms_reported"):
        r = float(p["rooms_reported"])
        lo, mid, hi = pri["beds_per_room"]
        p.update(rooms_mid=r, beds_low=r * lo, beds_mid=r * mid, beds_high=r * hi, basis="reported rooms x prior")
    else:
        (rl, rm, rh), (bl, bm, bh) = pri["rooms"], pri["beds_per_room"]
        p.update(rooms_mid=rm, beds_low=rl * bl, beds_mid=rm * bm, beds_high=rh * bh, basis="category prior")
    return p
