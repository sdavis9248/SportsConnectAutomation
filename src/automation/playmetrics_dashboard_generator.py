"""
PlayMetrics Enrollment Dashboard Generator

Generates a self-contained HTML dashboard from packages JSON + volunteers CSV.
Uses the same DIVISION_CONFIG and data model as playmetrics_enrollment_report.py.

Data flow:
  --pm-download packages   -> packages_*.json   \
  --pm-download volunteers -> volunteers_*.csv    >-> --pm-dashboard -> enrollment_dashboard.html
  --pm-download coaching   -> coaching-requests_*.csv (future)
"""

import os
import re
import csv
import json
import logging
import base64
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict
from collections import defaultdict

logger = logging.getLogger(__name__)

try:
    from automation.playmetrics_enrollment_report import (
        DIVISION_CONFIG, _parse_currency, _find_latest_json,
    )
    _USING_REPORT_MODULE = True
except ImportError:
    _USING_REPORT_MODULE = False

    DIVISION_CONFIG = {
        "05U Schoolyard Coed": {"roster_size":  0, "roster_min":  0, "on_field":  0,  "refs_required": False, "sort": 1},
        "06UB Boys":           {"roster_size":  6, "roster_min":  5, "on_field":  4,  "refs_required": False, "sort": 2},
        "06UG Girls":          {"roster_size":  6, "roster_min":  5, "on_field":  4,  "refs_required": False, "sort": 3},
        "07UB Boys":           {"roster_size":  7, "roster_min":  6, "on_field":  4,  "refs_required": False, "sort": 4},
        "07UG Girls":          {"roster_size":  7, "roster_min":  6, "on_field":  4,  "refs_required": False, "sort": 5},
        "08UB Boys":           {"roster_size":  7, "roster_min":  6, "on_field":  5,  "refs_required": False, "sort": 6},
        "08UG Girls":          {"roster_size":  7, "roster_min":  6, "on_field":  5,  "refs_required": False, "sort": 7},
        "10UB Boys":           {"roster_size":  9, "roster_min":  8, "on_field":  7,  "refs_required": True,  "sort": 8},
        "10UG Girls":          {"roster_size":  9, "roster_min":  8, "on_field":  7,  "refs_required": True,  "sort": 9},
        "12UB Boys":           {"roster_size": 12, "roster_min": 10, "on_field":  9,  "refs_required": True,  "sort": 10},
        "12UG Girls":          {"roster_size": 12, "roster_min": 10, "on_field":  9,  "refs_required": True,  "sort": 11},
        "14UB Boys":           {"roster_size": 14, "roster_min": 12, "on_field": 11,  "refs_required": True,  "sort": 12},
        "14UG Girls":          {"roster_size": 14, "roster_min": 12, "on_field": 11,  "refs_required": True,  "sort": 13},
        "16UB Boys":           {"roster_size": 14, "roster_min": 12, "on_field": 11,  "refs_required": True,  "sort": 14},
        "16UG Girls":          {"roster_size": 14, "roster_min": 12, "on_field": 11,  "refs_required": True,  "sort": 15},
        "19UB Boys":           {"roster_size": 22, "roster_min": 12, "on_field": 11,  "refs_required": True,  "sort": 16},
        "19UG Girls":          {"roster_size": 22, "roster_min": 12, "on_field": 11,  "refs_required": True,  "sort": 17},
    }

    def _parse_currency(val):
        if not val: return 0.0
        return float(re.sub(r'[^\d.\-]', '', str(val)))

    def _find_latest_json(data_dir, prefix="packages"):
        d = Path(data_dir)
        pattern = re.compile(rf'^{prefix}_(\d{{8}}_\d{{6}})\.json$')
        candidates = [f for f in d.iterdir() if f.is_file() and pattern.match(f.name)]
        return str(max(candidates, key=lambda f: f.name)) if candidates else None


def _find_latest_csv(data_dir, prefix):
    """Find the most recent {prefix}_*.csv in data_dir."""
    d = Path(data_dir)
    pattern = re.compile(rf'^{re.escape(prefix)}_\d{{8}}_\d{{6}}\.csv$')
    candidates = [f for f in d.iterdir() if f.is_file() and pattern.match(f.name)]
    return str(max(candidates, key=lambda f: f.name)) if candidates else None



