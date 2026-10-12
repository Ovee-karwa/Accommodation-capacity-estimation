# Nashik Bed Census

Estimates total beds in hotels and other accommodation within 35 km of Ramkund
(Nashik city, Nashik Road, Deolali, Ojhar, Trimbakeshwar), for Simhastha Kumbh 2027 planning.

```
pip install requests pandas
python run.py                          # OSM + EaseMyTrip + Cleartrip + OYO
GOOGLE_MAPS_API_KEY=... python run.py  # adds Google Places (biggest coverage gain)
```

Outputs go to `output/`:
- `master_properties.csv` has one row per unique property, with its category, zone, sources and low/central/high beds.
- `raw_records.csv` holds every record before deduplication.
- `dedupe_matches.csv` lists every merged pair and the reason (for audit).
- `summary.json` and `report.html` give the totals, map and breakdowns.

## Sources
- Fetched automatically: OpenStreetMap, the public summary pages of EaseMyTrip, Cleartrip and OYO, and Google Places (needs an API key).
- Collected by scrolling each site's full results in a browser, the way a visitor would, saved in `browser_lists/*.tsv`: Cleartrip, EaseMyTrip, Booking.com, MakeMyTrip, Agoda, Yatra and Goibibo. No site showed a bot check. Where a list has hotel IDs, coordinates are fetched from each hotel's public page.

Run everything with:
```
python run.py --sources osm,easemytrip,cleartrip,oyo,cleartrip_full,easemytrip_full,booking,makemytrip,agoda,yatra,goibibo
```

## Pipeline
1. **Collect** (`sources.py`): pages are fetched politely. robots.txt is respected, requests are rate-limited and pages are cached. Sites that block bots (Booking.com, MakeMyTrip, Yatra, TripAdvisor) are skipped, not worked around.
2. **Filter** to the study radius (`config.py`).
3. **Deduplicate** (`dedupe.py`): two records merge when they're close enough and their names are similar enough (see `DEDUP_RULES`), or when they share a phone number. Names are normalised first, which also handles OYO's "formerly X" names.
4. **Rooms only**: a place is kept if a booking site sells rooms there. A map-only place is kept only if it is tagged as lodging *and* its name says it offers stays. Everything else goes to `output/to_verify_map_only_places.csv`. Student/PG housing and out-of-area listings are dropped.
5. **Estimate** (`estimate.py`): reported beds or rooms are used where a source has them. Otherwise rooms and beds-per-room come from category priors in `config.CATEGORY_PRIORS`.

## Making it decision-grade
- Add Google Places, plus lists from NTKMA, Nashik police (lodge register), NMC trade licences and temple trusts. Append them as extra sources in the same record schema.
- Phone-survey a stratified sample of about 150–200 properties, then replace `CATEGORY_PRIORS` with the measured medians.
