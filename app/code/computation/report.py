"""Render the self-contained HTML compatibility report.

Sections:
1. Header + federation overview chips
2. Data Structure — site × column presence matrix + parallelism callouts
3. Global Descriptive Statistics — per-column summary table with per-site rows
4. Histogram Compatibility — interactive Plotly overlays + overlap/KL/chi2 metrics.
"""

import json
from typing import Any, Dict, Optional

SITE_COLORS = [
    "rgba(99,102,241,0.65)",
    "rgba(16,185,129,0.65)",
    "rgba(245,158,11,0.65)",
    "rgba(239,68,68,0.65)",
    "rgba(139,92,246,0.65)",
    "rgba(20,184,166,0.65)",
    "rgba(249,115,22,0.65)",
]
SITE_COLORS_SOLID = [c.replace("0.65", "1.0") for c in SITE_COLORS]
# Light-mode pill: very pale background tint
SITE_COLORS_PILL_BG = [c.replace("0.65", "0.12") for c in SITE_COLORS]
# Light-mode pill: dark readable text in the same hue family
SITE_COLORS_PILL_TEXT = [
    "#3730a3",  # indigo-800
    "#065f46",  # emerald-800
    "#92400e",  # amber-800
    "#991b1b",  # red-800
    "#5b21b6",  # violet-800
    "#134e4a",  # teal-800
    "#7c2d12",  # orange-900
]


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────


def generate_histogram_report_html(
    histogram_report: Dict[str, Any],
    global_csv_report: Optional[Dict[str, Any]] = None,
    security_level: str = "low",
    regression_data: Optional[Dict[str, Any]] = None,
) -> str:
    """Render the full report from the histogram and global CSV reports.

    With ``security_level="high"`` the descriptive statistics, correlation and
    site-effect sections are omitted.
    """
    csv_report = global_csv_report or {}
    sites = histogram_report.get("sites", [])
    hist_columns = histogram_report.get("columns", {})
    parallelism = csv_report.get("column_parallelism", {})
    column_stats = csv_report.get("column_stats", {})

    all_sites = parallelism.get("all_sites", sites) or sites
    site_color_map = {
        s: SITE_COLORS[i % len(SITE_COLORS)] for i, s in enumerate(all_sites)
    }
    site_solid_map = {
        s: SITE_COLORS_SOLID[i % len(SITE_COLORS_SOLID)]
        for i, s in enumerate(all_sites)
    }
    site_pill_bg_map = {
        s: SITE_COLORS_PILL_BG[i % len(SITE_COLORS_PILL_BG)]
        for i, s in enumerate(all_sites)
    }
    site_pill_text_map = {
        s: SITE_COLORS_PILL_TEXT[i % len(SITE_COLORS_PILL_TEXT)]
        for i, s in enumerate(all_sites)
    }

    n_sites = csv_report.get("total_sites", len(all_sites))
    total_rows = csv_report.get("total_rows", "N/A")
    par_summary = parallelism.get("summary", {})
    n_universal = par_summary.get("n_universal", "?")
    n_partial = par_summary.get("n_partial", 0)
    n_conflict = par_summary.get("n_type_conflict", 0)

    show_stats = security_level != "high"
    sections = [
        _build_header(
            n_sites,
            total_rows,
            n_universal,
            n_partial,
            n_conflict,
            len(hist_columns),
            all_sites,
            site_solid_map,
        ),
        _section(
            "Data Structure",
            _build_structure_section(
                parallelism,
                all_sites,
                site_solid_map,
                site_color_map,
                site_pill_bg_map,
                site_pill_text_map,
            ),
        ),
        _section(
            "Global Descriptive Statistics",
            _build_stats_section(
                column_stats, all_sites, site_solid_map, parallelism, site_pill_text_map
            ),
        )
        if show_stats
        else "",
        _section(
            "Correlation Structure",
            _build_correlation_section(
                regression_data, all_sites, site_solid_map, site_pill_text_map
            ),
        )
        if (show_stats and regression_data)
        else "",
        _section(
            "Site Effects",
            _build_site_effects_section(
                regression_data, all_sites, site_solid_map, site_pill_text_map
            ),
        )
        if (show_stats and regression_data)
        else "",
        _section(
            "Sample Size Guidance",
            _build_sample_guidance_section(
                regression_data, all_sites, site_solid_map, site_pill_text_map
            ),
        )
        if regression_data
        else "",
        "",  # placeholder, filled below
    ]

    hist_html, hist_js = _build_histograms_section(
        hist_columns, all_sites, site_color_map, site_solid_map, parallelism
    )
    sections[-1] = _section("Histogram Compatibility", hist_html)

    section_titles = [
        "Data Structure",
        "Global Descriptive Statistics",
        "Correlation Structure",
        "Site Effects",
        "Sample Size Guidance",
        "Histogram Compatibility",
    ]
    active_titles = [
        t
        for t in section_titles
        if any(
            (
                'id="sec-'
                + t.lower().replace(" ", "-").replace("(", "").replace(")", "")
                + '"'
            )
            in s
            for s in sections
        )
    ]
    return _wrap_page(
        "\n".join(sections), deferred_js=hist_js, nav_titles=active_titles
    )


# ─────────────────────────────────────────────────────────────────────────────
# 4. Correlation Structure
# ─────────────────────────────────────────────────────────────────────────────


def _corr_color(r):
    """Return an inline style for a correlation cell.

    Background opacity scales with v² for a smooth ramp.
    Text flips to white once the background is dark enough to support it.
    """
    if r is None:
        return ""
    v = abs(r)
    if v < 0.05:
        return ""
    # v² curve: 0.3→0.065, 0.5→0.18, 0.7→0.353, 0.9→0.583, 1.0→0.72
    alpha = round(v * v * 0.72, 3)
    if r > 0:
        bg = f"rgba(37,99,235,{alpha})"
    else:
        bg = f"rgba(220,38,38,{alpha})"
    # Above ~0.45 alpha the background is dark enough for white text
    text_style = ";color:#fff" if alpha >= 0.45 else ""
    weight = "700" if v >= 0.6 else "400"
    return f'style="background:{bg};font-weight:{weight}{text_style}"'


def _corr_matrix_table(matrix, columns):
    short = [c.replace("_", " ") for c in columns]
    header = "<tr><th></th>" + "".join(f"<th>{s}</th>" for s in short) + "</tr>"
    rows = ""
    for c1 in columns:
        row = f"<tr><td>{c1.replace('_', ' ')}</td>"
        for c2 in columns:
            if c1 == c2:
                row += '<td class="corr-diag">1.00</td>'
            else:
                r = (matrix.get(c1) or {}).get(c2)
                val = f"{r:+.2f}" if r is not None else "—"
                row += f"<td {_corr_color(r)}>{val}</td>"
        row += "</tr>"
        rows += row
    return f'<table class="corr-table"><thead>{header}</thead><tbody>{rows}</tbody></table>'


