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

## Pipeline
1. **Collect** (`sources.py`): pages are fetched politely. robots.txt is respected, requests are rate-limited and pages are cached. Sites that block bots (Booking.com, MakeMyTrip, Yatra, TripAdvisor) are skipped, not worked around.
2. **Filter** to the study radius (`config.py`).
3. **Deduplicate** (`dedupe.py`): two records merge when they're close enough and their names are similar enough (see `DEDUP_RULES`), or when they share a phone number. Names are normalised first, which also handles OYO's "formerly X" names.
4. **Estimate** (`estimate.py`): reported beds or rooms are used where a source has them. Otherwise rooms and beds-per-room come from category priors in `config.CATEGORY_PRIORS`.

## Making it decision-grade
- Add Google Places, plus lists from NTKMA, Nashik police (lodge register), NMC trade licences and temple trusts. Append them as extra sources in the same record schema.
- Phone-survey a stratified sample of about 150–200 properties, then replace `CATEGORY_PRIORS` with the measured medians.
