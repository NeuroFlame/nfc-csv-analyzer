import math
from typing import Dict, Any
from nvflare.apis.shareable import Shareable
from nvflare.apis.fl_context import FLContext
from nvflare.app_common.abstract.aggregator import Aggregator
from nvflare.apis.fl_constant import ReservedKey
from .histogram_aggregator import aggregate_histograms
from .report_generator import generate_histogram_report_html
from .regression_analysis import compute_regression_analysis


class MyAggregator(Aggregator):
    """
    Aggregates per-site CSV analysis results into a single federated global report.
    For numeric columns it computes exact global statistics using sufficient statistics
    (count, sum, sum-of-squares) so no raw data ever leaves each site.
    Also handles a second round of histogram aggregation with compatibility metrics.
    """

    def __init__(self):
        super().__init__()
        self.site_results: Dict[str, Dict[str, Any]] = {}
        self.site_histograms: Dict[str, Dict[str, Any]] = {}
        self._mode = "csv"  # switches to "histogram" for round 2
        self._global_csv_report: Dict[str, Any] = {}

    def accept(self, site_result: Shareable, fl_ctx: FLContext) -> bool:
        site_id = site_result.get_peer_prop(
            key=ReservedKey.IDENTITY_NAME, default=None
        )
        computation_parameters = fl_ctx.get_prop("COMPUTATION_PARAMETERS") or {}
        site_id_name_map = computation_parameters.get("site_id_name_map", {})
        site_name = site_id_name_map.get(site_id, site_id)

        if self._mode == "histogram":
            self.site_histograms[site_name] = site_result["histograms"]
        else:
            self.site_results[site_name] = site_result["result"]
        return True

    def accept_histograms(self, site_result: Shareable, fl_ctx: FLContext) -> bool:
        """Callback-compatible accept for histogram round."""
        self._mode = "histogram"
        return self.accept(site_result, fl_ctx)

    def aggregate(self, fl_ctx: FLContext) -> Shareable:
        computation_parameters = fl_ctx.get_prop("COMPUTATION_PARAMETERS")
        decimal_places = computation_parameters.get("decimal_places", 4) if computation_parameters else 4

        if self._mode == "histogram":
            security_level = computation_parameters.get("security_level", "low") if computation_parameters else "low"
            return self._aggregate_histograms(decimal_places, security_level)

        global_report = self._build_global_report(decimal_places)
        self._global_csv_report = global_report

        outgoing = Shareable()
        outgoing["global_report"] = global_report
        return outgoing

    def _aggregate_histograms(self, decimal_places: int, security_level: str = "low") -> Shareable:
        histogram_report = aggregate_histograms(self.site_histograms, decimal_places)
        regression_data  = compute_regression_analysis(self.site_results, self._global_csv_report, decimal_places)
        html_report      = generate_histogram_report_html(
            histogram_report,
            self._global_csv_report,
            security_level=security_level,
            regression_data=regression_data,
        )

        outgoing = Shareable()
        outgoing["histogram_report"] = histogram_report
        outgoing["html_report"] = html_report
        return outgoing

    def _build_global_report(self, decimal_places: int) -> Dict[str, Any]:
        if not self.site_results:
            return {}

        total_rows = sum(r.get("total_rows", 0) for r in self.site_results.values())
        all_files = []
        for r in self.site_results.values():
            all_files.extend(r.get("file_names", []))

        all_columns = set()
        for r in self.site_results.values():
            all_columns.update(r.get("column_stats", {}).keys())

        aggregated_columns = {}
        for col in sorted(all_columns):
            col_stats_per_site = {}
            for site_name, r in self.site_results.items():
                cs = r.get("column_stats", {}).get(col)
                if cs:
                    col_stats_per_site[site_name] = cs

            if not col_stats_per_site:
                continue

            aggregated_columns[col] = self._aggregate_column(
                col, col_stats_per_site, decimal_places
            )

        column_parallelism = self._build_column_parallelism(all_columns)

        return {
            "total_sites": len(self.site_results),
            "site_names": sorted(self.site_results.keys()),
            "total_rows": total_rows,
            "total_columns": len(aggregated_columns),
            "files_analyzed": sorted(set(all_files)),
            "column_stats": aggregated_columns,
            "column_parallelism": column_parallelism,
            "per_site_summary": {
                site: {
                    "total_rows": r.get("total_rows", 0),
                    "total_columns": r.get("total_columns", 0),
                    "files": r.get("file_names", []),
                }
                for site, r in self.site_results.items()
            },
        }

    def _build_column_parallelism(self, all_columns: set) -> Dict[str, Any]:
        """
        For every column seen across all sites, classify as:
          - universal:     present in all sites with consistent inferred type
          - partial:       present in some but not all sites (regardless of type)
          - type_conflict: present in multiple sites but with mismatched inferred types
        Also builds a site x column presence matrix for the HTML report.
        """
        all_sites = sorted(self.site_results.keys())
        n_sites = len(all_sites)

        # Build presence matrix: col -> {site -> inferred_type or None}
        presence: Dict[str, Dict[str, Any]] = {}
        for col in sorted(all_columns):
            presence[col] = {}
            for site in all_sites:
                cs = self.site_results[site].get("column_stats", {}).get(col)
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
        self,
        col: str,
        col_stats_per_site: Dict[str, Dict],
        decimal_places: int,
    ) -> Dict[str, Any]:
        type_votes = {}
        for cs in col_stats_per_site.values():
            t = cs.get("inferred_type", "string")
            type_votes[t] = type_votes.get(t, 0) + 1
        inferred_type = max(type_votes, key=type_votes.get)

        total_count = sum(cs.get("count", 0) for cs in col_stats_per_site.values())
        total_nan = sum(cs.get("nan_count", 0) for cs in col_stats_per_site.values())
        total_mismatch = sum(cs.get("type_mismatch_count", 0) for cs in col_stats_per_site.values())
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
                per_site_info[site].update({
                    "mean": cs.get("mean"),
                    "std_dev": cs.get("std_dev"),
                    "min": cs.get("min"),
                    "max": cs.get("max"),
                    "median": cs.get("median"),
                    "q1": cs.get("q1"),
                    "q3": cs.get("q3"),
                })

        result = {
            "inferred_type": inferred_type,
            "total_count": total_count,
            "total_nan_count": total_nan,
            "total_type_mismatch_count": total_mismatch,
            "total_unique_count_sum": total_unique,
            "per_site": per_site_info,
        }

        if inferred_type in ("boolean", "string"):
            # Collect union of all unique values seen across sites.
            # csv_analysis stores raw parsed values via unique_count only, so we
            # derive categories from the column values stored in each site's
            # raw result if available, otherwise fall back to known boolean set.
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
                    weighted_var_sum += (n_i - 1) * var_i + n_i * (mean_i - global_mean) ** 2

            global_variance = (
                weighted_var_sum / (total_count - 1) if total_count > 1 else 0.0
            )
            global_std_dev = math.sqrt(global_variance) if global_variance >= 0 else 0.0

            global_min = min(
                cs.get("min") for cs in col_stats_per_site.values()
                if cs.get("min") is not None
            )
            global_max = max(
                cs.get("max") for cs in col_stats_per_site.values()
                if cs.get("max") is not None
            )

            result.update({
                "global_mean": round(global_mean, decimal_places) if global_mean is not None else None,
                "global_variance": round(global_variance, decimal_places),
                "global_std_dev": round(global_std_dev, decimal_places),
                "global_min": round(global_min, decimal_places) if global_min is not None else None,
                "global_max": round(global_max, decimal_places) if global_max is not None else None,
                "note_median": "Per-site medians/quartiles shown; global exact median requires raw data exchange.",
            })

        return result