def _build_correlation_section(
    regression_data, all_sites, site_solid_map, site_pill_text_map=None
):
    if not regression_data:
        return "<p>No regression data available.</p>"
    corr = regression_data.get("correlations", {})
    if not corr.get("available"):
        return f'<p style="color:var(--text3);font-size:.87rem">{corr.get("reason", "Correlation not available.")}</p>'

    columns = corr.get("columns", [])
    global_matrix = corr.get("global", {})
    per_site = corr.get("per_site", {})

    cards = ""
    # Global card
    cards += f"""<div class="reg-card" style="grid-column:1/-1">
  <div class="reg-card-header"><span class="reg-card-title">Global (pooled)</span></div>
  <div class="reg-card-scroll">{_corr_matrix_table(global_matrix, columns)}</div>
  <p class="reg-note">Pearson r computed from federated cross-product sums — no raw data exchanged. Colour intensity indicates strength: blue = positive, red = negative.</p>
</div>"""

    for site in all_sites:
        sc = (site_pill_text_map or {}).get(site, site_solid_map.get(site, "#94a3b8"))
        matrix = per_site.get(site, {})
        cards += f"""<div class="reg-card">
  <div class="reg-card-header"><span class="reg-card-title" style="color:{sc}">{site}</span></div>
  <div class="reg-card-scroll">{_corr_matrix_table(matrix, columns)}</div>
</div>"""

    return f'<div class="reg-grid">{cards}</div>'


# ─────────────────────────────────────────────────────────────────────────────
# 5. Site Effects
# ─────────────────────────────────────────────────────────────────────────────


def _build_site_effects_section(
    regression_data, all_sites, site_solid_map, site_pill_text_map=None
):
    if not regression_data:
        return "<p>No regression data available.</p>"
    site_effects = regression_data.get("site_effects", {})
    if not site_effects:
        return '<p style="color:var(--text3);font-size:.87rem">No numeric universal columns available.</p>'

    header_cells = (
        "".join(f"<th>{s}</th>" for s in all_sites) + "<th>Max |z|</th><th>Flag</th>"
    )
    rows = ""
    for col, data in sorted(site_effects.items()):
        if not data.get("available"):
            continue
        zscores = data.get("site_zscores", {})
        max_z = data.get("max_abs_z")
        flagged = data.get("flagged", False)

        cells = ""
        for site in all_sites:
            z = zscores.get(site)
            if z is None:
                cells += "<td>—</td>"
            else:
                cls = "z-flag" if abs(z) >= 0.5 else "z-ok"
                cells += f'<td class="{cls}">{z:+.2f}</td>'

        flag_cell = (
            '<td class="z-flag">⚠ flagged</td>'
            if flagged
            else '<td class="z-ok">✓ ok</td>'
        )
        rows += f"<tr><td>{col}</td>{cells}<td>{max_z if max_z is not None else '—'}</td>{flag_cell}</tr>"

    if not rows:
        return '<p style="color:var(--text3);font-size:.87rem">Insufficient data for site effect analysis.</p>'

    table = f"""<div style="overflow-x:auto">
<table class="site-effect-table">
<thead><tr><th>Column</th>{header_cells}</tr></thead>
<tbody>{rows}</tbody>
</table></div>
<p class="reg-note">Z-score = (site mean − global mean) / global std dev. A site is flagged (|z| ≥ 0.5) when its mean is more than half a standard deviation from the global mean, suggesting a potential site effect worth investigating before pooling. This is an indicator, not a formal statistical test.</p>"""

    return table


# ─────────────────────────────────────────────────────────────────────────────
# 6. Sample Size Guidance
# ─────────────────────────────────────────────────────────────────────────────


def _build_sample_guidance_section(
    regression_data, all_sites, site_solid_map, site_pill_text_map=None
):
    if not regression_data:
        return "<p>No regression data available.</p>"
    sg = regression_data.get("sample_guidance", {})
    if not sg:
        return '<p style="color:var(--text3);font-size:.87rem">No sample size data available.</p>'

    n_pred = sg.get("n_predictors", 0)
    min_rec = sg.get("min_recommended_n", 0)
    ideal_rec = sg.get("ideal_recommended_n", 0)
    total_n = sg.get("total_n", 0)
    total_ratio = sg.get("total_ratio")
    total_status = sg.get("total_status", "unknown")
    per_site = sg.get("per_site", {})

    status_label = {
        "good": "Good",
        "adequate": "Adequate",
        "low": "Low",
        "unknown": "—",
    }
    status_cls = {
        "good": "status-good",
        "adequate": "status-adequate",
        "low": "status-low",
        "unknown": "",
    }

    cards = ""
    for site in all_sites:
        sc = (site_pill_text_map or {}).get(site, site_solid_map.get(site, "#94a3b8"))
        d = per_site.get(site, {})
        n = d.get("n", "—")
        ratio = d.get("ratio")
        st = d.get("status", "unknown")
        ratio_str = f"{ratio} subjects / predictor" if ratio is not None else "—"
        cards += f"""<div class="guidance-card">
  <div class="guidance-site" style="color:{sc}">{site}</div>
  <div class="guidance-n">{n}</div>
  <div class="guidance-ratio">{ratio_str}</div>
  <div class="guidance-status {status_cls[st]}">{status_label[st]}</div>
</div>"""

    # Total card
    total_ratio_str = (
        f"{total_ratio} subjects / predictor" if total_ratio is not None else "—"
    )
    cards += f"""<div class="guidance-card" style="border-color:var(--border2)">
  <div class="guidance-site" style="color:var(--text3)">Combined</div>
  <div class="guidance-n">{total_n}</div>
  <div class="guidance-ratio">{total_ratio_str}</div>
  <div class="guidance-status {status_cls[total_status]}">{status_label[total_status]}</div>
</div>"""

    summary = f"""<div style="padding:1rem 1rem .25rem;font-size:.83rem;color:var(--text3)">
  Analyzing <b style="color:var(--text)">{n_pred}</b> numeric universal column{"s" if n_pred != 1 else ""} as potential predictors.
  Rule of thumb: <b style="color:var(--text)">≥{min_rec}</b> subjects per site recommended (10× predictors),
  <b style="color:var(--text)">≥{ideal_rec}</b> preferred (20×).
</div>"""

    return summary + f'<div class="guidance-grid">{cards}</div>'


# ─────────────────────────────────────────────────────────────────────────────
# Page shell
# ─────────────────────────────────────────────────────────────────────────────


