"""Score how compatible each column's distribution is across sites."""

import math
from typing import Any, Dict, List, Optional, Tuple


def aggregate_histograms(
    site_histograms: Dict[str, Dict[str, Any]],
    decimal_places: int = 4,
) -> Dict[str, Any]:
    """Combine per-site histograms and score their compatibility.

    Computes:
    - Global combined histogram (summed counts)
    - Per-column compatibility metrics:
        * Overlap coefficient (pairwise and global)
        * KL divergence (per site vs global distribution)
        * Chi-squared test for homogeneity across sites
    Returns a report dict and also the bin_config for HTML rendering.
    """
    all_columns = set()
    for site_hists in site_histograms.values():
        all_columns.update(site_hists.keys())

    column_reports = {}
    for col in sorted(all_columns):
        site_col = {
            site: hists[col] for site, hists in site_histograms.items() if col in hists
        }
        if not site_col:
            continue
        column_reports[col] = _analyze_column_histograms(site_col, decimal_places)

    return {
        "sites": sorted(site_histograms.keys()),
        "columns": column_reports,
    }


def _analyze_column_histograms(
    site_col: Dict[str, Dict],
    decimal_places: int,
) -> Dict[str, Any]:
    # All sites should share the same edges
    first_site_data = list(site_col.values())[0]
    edges = first_site_data["edges"]
    # For numeric: n_bins = len(edges) - 1; for categorical edges ARE the bins
    sample_counts = first_site_data["counts"]
    n_bins = len(sample_counts)

    sites = sorted(site_col.keys())

    # Raw counts per site
    raw_counts = {site: site_col[site]["counts"] for site in sites}
    missing = {site: site_col[site].get("missing", 0) for site in sites}

    # Global summed counts
    global_counts = [0] * n_bins
    for counts in raw_counts.values():
        for i, c in enumerate(counts):
            global_counts[i] += c

    sum(global_counts)

    # Normalized distributions (proportions)
    def normalize(counts):
        total = sum(counts)
        if total == 0:
            return [0.0] * len(counts)
        return [c / total for c in counts]

    global_dist = normalize(global_counts)
    site_dists = {site: normalize(raw_counts[site]) for site in sites}

    # --- Overlap Coefficient ---
    # Between each pair of sites: sum(min(p_i, q_i))
    pairwise_overlap = {}
    for i, s1 in enumerate(sites):
        for s2 in sites[i + 1 :]:
            ov = sum(min(site_dists[s1][b], site_dists[s2][b]) for b in range(n_bins))
            pairwise_overlap[f"{s1}_vs_{s2}"] = round(ov, decimal_places)

    # Each site vs global
    site_vs_global_overlap = {}
    for site in sites:
        ov = sum(min(site_dists[site][b], global_dist[b]) for b in range(n_bins))
        site_vs_global_overlap[site] = round(ov, decimal_places)

    mean_pairwise = (
        round(sum(pairwise_overlap.values()) / len(pairwise_overlap), decimal_places)
        if pairwise_overlap
        else None
    )

    # --- KL Divergence (site || global) ---
    # KL(P||Q) = sum P(x) * log(P(x)/Q(x)), with smoothing to avoid log(0)
    epsilon = 1e-10

    def kl_divergence(p, q):
        return sum(
            p[i] * math.log((p[i] + epsilon) / (q[i] + epsilon))
            for i in range(len(p))
            if p[i] > 0
        )

    site_kl = {}
    for site in sites:
        kl = kl_divergence(site_dists[site], global_dist)
        site_kl[site] = round(kl, decimal_places)

    # Symmetric KL (Jensen-Shannon style): average of KL(P||Q) and KL(Q||P)
    pairwise_kl = {}
    for i, s1 in enumerate(sites):
        for s2 in sites[i + 1 :]:
            kl_fwd = kl_divergence(site_dists[s1], site_dists[s2])
            kl_rev = kl_divergence(site_dists[s2], site_dists[s1])
            sym_kl = (kl_fwd + kl_rev) / 2
            pairwise_kl[f"{s1}_vs_{s2}"] = round(sym_kl, decimal_places)

    # --- Chi-Squared Test for Homogeneity ---
    # H0: all sites have the same underlying distribution
    chi2, p_value, dof = _chi_squared_homogeneity(raw_counts, sites, n_bins)

    # --- Compatibility Summary ---
    # Simple heuristic: high overlap + low KL + non-significant chi2 → compatible
    mean_overlap = (
        sum(site_vs_global_overlap.values()) / len(site_vs_global_overlap)
        if site_vs_global_overlap
        else 0
    )
    mean_kl = sum(site_kl.values()) / len(site_kl) if site_kl else 0
    compatible = (
        mean_overlap >= 0.7 and mean_kl <= 0.1 and (p_value is None or p_value >= 0.05)
    )

    return {
        "edges": edges,
        "global_counts": global_counts,
        "global_distribution": [round(v, decimal_places) for v in global_dist],
        "per_site_counts": raw_counts,
        "per_site_distributions": {
            site: [round(v, decimal_places) for v in site_dists[site]] for site in sites
        },
        "per_site_missing": missing,
        "overlap": {
            "pairwise": pairwise_overlap,
            "site_vs_global": site_vs_global_overlap,
            "mean_pairwise": mean_pairwise,
        },
        "kl_divergence": {
            "site_vs_global": site_kl,
            "pairwise_symmetric": pairwise_kl,
            "mean_vs_global": round(mean_kl, decimal_places),
        },
        "chi_squared": {
            "statistic": round(chi2, decimal_places) if chi2 is not None else None,
            "p_value": round(p_value, decimal_places) if p_value is not None else None,
            "degrees_of_freedom": dof,
            "significant_difference": (p_value < 0.05) if p_value is not None else None,
        },
        "compatibility_summary": {
            "compatible": compatible,
            "mean_overlap_vs_global": round(mean_overlap, decimal_places),
            "mean_kl_vs_global": round(mean_kl, decimal_places),
            "note": (
                "Distributions appear compatible across sites."
                if compatible
                else "Distributions show notable differences across sites."
            ),
        },
    }


