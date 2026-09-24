"""Federated regression-readiness analysis.

Computes:
  1. Correlation matrices — per site and global, from cross-product sufficient statistics
  2. Site effect indicators — z-score of each site's mean vs global mean
  3. Sample size guidance — subjects-per-predictor ratio per site.
"""

import math
from typing import Any, Dict, List, Optional


def compute_regression_analysis(
    site_results: Dict[str, Dict],
    global_report: Dict[str, Any],
    decimal_places: int = 4,
) -> Dict[str, Any]:
    """Summarize correlations, site effects and sample sizes for universal columns."""
    column_stats = global_report.get("column_stats", {})
    parallelism = global_report.get("column_parallelism", {})
    universal = set(parallelism.get("universal_columns", []))
    all_sites = sorted(site_results.keys())

    numeric_universal = [
        col
        for col in sorted(universal)
        if column_stats.get(col, {}).get("inferred_type") == "number"
    ]

    correlations = _compute_correlations(
        site_results, numeric_universal, all_sites, decimal_places
    )
    site_effects = _compute_site_effects(
        column_stats, numeric_universal, all_sites, decimal_places
    )
    sample_guidance = _compute_sample_guidance(
        site_results, numeric_universal, all_sites
    )

    return {
        "numeric_columns": numeric_universal,
        "correlations": correlations,
        "site_effects": site_effects,
        "sample_guidance": sample_guidance,
    }


# ── 1. Federated Correlation ──────────────────────────────────────────────────


def _pearson_from_sums(n, sum1, sum2, sum_sq1, sum_sq2, sum12) -> Optional[float]:
    """Compute Pearson r from sufficient statistics."""
    if n < 2:
        return None
    mean1 = sum1 / n
    mean2 = sum2 / n
    cov = sum12 / n - mean1 * mean2
    var1 = sum_sq1 / n - mean1**2
    var2 = sum_sq2 / n - mean2**2
    denom = math.sqrt(max(var1, 0) * max(var2, 0))
    if denom == 0:
        return None
    return max(-1.0, min(1.0, cov / denom))


def _compute_correlations(
    site_results: Dict[str, Dict],
    numeric_cols: List[str],
    all_sites: List[str],
    decimal_places: int,
) -> Dict[str, Any]:
    if len(numeric_cols) < 2:
        return {"available": False, "reason": "Fewer than 2 universal numeric columns."}

    # Per-site correlation matrices
    per_site = {}
    for site in all_sites:
        cp = site_results[site].get("cross_products", {})
        matrix = {}
        for c1 in numeric_cols:
            matrix[c1] = {}
            for c2 in numeric_cols:
                if c1 == c2:
                    matrix[c1][c2] = 1.0
                    continue
                key = f"{c1}|||{c2}" if f"{c1}|||{c2}" in cp else f"{c2}|||{c1}"
                if key not in cp:
                    matrix[c1][c2] = None
                    continue
                s = cp[key]
                # Ensure c1 is "sum1" side
                if key.startswith(c1):
                    r = _pearson_from_sums(
                        s["n"],
                        s["sum1"],
                        s["sum2"],
                        s["sum_sq1"],
                        s["sum_sq2"],
                        s["sum12"],
                    )
                else:
                    r = _pearson_from_sums(
                        s["n"],
                        s["sum2"],
                        s["sum1"],
                        s["sum_sq2"],
                        s["sum_sq1"],
                        s["sum12"],
                    )
                matrix[c1][c2] = round(r, decimal_places) if r is not None else None
        per_site[site] = matrix

    # Global correlation — pool cross-products weighted by n
    pooled_cp = {}
    for site in all_sites:
        for key, s in site_results[site].get("cross_products", {}).items():
            if key not in pooled_cp:
                pooled_cp[key] = {
                    "n": 0,
                    "sum1": 0,
                    "sum2": 0,
                    "sum_sq1": 0,
                    "sum_sq2": 0,
                    "sum12": 0,
                }
            for k in pooled_cp[key]:
                pooled_cp[key][k] += s[k]

    global_matrix = {}
    for c1 in numeric_cols:
        global_matrix[c1] = {}
        for c2 in numeric_cols:
            if c1 == c2:
                global_matrix[c1][c2] = 1.0
                continue
            key = f"{c1}|||{c2}" if f"{c1}|||{c2}" in pooled_cp else f"{c2}|||{c1}"
            if key not in pooled_cp:
                global_matrix[c1][c2] = None
                continue
            s = pooled_cp[key]
            if key.startswith(c1):
                r = _pearson_from_sums(
                    s["n"], s["sum1"], s["sum2"], s["sum_sq1"], s["sum_sq2"], s["sum12"]
                )
            else:
                r = _pearson_from_sums(
                    s["n"], s["sum2"], s["sum1"], s["sum_sq2"], s["sum_sq1"], s["sum12"]
                )
            global_matrix[c1][c2] = round(r, decimal_places) if r is not None else None

    return {
        "available": True,
        "columns": numeric_cols,
        "per_site": per_site,
        "global": global_matrix,
    }


