"""Compute per-column statistics for one site's CSV files."""

import logging
import math
from typing import Any, Dict, List, Optional

from .types import CsvTable


def infer_type(values: list) -> str:
    """Infer the dominant data type of a column's values."""
    filtered = [v for v in values if v is not None and v != ""]

    if not filtered:
        return "empty"

    # Check for boolean (only 0/1 or True/False)
    if all(
        str(v).strip() in {"0", "1", "true", "false", "True", "False", "TRUE", "FALSE"}
        for v in filtered
    ):
        return "boolean"

    # Try numeric
    numeric_count = 0
    for v in filtered:
        try:
            float(str(v).strip())
            numeric_count += 1
        except (ValueError, TypeError):
            pass

    if numeric_count == len(filtered):
        return "number"

    return "string"


def parse_value(v: str, inferred_type: str):
    """Parse a raw CSV string value into the appropriate Python type."""
    if v is None or str(v).strip() == "":
        return None
    v = str(v).strip()
    if inferred_type == "number":
        try:
            return float(v)
        except ValueError:
            return None
    if inferred_type == "boolean":
        return v.lower() in ("1", "true")
    return v


def compute_percentile(sorted_vals: list, p: float) -> float:
    """Compute the p-th percentile (0-100) of a sorted list."""
    if not sorted_vals:
        return None
    n = len(sorted_vals)
    idx = (p / 100) * (n - 1)
    lower = int(idx)
    upper = lower + 1
    if upper >= n:
        return sorted_vals[-1]
    frac = idx - lower
    return sorted_vals[lower] * (1 - frac) + sorted_vals[upper] * frac


