"""Self-contained HTML report: headline numbers, map, breakdowns, property table."""
import html
import json

import config

COLORS = {
    "upscale (4-5 star)": "#7c3aed", "midscale (3 star)": "#2563eb", "resort": "#0891b2",
    "budget hotel (0-2 star)": "#16a34a", "lodge": "#65a30d", "guest house / homestay": "#ca8a04",
    "hostel": "#ea580c", "dharamshala / bhakta niwas": "#dc2626", "ashram / math": "#db2777",
    "campsite / tents": "#64748b",
}


def _table(rows, cols, fmt=None):
    head = "".join(f"<th>{html.escape(c)}</th>" for c in cols)
    body = ""
    for r in rows:
        cells = []
        for c in cols:
            v = r.get(c)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                cells.append(f'<td class="n">{v:,.0f}</td>')
            else:
                cells.append(f"<td>{html.escape('' if v is None else str(v))}</td>")
        body += "<tr>" + "".join(cells) + "</tr>"
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def write(df, summary, pairs, path):
    t = summary["beds_total"]
    pts = [dict(n=r["name"], c=r["category"], z=r["zone"], s=r["sources"], b=round(r["beds_mid"]),
                la=r["lat"], lo=r["lon"])
           for r in df.to_dict("records") if r["lat"] == r["lat"] and r["lat"] is not None]
    cat_rows = summary["by_category"]
    zone_rows = summary["by_zone"]
    src = summary["properties_per_source"]
    basis = summary["basis_counts"]
    prop_rows = df.sort_values("beds_mid", ascending=False)[
        ["name", "category", "stars", "zone", "sources", "basis", "beds_mid"]].to_dict("records")
    pair_rows = [dict(zip(["source A", "name A", "source B", "name B", "reason"], p)) for p in pairs]
    legend = "".join(f'<span><i style="background:{c}"></i>{html.escape(k)}</span>' for k, c in COLORS.items())

    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Nashik Bed Census</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