# ── HTML Template (uses %%TOKEN%% placeholders, not f-string braces) ──
_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Enrollment Dashboard — AYSO Region 58</title>
<link href="https://fonts.googleapis.com/css2?family=Anybody:wght@400;600;800&family=Source+Serif+4:ital,wght@0,400;0,600;1,400&display=swap" rel="stylesheet">
<style>
:root { --ink:#1c1917;--paper:#fafaf9;--warm:#f5f0eb;--accent:#1d4ed8;--green:#166534;--amber:#92400e;--red:#991b1b;--gray:#78716c;--border:#e7e5e4;--purple:#581c87; }
* { box-sizing:border-box;margin:0;padding:0; }
body { font-family:'Source Serif 4',Georgia,serif;background:var(--paper);color:var(--ink);line-height:1.7; }
header { background:var(--ink);color:var(--paper);padding:2.5rem 2rem 2rem; }
header h1 { font-family:'Anybody',sans-serif;font-weight:800;font-size:1.8rem;letter-spacing:-0.03em; }
header .meta { font-size:0.82rem;opacity:0.6;margin-top:0.4rem;font-family:'Anybody',sans-serif; }
.container { max-width:1020px;margin:0 auto;padding:1.5rem 1.5rem 3rem; }
.cards { display:grid;grid-template-columns:repeat(4,1fr);gap:0.75rem;margin-bottom:1.5rem; }
.card { background:white;border:1px solid var(--border);border-radius:8px;padding:1rem 1.1rem; }
.card .label { font-family:'Anybody',sans-serif;font-size:0.72rem;text-transform:uppercase;letter-spacing:0.04em;color:var(--gray);margin-bottom:0.2rem; }
.card .value { font-family:'Anybody',sans-serif;font-weight:800;font-size:1.6rem;line-height:1.2; }
.card .sub { font-size:0.78rem;color:var(--gray);margin-top:0.15rem; }
.section-label { font-family:'Anybody',sans-serif;font-weight:600;font-size:0.78rem;text-transform:uppercase;letter-spacing:0.06em;color:var(--gray);margin:1.5rem 0 0.5rem;padding-bottom:0.3rem;border-bottom:1px solid var(--border); }
.chart-section { margin:1.5rem 0; }
.chart-title { font-family:'Anybody',sans-serif;font-weight:600;font-size:0.95rem;margin-bottom:0.5rem; }
.chart-wrap { position:relative;width:100%; }
.legend { display:flex;flex-wrap:wrap;gap:1rem;font-size:0.78rem;color:var(--gray);margin-bottom:0.4rem;font-family:'Anybody',sans-serif; }
.legend-dot { display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px;vertical-align:-1px; }
.two-col { display:grid;grid-template-columns:1fr 1fr;gap:1.5rem; }
table { width:100%;border-collapse:collapse;font-size:0.78rem; }
th { font-family:'Anybody',sans-serif;font-weight:600;font-size:0.68rem;text-transform:uppercase;letter-spacing:0.03em;color:var(--gray);padding:0.4rem 0.5rem;text-align:left;border-bottom:2px solid var(--border);background:var(--warm); }
th.r,td.r { text-align:right; }
th.grad,td.grad { text-align:right;width:5.5rem;min-width:5.5rem; }
td { padding:0.4rem 0.5rem;border-bottom:1px solid var(--border); }
td:first-child { min-width:10rem; }
tr:hover { background:var(--warm); }
th.vol { background:#f3e8ff; }
footer { text-align:center;font-size:0.78rem;color:var(--gray);padding:2rem 0 1rem;border-top:1px solid var(--border);margin-top:2rem; }
@media(max-width:700px) { .cards{grid-template-columns:repeat(2,1fr);} .two-col{grid-template-columns:1fr;} }
</style>
</head>
<body>
<header>
<div style="display:flex;align-items:center;gap:1.5rem">
<img src="AYSO58_logo.png" alt="AYSO Region 58 Logo" style="height:96px;width:auto" />
<div>
<h1>Enrollment Dashboard</h1>
<div class="meta">AYSO Region 58 &mdash; %%PROGRAM%% &nbsp;|&nbsp; Data as of %%DT%%</div>
</div>
</div>
</header>
<div class="container">
<div class="section-label">Enrollment</div>
<div class="cards">
<div class="card"><div class="label">Total enrolled</div><div class="value">%%TE%%</div><div class="sub">of %%TC%% spots</div></div>
<div class="card"><div class="label">Capacity filled</div><div class="value">%%PF%%%</div><div class="sub">%%AVAIL%% available</div></div>
<div class="card"><div class="label">Revenue</div><div class="value">$%%TR%%</div><div class="sub">$%%TRF%% refunded (%%PCTREF%%%)</div></div>
<div class="card"><div class="label">Teams</div><div class="value">%%TCT%% / %%TT%%</div><div class="sub">%%TW%% on waitlist</div></div>
</div>
<div class="section-label">Volunteers</div>
<div class="cards">
<div class="card"><div class="label">Total volunteers</div><div class="value">%%TVOL%%</div><div class="sub">across all positions</div></div>
<div class="card"><div class="label">Head coaches</div><div class="value">%%THC%% / %%TCT%%</div><div class="sub">%%PCTHC%%% coverage</div></div>
<div class="card"><div class="label">Asst coaches / Mgrs</div><div class="value">%%TAC%% / %%TTM%%</div><div class="sub">supporting roles</div></div>
<div class="card"><div class="label">Referees</div><div class="value">%%TRFV%%</div><div class="sub">volunteer refs</div></div>
</div>
<div class="section-label">Coaching Requests</div>
<div class="cards">
<div class="card"><div class="label">Coach requests</div><div class="value">%%C_TOTAL%%</div><div class="sub">%%C_EXP%% experienced, %%C_NEW%% new</div></div>
<div class="card"><div class="label">HC / AC requests</div><div class="value">%%C_HC%% / %%C_AC%%</div><div class="sub">head coach / assistant</div></div>
<div class="card"><div class="label">Team assignment</div><div class="value">%%C_ASSIGNED%% / %%C_TOTAL%%</div><div class="sub">%%C_UNASSIGNED%% unassigned</div></div>
<div class="card"><div class="label">Jerseys needed</div><div class="value">%%C_JERSEYS%%</div><div class="sub">new coach shirts</div></div>
</div>
<div class="section-label">Coach Cross-Reference</div>
<div class="cards">
<div class="card"><div class="label">Volunteer signups</div><div class="value">%%XR_VOL%%</div><div class="sub">selected HC or AC role</div></div>
<div class="card"><div class="label">Coaching requests</div><div class="value">%%XR_REQ%%</div><div class="sub">completed coach form</div></div>
<div class="card" style="border-color:#166534"><div class="label">In both</div><div class="value" style="color:#166534">%%XR_BOTH%%</div><div class="sub">signed up + submitted form</div></div>
<div class="card" style="border-color:#92400e"><div class="label">Gaps</div><div class="value" style="color:#92400e">%%XR_VOL_ONLY%% / %%XR_REQ_ONLY%%</div><div class="sub">volunteer only / form only</div></div>
</div>
<div class="chart-section">
<div class="chart-title">Enrollment by division</div>
<div class="legend"><span><span class="legend-dot" style="background:#1d4ed8"></span>Enrolled</span><span><span class="legend-dot" style="background:#d6d3d1"></span>Available</span></div>
<div class="chart-wrap" style="height:300px"><canvas id="enrollChart"></canvas></div>
</div>
<div class="two-col">
<div class="chart-section">
<div class="chart-title">Financial breakdown</div>
<div class="legend"><span><span class="legend-dot" style="background:#166534"></span>Paid $%%TP%%</span><span><span class="legend-dot" style="background:#d97706"></span>Outstanding $%%TO%%</span><span><span class="legend-dot" style="background:#dc2626"></span>Refunded $%%TRF%%</span></div>
<div class="chart-wrap" style="height:220px"><canvas id="finChart"></canvas></div>
</div>
<div class="chart-section">
<div class="chart-title">Volunteers by division</div>
<div class="legend"><span><span class="legend-dot" style="background:#7c3aed"></span>Head Coach</span><span><span class="legend-dot" style="background:#a78bfa"></span>Asst Coach</span><span><span class="legend-dot" style="background:#c4b5fd"></span>Team Mgr</span><span><span class="legend-dot" style="background:#ddd6fe"></span>Referee</span></div>
<div class="chart-wrap" style="height:220px"><canvas id="volChart"></canvas></div>
</div>
</div>
<div class="chart-section">
<div class="chart-title">Division detail</div>
<div style="overflow-x:auto"><table>
<thead><tr><th>Division</th><th class="r">Enrolled</th><th class="r">Capacity</th><th class="grad">% Full</th><th class="r">Waitlist</th><th class="r">Revenue</th><th class="r">Roster</th><th class="r">On Field</th><th class="r">Target Teams</th><th class="grad">Current Teams</th><th class="grad vol">HC</th><th class="r vol">AC</th><th class="r vol">TM</th><th class="r vol">Ref</th></tr></thead>
<tbody>%%TBL%%</tbody>
<tfoot><tr style="font-weight:600;border-top:2px solid var(--border)"><td>Total</td><td class="r">%%TE%%</td><td class="r" style="color:#78716c">%%TC%%</td><td class="grad" style="background:%%TOT_PF_BG%%">%%PF%%%</td><td class="r">%%TW%%</td><td class="r">$%%TR%%</td><td class="r"></td><td class="r"></td><td class="r">%%TT%%</td><td class="grad" style="background:%%TOT_CT_BG%%">%%TCT%%</td><td class="grad" style="background:%%TOT_HC_BG%%">%%THC%%</td><td class="r">%%TAC%%</td><td class="r">%%TTM%%</td><td class="r">%%TRFV%%</td></tr></tfoot>
</table></div>
</div>
<footer>Region 58 &mdash; Sherman Oaks, CA &nbsp;|&nbsp; Generated %%GT%% &nbsp;|&nbsp; Source: PlayMetrics packages + volunteer data</footer>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<script>
const D=%%RJ%%;
new Chart(document.getElementById('enrollChart'),{type:'bar',data:{labels:D.map(d=>d.name),datasets:[{label:'Enrolled',data:D.map(d=>d.enrollments),backgroundColor:'#1d4ed8',borderRadius:3},{label:'Available',data:D.map(d=>d.available),backgroundColor:'#d6d3d1',borderRadius:3}]},options:{responsive:true,maintainAspectRatio:false,scales:{x:{stacked:true,ticks:{font:{size:9},maxRotation:50,autoSkip:false}},y:{stacked:true}},plugins:{legend:{display:false}}}});
new Chart(document.getElementById('finChart'),{type:'doughnut',data:{labels:['Paid','Outstanding','Refunded'],datasets:[{data:[%%TP_RAW%%,%%TO_RAW%%,%%TRF_RAW%%],backgroundColor:['#166534','#d97706','#dc2626'],borderWidth:0}]},options:{responsive:true,maintainAspectRatio:false,cutout:'55%',plugins:{legend:{display:false}}}});
new Chart(document.getElementById('volChart'),{type:'bar',data:{labels:D.map(d=>d.name),datasets:[{label:'Head Coach',data:D.map(d=>d.head_coach),backgroundColor:'#7c3aed',borderRadius:2},{label:'Asst Coach',data:D.map(d=>d.asst_coach),backgroundColor:'#a78bfa',borderRadius:2},{label:'Team Mgr',data:D.map(d=>d.team_mgr),backgroundColor:'#c4b5fd',borderRadius:2},{label:'Referee',data:D.map(d=>d.referees),backgroundColor:'#ddd6fe',borderRadius:2}]},options:{responsive:true,maintainAspectRatio:false,scales:{x:{stacked:true,ticks:{font:{size:9},maxRotation:50,autoSkip:false}},y:{stacked:true}},plugins:{legend:{display:false}}}});
</script>
</body></html>"""

class PlayMetricsDashboardGenerator:

    def __init__(self, data_dir="data/playmetrics", output_dir="data/playmetrics"):
        self.data_dir = data_dir
        self.output_dir = output_dir
        Path(output_dir).mkdir(parents=True, exist_ok=True)

    def generate(self, packages_file=None, volunteers_file=None,
                 coaching_file=None, output_file=None):
        try:
            if not packages_file:
                packages_file = _find_latest_json(self.data_dir, "packages")
            if not packages_file:
                logger.error("No packages JSON found in %s", self.data_dir)
                return None

            logger.info("Reading packages from: %s", packages_file)
            with open(packages_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Read volunteer data
            if not volunteers_file:
                volunteers_file = _find_latest_csv(self.data_dir, "volunteers")
            vol_data = {}
            if volunteers_file:
                logger.info("Reading volunteers from: %s", volunteers_file)
                vol_data = self._read_volunteers(volunteers_file)
            else:
                logger.warning("No volunteers CSV found - volunteer columns will be 0")

            # Read coaching requests
            if not coaching_file:
                coaching_file = _find_latest_csv(self.data_dir, "coaching-requests")
            coach_data = {}
            if coaching_file:
                logger.info("Reading coaching requests from: %s", coaching_file)
                coach_data = self._read_coaching_requests(coaching_file)
            else:
                logger.warning("No coaching-requests CSV found")

            # Cross-reference volunteers vs coaching requests
            xref = self._cross_reference_coaches(volunteers_file, coaching_file)

            packages = data.get("packages", [])
            rows = self._build_rows(packages, vol_data)
            if not rows:
                logger.error("No rows generated")
                return None

            scraped_at = data.get("scraped_at", datetime.now().isoformat())
            program_name = data.get("program_name", "Fall 2026")
            html = self._render_html(rows, scraped_at, program_name, coach_data, xref)

            if not output_file:
                output_file = str(Path(self.output_dir) / "enrollment_dashboard.html")
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(html)
            logger.info("Dashboard generated: %s (%d divisions)", output_file, len(rows))
            return output_file
        except Exception as e:
            logger.error("Failed to generate dashboard: %s", e)
            import traceback; traceback.print_exc()
            return None

    def _read_volunteers(self, csv_path):
        """Read volunteers CSV → dict of {division: {position: count}}."""
        by_div = defaultdict(lambda: defaultdict(set))
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                pos = row.get('volunteer_position', '')
                div = row.get('package_name', '')
                email = row.get('volunteer_email', '')
                if pos and div and email:
                    by_div[div][pos].add(email)
        return {div: {pos: len(emails) for pos, emails in positions.items()}
                for div, positions in by_div.items()}

    def _read_coaching_requests(self, csv_path):
        """Read coaching-requests CSV → summary dict."""
        coaches = {}
        with open(csv_path, 'r', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                email = row.get('coach_email', '')
                if email and email not in coaches:
                    coaches[email] = row
        total = len(coaches)
        hc_req = sum(1 for c in coaches.values() if c.get('request_head_coach') == 'Y')
        ac_req = sum(1 for c in coaches.values() if c.get('request_asst_coach') == 'Y')
        assigned = sum(1 for c in coaches.values() if c.get('coach_assigned_to_player_team') == 'Y')
        experienced = sum(1 for c in coaches.values()
                         if c.get('Have you Coached with AYSO in the past?') == 'Yes')
        jerseys = sum(1 for c in coaches.values()
                      if c.get('Coach shirts are required to be worn on game days. Do you need a new one?') == 'Yes')
        return {
            'total': total, 'hc_req': hc_req, 'ac_req': ac_req,
            'assigned': assigned, 'unassigned': total - assigned,
            'experienced': experienced, 'new': total - experienced,
            'jerseys_needed': jerseys,
        }

    def _cross_reference_coaches(self, volunteers_file, coaching_file):
        """Cross-reference volunteer coach signups vs coaching request forms."""
        # Get unique coach-type volunteer emails
        vol_coaches = set()
        if volunteers_file:
            with open(volunteers_file, 'r', encoding='utf-8') as f:
                for row in csv.DictReader(f):
                    pos = row.get('volunteer_position', '')
                    email = row.get('volunteer_email', '').lower().strip()
                    if pos in ('Head Coach', 'Assistant Coach') and email:
                        vol_coaches.add(email)

        # Get unique coaching request emails
        req_coaches = set()
        if coaching_file:
            with open(coaching_file, 'r', encoding='utf-8') as f:
                for row in csv.DictReader(f):
                    email = row.get('coach_email', '').lower().strip()
                    if email:
                        req_coaches.add(email)

        both = vol_coaches & req_coaches
        vol_only = vol_coaches - req_coaches
        req_only = req_coaches - vol_coaches

        return {
            'vol_coaches': len(vol_coaches),
            'req_coaches': len(req_coaches),
            'in_both': len(both),
            'vol_only': len(vol_only),
            'req_only': len(req_only),
        }

    def _build_rows(self, packages, vol_data=None):
        vol_data = vol_data or {}
        rows = []
        for pkg in packages:
            name = pkg["name"]
            cfg = DIVISION_CONFIG.get(name)
            if not cfg:
                logger.warning("Division '%s' not in DIVISION_CONFIG - skipping", name)
                continue
            active = pkg["active_registrations"]
            maximum = pkg["max_spots"]
            roster = cfg["roster_size"]
            roster_min = cfg["roster_min"]
            waitlist = pkg.get("waitlist", 0) or pkg.get("waitlist_count", 0) or 0
            target_teams = int(maximum / roster) if roster > 0 else 0
            if roster > 0:
                if active < roster:
                    effective = roster if active >= roster_min else active
                else:
                    effective = active
                capped = maximum if (effective + waitlist) > maximum else effective
                current_teams = int(capped / roster)
            else:
                current_teams = 0
            total_rev = _parse_currency(pkg.get("total")) or _parse_currency((pkg.get("financials") or {}).get("total"))
            paid = _parse_currency(pkg.get("paid")) or _parse_currency((pkg.get("financials") or {}).get("paid"))
            refunded = _parse_currency(pkg.get("refunded")) or _parse_currency((pkg.get("financials") or {}).get("refunded"))
            outstanding = _parse_currency(pkg.get("outstanding")) or _parse_currency((pkg.get("financials") or {}).get("outstanding"))
            pct_enrolled = min(active / maximum, 1) if maximum else 0
            pct_collected = paid / total_rev if total_rev > 0 else 0

            # Volunteer data
            vd = vol_data.get(name, {})
            hc = vd.get("Head Coach", 0)
            ac = vd.get("Assistant Coach", 0)
            tm = vd.get("Team Manager", 0)
            refs = vd.get("Referee", 0)
            pct_hc = hc / current_teams if current_teams > 0 else 0

            rows.append({
                "name": name, "enrollments": active, "maximum": maximum,
                "waitlist": waitlist, "pct_enrolled": pct_enrolled,
                "available": maximum - active,
                "total_rev": total_rev, "paid": paid, "refunded": refunded,
                "outstanding": outstanding, "pct_collected": pct_collected,
                "roster_size": roster, "on_field": cfg["on_field"],
                "target_teams": target_teams, "current_teams": current_teams,
                "pct_teams": min(current_teams / target_teams, 1) if target_teams else 0,
                "head_coach": hc, "asst_coach": ac, "team_mgr": tm,
                "referees": refs, "pct_hc": pct_hc,
                "refs_required": cfg.get("refs_required", False),
                "sort": cfg.get("sort", 99),
            })
        rows.sort(key=lambda r: r["sort"])
        return rows

    def _render_html(self, rows, scraped_at, program_name, coach_data=None, xref=None):
        te = sum(r['enrollments'] for r in rows)
        tc = sum(r['maximum'] for r in rows)
        tw = sum(r['waitlist'] for r in rows)
        tr_ = sum(r['total_rev'] for r in rows)
        tp = sum(r['paid'] for r in rows)
        trf = sum(r['refunded'] for r in rows)
        to = sum(r['outstanding'] for r in rows)
        tt = sum(r['target_teams'] for r in rows)
        tct = sum(r['current_teams'] for r in rows)
        pf = round(te / tc * 100, 1) if tc else 0
        pc = round(tp / tr_ * 100, 1) if tr_ else 0
        pct_ref = round(trf / (tr_ + trf) * 100, 1) if (tr_ + trf) > 0 else 0
        # Volunteer totals
        thc = sum(r['head_coach'] for r in rows)
        tac = sum(r['asst_coach'] for r in rows)
        ttm = sum(r['team_mgr'] for r in rows)
        trf_v = sum(r['referees'] for r in rows)
        tvol = thc + tac + ttm + trf_v
        pct_hc_total = round(thc / tct * 100, 1) if tct else 0
        # Coaching request totals
        cd = coach_data or {}
        c_total = cd.get('total', 0)
        c_hc = cd.get('hc_req', 0)
        c_ac = cd.get('ac_req', 0)
        c_assigned = cd.get('assigned', 0)
        c_unassigned = cd.get('unassigned', 0)
        c_exp = cd.get('experienced', 0)
        c_new = cd.get('new', 0)
        c_jerseys = cd.get('jerseys_needed', 0)
        # Cross-reference
        xr = xref or {}
        xr_both = xr.get('in_both', 0)
        xr_vol_only = xr.get('vol_only', 0)
        xr_req_only = xr.get('req_only', 0)
        xr_vol = xr.get('vol_coaches', 0)
        xr_req = xr.get('req_coaches', 0)

        rj = json.dumps(rows)
        def _gradient(ratio):
            """Red(0) → Yellow(0.5) → Green(1.0) background color scale."""
            r = max(0.0, min(1.0, ratio))
            if r < 0.5:
                t = r / 0.5
                red = int(248 * (1 - t) + 253 * t)
                grn = int(185 * (1 - t) + 224 * t)
                blu = int(185 * (1 - t) + 138 * t)
            else:
                t = (r - 0.5) / 0.5
                red = int(253 * (1 - t) + 134 * t)
                grn = int(224 * (1 - t) + 214 * t)
                blu = int(138 * (1 - t) + 104 * t)
            return f'#{red:02x}{grn:02x}{blu:02x}'

        tbl = []
        for r in rows:
            pf_bg = _gradient(r['pct_enrolled'])
            if r['roster_size'] > 0:
                ct_ratio = r['current_teams'] / r['target_teams'] if r['target_teams'] > 0 else 0
                ct_bg = _gradient(ct_ratio)
                hc_ratio = r['head_coach'] / r['target_teams'] if r['target_teams'] > 0 else 0
                hc_bg = _gradient(hc_ratio)
                team_cells = (
                    f'<td class="r">{r["target_teams"]}</td>'
                    f'<td class="grad" style="background:{ct_bg};font-weight:600">{r["current_teams"]}</td>'
                    f'<td class="grad" style="background:{hc_bg};font-weight:600">{r["head_coach"]}</td>'
                    f'<td class="r">{r["asst_coach"]}</td>'
                    f'<td class="r">{r["team_mgr"]}</td>'
                    f'<td class="r">{r["referees"]}</td>'
                )
            else:
                team_cells = '<td class="r"></td>' * 6
            ws = 'color:#991b1b;font-weight:600' if r['waitlist']>0 else ''
            tbl.append(
                f'<tr><td style="font-weight:600">{r["name"]}</td>'
                f'<td class="r">{r["enrollments"]}</td>'
                f'<td class="r" style="color:#78716c">{r["maximum"]}</td>'
                f'<td class="grad" style="background:{pf_bg};font-weight:600">{r["pct_enrolled"]:.0%}</td>'
                f'<td class="r" style="{ws}">{r["waitlist"]}</td>'
                f'<td class="r">${r["total_rev"]:,.0f}</td>'
                f'<td class="r">{r["roster_size"]}</td>'
                f'<td class="r">{r["on_field"]}</td>'
                f'{team_cells}</tr>'
            )

        # Compute totals gradient backgrounds
        tot_pf_bg = _gradient(te / tc if tc else 0)
        tot_ct_bg = _gradient(tct / tt if tt else 0)
        tot_hc_bg = _gradient(thc / tt if tt else 0)
        try: dt = datetime.fromisoformat(scraped_at).strftime('%B %d, %Y at %I:%M %p')
        except: dt = scraped_at
        gt = datetime.now().strftime('%B %d, %Y at %I:%M %p')
        nl = '\n'

        # Use token replacement instead of f-strings to avoid CSS/JS brace escaping
        subs = {
            '%%PROGRAM%%': program_name, '%%DT%%': dt, '%%GT%%': gt,
            '%%TE%%': f'{te:,}', '%%TC%%': f'{tc:,}', '%%PF%%': str(pf),
            '%%AVAIL%%': f'{tc-te:,}', '%%TR%%': f'{tr_:,.0f}',
            '%%PC%%': str(pc), '%%TCT%%': str(tct), '%%TT%%': str(tt),
            '%%TW%%': str(tw), '%%TP%%': f'{tp:,.0f}', '%%TO%%': f'{to:,.0f}',
            '%%TRF%%': f'{trf:,.0f}',
            '%%PCTREF%%': str(pct_ref),
            '%%TP_RAW%%': str(tp), '%%TO_RAW%%': str(to), '%%TRF_RAW%%': str(trf),
            '%%C_TOTAL%%': str(c_total), '%%C_HC%%': str(c_hc), '%%C_AC%%': str(c_ac),
            '%%C_ASSIGNED%%': str(c_assigned), '%%C_UNASSIGNED%%': str(c_unassigned),
            '%%C_EXP%%': str(c_exp), '%%C_NEW%%': str(c_new),
            '%%C_JERSEYS%%': str(c_jerseys),
            '%%XR_BOTH%%': str(xr_both), '%%XR_VOL_ONLY%%': str(xr_vol_only),
            '%%XR_REQ_ONLY%%': str(xr_req_only), '%%XR_VOL%%': str(xr_vol),
            '%%XR_REQ%%': str(xr_req),
            '%%TOT_PF_BG%%': tot_pf_bg, '%%TOT_CT_BG%%': tot_ct_bg,
            '%%TOT_HC_BG%%': tot_hc_bg, '%%TVOL%%': str(tvol),
            '%%THC%%': str(thc), '%%TAC%%': str(tac), '%%TTM%%': str(ttm),
            '%%TRFV%%': str(trf_v), '%%PCTHC%%': str(pct_hc_total),
            '%%RJ%%': rj, '%%TBL%%': nl.join(tbl),
        }

        html = _HTML_TEMPLATE
        for token, value in subs.items():
            html = html.replace(token, value)
        return html

    def publish_to_github_pages(self, html_path, github_token=None):
        """Publish dashboard HTML to GitHub Pages via the GitHub API."""
        import subprocess
        try:
            import requests
        except ImportError:
            logger.error("requests not installed: pip install requests")
            return False
        REPO = "sdavis9248/playmetrics-migration-region58"
        FILE_PATH = "enrollment_dashboard.html"
        API_URL = f"https://api.github.com/repos/{REPO}/contents/{FILE_PATH}"
        token = github_token or os.environ.get("GITHUB_TOKEN")
        if not token:
            try:
                result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True)
                token = result.stdout.strip()
            except (FileNotFoundError, subprocess.CalledProcessError):
                pass
        if not token:
            logger.error("No GitHub token found. Set GITHUB_TOKEN env var, install gh CLI, or pass --github-token.")
            return False
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        with open(html_path, 'r', encoding='utf-8') as f:
            content = f.read()
        content_b64 = base64.b64encode(content.encode('utf-8')).decode('ascii')
        sha = None
        resp = requests.get(API_URL, headers=headers)
        if resp.status_code == 200:
            sha = resp.json().get("sha")
        payload = {"message": "Update enrollment dashboard", "content": content_b64, "branch": "main"}
        if sha:
            payload["sha"] = sha
        resp = requests.put(API_URL, headers=headers, json=payload)
        if resp.status_code in (200, 201):
            url = f"https://sdavis9248.github.io/playmetrics-migration-region58/{FILE_PATH}"
            logger.info("Published: %s", url)
            print(f"Published: {url}")
            return True
        else:
            logger.error("GitHub API error %d: %s", resp.status_code, resp.text[:300])
            return False


def handle_pm_dashboard(config, args):
    try:
        data_dir = config.get('playmetrics_config.download_dir', 'data/playmetrics') if config else 'data/playmetrics'
        gen = PlayMetricsDashboardGenerator(data_dir=data_dir)
        result = gen.generate(
            packages_file=getattr(args, 'packages_file', None),
            volunteers_file=getattr(args, 'volunteers_file', None),
            coaching_file=getattr(args, 'coaching_file', None),
            output_file=getattr(args, 'pm_dashboard_output', None),
        )
        if result:
            print(f"Dashboard generated: {result}")
            if getattr(args, 'publish', False):
                gen.publish_to_github_pages(result, getattr(args, 'github_token', None))
            return 0
        else: print("Failed to generate dashboard"); return 1
    except Exception as e:
        logger.error("Error: %s", e); import traceback; traceback.print_exc(); return 1

if __name__ == '__main__':
    import argparse
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    p = argparse.ArgumentParser(description='Generate PlayMetrics enrollment dashboard')
    p.add_argument('--packages-file', help='Path to packages_*.json')
    p.add_argument('--volunteers-file', help='Path to volunteers_*.csv')
    p.add_argument('--coaching-file', help='Path to coaching-requests_*.csv')
    p.add_argument('--output', '-o', help='Output HTML path')
    p.add_argument('--publish', action='store_true', help='Publish to GitHub Pages via API')
    p.add_argument('--github-token', help='GitHub token (or set GITHUB_TOKEN env var)')
    a = p.parse_args()
    gen = PlayMetricsDashboardGenerator()
    r = gen.generate(packages_file=a.packages_file, volunteers_file=a.volunteers_file,
                     coaching_file=a.coaching_file, output_file=a.output)
    if r:
        print(f"Dashboard generated: {r}")
        if a.publish:
            gen.publish_to_github_pages(r, a.github_token)
    else: print("Failed"); exit(1)