# ── 2. Site Effect Indicators ─────────────────────────────────────────────────


def _compute_site_effects(
    column_stats: Dict[str, Any],
    numeric_cols: List[str],
    all_sites: List[str],
    decimal_places: int,
) -> Dict[str, Any]:
    results = {}
    for col in numeric_cols:
        stats = column_stats.get(col, {})
        global_mean = stats.get("global_mean")
        global_std = stats.get("global_std_dev")
        per_site = stats.get("per_site", {})

        if global_mean is None or not global_std or global_std == 0:
            results[col] = {"available": False}
            continue

        site_zscores = {}
        for site in all_sites:
            ps = per_site.get(site, {})
            site_mean = ps.get("mean")
            if site_mean is None:
                site_zscores[site] = None
                continue
            z = (site_mean - global_mean) / global_std
            site_zscores[site] = round(z, decimal_places)

        # Flag if any site z-score exceeds threshold
        flagged = any(abs(z) >= 0.5 for z in site_zscores.values() if z is not None)
        max_z = max(
            (abs(z) for z in site_zscores.values() if z is not None), default=None
        )

        results[col] = {
            "available": True,
            "global_mean": global_mean,
            "global_std": global_std,
            "site_zscores": site_zscores,
            "flagged": flagged,
            "max_abs_z": round(max_z, decimal_places) if max_z is not None else None,
        }

    return results


# ── 3. Sample Size Guidance ───────────────────────────────────────────────────


def _compute_sample_guidance(
    site_results: Dict[str, Dict],
    numeric_cols: List[str],
    all_sites: List[str],
) -> Dict[str, Any]:
    n_predictors = len(numeric_cols)
    # Rule of thumb: 10 obs per predictor (conservative), 20 (liberal)
    min_recommended = n_predictors * 10
    ideal_recommended = n_predictors * 20

    site_ns = {}
    for site in all_sites:
        site_ns[site] = site_results[site].get("total_rows", 0)

    total_n = sum(site_ns.values())

    site_guidance = {}
    for site, n in site_ns.items():
        if n == 0:
            ratio = None
            status = "unknown"
        else:
            ratio = round(n / n_predictors, 1) if n_predictors else None
            if ratio is None:
                status = "unknown"
            elif ratio < 10:
                status = "low"
            elif ratio < 20:
                status = "adequate"
            else:
                status = "good"
        site_guidance[site] = {
            "n": n,
            "ratio": ratio,
            "status": status,
        }

    total_ratio = round(total_n / n_predictors, 1) if n_predictors else None
    if total_ratio is None:
        total_status = "unknown"
    elif total_ratio < 10:
        total_status = "low"
    elif total_ratio < 20:
        total_status = "adequate"
    else:
        total_status = "good"

    return {
        "n_predictors": n_predictors,
        "min_recommended_n": min_recommended,
        "ideal_recommended_n": ideal_recommended,
        "per_site": site_guidance,
        "total_n": total_n,
        "total_ratio": total_ratio,
        "total_status": total_status,
    }
