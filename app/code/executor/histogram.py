import csv
import os
from typing import Dict, Any, List, Optional


def compute_local_histograms(
    data_dir: str,
    bin_config: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Given a bin_config dict mapping column name -> list of bin edges,
    read all CSVs in data_dir and return per-column histogram counts.

    bin_config example:
    {
      "age":    {"edges": [20, 30, 40, 50, 60, 70], "type": "number"},
      "weight_kg": {"edges": [50, 65, 80, 95, 110], "type": "number"}
    }

    Returns:
    {
      "age": {"edges": [...], "counts": [n0, n1, ...], "missing": k},
      ...
    }
    """
    csv_files = [f for f in os.listdir(data_dir) if f.lower().endswith(".csv")]
    if not csv_files:
        raise FileNotFoundError(f"No CSV files found in {data_dir}")

    # Accumulate raw values per column
    col_values: Dict[str, list] = {col: [] for col in bin_config}

    for fname in sorted(csv_files):
        fpath = os.path.join(data_dir, fname)
        with open(fpath, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                for col in bin_config:
                    if col in row:
                        col_values[col].append(row[col])

    histograms = {}
    for col, cfg in bin_config.items():
        edges = cfg["edges"]
        col_type = cfg.get("type", "number")
        values = col_values.get(col, [])

        # Skip columns that are entirely absent from this site's data
        if not values:
            continue

        if col_type == "number":
            counts, missing = _bin_numeric(values, edges)
        else:
            # categorical: edges treated as category labels
            counts, missing = _bin_categorical(values, edges)

        histograms[col] = {
            "edges": edges,
            "counts": counts,
            "missing": missing,
            "n_bins": len(counts),
        }

    return histograms


def _bin_numeric(raw_values: list, edges: list):
    """
    Bin numeric values into (len(edges) - 1) bins.
    Bins are half-open [left, right), last bin is [left, right].
    Returns (counts list, missing_count).
    """
    n_bins = len(edges) - 1
    counts = [0] * n_bins
    missing = 0

    for v in raw_values:
        if v is None or str(v).strip() == "":
            missing += 1
            continue
        try:
            fv = float(str(v).strip())
        except ValueError:
            missing += 1
            continue

        placed = False
        for i in range(n_bins):
            left = edges[i]
            right = edges[i + 1]
            # Last bin: inclusive on both ends
            if i == n_bins - 1:
                if left <= fv <= right:
                    counts[i] += 1
                    placed = True
                    break
            else:
                if left <= fv < right:
                    counts[i] += 1
                    placed = True
                    break

        if not placed:
            missing += 1  # Out of range

    return counts, missing


def _bin_categorical(raw_values: list, categories: list):
    """
    Count occurrences of each category label.
    Values not in categories are counted as missing.
    """
    counts = [0] * len(categories)
    missing = 0
    cat_index = {str(c): i for i, c in enumerate(categories)}

    for v in raw_values:
        if v is None or str(v).strip() == "":
            missing += 1
            continue
        key = str(v).strip()
        if key in cat_index:
            counts[cat_index[key]] += 1
        else:
            missing += 1

    return counts, missing
