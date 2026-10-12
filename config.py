"""Study area, zones and bed-estimation assumptions.

Everything a planner may want to tweak lives here. The room/bed priors are
ASSUMPTIONS used only where a source gives no real room/bed count; replace them
with numbers from a field survey (see README) before quoting results.
"""

# Ramkund, Panchavati: the ritual centre of the Nashik Kumbh
CENTER = (20.0076, 73.7927)
RADIUS_KM = 35  # covers Nashik city, Nashik Road/Deolali, Ojhar and Trimbakeshwar (~28 km)

# Zones: each property is assigned to the nearest anchor.
ZONES = {
    "Panchavati / Ramkund / Old Nashik": (20.0076, 73.7927),
    "CBS / College Rd / Gangapur Rd": (20.0000, 73.7650),
    "Mumbai Naka / Dwarka / Pathardi": (19.9850, 73.7900),
    "CIDCO / Ambad / Satpur MIDC": (19.9600, 73.7400),
    "Nashik Road / Deolali / Jail Rd": (19.9500, 73.8400),
    "Trimbakeshwar": (19.9324, 73.5306),
    "Ojhar / Airport / Pimpalgaon": (20.1000, 73.9200),
    "Wine belt (Sula/Gangapur dam)": (20.0200, 73.6800),
    "Sinnar / Shirdi road": (19.8500, 73.9900),
}

# Room priors per category: (low, central, high) rooms per property,
# plus beds per room (low, central, high). Used ONLY when no real count exists.
CATEGORY_PRIORS = {
    "upscale (4-5 star)": {"rooms": (60, 90, 140), "beds_per_room": (1.8, 2.0, 2.2)},
    "midscale (3 star)": {"rooms": (25, 40, 65), "beds_per_room": (1.8, 2.0, 2.3)},
    "resort": {"rooms": (15, 30, 55), "beds_per_room": (2.0, 2.2, 2.6)},
    "budget hotel (0-2 star)": {"rooms": (10, 18, 30), "beds_per_room": (2.0, 2.3, 2.8)},
    "lodge": {"rooms": (8, 16, 28), "beds_per_room": (2.0, 2.5, 3.0)},
    "guest house / homestay": {"rooms": (2, 5, 9), "beds_per_room": (2.0, 2.5, 3.0)},
    "hostel": {"rooms": (3, 6, 10), "beds_per_room": (3.0, 4.0, 6.0)},
    "dharamshala / bhakta niwas": {"rooms": (12, 30, 60), "beds_per_room": (3.0, 4.0, 6.0)},
    "ashram / math": {"rooms": (4, 12, 30), "beds_per_room": (3.0, 4.0, 6.0)},
    "campsite / tents": {"rooms": (5, 15, 30), "beds_per_room": (2.0, 3.0, 4.0)},
}

# Dedup thresholds (metres, name similarity 0-1)
DEDUP_RULES = [
    (75, 0.60),    # practically the same pin, names loosely similar
    (400, 0.85),   # nearby, names clearly the same
    (2500, 0.96),  # OTA pins can be badly off: only near-identical names
    (8000, 0.999), # identical normalised names (OTA pin placed on wrong locality)
]

USER_AGENT = "NashikBedCensus/0.1 (Kumbh capacity research; polite crawler)"
REQUEST_DELAY_S = 1.5      # per host
MAX_PAGES_PER_SITE = 120
