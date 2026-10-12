"""Nashik accommodation bed census - end-to-end pipeline.

    python run.py                 # all sources (Google only if GOOGLE_MAPS_API_KEY is set)
    python run.py --sources osm,oyo
    python run.py --no-cache      # refetch everything
"""
import argparse
import json
import re
from pathlib import Path

import pandas as pd

import config
import fetch
import sources
from dedupe import dedupe, haversine
from estimate import estimate

OUT = Path(__file__).parent / "output"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default=",".join(sources.ALL))
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()
    if args.no_cache:
        for f in fetch.CACHE.glob("*"):
            f.unlink()

    raw = []
    for name in args.sources.split(","):
        print(f"[collect] {name}")
        got = sources.ALL[name]()
        print(f"  -> {len(got)} records")
        raw += got
    for r in raw:
        if r["lat"] is not None:
            r["in_area"] = haversine((r["lat"], r["lon"]), config.CENTER) <= config.RADIUS_KM * 1000
        else:
            r["in_area"] = (r.get("ring_km") or 0) <= config.RADIUS_KM and not re.search(
                r"igatpuri|thane|shahapur|shahpur|murbad|dehradun|saputara|hatgad|koknipura|vaitarna|kasara",
                r["name"], re.I)
        # paying-guest (PG) student housing is not short-stay accommodation
        if re.search(r"\bpg\b|paying guest", r["name"], re.I):
            r["in_area"] = False
    pd.DataFrame(raw).to_csv(OUT / "raw_records.csv", index=False)
    area = [r for r in raw if r["in_area"]]
    print(f"[filter] {len(area)}/{len(raw)} records within {config.RADIUS_KM} km of Ramkund (or no coords)")

    props, pairs = dedupe(area)
    print(f"[dedupe] {len(area)} records -> {len(props)} unique properties ({len(pairs)} matched pairs)")
    pd.DataFrame(pairs, columns=["source_a", "name_a", "source_b", "name_b", "reason"]) \
        .to_csv(OUT / "dedupe_matches.csv", index=False)

    # Keep only places that offer rooms: listed on a booking site, or tagged as lodging on the map.
    # Map entries merely *named* "Hotel X" are often eateries in India, so they are set aside.
    lodging_tags = {"hotel", "motel", "guest_house", "hostel", "apartment", "chalet", "camp_site",
                    "resort", "dharamshala", "dharmashala", "dormitory", "shelter_lodging"}
    stay_words = re.compile(r"lodg|guest ?house|dharm?a?sh?ala|dharmshala|homestay|home stay|holiday home|"
                            r"hostel|niwas|nivas|yatri|bhavan|bhawan|\binn\b|residency|farm ?stay|retreat", re.I)
    food_words = re.compile(r"restaurant|dhaba|ढाबा|fast ?food|cafe|bhojnalaya|khanaval|misal|bar\b|food", re.I)

    def offers_rooms(p):
        if set(p["sources"].split(",")) - {"osm"}:
            return True  # a booking site sells rooms here
        # map-only: needs a lodging tag AND a name that says it offers stays, and nothing food-only
        return bool(lodging_tags & set(p["kinds"].split(","))) and bool(stay_words.search(p["all_names"])) \
            and not food_words.search(p["all_names"])
    dropped = [p for p in props if not offers_rooms(p)]
    props = [p for p in props if offers_rooms(p)]
    pd.DataFrame(dropped)[["name", "all_names", "kinds", "lat", "lon", "urls"]] \
        .to_csv(OUT / "to_verify_map_only_places.csv", index=False)
    print(f"[rooms filter] removed {len(dropped)} map-only places with no evidence of rooms "
          f"(see to_verify_map_only_places.csv); {len(props)} remain")

    df = pd.DataFrame([estimate(p) for p in props])
    df = df.sort_values(["zone", "category", "name"])
    df.to_csv(OUT / "master_properties.csv", index=False)

    def agg(by):
        g = df.groupby(by).agg(properties=("name", "size"), rooms_mid=("rooms_mid", "sum"),
                               beds_low=("beds_low", "sum"), beds_mid=("beds_mid", "sum"),
                               beds_high=("beds_high", "sum"))
        return g.round(0).astype(int).sort_values("beds_mid", ascending=False)

    by_cat, by_zone = agg("category"), agg("zone")
    src_counts = {s: int(df["sources"].str.split(",").apply(lambda xs: s in xs).sum())
                  for s in sorted({x for xs in df["sources"].str.split(",") for x in xs})}
    summary = {
        "study_area": f"{config.RADIUS_KM} km radius around Ramkund {config.CENTER}",
        "raw_records": len(raw), "records_in_area": len(area), "unique_properties": len(df),
        "multi_source_properties": int((df["n_sources"] > 1).sum()),
        "properties_per_source": src_counts,
        "basis_counts": df["basis"].value_counts().to_dict(),
        "beds_total": {k: int(df[f"beds_{k}"].sum()) for k in ("low", "mid", "high")},
        "rooms_total_mid": int(df["rooms_mid"].sum()),
        "by_category": by_cat.reset_index().to_dict("records"),
        "by_zone": by_zone.reset_index().to_dict("records"),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))
    print("\n=== Unique properties by category ===\n" + by_cat.to_string())
    print("\n=== By zone ===\n" + by_zone.to_string())
    print(f"\nProperties per source (after dedup): {src_counts}")
    t = summary["beds_total"]
    print(f"\nESTIMATED BEDS (listed properties only): low {t['low']:,} | central {t['mid']:,} | high {t['high']:,}")

    import report
    report.write(df, summary, pairs, OUT / "report.html")
    print(f"\nWrote {OUT}/master_properties.csv, raw_records.csv, dedupe_matches.csv, summary.json, report.html")


if __name__ == "__main__":
    main()
