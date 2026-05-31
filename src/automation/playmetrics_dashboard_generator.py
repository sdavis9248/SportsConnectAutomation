"""
PlayMetrics Enrollment Dashboard Generator

Generates a self-contained HTML dashboard from packages JSON.
Uses the same DIVISION_CONFIG and data model as playmetrics_enrollment_report.py.

Data flow:
  --pm-download packages -> packages_*.json -> --pm-dashboard -> enrollment_dashboard.html
"""

import os
import re
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict

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


class PlayMetricsDashboardGenerator:

    def __init__(self, data_dir="data/playmetrics", output_dir="data/playmetrics"):
        self.data_dir = data_dir
        self.output_dir = output_dir
        Path(output_dir).mkdir(parents=True, exist_ok=True)

    def generate(self, packages_file=None, output_file=None):
        try:
            if not packages_file:
                packages_file = _find_latest_json(self.data_dir, "packages")
            if not packages_file:
                logger.error("No packages JSON found in %s", self.data_dir)
                return None
            logger.info("Reading packages from: %s", packages_file)
            with open(packages_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            packages = data.get("packages", [])
            rows = self._build_rows(packages)
            if not rows:
                logger.error("No rows generated")
                return None
            scraped_at = data.get("scraped_at", datetime.now().isoformat())
            program_name = data.get("program_name", "Fall 2026")
            html = self._render_html(rows, scraped_at, program_name)
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

    def _build_rows(self, packages):
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
            rows.append({
                "name": name, "enrollments": active, "maximum": maximum,
                "waitlist": waitlist, "pct_enrolled": pct_enrolled,
                "available": maximum - active,
                "total_rev": total_rev, "paid": paid, "refunded": refunded,
                "outstanding": outstanding, "pct_collected": pct_collected,
                "roster_size": roster, "on_field": cfg["on_field"],
                "target_teams": target_teams, "current_teams": current_teams,
                "pct_teams": min(current_teams / target_teams, 1) if target_teams else 0,
                "sort": cfg.get("sort", 99),
            })
        rows.sort(key=lambda r: r["sort"])
        return rows

    def _render_html(self, rows, scraped_at, program_name):
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
        rj = json.dumps(rows)
        tbl = []
        for r in rows:
            clr = '#166534' if r['pct_enrolled']>=0.75 else '#92400e' if r['pct_enrolled']>=0.50 else '#991b1b'
            ws = 'color:#991b1b;font-weight:600' if r['waitlist']>0 else ''
            tbl.append(f'<tr><td style="font-weight:600">{r["name"]}</td><td class="r">{r["enrollments"]}</td><td class="r" style="color:#78716c">{r["maximum"]}</td><td class="r" style="color:{clr};font-weight:600">{r["pct_enrolled"]:.0%}</td><td class="r" style="{ws}">{r["waitlist"]}</td><td class="r">${r["total_rev"]:,.0f}</td><td class="r">{r["roster_size"]}</td><td class="r">{r["on_field"]}</td><td class="r">{r["target_teams"]}</td><td class="r">{r["current_teams"]}</td></tr>')
        try: dt = datetime.fromisoformat(scraped_at).strftime('%B %d, %Y at %I:%M %p')
        except: dt = scraped_at
        gt = datetime.now().strftime('%B %d, %Y at %I:%M %p')
        nl = '\n'
        return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Enrollment Dashboard — AYSO Region 58</title>
<link href="https://fonts.googleapis.com/css2?family=Anybody:wght@400;600;800&family=Source+Serif+4:ital,wght@0,400;0,600;1,400&display=swap" rel="stylesheet">
<style>
:root {{ --ink:#1c1917;--paper:#fafaf9;--warm:#f5f0eb;--accent:#1d4ed8;--green:#166534;--amber:#92400e;--red:#991b1b;--gray:#78716c;--border:#e7e5e4; }}
* {{ box-sizing:border-box;margin:0;padding:0; }}
body {{ font-family:'Source Serif 4',Georgia,serif;background:var(--paper);color:var(--ink);line-height:1.7; }}
header {{ background:var(--ink);color:var(--paper);padding:2.5rem 2rem 2rem; }}
header h1 {{ font-family:'Anybody',sans-serif;font-weight:800;font-size:1.8rem;letter-spacing:-0.03em; }}
header .meta {{ font-size:0.82rem;opacity:0.6;margin-top:0.4rem;font-family:'Anybody',sans-serif; }}
.container {{ max-width:960px;margin:0 auto;padding:1.5rem 1.5rem 3rem; }}
.cards {{ display:grid;grid-template-columns:repeat(4,1fr);gap:0.75rem;margin-bottom:1.5rem; }}
.card {{ background:white;border:1px solid var(--border);border-radius:8px;padding:1rem 1.1rem; }}
.card .label {{ font-family:'Anybody',sans-serif;font-size:0.72rem;text-transform:uppercase;letter-spacing:0.04em;color:var(--gray);margin-bottom:0.2rem; }}
.card .value {{ font-family:'Anybody',sans-serif;font-weight:800;font-size:1.6rem;line-height:1.2; }}
.card .sub {{ font-size:0.78rem;color:var(--gray);margin-top:0.15rem; }}
.chart-section {{ margin:1.5rem 0; }}
.chart-title {{ font-family:'Anybody',sans-serif;font-weight:600;font-size:0.95rem;margin-bottom:0.5rem; }}
.chart-wrap {{ position:relative;width:100%; }}
.legend {{ display:flex;flex-wrap:wrap;gap:1rem;font-size:0.78rem;color:var(--gray);margin-bottom:0.4rem;font-family:'Anybody',sans-serif; }}
.legend-dot {{ display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px;vertical-align:-1px; }}
.two-col {{ display:grid;grid-template-columns:1fr 1fr;gap:1.5rem; }}
table {{ width:100%;border-collapse:collapse;font-size:0.82rem; }}
th {{ font-family:'Anybody',sans-serif;font-weight:600;font-size:0.72rem;text-transform:uppercase;letter-spacing:0.03em;color:var(--gray);padding:0.5rem 0.6rem;text-align:left;border-bottom:2px solid var(--border);background:var(--warm); }}
th.r,td.r {{ text-align:right; }}
td {{ padding:0.45rem 0.6rem;border-bottom:1px solid var(--border); }}
tr:hover {{ background:var(--warm); }}
footer {{ text-align:center;font-size:0.78rem;color:var(--gray);padding:2rem 0 1rem;border-top:1px solid var(--border);margin-top:2rem; }}
@media(max-width:700px) {{ .cards{{grid-template-columns:repeat(2,1fr);}} .two-col{{grid-template-columns:1fr;}} }}
</style>
</head>
<body>
<header><h1>Enrollment Dashboard</h1><div class="meta">AYSO Region 58 &mdash; {program_name} &nbsp;|&nbsp; Data as of {dt}</div></header>
<div class="container">
<div class="cards">
<div class="card"><div class="label">Total enrolled</div><div class="value">{te:,}</div><div class="sub">of {tc:,} spots</div></div>
<div class="card"><div class="label">Capacity filled</div><div class="value">{pf}%</div><div class="sub">{tc-te:,} available</div></div>
<div class="card"><div class="label">Revenue</div><div class="value">${tr_:,.0f}</div><div class="sub">{pc}% collected</div></div>
<div class="card"><div class="label">Teams</div><div class="value">{tct} / {tt}</div><div class="sub">{tw} on waitlist</div></div>
</div>
<div class="chart-section">
<div class="chart-title">Enrollment by division</div>
<div class="legend"><span><span class="legend-dot" style="background:#1d4ed8"></span>Enrolled</span><span><span class="legend-dot" style="background:#d6d3d1"></span>Available</span></div>
<div class="chart-wrap" style="height:300px"><canvas id="enrollChart"></canvas></div>
</div>
<div class="two-col">
<div class="chart-section">
<div class="chart-title">Financial breakdown</div>
<div class="legend"><span><span class="legend-dot" style="background:#166534"></span>Paid ${tp:,.0f}</span><span><span class="legend-dot" style="background:#d97706"></span>Outstanding ${to:,.0f}</span><span><span class="legend-dot" style="background:#dc2626"></span>Refunded ${trf:,.0f}</span></div>
<div class="chart-wrap" style="height:220px"><canvas id="finChart"></canvas></div>
</div>
<div class="chart-section">
<div class="chart-title">Enrollment by age group</div>
<div class="chart-wrap" style="height:220px"><canvas id="ageChart"></canvas></div>
</div>
</div>
<div class="chart-section">
<div class="chart-title">Division detail</div>
<div style="overflow-x:auto"><table>
<thead><tr><th>Division</th><th class="r">Enrolled</th><th class="r">Capacity</th><th class="r">% Full</th><th class="r">Waitlist</th><th class="r">Revenue</th><th class="r">Roster</th><th class="r">On Field</th><th class="r">Target Teams</th><th class="r">Current Teams</th></tr></thead>
<tbody>{nl.join(tbl)}</tbody>
<tfoot><tr style="font-weight:600;border-top:2px solid var(--border)"><td>Total</td><td class="r">{te:,}</td><td class="r" style="color:#78716c">{tc:,}</td><td class="r">{pf}%</td><td class="r">{tw}</td><td class="r">${tr_:,.0f}</td><td class="r"></td><td class="r"></td><td class="r">{tt}</td><td class="r">{tct}</td></tr></tfoot>
</table></div>
</div>
<footer>Region 58 &mdash; Sherman Oaks, CA &nbsp;|&nbsp; Generated {gt} &nbsp;|&nbsp; Source: PlayMetrics packages data</footer>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<script>
const D={rj};
new Chart(document.getElementById('enrollChart'),{{type:'bar',data:{{labels:D.map(d=>d.name),datasets:[{{label:'Enrolled',data:D.map(d=>d.enrollments),backgroundColor:'#1d4ed8',borderRadius:3}},{{label:'Available',data:D.map(d=>d.available),backgroundColor:'#d6d3d1',borderRadius:3}}]}},options:{{responsive:true,maintainAspectRatio:false,scales:{{x:{{stacked:true,ticks:{{font:{{size:10}},maxRotation:50,autoSkip:false}}}},y:{{stacked:true}}}},plugins:{{legend:{{display:false}}}}}}}});
new Chart(document.getElementById('finChart'),{{type:'doughnut',data:{{labels:['Paid','Outstanding','Refunded'],datasets:[{{data:[{tp},{to},{trf}],backgroundColor:['#166534','#d97706','#dc2626'],borderWidth:0}}]}},options:{{responsive:true,maintainAspectRatio:false,cutout:'55%',plugins:{{legend:{{display:false}}}}}}}});
const ages={{}};D.forEach(d=>{{const m=d.name.match(/^(\d+)U/);if(m){{const ag='U'+parseInt(m[1]);ages[ag]=(ages[ag]||0)+d.enrollments;}}}});
const aL=Object.keys(ages).sort((a,b)=>parseInt(a.slice(1))-parseInt(b.slice(1)));
new Chart(document.getElementById('ageChart'),{{type:'bar',data:{{labels:aL,datasets:[{{data:aL.map(l=>ages[l]),backgroundColor:'#7c3aed',borderRadius:3}}]}},options:{{indexAxis:'y',responsive:true,maintainAspectRatio:false,scales:{{x:{{beginAtZero:true}}}},plugins:{{legend:{{display:false}}}}}}}});
</script>
</body></html>'''


    def publish_to_github_pages(self, html_path, github_token=None):
        """Publish dashboard HTML to GitHub Pages via the GitHub API.
        No local clone needed — pushes directly via the Contents API.

        Token resolution (first match wins):
          1. github_token parameter
          2. GITHUB_TOKEN environment variable
          3. gh CLI auth token (if gh is installed)
        """
        import base64
        import subprocess
        try:
            import requests
        except ImportError:
            logger.error("requests not installed: pip install requests")
            return False

        REPO = "sdavis9248/playmetrics-migration-region58"
        FILE_PATH = "enrollment_dashboard.html"
        API_URL = f"https://api.github.com/repos/{REPO}/contents/{FILE_PATH}"

        # Resolve token
        token = github_token or os.environ.get("GITHUB_TOKEN")
        if not token:
            try:
                result = subprocess.run(
                    ["gh", "auth", "token"], capture_output=True, text=True, check=True
                )
                token = result.stdout.strip()
            except (FileNotFoundError, subprocess.CalledProcessError):
                pass
        if not token:
            logger.error(
                "No GitHub token found. Set GITHUB_TOKEN env var, "
                "install gh CLI, or pass --github-token."
            )
            return False

        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        }

        # Read the HTML content
        with open(html_path, 'r', encoding='utf-8') as f:
            content = f.read()
        content_b64 = base64.b64encode(content.encode('utf-8')).decode('ascii')

        # Get current file SHA (needed for updates; None for first push)
        sha = None
        resp = requests.get(API_URL, headers=headers)
        if resp.status_code == 200:
            sha = resp.json().get("sha")

        # Push
        payload = {
            "message": "Update enrollment dashboard",
            "content": content_b64,
            "branch": "main",
        }
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
        result = gen.generate(packages_file=getattr(args, 'packages_file', None), output_file=getattr(args, 'pm_dashboard_output', None))
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
    p.add_argument('--output', '-o', help='Output HTML path')
    p.add_argument('--publish', action='store_true', help='Publish to GitHub Pages via API')
    p.add_argument('--github-token', help='GitHub token (or set GITHUB_TOKEN env var)')
    a = p.parse_args()
    gen = PlayMetricsDashboardGenerator()
    r = gen.generate(packages_file=a.packages_file, output_file=a.output)
    if r:
        print(f"Dashboard generated: {r}")
        if a.publish:
            gen.publish_to_github_pages(r, a.github_token)
    else: print("Failed"); exit(1)