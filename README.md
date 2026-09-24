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

## Architecture

This computation is authored against [computation-nvflare-boilerplate](https://github.com/NeuroFlame/computation-nvflare-boilerplate).
Only `app/code/computation/` is computation-specific; `app/code/framework/`,
`app/code/runtime/`, `app/config/`, `system/`, and the tooling scripts are
boilerplate-managed and are updated with `scripts/migrate_computation.py`
from the boilerplate repository.

The workflow is declared in `app/code/computation/spec.py`:

| Step | Runs on | Function | Purpose |
|---|---|---|---|
| `local_step` | sites | `inputs.load_site_tables` → `local_math.analyze_csv` | Validate parameters, read the site's CSVs, compute column stats and cross-product sums (no raw data) |
| `remote_step` | central | `remote_math.build_global_csv_report` | Pool statistics into the global report, classify column parallelism, and generate histogram bins for every universal column |
| `local_step` | sites | `local_math.compute_histograms` | Count local values into the shared bins |
| `remote_step` | central | `remote_math.build_histogram_report` | Compute compatibility metrics and regression-readiness analysis, and render the HTML report |
| `site_output_step` | sites | `results.build_site_outputs` | Write the local and global JSON results and `index.html` |

| Module | Role |
|---|---|
| `computation/csv_analysis.py` | Type inference and per-column statistics |
| `computation/histograms.py` | Local histogram binning |
| `computation/compatibility.py` | Overlap, KL divergence and chi-squared homogeneity |
| `computation/regression.py` | Federated correlations, site effects, sample size guidance |
| `computation/report.py` | Self-contained HTML report |

Numeric columns are binned with `num_bins` equal-width bins between the global
min and max; boolean and string columns are binned by category label. When no
column is universal, the histogram round still runs and the report explains
that no histograms were compared.

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

Results appear in `test_output/simulate_job/<site>/` for each site:

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

Run the NVFlare simulator in Docker against `test_data/`:

```bash
./run_local_simulation.sh site1,site2,site3            # builds Dockerfile-dev, then simulates
./run_local_simulation.sh site1,site2,site3 --no-build # reuse the image after code-only changes
```

Lint, format-check, compile, and unit tests:

```bash
make check
```

For an interactive shell in the dev image, use `./dockerRun.sh`.

Publishing production images uses `./dockerPush.sh` (a wrapper for
`scripts/publish_computation_image.py`) with the image coordinates in
`.neuroflame.json`.
