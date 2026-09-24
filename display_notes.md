### Overview

This computation performs a federated CSV analysis on datasets provided in `.csv` format from multiple sites. It automatically discovers all columns, infers their data types, and computes descriptive statistics locally at each site. The server aggregates these into a global report and auto-generates histogram bin edges from the global data range. Sites then compute local histogram counts which are aggregated to produce distribution compatibility metrics across sites. The final output is an interactive HTML report summarising data structure, descriptive statistics, and histogram compatibility for all columns. No raw subject-level data leaves any site at any point.

### Example Settings

```json
{
    "decimal_places": 4,
    "num_bins": 10,
    "security_level": "low"
}
```

### Settings Specification

| Variable Name | Type | Description | Allowed Options | Default | Required |
| --- | --- | --- | --- | --- | --- |
| `decimal_places` | `integer` | Number of decimal places to round all computed statistics to. | any non-negative integer | `4` | ❌ false |
| `num_bins` | `integer` | Number of histogram bins to use for each numeric column. Bin edges are auto-generated from the global min/max discovered in round 1. | any positive integer | `10` | ❌ false |
| `security_level` | `string` | Controls how much aggregated information is included in the output report. When set to `high`, the Global Descriptive Statistics section (which includes pooled means, standard deviations, and per-site breakdowns) is omitted from the report. Histogram compatibility charts and metrics are always shown regardless of this setting. | `low`, `high` | `low` | ❌ false |

### Input Description

One or more `.csv` files are required per site. Files must be placed in the site's data directory. The computation supports two file layouts:

**Single-file layout**: All columns (covariates and measurements) are contained in a single CSV file.

**Split-file layout** (e.g. `covariates.csv` + `data.csv`): Two or more CSV files where each file has the same number of rows and no overlapping column names. The computation detects this pattern automatically and merges the files side-by-side, treating each row index as the same subject across files.

If the files do not meet the side-by-side criteria (i.e. they have overlapping column names or different row counts), the computation falls back to row-stacking, appending all rows across files as if they were a single dataset.

**General structure for each CSV file**:

    <Column_1>,<Column_2>,...,<Column_N>
    <value_1>,<value_2>,...,<value_N>
    <value_1>,<value_2>,...,<value_N>
    ...

- **Format**: CSV (Comma-Separated Values)
- **Headers**: Each file must include a header row with column names.
- **Rows**: Each row represents one subject or observation.
- **Types**: Column types are inferred automatically. Supported types are `number`, `boolean`, and `string`.

### Algorithm Description

The computation runs in two federated rounds:

1. **Round 1 — Local CSV Analysis (per site)**:
    - Each site reads all CSV files in its data directory and merges them using the side-by-side or row-stacking strategy described above.
    - Per-column statistics are computed locally: count, missing value count, type mismatch count, unique value count, mean, variance, standard deviation, median, Q1, Q3, min, and max for numeric columns; count, missing, and unique count for non-numeric columns.
    - Only sufficient statistics (sums, sums of squares, counts, and pairwise cross-product sums for all numeric column pairs) are shared — no raw subject data leaves the site.
    - The server aggregates these into a **global report** containing pooled statistics and a column parallelism analysis (classifying each column as `universal`, `partial`, or `type_conflict` across sites).
    - The global report is broadcast back to all sites.

2. **Round 2 — Histogram Computation (per site)**:
    - The server auto-generates histogram bins for every universal column: numeric columns use `num_bins` equal-width bins between the global min and max from round 1; boolean and string columns use their category labels.
    - Each site counts its local values into these shared bin edges and returns the counts.
    - The server aggregates the per-site counts and computes three compatibility metrics per column: **Overlap Coefficient**, **KL Divergence**, and a **Chi-Squared homogeneity test**.
    - The final HTML report is generated and broadcast to all sites. The contents of the report are determined by the `security_level` parameter.

### Assumptions

- All CSV files at each site are UTF-8 encoded and include a valid header row.
- For split-file layouts (e.g. `covariates.csv` + `data.csv`), all files must have the same number of rows, with each row index corresponding to the same subject.
- Column names do not need to be specified in `parameters.json` — the computation discovers them automatically from the data files.
- The computation is run in a federated environment where each site contributes valid data.
- Histogram compatibility metrics are computed only for columns that are `universal` (present at all sites with the same inferred type). Partial or type-conflicting columns are flagged in the report but excluded from histogram analysis.

### Output Description

- **Output files: `local_csv_analysis.json`, `global_csv_report.json`, `local_histograms.json`, `histogram_report.json`, `index.html`**

- `local_csv_analysis.json` and `local_histograms.json` contain site-level intermediate results and are saved at each site.
- `global_csv_report.json` and `histogram_report.json` contain the server-aggregated results and are saved at each site upon receipt.
- `index.html` is a self-contained interactive HTML report saved at each site, viewable in any browser.

The HTML report is divided into the following sections, subject to the `security_level` setting:

- **Summary Header**: Total sites, total subjects, universal column count, and a per-site colour legend. Always shown.
- **Data Structure**: A site × column presence matrix showing which columns exist at which sites and their inferred types, with callout cards flagging partial or type-conflicting columns. Always shown.
- **Global Descriptive Statistics**: Per-column cards showing per-site and globally pooled values for count, mean, standard deviation, min, median, and max (numeric columns), or count, unique values, and missing count (non-numeric columns). **Shown only when `security_level` is `low`.**
- **Correlation Structure**: Per-site and global Pearson correlation matrices computed from the federated cross-product sums — no raw data exchanged. Colour-coded by direction and strength. **Shown only when `security_level` is `low` and at least 2 universal numeric columns are present.**
- **Site Effects**: A table of z-scores comparing each site's column mean to the global mean, with sites flagged when their mean deviates by more than 0.5 standard deviations. Intended as an exploratory indicator rather than a formal test. **Shown only when `security_level` is `low`.**
- **Sample Size Guidance**: Per-site and combined subjects-per-predictor ratio cards, rated Good / Adequate / Low based on the 10× and 20× rules of thumb. Always shown.
- **Histogram Compatibility**: Smooth overlapping distribution curves per column with three compatibility metrics. Always shown.
    - **Overlap Coefficient**: Fraction of distributional overlap between sites (compatible if ≥ 0.70).
    - **KL Divergence**: Information-theoretic divergence between site and global distributions (compatible if ≤ 0.10).
    - **Chi-Squared Homogeneity Test**: Statistical test of whether all sites draw from the same distribution, reported with χ² statistic, degrees of freedom, p-value, and a significant/not-significant label (compatible if p ≥ 0.05).
    - A column is marked **Compatible** only if all three criteria are met simultaneously.
