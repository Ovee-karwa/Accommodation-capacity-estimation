"""Nashik accommodation bed census - end-to-end pipeline.

    python run.py                 # all sources (Google only if GOOGLE_MAPS_API_KEY is set)
    python run.py --sources osm,oyo
    python run.py --no-cache      # refetch everything
"""
import argparse
import json
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
        r["in_area"] = r["lat"] is None or haversine((r["lat"], r["lon"]), config.CENTER) <= config.RADIUS_KM * 1000
    pd.DataFrame(raw).to_csv(OUT / "raw_records.csv", index=False)
    area = [r for r in raw if r["in_area"]]
    print(f"[filter] {len(area)}/{len(raw)} records within {config.RADIUS_KM} km of Ramkund (or no coords)")

    props, pairs = dedupe(area)
    print(f"[dedupe] {len(area)} records -> {len(props)} unique properties ({len(pairs)} matched pairs)")
    pd.DataFrame(pairs, columns=["source_a", "name_a", "source_b", "name_b", "reason"]) \
        .to_csv(OUT / "dedupe_matches.csv", index=False)

    df = pd.DataFrame([estimate(p) for p in props])
    df = df.sort_values(["zone", "category", "name"])
    df.to_csv(OUT / "master_properties.csv", index=False)

    def agg(by):
        g = df.groupby(by).agg(properties=("name", "size"), rooms_mid=("rooms_mid", "sum"),
                               beds_low=("beds_low", "sum"), beds_mid=("beds_mid", "sum"),
                               beds_high=("beds_high", "sum"))
        return g.round(0).astype(int).sort_values("beds_mid", ascending=False)

    by_cat, by_zone = agg("category"), agg("zone")
    src_counts = {s: int(df["sources"].str.contains(s).sum()) for s in args.sources.split(",")}
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