:root{{--bg:#fafaf9;--fg:#1c1917;--mut:#57534e;--card:#fff;--line:#e7e5e4;--acc:#b45309}}
@media (prefers-color-scheme:dark){{:root{{--bg:#1c1917;--fg:#f5f5f4;--mut:#a8a29e;--card:#292524;--line:#44403c;--acc:#f59e0b}}}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,sans-serif}}
main{{max-width:1100px;margin:0 auto;padding:24px 16px 64px}}
h1{{font-size:28px;margin:0 0 4px}} h2{{font-size:19px;margin:36px 0 10px}} .mut{{color:var(--mut)}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:20px 0}}
.kpi{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}}
.kpi b{{display:block;font-size:26px;font-variant-numeric:tabular-nums}} .kpi.main b{{color:var(--acc)}}
.warn{{background:var(--card);border-left:4px solid var(--acc);padding:12px 16px;border-radius:6px;margin:16px 0}}
#map{{height:520px;border-radius:10px;border:1px solid var(--line)}}
.legend{{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:13px;margin:8px 0}} .legend i{{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px}}
.tw{{overflow-x:auto;max-height:520px;overflow-y:auto;border:1px solid var(--line);border-radius:8px}}
table{{border-collapse:collapse;width:100%;font-size:13.5px;background:var(--card)}}
th,td{{padding:6px 10px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}}
th{{position:sticky;top:0;background:var(--card)}} td.n{{text-align:right;font-variant-numeric:tabular-nums}}
input{{padding:8px 10px;width:100%;max-width:360px;margin:6px 0;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--fg)}}
</style></head><body><main>
<h1>Nashik Bed Census</h1>
<div class="mut">Accommodation listed online within {config.RADIUS_KM} km of Ramkund, Panchavati (Nashik city, Nashik Road, Deolali, Ojhar, Trimbakeshwar)</div>

<div class="kpis">
 <div class="kpi main"><span class="mut">Estimated beds (central)</span><b>{t['mid']:,}</b></div>
 <div class="kpi"><span class="mut">Range (low – high)</span><b>{t['low']:,} – {t['high']:,}</b></div>
 <div class="kpi"><span class="mut">Unique properties</span><b>{summary['unique_properties']:,}</b></div>
 <div class="kpi"><span class="mut">Rooms (central)</span><b>{summary['rooms_total_mid']:,}</b></div>
 <div class="kpi"><span class="mut">Raw records → duplicates merged</span><b>{summary['records_in_area']:,} → {summary['unique_properties']:,}</b></div>
</div>

<div class="warn"><b>Read this as a floor, not the answer.</b> It counts only properties visible in the sources
crawled ({", ".join(f"{k}: {v}" for k, v in src.items())} properties after dedup). Booking.com, MakeMyTrip, Yatra
and TripAdvisor block automated access and were not used; Google Places runs only with an API key. Most
dharamshalas, ashrams, trust lodges and homestays are not online. Bed counts are mostly <i>estimated</i> from
category priors (basis: {", ".join(f"{k}: {v}" for k, v in basis.items())}) — calibrate with a phone/field survey.</div>

<h2>Map</h2>
<div class="legend">{legend}</div>
<div id="map"></div>

<h2>By category</h2>
<div class="tw">{_table(cat_rows, ["category", "properties", "rooms_mid", "beds_low", "beds_mid", "beds_high"])}</div>
<h2>By zone</h2>
<div class="tw">{_table(zone_rows, ["zone", "properties", "rooms_mid", "beds_low", "beds_mid", "beds_high"])}</div>

<h2>All properties</h2>
<input id="q" placeholder="Filter by name, zone, category…">
<div class="tw" id="props">{_table(prop_rows, ["name", "category", "stars", "zone", "sources", "basis", "beds_mid"])}</div>

<h2>Duplicate matches (audit)</h2>
<div class="mut">Every pair merged by the de-duplication step and why.</div>
<div class="tw">{_table(pair_rows, ["source A", "name A", "source B", "name B", "reason"])}</div>

<h2>Assumptions used where no real count exists</h2>
<div class="tw">{_table([dict(category=k, rooms_low=v["rooms"][0], rooms_mid=v["rooms"][1], rooms_high=v["rooms"][2],
                               beds_per_room=f'{v["beds_per_room"][0]} / {v["beds_per_room"][1]} / {v["beds_per_room"][2]}')
                          for k, v in config.CATEGORY_PRIORS.items()],
                         ["category", "rooms_low", "rooms_mid", "rooms_high", "beds_per_room"])}</div>
</main>
<script>
const P={json.dumps(pts)}, C={json.dumps(COLORS)};
const m=L.map('map').setView([{config.CENTER[0]},{config.CENTER[1]}],11);
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:19,attribution:'&copy; OpenStreetMap'}}).addTo(m);
L.circle([{config.CENTER[0]},{config.CENTER[1]}],{{radius:{config.RADIUS_KM * 1000},color:'#b45309',fill:false,weight:1,dashArray:'4'}}).addTo(m);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c]));
P.forEach(p=>L.circleMarker([p.la,p.lo],{{radius:Math.max(3,Math.sqrt(p.b)/1.6),color:C[p.c]||'#444',weight:1,fillOpacity:.6}})
  .bindPopup(`<b>${{esc(p.n)}}</b><br>${{esc(p.c)}}<br>${{esc(p.z)}}<br>~${{p.b}} beds<br><small>${{esc(p.s)}}</small>`).addTo(m));
document.getElementById('q').addEventListener('input',e=>{{const q=e.target.value.toLowerCase();
  document.querySelectorAll('#props tbody tr').forEach(r=>r.style.display=r.textContent.toLowerCase().includes(q)?'':'none');}});
</script></body></html>"""
    path.write_text(doc, encoding="utf-8")
