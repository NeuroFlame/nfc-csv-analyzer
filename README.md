# NVFlare CSV Analyzer Computation

A federated computation built on the NVFlare/NeuroFLAME boilerplate that performs privacy-preserving statistical analysis across multiple sites CSV data without any raw data leaving each site.

## What It Does

Each participating site reads its local CSV file(s), computes per-column statistics locally, and sends only aggregated summaries (not raw rows) to the server. The server merges all site results into a single global report.

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

Privacy note: Global mean and variance are computed exactly using sufficient statistics. Median and quartiles are reported per-site only.

## Computation Flow

1. Server broadcasts ANALYZE_CSV task to all sites
2. Each site reads local CSV(s), computes column-level stats, returns summary (no raw data)
3. Server aggregates all site results into a global report
4. Server broadcasts ACCEPT_GLOBAL_REPORT back to sites for local saving

## Input Format

Place one or more .csv files (with header row) in each site data directory. Supported column types: numeric, string/categorical, boolean (0/1 or true/false).

## Parameters

Edit test_data/server/parameters.json:

```json
{
    "decimal_places": 4
}
```

## Running

```bash
pip install nvflare
python debug.py
```

Results appear in test_output/ as local_csv_analysis.json and global_csv_report.json per site.