def analyze_csv_tables(
    tables: List[CsvTable],
    decimal_places: int = 4,
    logger: Optional[logging.Logger] = None,
) -> Dict[str, Any]:
    """Compute per-column statistics over a site's CSV files.

    Merge strategy:
      - If all files share the same row count AND have no overlapping column
        names, they are treated as a row-aligned split dataset (e.g. a
        covariates.csv + data.csv pair) and merged side-by-side.
      - Otherwise files are stacked row-wise (original behaviour for
        genuinely multi-file datasets with the same schema).
    """
    logger = logger or logging.getLogger(__name__)
    file_names = [t.name for t in tables]
    loaded = [
        {"fname": t.name, "rows": t.rows, "fieldnames": t.fieldnames} for t in tables
    ]

    # Decide merge strategy
    row_counts = [len(d["rows"]) for d in loaded]
    all_cols = [set(d["fieldnames"]) for d in loaded]
    same_length = len(set(row_counts)) == 1
    no_overlap = sum(len(c) for c in all_cols) == len(
        set(col for cols in all_cols for col in cols)
    )
    side_by_side = same_length and no_overlap and len(loaded) > 1

    combined_columns: Dict[str, list] = {}
    total_rows = 0

    if side_by_side:
        # Row-aligned merge: each row index is the same subject
        total_rows = row_counts[0]
        for d in loaded:
            for col in d["fieldnames"]:
                combined_columns[col] = [row.get(col, "") for row in d["rows"]]
        logger.info(
            f"Side-by-side merge of {len(loaded)} files "
            f"({total_rows} subjects, {len(combined_columns)} total columns): "
            + ", ".join(d["fname"] for d in loaded)
        )
    else:
        # Stack rows (original behaviour)
        for d in loaded:
            total_rows += len(d["rows"])
            for col in d["fieldnames"]:
                if col not in combined_columns:
                    combined_columns[col] = []
                combined_columns[col].extend([row.get(col, "") for row in d["rows"]])
        logger.info(
            f"Row-stacked merge of {len(loaded)} files "
            f"({total_rows} total rows): " + ", ".join(d["fname"] for d in loaded)
        )

    column_stats = {}
    bad_row_counts: Dict[str, int] = {}

    for col, raw_values in combined_columns.items():
        inferred_type = infer_type(raw_values)
        parsed = [parse_value(v, inferred_type) for v in raw_values]

        nan_count = sum(1 for v in parsed if v is None)
        non_null = [v for v in parsed if v is not None]
        unique_count = len(set(str(v) for v in non_null))

        # Type mismatch: values that couldn't be parsed to the inferred type
        type_mismatch_count = 0
        for raw, p in zip(raw_values, parsed, strict=False):
            if raw is not None and str(raw).strip() != "" and p is None:
                type_mismatch_count += 1

        bad_row_counts[col] = type_mismatch_count + nan_count

        if inferred_type == "number" and non_null:
            numeric_vals = [v for v in non_null if v is not None]
            sorted_vals = sorted(numeric_vals)
            n = len(numeric_vals)
            mean = sum(numeric_vals) / n
            variance = sum((v - mean) ** 2 for v in numeric_vals) / n if n > 1 else 0.0
            std_dev = math.sqrt(variance)
            median = compute_percentile(sorted_vals, 50)
            q1 = compute_percentile(sorted_vals, 25)
            q3 = compute_percentile(sorted_vals, 75)
            col_min = sorted_vals[0]
            col_max = sorted_vals[-1]

            column_stats[col] = {
                "inferred_type": inferred_type,
                "count": n,
                "nan_count": nan_count,
                "type_mismatch_count": type_mismatch_count,
                "unique_count": unique_count,
                "sum": round(sum(numeric_vals), decimal_places),
                "sum_of_squares": round(
                    sum(v**2 for v in numeric_vals), decimal_places
                ),
                "mean": round(mean, decimal_places),
                "variance": round(variance, decimal_places),
                "std_dev": round(std_dev, decimal_places),
                "median": round(median, decimal_places),
                "q1": round(q1, decimal_places),
                "q3": round(q3, decimal_places),
                "min": round(col_min, decimal_places),
                "max": round(col_max, decimal_places),
            }
        else:
            column_stats[col] = {
                "inferred_type": inferred_type,
                "count": len(non_null),
                "nan_count": nan_count,
                "type_mismatch_count": type_mismatch_count,
                "unique_count": unique_count,
                "unique_values": sorted(
                    set(
                        str(v).strip()
                        for v in raw_values
                        if v is not None and str(v).strip() != ""
                    )
                ),
                "sum": None,
                "sum_of_squares": None,
                "mean": None,
                "variance": None,
                "std_dev": None,
                "median": None,
                "q1": None,
                "q3": None,
                "min": None,
                "max": None,
            }

    # Cross-product sums for numeric universal columns (needed for federated correlation)
    numeric_cols = [
        col
        for col, stats in column_stats.items()
        if stats.get("inferred_type") == "number"
    ]
    cross_products = {}
    if len(numeric_cols) >= 2:
        # Build aligned numeric value arrays (using parsed values, NaN-excluded rows excluded pairwise)
        col_parsed = {}
        for col in numeric_cols:
            raw = combined_columns.get(col, [])
            col_parsed[col] = [parse_value(v, "number") for v in raw]

        max(len(v) for v in col_parsed.values()) if col_parsed else 0
        for i, c1 in enumerate(numeric_cols):
            for c2 in numeric_cols[i:]:
                v1 = col_parsed[c1]
                v2 = col_parsed[c2]
                pairs = [
                    (a, b)
                    for a, b in zip(v1, v2, strict=False)
                    if a is not None and b is not None
                ]
                if pairs:
                    n = len(pairs)
                    sum1 = sum(a for a, _ in pairs)
                    sum2 = sum(b for _, b in pairs)
                    sum12 = sum(a * b for a, b in pairs)
                    cross_products[f"{c1}|||{c2}"] = {
                        "n": n,
                        "sum1": round(sum1, decimal_places),
                        "sum2": round(sum2, decimal_places),
                        "sum_sq1": round(sum(a * a for a, _ in pairs), decimal_places),
                        "sum_sq2": round(sum(b * b for _, b in pairs), decimal_places),
                        "sum12": round(sum12, decimal_places),
                    }

    return {
        "total_rows": total_rows,
        "total_columns": len(combined_columns),
        "file_names": file_names,
        "column_stats": column_stats,
        "cross_products": cross_products,
    }