def _chi_squared_homogeneity(
    raw_counts: Dict[str, List[int]],
    sites: List[str],
    n_bins: int,
) -> Tuple[Optional[float], Optional[float], Optional[int]]:
    """Chi-squared test for homogeneity.

    Rows = sites, columns = bins.
    Removes bins with zero total (expected = 0 causes undefined chi2).
    Falls back to None if degrees of freedom < 1.
    """
    n_sites = len(sites)

    # Build contingency table: rows=sites, cols=bins
    table = [[raw_counts[site][b] for b in range(n_bins)] for site in sites]

    row_totals = [sum(table[r]) for r in range(n_sites)]
    col_totals = [sum(table[r][c] for r in range(n_sites)) for c in range(n_bins)]
    grand_total = sum(row_totals)

    if grand_total == 0:
        return None, None, None

    # Remove zero-total columns
    active_cols = [c for c in range(n_bins) if col_totals[c] > 0]
    if len(active_cols) < 2:
        return None, None, None

    dof = (n_sites - 1) * (len(active_cols) - 1)
    if dof < 1:
        return None, None, None

    chi2 = 0.0
    for r in range(n_sites):
        for c in active_cols:
            expected = (row_totals[r] * col_totals[c]) / grand_total
            if expected > 0:
                chi2 += (table[r][c] - expected) ** 2 / expected

    # p-value via chi-squared CDF (regularized incomplete gamma)
    p_value = _chi2_sf(chi2, dof)
    return chi2, p_value, dof


def _chi2_sf(x: float, k: int) -> float:
    """Survival function of chi-squared distribution: P(X > x) for X ~ chi2(k).

    Uses the regularized upper incomplete gamma function approximation.
    Pure Python — no scipy needed.
    """
    if x <= 0:
        return 1.0
    return _upper_regularized_gamma(k / 2, x / 2)


def _upper_regularized_gamma(a: float, x: float) -> float:
    """Q(a, x) = 1 - P(a, x) — upper regularized incomplete gamma.

    Uses continued fraction for x > a+1, series for x <= a+1.
    """
    if x < 0:
        return 1.0
    if x == 0:
        return 1.0

    if x <= a + 1:
        # Series expansion for lower gamma, then 1 - result
        return 1.0 - _lower_gamma_series(a, x)
    else:
        return _upper_gamma_cf(a, x)


def _lower_gamma_series(
    a: float, x: float, max_iter: int = 200, tol: float = 1e-10
) -> float:
    """Lower regularized gamma via series: P(a,x)."""
    if x == 0:
        return 0.0
    ap = a
    total = 1.0 / a
    delta = total
    for _ in range(max_iter):
        ap += 1
        delta *= x / ap
        total += delta
        if abs(delta) < abs(total) * tol:
            break
    return total * math.exp(-x + a * math.log(x) - math.lgamma(a))


def _upper_gamma_cf(
    a: float, x: float, max_iter: int = 200, tol: float = 1e-10
) -> float:
    """Upper regularized gamma via Lentz continued fraction: Q(a,x)."""
    fpmin = 1e-300
    b = x + 1.0 - a
    c = 1.0 / fpmin
    d = 1.0 / b
    h = d
    for i in range(1, max_iter + 1):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < fpmin:
            d = fpmin
        c = b + an / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < tol:
            break
    return math.exp(-x + a * math.log(x) - math.lgamma(a)) * h
