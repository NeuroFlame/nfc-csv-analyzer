"""Aggregate site CSV analyses and histograms into federated reports.

Numeric columns get exact global statistics from sufficient statistics
(count, sum, variance) so no raw data ever leaves a site.
"""

import math
from typing import Any, Dict

from framework import with_state

from .compatibility import aggregate_histograms
from .regression import compute_regression_analysis
from .report import generate_histogram_report_html
from .types import GlobalCsvRound, HistogramRound, RemoteState


def build_global_csv_report(
    site_results: Dict[str, Dict[str, Any]],
    decimal_places: int = 4,
    num_bins: int = 10,
):
    """Combine the per-site CSV analyses and choose the histogram bins."""
    site_results = dict(sorted(site_results.items()))
    global_report = build_global_report(site_results, decimal_places)
    bin_config = build_bin_config(global_report, num_bins)
    return with_state(
        GlobalCsvRound(global_report=global_report, bin_config=bin_config),
        RemoteState(site_results=site_results, global_report=global_report),
    )


def build_histogram_report(
    site_histograms: Dict[str, Dict[str, Any]],
    state: RemoteState,
    decimal_places: int = 4,
    security_level: str = "low",
) -> HistogramRound:
    """Score cross-site histogram compatibility and render the HTML report."""
    site_histograms = dict(sorted(site_histograms.items()))
    histogram_report = aggregate_histograms(site_histograms, decimal_places)
    regression_data = compute_regression_analysis(
        state.site_results, state.global_report, decimal_places
    )
    html_report = generate_histogram_report_html(
        histogram_report,
        state.global_report,
        security_level=security_level,
        regression_data=regression_data,
    )
    return HistogramRound(histogram_report=histogram_report, html_report=html_report)


def build_bin_config(global_report: Dict[str, Any], num_bins: int = 10) -> dict:
    """Auto-generate bin config for every universal column.

    - Numeric: equally spaced edges between global min and max.
    - Boolean/String: unique category labels discovered from per-site stats.

    Columns that are partial or have type conflicts are skipped.
    """
    bin_config = {}
    column_stats = global_report.get("column_stats", {})
    parallelism = global_report.get("column_parallelism", {})
    universal = set(parallelism.get("universal_columns", []))

    for col, stats in column_stats.items():
        if col not in universal:
            continue

        inferred_type = stats.get("inferred_type")

        if inferred_type == "number":
            col_min = stats.get("global_min")
            col_max = stats.get("global_max")
            if col_min is None or col_max is None or col_min == col_max:
                continue
            step = (col_max - col_min) / num_bins
            edges = [round(col_min + i * step, 6) for i in range(num_bins + 1)]
            bin_config[col] = {"edges": edges, "type": "number"}

        elif inferred_type in ("boolean", "string"):
            categories = stats.get("unique_values_union", None)
            if not categories:
                # Build from per-site unique value lists if present
                cat_set = set()
                for site_stats in stats.get("per_site", {}).values():
                    for v in site_stats.get("unique_values", []):
                        cat_set.add(str(v))
                categories = sorted(cat_set)
            if categories:
                bin_config[col] = {"edges": categories, "type": "categorical"}

    return bin_config


def build_global_report(
    site_results: Dict[str, Dict[str, Any]], decimal_places: int = 4
) -> Dict[str, Any]:
    """Build the federated global CSV report from per-site analyses."""
    if not site_results:
        return {}

    total_rows = sum(r.get("total_rows", 0) for r in site_results.values())
    all_files = []
    for r in site_results.values():
        all_files.extend(r.get("file_names", []))

    all_columns = set()
    for r in site_results.values():
        all_columns.update(r.get("column_stats", {}).keys())

    aggregated_columns = {}
    for col in sorted(all_columns):
        col_stats_per_site = {}
        for site_name, r in site_results.items():
            cs = r.get("column_stats", {}).get(col)
            if cs:
                col_stats_per_site[site_name] = cs

        if not col_stats_per_site:
            continue

        aggregated_columns[col] = _aggregate_column(col_stats_per_site, decimal_places)

    return {
        "total_sites": len(site_results),
        "site_names": sorted(site_results.keys()),
        "total_rows": total_rows,
        "total_columns": len(aggregated_columns),
        "files_analyzed": sorted(set(all_files)),
        "column_stats": aggregated_columns,
        "column_parallelism": _build_column_parallelism(site_results, all_columns),
        "per_site_summary": {
            site: {
                "total_rows": r.get("total_rows", 0),
                "total_columns": r.get("total_columns", 0),
                "files": r.get("file_names", []),
            }
            for site, r in site_results.items()
        },
    }


