# NVFlare CSV Analyzer Computation

A federated computation built on the NVFlare/NeuroFLAME boilerplate that performs privacy-preserving statistical analysis across multiple sites' CSV data without any raw data leaving each site.

## What It Does

Each participating site reads its local CSV file(s), computes per-column statistics locally, and sends only aggregated summaries (not raw rows) to the server. The server merges all site results into a global report, generates histogram bin edges from the global data range, and sends those back so each site can count its own values into the shared bins. The aggregated histograms — along with correlation matrices, site effect indicators, and sample size guidance — are assembled into a self-contained interactive HTML report delivered to every site.

### Statistics Computed Per Column

| Statistic | Numeric | String/Boolean |
|---|---|---|
| Inferred type | ✓ | ✓ |
| Row count | ✓ | ✓ |
| NaN / missing count | ✓ | ✓ |
| Type mismatch count | ✓ | ✓ |
| Unique value count | ✓ | ✓ |
| Mean (global, exact) | ✓ | — |
| Variance and Std Dev (global, exact) | ✓ | — |
| Min / Max (global) | ✓ | — |
| Median, Q1, Q3 (per-site) | ✓ | — |
| Pearson correlation (federated, exact) | ✓ | — |

Privacy note: Global mean, variance, and correlation are computed exactly using sufficient statistics (counts, sums, sums of squares, and cross-product sums). Median and quartiles are reported per-site only. No raw subject data leaves any site.

## Computation Flow

**Round 1 — Local CSV Analysis**

1. Server broadcasts `ANALYZE_CSV` task to all sites
2. Each site reads local CSV(s), computes column-level stats and cross-product sums, returns summary (no raw data)
3. Server aggregates all site results into a global report with pooled statistics and column parallelism analysis
4. Server broadcasts `ACCEPT_GLOBAL_REPORT` back to sites for local saving

**Round 2 — Histogram Computation**

5. Server auto-generates histogram bin edges for each universal numeric column from the global min/max, then broadcasts `COMPUTE_HISTOGRAMS` with the bin config
6. Each site counts its local values into the shared bin edges and returns the counts
7. Server aggregates per-site counts, computes compatibility metrics and regression-readiness analysis, generates the HTML report
8. Server broadcasts `ACCEPT_HISTOGRAM_REPORT` to all sites; each site saves the report locally

## Input Format

Place one or more `.csv` files (with header row) in each site's data directory. The computation auto-detects two layouts:

- **Single-file layout**: all columns in one file
- **Split-file layout** (e.g. `covariates.csv` + `data.csv`): files with the same row count and no overlapping column names are merged side-by-side; otherwise files are row-stacked

Supported column types: `number`, `boolean` (0/1 or true/false), `string`.

## Parameters

Edit `test_data/server/parameters.json`:

```json
{
    "decimal_places": 4,
    "num_bins": 10,
    "security_level": "low"
}
```

| Parameter | Type | Description | Default |
|---|---|---|---|
| `decimal_places` | integer | Decimal places to round all computed statistics | `4` |
| `num_bins` | integer | Number of equal-width histogram bins per numeric column | `10` |
| `security_level` | `"low"` / `"high"` | When `"high"`, the Global Descriptive Statistics, Correlation Structure, and Site Effects sections are omitted from the HTML report | `"low"` |

## Output Files

Results appear in `test_output/` at each site:

| File | Description |
|---|---|
| `local_csv_analysis.json` | Per-site intermediate results (round 1) |
| `global_csv_report.json` | Server-aggregated global report (round 1) |
| `local_histograms.json` | Per-site histogram counts (round 2) |
| `histogram_report.json` | Server-aggregated histogram metrics (round 2) |
| `index.html` | Self-contained interactive HTML report (round 2) |

The HTML report contains the following sections (subject to `security_level`):

- **Summary Header** — total sites, subjects, universal columns, and site colour legend. Always shown.
- **Data Structure** — site × column presence matrix with parallelism callouts. Always shown.
- **Global Descriptive Statistics** — per-column cards with per-site and pooled values. Shown when `security_level` is `"low"`.
- **Correlation Structure** — per-site and global Pearson correlation matrices computed from federated cross-product sums. Shown when `security_level` is `"low"` and ≥ 2 universal numeric columns exist.
- **Site Effects** — z-score table comparing each site's column means to the global mean, flagging sites that deviate by more than 0.5 standard deviations. Shown when `security_level` is `"low"`.
- **Sample Size Guidance** — subjects-per-predictor ratio cards per site. Always shown.
- **Histogram Compatibility** — overlapping distribution curves with Overlap Coefficient, KL Divergence, and Chi-Squared homogeneity metrics. Always shown.

## Running

```bash
pip install nvflare
python debug.py
```