def _wrap_page(body: str, deferred_js: str = "", nav_titles: list = None) -> str:
    nav_titles = nav_titles or []

    def _slug(t):
        return t.lower().replace(" ", "-").replace("(", "").replace(")", "")

    nav_items_html = "\n".join(
        f'<button class="nav-item" data-sec="sec-{_slug(t)}" '
        f"onclick=\"document.getElementById('sec-{_slug(t)}').scrollIntoView({{behavior:'smooth',block:'start'}})\">{t}</button>"
        for t in nav_titles
    )
    sidebar_html = (
        '<aside class="sidebar" id="sidebar">'
        '<div class="sidebar-inner">'
        '<div class="sidebar-header">'
        '<span class="sidebar-label">Sections</span>'
        '<button class="sidebar-toggle" onclick="toggleSidebar()">&#x2715;</button>'
        "</div>" + nav_items_html + "</div></aside>"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>Federated CSV Compatibility Analysis Report</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
/* ── CSS custom properties: light (default) and dark ── */
:root {{
  --bg:          #ffffff;
  --bg2:         #ffffff;
  --bg3:         #f1f5f9;
  --bg4:         #e2e8f0;
  --border:      #e2e8f0;
  --border2:     #cbd5e1;
  --text:        #0f172a;
  --text2:       #334155;
  --text3:       #64748b;
  --text4:       #94a3b8;
  --header-bg:   linear-gradient(135deg,#e0e9ff 0%,#f8fafc 100%);
  --header-border: #e2e8f0;
  --chip-bg:     #f1f5f9;
  --chip-color:  #475569;
  --chip-b:      #6366f1;
  --legend-color:#334155;
  --card-bg:     #ffffff;
  --card-hover:  #f8fafc;
  --th-bg:       #f8fafc;
  --td-mono:     #1e293b;
  --global-row:  rgba(99,102,241,.06);
  --global-color:#4338ca;
  --chart-bg:    #f8fafc;
  --mgroup-bg:   #f1f5f9;
  --mrow-border: #e2e8f0;
  --mval-color:  #1e293b;
  --plotly-paper:#f8fafc;
  --plotly-plot: #f8fafc;
  --plotly-grid: #e2e8f0;
  --plotly-line: #cbd5e1;
  --plotly-font: #475569;
}}
[data-theme="dark"] {{
  --bg:          #0f172a;
  --bg2:         #1e293b;
  --bg3:         #0f172a;
  --bg4:         #1a2640;
  --border:      #334155;
  --border2:     #334155;
  --text:        #e2e8f0;
  --text2:       #cbd5e1;
  --text3:       #64748b;
  --text4:       #94a3b8;
  --header-bg:   linear-gradient(135deg,#1e1b4b 0%,#0f172a 100%);
  --header-border:#334155;
  --chip-bg:     #1e293b;
  --chip-color:  #94a3b8;
  --chip-b:      #a5b4fc;
  --legend-color:#cbd5e1;
  --card-bg:     #1e293b;
  --card-hover:  #1a2640;
  --th-bg:       #161f30;
  --td-mono:     #cbd5e1;
  --global-row:  rgba(99,102,241,.06);
  --global-color:#a5b4fc;
  --chart-bg:    #0f172a;
  --mgroup-bg:   #0f172a;
  --mrow-border: #0f172a;
  --mval-color:  #e2e8f0;
  --plotly-paper:#0f172a;
  --plotly-plot: #0f172a;
  --plotly-grid: #1e293b;
  --plotly-line: #334155;
  --plotly-font: #94a3b8;
}}

*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;transition:background .2s,color .2s;margin: 1rem 0}}
a{{color:var(--chip-b)}}
button {{ font-family: inherit }}

/* ── theme toggle ── */
.theme-toggle{{position:fixed;top:2rem;right:1.25rem;z-index:999;background:var(--card-bg);border:1px solid var(--border);border-radius:999px;padding:.35rem .85rem;font-size:.8rem;font-weight:600;color:var(--text2);cursor:pointer;display:flex;align-items:center;gap:.4rem;box-shadow:0 1px 4px rgba(0,0,0,.08);transition:background .2s,color .2s,border-color .2s}}
.theme-toggle:hover{{background:var(--bg3)}}

/* ── layout ── */
.page-header{{background:var(--header-bg);border-bottom:1px solid var(--header-border);padding:2rem 2.5rem;padding-right:8rem}}
.page-header h1{{font-size:1.7rem;font-weight:700;color:var(--text);letter-spacing:-.02em}}
.page-header p{{color:var(--text3);margin-top:.35rem;font-size:.93rem}}
.chips{{display:flex;gap:.6rem;margin-top:1rem;flex-wrap:wrap}}
.chip{{background:var(--chip-bg);border:1px solid var(--border);border-radius:999px;padding:.25rem .75rem;font-size:.78rem;color:var(--chip-color)}}
.chip b{{color:var(--chip-b)}}
.site-legend{{display:flex;gap:.9rem;flex-wrap:wrap;margin-top:1rem}}
.legend-item{{display:flex;align-items:center;gap:.45rem;font-size:.83rem;color:var(--legend-color)}}
.legend-dot{{width:11px;height:11px;border-radius:3px;flex-shrink:0}}
.warn-banner{{background:rgba(245,158,11,.1);border:1px solid rgba(245,158,11,.3);border-radius:8px;padding:.6rem 1rem;color:#b45309;font-size:.85rem;margin-top:1rem}}
[data-theme="dark"] .warn-banner{{color:#fbbf24}}

.container{{max-width:1400px;margin:0 auto;padding:2rem 0}}
.section{{margin-bottom:3rem}}
.section-title{{font-size:.82rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--text3);margin-bottom:1.1rem;padding-bottom:.5rem;border-bottom:1px solid var(--border)}}

/* ── presence matrix ── */
.matrix-wrap{{overflow-x:auto;border-radius:12px;border:1px solid var(--border)}}
table.matrix{{width:100%;border-collapse:collapse;font-size:.82rem}}
table.matrix th{{background:var(--th-bg);color:var(--text3);font-weight:600;padding:.6rem .9rem;text-align:left;white-space:nowrap;border-bottom:1px solid var(--border)}}
table.matrix td{{padding:.55rem .9rem;border-bottom:1px solid var(--border);white-space:nowrap}}
table.matrix tr:last-child td{{border-bottom:none}}
table.matrix tr:hover td{{background:var(--card-hover)}}
.cell-present{{border-radius:5px;padding:.2rem .55rem;font-size:.77rem;font-weight:600;display:inline-block}}
.cell-missing{{color:var(--border2);font-size:.8rem}}

.parallelism-callouts{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:.9rem;margin-top:1.1rem}}
.callout{{border-radius:10px;padding:1rem 1.1rem;font-size:.83rem}}
.callout-title{{font-weight:700;margin-bottom:.4rem;font-size:.85rem}}
.callout-body{{color:var(--text3);line-height:1.5}}
.callout-body b{{color:var(--text2)}}

/* ── stats table ── */
.stats-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:1rem}}
.stat-card{{background:var(--card-bg);border:1px solid var(--border);border-radius:12px;overflow:hidden}}
.stat-card-scroll{{overflow-x:auto;-webkit-overflow-scrolling:touch}}
.stat-card-header{{padding:.75rem 1rem;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:.6rem}}
.stat-card-title{{font-weight:700;color:var(--text);font-size:.9rem}}
table.stat-table{{width:100%;border-collapse:collapse;font-size:.8rem}}
table.stat-table th{{color:var(--text3);font-weight:600;padding:.45rem .85rem;text-align:right;background:var(--th-bg)}}
table.stat-table th:first-child{{text-align:left}}
table.stat-table td{{padding:.42rem .85rem;border-top:1px solid var(--border);text-align:right;color:var(--td-mono);font-family:monospace}}
table.stat-table td:first-child{{text-align:left;color:var(--text3);font-family:inherit}}
table.stat-table tr.global-row td{{color:var(--global-color);font-weight:600;background:var(--global-row)}}

/* ── regression analysis sections ── */
.reg-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:1rem;margin-bottom:1rem}}
.reg-card{{background:var(--card-bg);border:1px solid var(--border);border-radius:12px;overflow:hidden}}
.reg-card-header{{padding:.75rem 1rem;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:.6rem}}
.reg-card-title{{font-weight:700;color:var(--text);font-size:.9rem;flex:1}}
.reg-card-scroll{{overflow-x:auto;-webkit-overflow-scrolling:touch}}
.corr-table{{width:100%;border-collapse:collapse;font-size:.78rem}}
.corr-table th{{color:var(--text3);font-weight:600;padding:.4rem .6rem;text-align:center;background:var(--th-bg);white-space:nowrap}}
.corr-table th:first-child{{text-align:left}}
.corr-table td{{padding:.38rem .6rem;border-top:1px solid var(--border);text-align:center;font-family:monospace;font-size:.77rem}}
.corr-table td:first-child{{text-align:left;font-family:inherit;color:var(--text3);font-weight:600;white-space:nowrap}}
.corr-diag{{color:var(--text3)}}
.guidance-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:.75rem;padding:1rem}}
.guidance-card{{border-radius:10px;padding:.85rem 1rem;border:1px solid var(--border);background:var(--bg3)}}
.guidance-site{{font-size:.8rem;font-weight:700;margin-bottom:.3rem}}
.guidance-n{{font-size:1.3rem;font-weight:800;color:var(--text)}}
.guidance-ratio{{font-size:.77rem;color:var(--text3);margin-top:.1rem}}
.guidance-status{{font-size:.72rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;margin-top:.4rem}}
.status-good{{color:#059669}}.status-adequate{{color:#d97706}}.status-low{{color:#dc2626}}
.site-effect-table{{width:100%;border-collapse:collapse;font-size:.8rem}}
.site-effect-table th{{color:var(--text3);font-weight:600;padding:.4rem .85rem;text-align:right;background:var(--th-bg)}}
.site-effect-table th:first-child{{text-align:left}}
.site-effect-table td{{padding:.38rem .85rem;border-top:1px solid var(--border);text-align:right;font-family:monospace;font-size:.79rem}}
.site-effect-table td:first-child{{text-align:left;font-family:inherit;color:var(--text3)}}
.z-flag{{color:#dc2626;font-weight:700}}.z-ok{{color:#059669}}
.reg-note{{font-size:.73rem;color:var(--text3);padding:.5rem 1rem 0.75rem;border-top:1px solid var(--border);margin-top:.25rem}}

/* ── histogram sections ── */
.hist-section{{background:var(--card-bg);border:1px solid var(--border);border-radius:14px;margin-bottom:1.5rem;overflow:hidden}}
.hist-scroll{{overflow-x:auto;-webkit-overflow-scrolling:touch}}
.hist-header{{padding:1.1rem 1.4rem;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:.8rem;flex-wrap:wrap}}
.hist-title{{font-size:1rem;font-weight:700;color:var(--text)}}
.hist-body{{padding:1.4rem;display:grid;grid-template-columns:1fr 320px;gap:1.4rem}}
@media(max-width:860px){{.hist-body{{grid-template-columns:1fr}}}}
.chart-box{{background:var(--chart-bg);border-radius:10px;min-height:300px;overflow:hidden;border:1px solid var(--border)}}
.metrics-col{{display:flex;flex-direction:column;gap:.85rem}}
.mgroup{{background:var(--mgroup-bg);border-radius:10px;padding:.9rem 1rem}}
.mgroup-title{{font-size:.72rem;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:var(--text3);margin-bottom:.55rem}}
.mrow{{display:flex;justify-content:space-between;align-items:center;padding:.28rem 0;border-bottom:1px solid var(--mrow-border);font-size:.8rem}}
.mrow:last-child{{border-bottom:none}}
.mlabel{{color:var(--text3)}}
.mval{{color:var(--mval-color);font-family:monospace;font-weight:500}}
.compat-note{{margin-top:.9rem;border-radius:8px;padding:.55rem .9rem;font-size:.82rem;font-weight:500}}
.compat-ok{{background:rgba(16,185,129,.1);border:1px solid rgba(16,185,129,.25);color:#15803d}}
.compat-warn{{background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.25);color:#dc2626}}
[data-theme="dark"] .compat-ok{{color:#34d399}}
[data-theme="dark"] .compat-warn{{color:#f87171}}
.partial-note{{background:rgba(245,158,11,.08);border:1px solid rgba(245,158,11,.25);color:#b45309;border-radius:8px;padding:.5rem .9rem;font-size:.8rem;margin-bottom:.7rem}}
[data-theme="dark"] .partial-note{{color:#fbbf24}}

/* ── badges ── */
.badge{{display:inline-block;padding:.14rem .55rem;border-radius:999px;font-size:.73rem;font-weight:600}}
.badge-green{{background:rgba(16,185,129,.12);color:#15803d;border:1px solid rgba(16,185,129,.3)}}
.badge-red{{background:rgba(239,68,68,.12);color:#dc2626;border:1px solid rgba(239,68,68,.3)}}
.badge-yellow{{background:rgba(245,158,11,.12);color:#b45309;border:1px solid rgba(245,158,11,.3)}}
.badge-blue{{background:rgba(99,102,241,.12);color:#4338ca;border:1px solid rgba(99,102,241,.3)}}
.badge-gray{{background:rgba(100,116,139,.12);color:#475569;border:1px solid rgba(100,116,139,.3)}}
[data-theme="dark"] .badge-green{{color:#34d399}}
[data-theme="dark"] .badge-red{{color:#f87171}}
[data-theme="dark"] .badge-yellow{{color:#fbbf24}}
[data-theme="dark"] .badge-blue{{color:#a5b4fc}}
[data-theme="dark"] .badge-gray{{color:#94a3b8}}

/* ── sidebar nav ── */
.layout{{display:flex;align-items:flex-start;padding:1.5rem 2rem 0}}
.sidebar{{width:190px;flex-shrink:0;position:sticky;top:1.5rem;max-height:calc(100vh - 3rem);overflow-y:auto;margin-right:1.5rem;transition:width .2s,opacity .2s,margin .2s}}
.sidebar.hidden{{width:0;opacity:0;overflow:hidden;margin-right:0;pointer-events:none}}
.sidebar-inner{{background:var(--card-bg);border:1px solid var(--border);border-radius:12px;padding:.6rem .5rem}}
.sidebar-header{{display:flex;align-items:center;justify-content:space-between;padding:.2rem .3rem .45rem;border-bottom:1px solid var(--border);margin-bottom:.4rem}}
.sidebar-label{{font-size:.67rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--text3)}}
.sidebar-toggle{{background:none;border:none;cursor:pointer;font-size:.75rem;color:var(--text3);padding:.15rem .35rem;border-radius:5px;font-family:inherit;line-height:1}}
.sidebar-toggle:hover{{background:var(--bg3);color:var(--text)}}
.nav-item{{display:block;width:100%;padding:.4rem .65rem;border-radius:7px;font-size:.78rem;color:var(--text3);text-decoration:none;line-height:1.35;cursor:pointer;border:none;background:none;text-align:left;font-family:inherit;transition:background .12s,color .12s}}
.nav-item:hover{{background:var(--bg3);color:var(--text)}}
.nav-item.active{{background:rgba(99,102,241,.13);color:#6366f1;font-weight:600}}
[data-theme="dark"] .nav-item.active{{background:rgba(165,180,252,.1);color:#a5b4fc}}
.main-content{{flex:1;min-width:0}}
.sidebar-peek{{position:fixed;left:0;top:50%;transform:translateY(-50%);background:var(--card-bg);border:1px solid var(--border);border-left:none;border-radius:0 8px 8px 0;padding:.55rem .35rem;cursor:pointer;font-size:.72rem;color:var(--text3);display:none;z-index:200;writing-mode:vertical-rl;letter-spacing:.06em;font-family:inherit;line-height:1}}
.sidebar-peek:hover{{color:var(--text)}}
.sidebar-peek.visible{{display:block}}
</style>
</head>
<body>
<button class="theme-toggle" onclick="toggleTheme()" id="themeBtn">🌙 Dark mode</button>
<div class="layout">
{sidebar_html}
<button class="sidebar-peek" id="sidebarPeek" onclick="toggleSidebar()">Sections</button>
<div class="main-content">
{body}
</div>
</div>
<script>
// ── Theme toggle ──
function getTheme() {{
  try {{ return localStorage.getItem('theme') || 'light'; }} catch(e) {{ return 'light'; }}
}}
function applyTheme(theme) {{
  document.documentElement.setAttribute('data-theme', theme === 'dark' ? 'dark' : '');
  document.getElementById('themeBtn').textContent = theme === 'dark' ? '☀️ Light mode' : '🌙 Dark mode';
  relayoutCharts(theme);
}}
function toggleTheme() {{
  var next = getTheme() === 'dark' ? 'light' : 'dark';
  try {{ localStorage.setItem('theme', next); }} catch(e) {{}}
  applyTheme(next);
}}
function relayoutCharts(theme) {{
  var paper      = theme === 'dark' ? '#0f172a' : '#f8fafc';
  var grid       = theme === 'dark' ? '#1e293b' : '#e2e8f0';
  var line       = theme === 'dark' ? '#334155' : '#cbd5e1';
  var font       = theme === 'dark' ? '#94a3b8' : '#475569';
  var globalLine = theme === 'dark' ? '#e2e8f0' : '#0f172a';
  var charts = document.querySelectorAll('.chart-box');
  charts.forEach(function(el) {{
    try {{
      Plotly.relayout(el, {{
        'paper_bgcolor': paper, 'plot_bgcolor': paper,
        'font.color': font,
        'xaxis.gridcolor': grid, 'xaxis.linecolor': line,
        'yaxis.gridcolor': grid, 'yaxis.linecolor': line
      }});
      // Restyle the Global trace line colour (always the last trace)
      var gd = el;
      if (gd.data && gd.data.length > 0) {{
        var lastIdx = gd.data.length - 1;
        if (gd.data[lastIdx].name === 'Global') {{
          Plotly.restyle(gd, {{'line.color': globalLine}}, [lastIdx]);
        }}
      }}
    }} catch(e) {{}}
  }});
}}

// ── Sidebar toggle ──
function toggleSidebar() {{
  var sb = document.getElementById('sidebar');
  var pk = document.getElementById('sidebarPeek');
  var hidden = sb.classList.toggle('hidden');
  try {{ localStorage.setItem('sidebarHidden', hidden ? '1' : '0'); }} catch(e) {{}}
  if (pk) pk.classList.toggle('visible', hidden);
  // Resize charts after CSS transition finishes (transition is 0.2s)
  setTimeout(function() {{
    document.querySelectorAll('.chart-box').forEach(function(el) {{
      try {{ Plotly.Plots.resize(el); }} catch(e) {{}}
    }});
  }}, 220);
}}
(function() {{
  try {{
    if (localStorage.getItem('sidebarHidden') === '1') {{
      var sb = document.getElementById('sidebar');
      var pk = document.getElementById('sidebarPeek');
      if (sb) sb.classList.add('hidden');
      if (pk) pk.classList.add('visible');
    }}
  }} catch(e) {{}}
}})();

// ── Active nav on scroll ──
document.addEventListener('DOMContentLoaded', function() {{
  var navItems = document.querySelectorAll('.nav-item[data-sec]');
  if (!navItems.length) return;
  var secs = Array.from(navItems).map(function(el) {{
    return document.getElementById(el.getAttribute('data-sec'));
  }}).filter(Boolean);
  function onScroll() {{
    var y = window.scrollY + 140;
    var active = secs[0];
    secs.forEach(function(s) {{ if (s.offsetTop <= y) active = s; }});
    navItems.forEach(function(el) {{
      el.classList.toggle('active', active && el.getAttribute('data-sec') === active.id);
    }});
  }}
  window.addEventListener('scroll', onScroll, {{passive:true}});
  onScroll();
}});

// ── Charts (deferred until DOM + Plotly ready) ──
document.addEventListener('DOMContentLoaded', function() {{
  {deferred_js}
  applyTheme(getTheme());
}});
</script>
</body>
</html>"""


def _section(title: str, content: str) -> str:
    slug = title.lower().replace(" ", "-").replace("(", "").replace(")", "")
    return f'<div class="container"><div class="section" id="sec-{slug}"><div class="section-title">{title}</div>{content}</div></div>'


# ─────────────────────────────────────────────────────────────────────────────
# 1. Header
# ─────────────────────────────────────────────────────────────────────────────


def _build_header(
    n_sites,
    total_rows,
    n_universal,
    n_partial,
    n_conflict,
    n_hist_cols,
    all_sites,
    site_solid_map,
):
    legend_items = "".join(
        f'<div class="legend-item"><div class="legend-dot" style="background:{site_solid_map[s]}"></div>{s}</div>'
        for s in all_sites
    )

    warn = ""
    if n_partial or n_conflict:
        parts = []
        if n_partial:
            parts.append(
                f"<b>{n_partial}</b> column{'s' if n_partial != 1 else ''} present in only some sites"
            )
        if n_conflict:
            parts.append(
                f"<b>{n_conflict}</b> column{'s' if n_conflict != 1 else ''} with type conflicts across sites"
            )
        warn = f'<div class="warn-banner">⚠ &nbsp;{" · ".join(parts)}. See Data Structure section for details.</div>'

    return f"""<div class="page-header">
  <h1>Federated CSV Analysis Report</h1>
  <p>Cross-site data structure, descriptive statistics, and distribution compatibility</p>
  <div class="chips">
    <div class="chip">Sites: <b>{n_sites}</b></div>
    <div class="chip">Total rows: <b>{total_rows}</b></div>
    <div class="chip">Universal columns: <b>{n_universal}</b></div>
    <div class="chip">Histograms analyzed: <b>{n_hist_cols}</b></div>
  </div>
  <div class="site-legend">{legend_items}</div>
  {warn}
</div>"""


# ─────────────────────────────────────────────────────────────────────────────
# 2. Data Structure — presence matrix + callouts
# ─────────────────────────────────────────────────────────────────────────────


def _build_structure_section(
    parallelism,
    all_sites,
    site_solid_map,
    site_color_map,
    site_pill_bg_map=None,
    site_pill_text_map=None,
):
    presence_matrix = parallelism.get("presence_matrix", {})
    column_details = parallelism.get("column_details", {})
    universal_cols = parallelism.get("universal_columns", [])
    partial_cols = parallelism.get("partial_columns", [])
    conflict_cols = parallelism.get("type_conflict_columns", [])

    if not presence_matrix:
        return "<p style='color:#64748b'>No column data available.</p>"

    # ── presence matrix table ──
    header_cells = "".join(f"<th>{s}</th>" for s in all_sites)
    rows = ""
    for col in sorted(presence_matrix.keys()):
        detail = column_details.get(col, {})
        status = detail.get("status", "universal")
        txt_color, bg, border = {
            "universal": ("#34d399", "rgba(16,185,129,0.12)", "rgba(16,185,129,0.3)"),
            "partial": ("#fbbf24", "rgba(245,158,11,0.12)", "rgba(245,158,11,0.3)"),
            "type_conflict": ("#f87171", "rgba(239,68,68,0.12)", "rgba(239,68,68,0.3)"),
        }[status]

        status_badge = f'<span class="badge" style="color:{txt_color};background:{bg};border:1px solid {border}">{status.replace("_", " ")}</span>'

        site_cells = ""
        for site in all_sites:
            t = presence_matrix[col].get(site)
            if t:
                pill_bg = (site_pill_bg_map or {}).get(site, "rgba(99,102,241,0.12)")
                pill_text = (site_pill_text_map or {}).get(site, "#3730a3")
                site_cells += f'<td><span class="cell-present" style="background:{pill_bg};color:{pill_text}">{t}</span></td>'
            else:
                site_cells += '<td><span class="cell-missing">—</span></td>'

        rows += f"<tr><td><b style='color:var(--text)'>{col}</b></td>{site_cells}<td>{status_badge}</td></tr>"

    table = f"""<div class="matrix-wrap">
<table class="matrix">
  <thead><tr><th>Column</th>{header_cells}<th>Status</th></tr></thead>
  <tbody>{rows}</tbody>
</table></div>"""

    # ── callouts ──
    callouts = ""

    if universal_cols:
        names = ", ".join(f"<b>{c}</b>" for c in universal_cols)
        callouts += f"""<div class="callout" style="background:rgba(16,185,129,.06);border:1px solid rgba(16,185,129,.2)">
  <div class="callout-title" style="color:#34d399">✓ Universal columns ({len(universal_cols)})</div>
  <div class="callout-body">Present in all sites with consistent type: {names}. These columns are fully parallel and suitable for federated analysis.</div>
</div>"""

    for col in partial_cols:
        detail = column_details.get(col, {})
        present = detail.get("present_in", [])
        missing = detail.get("missing_from", [])
        present_str = ", ".join(f"<b>{s}</b>" for s in present)
        missing_str = ", ".join(f"<b>{s}</b>" for s in missing)
        types = detail.get("types_by_site", {})
        type_info = ", ".join(f"{s}: {t}" for s, t in types.items() if t)
        callouts += f"""<div class="callout" style="background:rgba(245,158,11,.06);border:1px solid rgba(245,158,11,.2)">
  <div class="callout-title" style="color:#fbbf24">⚠ Partial column: <b>{col}</b></div>
  <div class="callout-body">
    Present in: {present_str}<br>
    Missing from: {missing_str}<br>
    Types: {type_info}<br>
    Histogram analysis will only include contributing sites.
  </div>
</div>"""

    for col in conflict_cols:
        detail = column_details.get(col, {})
        types = detail.get("types_by_site", {})
        type_info = ", ".join(f"<b>{s}</b>: {t}" for s, t in types.items() if t)
        callouts += f"""<div class="callout" style="background:rgba(239,68,68,.06);border:1px solid rgba(239,68,68,.2)">
  <div class="callout-title" style="color:#f87171">✗ Type conflict: <b>{col}</b></div>
  <div class="callout-body">Sites report different types for this column — {type_info}. Cross-site comparison may be unreliable.</div>
</div>"""

    callouts_html = (
        f'<div class="parallelism-callouts">{callouts}</div>' if callouts else ""
    )
    return table + callouts_html


# ─────────────────────────────────────────────────────────────────────────────
# 3. Global Descriptive Statistics
# ─────────────────────────────────────────────────────────────────────────────


def _build_stats_section(
    column_stats, all_sites, site_solid_map, parallelism, site_pill_text_map=None
):
    if not column_stats:
        return "<p style='color:#64748b'>No statistics available.</p>"

    column_details = parallelism.get("column_details", {})
    cards = ""

    for col, stats in sorted(column_stats.items()):
        inferred_type = stats.get("inferred_type", "string")
        detail = column_details.get(col, {})
        status = detail.get("status", "universal")
        present_sites = detail.get("present_in", all_sites)

        txt_color, bg, border = {
            "universal": ("#34d399", "rgba(16,185,129,0.12)", "rgba(16,185,129,0.3)"),
            "partial": ("#fbbf24", "rgba(245,158,11,0.12)", "rgba(245,158,11,0.3)"),
            "type_conflict": ("#f87171", "rgba(239,68,68,0.12)", "rgba(239,68,68,0.3)"),
        }[status]
        status_badge = f'<span class="badge" style="color:{txt_color};background:{bg};border:1px solid {border}">{status.replace("_", " ")}</span>'
        type_badge = f'<span class="badge badge-blue">{inferred_type}</span>'

        if inferred_type == "number":
            # header row
            table = """<table class="stat-table">
<thead><tr><th>Site</th><th>N</th><th>Unique</th><th>Missing</th><th>Mean</th><th>Std Dev</th><th>Min</th><th>Median</th><th>Max</th></tr></thead><tbody>"""
            per_site = stats.get("per_site", {})
            for site in all_sites:
                if site not in present_sites:
                    _sc = (site_pill_text_map or {}).get(
                        site, site_solid_map.get(site, "#94a3b8")
                    )
                    table += f"<tr><td style='color:{_sc}'>{site}</td><td colspan='8' style='color:var(--text3);text-align:center'>not present</td></tr>"
                    continue
                ps = per_site.get(site, {})

                def fmt(v):
                    return f"{v}" if v is not None else "—"

                table += f"""<tr>
  <td style='color:{(site_pill_text_map or {{}}).get(site, site_solid_map.get(site, "#94a3b8"))};font-weight:600'>{site}</td>
  <td>{fmt(ps.get("count"))}</td>
  <td>{fmt(ps.get("unique_count"))}</td>
  <td>{fmt(ps.get("nan_count"))}</td>
  <td>{fmt(ps.get("mean"))}</td>
  <td>{fmt(ps.get("std_dev"))}</td>
  <td>{fmt(ps.get("min"))}</td>
  <td>{fmt(ps.get("median"))}</td>
  <td>{fmt(ps.get("max"))}</td>
</tr>"""

            # global row
            def g(k, stats=stats):
                return stats.get(k, "—")

            table += f"""<tr class="global-row">
  <td>Global</td>
  <td>{stats.get("total_count", "—")}</td>
  <td>—</td>
  <td>{stats.get("total_nan_count", "—")}</td>
  <td>{g("global_mean")}</td>
  <td>{g("global_std_dev")}</td>
  <td>{g("global_min")}</td>
  <td>—*</td>
  <td>{g("global_max")}</td>
</tr>"""
            table += "</tbody></table>"
            footnote = '<p style="font-size:.73rem;color:#475569;padding:.5rem .85rem">* Global median requires raw data exchange — not computed.</p>'
        else:
            table = """<table class="stat-table">
<thead><tr><th>Site</th><th>N</th><th>Unique values</th><th>Missing</th></tr></thead><tbody>"""
            per_site = stats.get("per_site", {})
            for site in all_sites:
                if site not in present_sites:
                    _sc = (site_pill_text_map or {}).get(
                        site, site_solid_map.get(site, "#94a3b8")
                    )
                    table += f"<tr><td style='color:{_sc}'>{site}</td><td colspan='3' style='color:var(--text3);text-align:center'>not present</td></tr>"
                    continue
                ps = per_site.get(site, {})

                def fmt(v):
                    return f"{v}" if v is not None else "—"

                table += f"""<tr>
  <td style='color:{(site_pill_text_map or {{}}).get(site, site_solid_map.get(site, "#94a3b8"))};font-weight:600'>{site}</td>
  <td>{fmt(ps.get("count"))}</td>
  <td>{fmt(ps.get("unique_count"))}</td>
  <td>{fmt(ps.get("nan_count"))}</td>
</tr>"""
            table += f"""<tr class="global-row">
  <td>Global</td>
  <td>{stats.get("total_count", "—")}</td>
  <td>—</td>
  <td>{stats.get("total_nan_count", "—")}</td>
</tr></tbody></table>"""
            footnote = ""

        cards += f"""<div class="stat-card">
  <div class="stat-card-header">{type_badge} <span class="stat-card-title">{col}</span> {status_badge}</div>
  <div class="stat-card-scroll">{table}</div>{footnote}
</div>"""

    return f'<div class="stats-grid">{cards}</div>'


# ─────────────────────────────────────────────────────────────────────────────
# 4. Histogram Compatibility
# ─────────────────────────────────────────────────────────────────────────────


def _build_histograms_section(
    hist_columns, all_sites, site_color_map, site_solid_map, parallelism
):
    if not hist_columns:
        return (
            "<p style='color:#64748b'>No column is present with the same type at "
            "every site with more than one distinct value, so no histograms were "
            "compared.</p>",
            "",
        )

    column_details = parallelism.get("column_details", {})

    # Overview cards row
    overview = _build_hist_overview(hist_columns)

    html_parts = [overview]
    js_parts = []
    for col, col_data in hist_columns.items():
        detail = column_details.get(col, {})
        present_in = detail.get("present_in", all_sites)
        col_html, col_js = _build_hist_column(
            col, col_data, all_sites, present_in, site_color_map, site_solid_map
        )
        html_parts.append(col_html)
        js_parts.append(col_js)

    return "".join(html_parts), "\n  ".join(js_parts)


def _build_hist_overview(hist_columns):
    cards = ""
    for col, col_data in hist_columns.items():
        compat = col_data.get("compatibility_summary", {})
        overlap = col_data.get("overlap", {})
        kl = col_data.get("kl_divergence", {})
        chi2 = col_data.get("chi_squared", {})
        ok = compat.get("compatible", None)

        if ok is True:
            badge = '<span class="badge badge-green">Compatible</span>'
        elif ok is False:
            badge = '<span class="badge badge-red">Divergent</span>'
        else:
            badge = '<span class="badge badge-gray">Partial data</span>'

        cards += f"""<div style="background:var(--card-bg);border:1px solid var(--border);border-radius:10px;padding:1rem">
  <div style="font-weight:700;color:var(--text);margin-bottom:.6rem">{col} {badge}</div>
  <div class="mrow"><span class="mlabel">Mean overlap</span><span class="mval">{overlap.get("mean_pairwise", "—")}</span></div>
  <div class="mrow"><span class="mlabel">Mean KL (vs global)</span><span class="mval">{kl.get("mean_vs_global", "—")}</span></div>
  <div class="mrow"><span class="mlabel">χ² p-value</span><span class="mval">{chi2.get("p_value", "—")}</span></div>
</div>"""

    return f'<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:.85rem;margin-bottom:2rem">{cards}</div>'


def _build_hist_column(
    col, col_data, all_sites, present_sites, site_color_map, site_solid_map
):
    edges = col_data.get("edges", [])
    per_site_counts = col_data.get("per_site_counts", {})
    compat = col_data.get("compatibility_summary", {})
    overlap = col_data.get("overlap", {})
    kl = col_data.get("kl_divergence", {})
    chi2 = col_data.get("chi_squared", {})
    missing = col_data.get("per_site_missing", {})

    # Bin labels
    if len(edges) > 1 and isinstance(edges[0], (int, float)):
        labels = [f"[{edges[i]},{edges[i + 1]})" for i in range(len(edges) - 1)]
        if labels:
            labels[-1] = labels[-1][:-1] + "]"
    else:
        labels = [str(e) for e in edges]

    # Only include sites that actually have data for this column
    contributing_sites = [s for s in all_sites if s in per_site_counts]
    missing_sites = [s for s in all_sites if s not in per_site_counts]

    def _normalize(counts):
        total = sum(counts)
        return [round(c / total, 6) if total else 0 for c in counts]

    is_categorical = col_data.get("type") == "categorical" or (
        edges and isinstance(edges[0], str)
    )

    traces = []
    if is_categorical:
        # Grouped bars — one bar group per site, one bar per category
        for site in contributing_sites:
            counts = per_site_counts.get(site, [])
            solid = site_solid_map.get(site, "#6366f1")
            fill = site_color_map.get(site, "rgba(99,102,241,0.65)")
            fill_bar = (
                fill.rsplit(",", 1)[0] + ",0.75)" if fill.startswith("rgba") else fill
            )
            traces.append(
                {
                    "type": "bar",
                    "name": site,
                    "x": labels,
                    "y": _normalize(counts),
                    "marker": {
                        "color": fill_bar,
                        "line": {"color": solid, "width": 1.5},
                    },
                }
            )
    else:
        # Smooth filled area curves for numeric columns
        for site in contributing_sites:
            counts = per_site_counts.get(site, [])
            solid = site_solid_map.get(site, "#6366f1")
            fill = site_color_map.get(site, "rgba(99,102,241,0.65)")
            fill_area = (
                fill.rsplit(",", 1)[0] + ",0.18)" if fill.startswith("rgba") else fill
            )
            traces.append(
                {
                    "type": "scatter",
                    "mode": "lines",
                    "name": site,
                    "x": labels,
                    "y": _normalize(counts),
                    "line": {
                        "color": solid,
                        "width": 2.5,
                        "shape": "spline",
                        "smoothing": 1.0,
                    },
                    "fill": "tozeroy",
                    "fillcolor": fill_area,
                }
            )

        # Global line — pooled normalized distribution, drawn last so it sits on top
        global_dist = col_data.get("global_distribution", [])
        if global_dist:
            traces.append(
                {
                    "type": "scatter",
                    "mode": "lines",
                    "name": "Global",
                    "x": labels,
                    "y": global_dist,
                    "line": {
                        "color": "#0f172a",
                        "width": 2.5,
                        "dash": "dash",
                        "shape": "spline",
                        "smoothing": 1.0,
                    },
                    "fill": "none",
                }
            )

    # Build clean x-axis tick positions: ~6 evenly spaced labels across the range
    n_bins = len(labels)
    if n_bins > 1:
        step = max(1, round(n_bins / 6))
        tick_indices = list(range(0, n_bins, step))
        if (n_bins - 1) not in tick_indices:
            tick_indices.append(n_bins - 1)

        # Show just the left edge value as a short number
        def _short(lbl):
            # Extract left edge from "[val,..." or just return as-is
            try:
                return str(round(float(lbl.lstrip("[").split(",")[0]), 1))
            except ValueError:
                return lbl

        tick_vals = [labels[i] for i in tick_indices]
        tick_text = [_short(labels[i]) for i in tick_indices]
    else:
        tick_vals = labels
        tick_text = labels

    base_layout = {
        "paper_bgcolor": "#f8fafc",
        "plot_bgcolor": "#f8fafc",
        "font": {"color": "#475569", "size": 11},
        "margin": {"t": 16, "b": 56, "l": 46, "r": 10},
        "xaxis": {
            "tickvals": tick_vals,
            "ticktext": tick_text,
            "tickangle": -30,
            "gridcolor": "#e2e8f0",
            "linecolor": "#cbd5e1",
            "title": {"text": col, "font": {"color": "#475569"}},
        },
        "yaxis": {
            "gridcolor": "#e2e8f0",
            "linecolor": "#cbd5e1",
            "title": {"text": "Proportion", "font": {"color": "#475569"}},
        },
        "legend": {"orientation": "h", "y": -0.25, "font": {"size": 10}},
    }
    layout = {**base_layout, "barmode": "group"} if is_categorical else base_layout

    chart_id = f"chart_{col.replace(' ', '_').replace('.', '_').replace('-', '_')}"
    traces_json = json.dumps(traces)
    layout_json = json.dumps(layout)

    ok = compat.get("compatible", None)
    if ok is True:
        compat_cls, compat_badge = (
            "compat-ok",
            '<span class="badge badge-green">Compatible</span>',
        )
    elif ok is False:
        compat_cls, compat_badge = (
            "compat-warn",
            '<span class="badge badge-red">Divergent</span>',
        )
    else:
        compat_cls, compat_badge = (
            "compat-warn",
            '<span class="badge badge-gray">Partial</span>',
        )

    # Partial-data notice
    partial_notice = ""
    if missing_sites:
        ms = ", ".join(f"<b>{s}</b>" for s in missing_sites)
        partial_notice = f'<div class="partial-note">⚠ Column not present at: {ms}. Compatibility metrics reflect contributing sites only.</div>'

    # Metrics panel rows
    def mrow(label, val):
        return f'<div class="mrow"><span class="mlabel">{label}</span><span class="mval">{val}</span></div>'

    pw_overlap = "".join(mrow(k, v) for k, v in overlap.get("pairwise", {}).items())
    sv_overlap = "".join(
        mrow(f"{s} vs global", v) for s, v in overlap.get("site_vs_global", {}).items()
    )
    kl_rows = "".join(mrow(s, v) for s, v in kl.get("site_vs_global", {}).items())
    pklo_rows = "".join(mrow(k, v) for k, v in kl.get("pairwise_symmetric", {}).items())
    miss_rows = "".join(
        mrow(s, f"{v} out-of-range/missing") for s, v in missing.items() if v
    )

    chi2_sig = chi2.get("significant_difference", None)
    chi2_lbl = (
        '<span class="badge badge-red">Significant difference</span>'
        if chi2_sig is True
        else '<span class="badge badge-green">No significant difference</span>'
        if chi2_sig is False
        else "—"
    )

    metrics_html = f"""
<div class="mgroup">
  <div class="mgroup-title">Overlap Coefficient</div>
  {pw_overlap}{sv_overlap}
  {mrow("Mean pairwise", overlap.get("mean_pairwise", "—"))}
</div>
<div class="mgroup">
  <div class="mgroup-title">KL Divergence</div>
  {kl_rows}{pklo_rows}
  {mrow("Mean vs global", kl.get("mean_vs_global", "—"))}
</div>
<div class="mgroup">
  <div class="mgroup-title">Chi-Squared Homogeneity</div>
  {mrow("χ² statistic", chi2.get("statistic", "—"))}
  {mrow("Degrees of freedom", chi2.get("degrees_of_freedom", "—"))}
  {mrow("p-value", str(chi2.get("p_value", "—")) + " " + chi2_lbl)}
</div>
{f'<div class="mgroup"><div class="mgroup-title">Missing / Out-of-range</div>{miss_rows}</div>' if miss_rows else ""}"""

    html = f"""
<div class="hist-section">
  <div class="hist-header">
    <span class="hist-title">{col}</span>
    {compat_badge}
    {"".join('<span class="badge badge-yellow">partial</span>' for _ in [1] if missing_sites)}
  </div>
  <div class="hist-body">
    <div>
      {partial_notice}
      <div class="chart-box" id="{chart_id}" style="height:300px"></div>
      <div class="{compat_cls} compat-note">{compat.get("note", "")}</div>
    </div>
    <div class="metrics-col">{metrics_html}</div>
  </div>
</div>"""
    js = f"Plotly.newPlot('{chart_id}',{traces_json},{layout_json},{{responsive:true,displayModeBar:false}});"
    return html, js