def _build_column_parallelism(
    site_results: Dict[str, Dict[str, Any]], all_columns: set
) -> Dict[str, Any]:
    """Classify every column seen across sites.

    - universal:     present in all sites with consistent inferred type
    - partial:       present in some but not all sites (regardless of type)
    - type_conflict: present in multiple sites but with mismatched inferred types

    Also builds a site x column presence matrix for the HTML report.
    """
    all_sites = sorted(site_results.keys())
    n_sites = len(all_sites)

    # Build presence matrix: col -> {site -> inferred_type or None}
    presence: Dict[str, Dict[str, Any]] = {}
    for col in sorted(all_columns):
        presence[col] = {}
        for site in all_sites:
            cs = site_results[site].get("column_stats", {}).get(col)
            presence[col][site] = cs.get("inferred_type") if cs else None

    columns_by_status: Dict[str, list] = {
        "universal": [],
        "partial": [],
        "type_conflict": [],
    }
    column_details: Dict[str, Dict] = {}

    for col, site_types in presence.items():
        present_sites = [s for s, t in site_types.items() if t is not None]
        missing_sites = [s for s, t in site_types.items() if t is None]
        types_present = list({t for t in site_types.values() if t is not None})

        if len(present_sites) == n_sites and len(types_present) == 1:
            status = "universal"
        elif len(present_sites) > 1 and len(types_present) > 1:
            status = "type_conflict"
        else:
            status = "partial"

        columns_by_status[status].append(col)
        column_details[col] = {
            "status": status,
            "present_in": present_sites,
            "missing_from": missing_sites,
            "types_by_site": site_types,
        }

    return {
        "all_sites": all_sites,
        "presence_matrix": presence,
        "column_details": column_details,
        "universal_columns": columns_by_status["universal"],
        "partial_columns": columns_by_status["partial"],
        "type_conflict_columns": columns_by_status["type_conflict"],
        "summary": {
            "n_universal": len(columns_by_status["universal"]),
            "n_partial": len(columns_by_status["partial"]),
            "n_type_conflict": len(columns_by_status["type_conflict"]),
        },
    }


def _aggregate_column(
    col_stats_per_site: Dict[str, Dict], decimal_places: int
) -> Dict[str, Any]:
    """Combine one column's per-site statistics into global statistics."""
    type_votes = {}
    for cs in col_stats_per_site.values():
        t = cs.get("inferred_type", "string")
        type_votes[t] = type_votes.get(t, 0) + 1
    inferred_type = max(type_votes, key=type_votes.get)

    total_count = sum(cs.get("count", 0) for cs in col_stats_per_site.values())
    total_nan = sum(cs.get("nan_count", 0) for cs in col_stats_per_site.values())
    total_mismatch = sum(
        cs.get("type_mismatch_count", 0) for cs in col_stats_per_site.values()
    )
    total_unique = sum(cs.get("unique_count", 0) for cs in col_stats_per_site.values())

    per_site_info = {}
    for site, cs in col_stats_per_site.items():
        per_site_info[site] = {
            "count": cs.get("count"),
            "nan_count": cs.get("nan_count"),
            "type_mismatch_count": cs.get("type_mismatch_count"),
            "unique_count": cs.get("unique_count"),
        }
        if inferred_type == "number":
            per_site_info[site].update(
                {
                    "mean": cs.get("mean"),
                    "std_dev": cs.get("std_dev"),
                    "min": cs.get("min"),
                    "max": cs.get("max"),
                    "median": cs.get("median"),
                    "q1": cs.get("q1"),
                    "q3": cs.get("q3"),
                }
            )

    result = {
        "inferred_type": inferred_type,
        "total_count": total_count,
        "total_nan_count": total_nan,
        "total_type_mismatch_count": total_mismatch,
        "total_unique_count_sum": total_unique,
        "per_site": per_site_info,
    }

    if inferred_type in ("boolean", "string"):
        # Union of the category labels each site reported.
        cat_set = set()
        for cs in col_stats_per_site.values():
            for v in cs.get("unique_values", []):
                cat_set.add(str(v))
        if not cat_set and inferred_type == "boolean":
            cat_set = {"0", "1"}
        if cat_set:
            result["unique_values_union"] = sorted(cat_set)

    if inferred_type == "number":
        total_sum = sum(cs.get("sum", 0) or 0 for cs in col_stats_per_site.values())
        global_mean = (total_sum / total_count) if total_count > 0 else None

        weighted_var_sum = 0.0
        for cs in col_stats_per_site.values():
            n_i = cs.get("count", 0) or 0
            var_i = cs.get("variance", 0) or 0
            mean_i = cs.get("mean") or 0
            if n_i > 0 and global_mean is not None:
                weighted_var_sum += (n_i - 1) * var_i + n_i * (
                    mean_i - global_mean
                ) ** 2

        global_variance = (
            weighted_var_sum / (total_count - 1) if total_count > 1 else 0.0
        )
        global_std_dev = math.sqrt(global_variance) if global_variance >= 0 else 0.0

        global_min = min(
            cs.get("min")
            for cs in col_stats_per_site.values()
            if cs.get("min") is not None
        )
        global_max = max(
            cs.get("max")
            for cs in col_stats_per_site.values()
            if cs.get("max") is not None
        )

        result.update(
            {
                "global_mean": round(global_mean, decimal_places)
                if global_mean is not None
                else None,
                "global_variance": round(global_variance, decimal_places),
                "global_std_dev": round(global_std_dev, decimal_places),
                "global_min": round(global_min, decimal_places)
                if global_min is not None
                else None,
                "global_max": round(global_max, decimal_places)
                if global_max is not None
                else None,
                "note_median": (
                    "Per-site medians/quartiles shown; global exact median "
                    "requires raw data exchange."
                ),
            }
        )

    return result
