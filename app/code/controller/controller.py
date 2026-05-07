import json
import logging
from nvflare.apis.impl.controller import Controller, Task, ClientTask
from nvflare.apis.fl_context import FLContext
from nvflare.apis.signal import Signal
from nvflare.apis.shareable import Shareable
from _utils.utils import get_parameters_file_path
from typing import Callable

TASK_NAME_ANALYZE_CSV = "ANALYZE_CSV"
TASK_NAME_ACCEPT_GLOBAL_REPORT = "ACCEPT_GLOBAL_REPORT"
TASK_NAME_COMPUTE_HISTOGRAMS = "COMPUTE_HISTOGRAMS"
TASK_NAME_ACCEPT_HISTOGRAM_REPORT = "ACCEPT_HISTOGRAM_REPORT"
AGGREGATOR_ID = "aggregator"



def _build_bin_config(global_report: dict, num_bins: int = 10) -> dict:
    """
    Auto-generate bin config for every universal column:
    - Numeric: equally spaced edges between global min and max.
    - Boolean/String: unique category labels discovered from per-site stats.
    Columns that are partial or have type conflicts are skipped.
    """
    bin_config = {}
    column_stats = global_report.get("column_stats", {})
    parallelism  = global_report.get("column_parallelism", {})
    universal    = set(parallelism.get("universal_columns", []))

    for col, stats in column_stats.items():
        if col not in universal:
            continue  # skip partial / type-conflict columns

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
            # Collect all unique values seen across sites from per_site stats
            per_site = stats.get("per_site", {})
            # unique_values may not be available directly, so we rely on the
            # aggregator having stored a union of categories. Fall back to
            # a placeholder — the executor will skip unknown values gracefully.
            # The authoritative category list comes from unique_values_union
            # stored in the global report if available, otherwise derive below.
            categories = stats.get("unique_values_union", None)
            if not categories:
                # Build from per-site unique value lists if present
                cat_set = set()
                for site_stats in per_site.values():
                    for v in site_stats.get("unique_values", []):
                        cat_set.add(str(v))
                categories = sorted(cat_set)
            if categories:
                bin_config[col] = {"edges": categories, "type": "categorical"}

    return bin_config


class MyController(Controller):
    def __init__(
        self,
        min_clients: int = 2,
        wait_time_after_min_received: int = 10,
        task_timeout: int = 0,
    ):
        super().__init__()
        self._task_timeout = task_timeout
        self._min_clients = min_clients
        self._wait_time_after_min_received = wait_time_after_min_received

#### Computation Author Defined Section ####

    def start_controller(self, fl_ctx: FLContext) -> None:
        self.aggregator = self._engine.get_component(AGGREGATOR_ID)
        self._load_and_set_computation_parameters(fl_ctx)

    def control_flow(self, abort_signal: Signal, fl_ctx: FLContext) -> None:
        # Step 1: Ask all sites to analyze their local CSV data
        self._broadcast_task(
            task_name=TASK_NAME_ANALYZE_CSV,
            data=Shareable(),
            result_cb=self._accept_site_csv_result,
            fl_ctx=fl_ctx,
            abort_signal=abort_signal,
        )

        # Step 2: Aggregate all site results into a global report
        aggregate_result = self.aggregator.aggregate(fl_ctx)

        # Step 3: Send the global report back to all sites
        self._broadcast_task(
            task_name=TASK_NAME_ACCEPT_GLOBAL_REPORT,
            data=aggregate_result,
            result_cb=None,
            fl_ctx=fl_ctx,
            abort_signal=abort_signal,
        )

        # Step 4: Auto-generate bin edges from the aggregated global report
        computation_parameters = fl_ctx.get_prop("COMPUTATION_PARAMETERS")
        num_bins = computation_parameters.get("num_bins", 10)
        global_report = aggregate_result.get("global_report", {})
        bin_config = _build_bin_config(global_report, num_bins)

        if bin_config:
            logging.info(f"Auto-generated histogram bins for {len(bin_config)} columns (numeric + categorical).")

            histogram_task_data = Shareable()
            histogram_task_data["bin_config"] = bin_config

            # Switch aggregator to histogram mode
            self.aggregator._mode = "histogram"

            self._broadcast_task(
                task_name=TASK_NAME_COMPUTE_HISTOGRAMS,
                data=histogram_task_data,
                result_cb=self._accept_site_histogram_result,
                fl_ctx=fl_ctx,
                abort_signal=abort_signal,
            )

            # Step 5: Aggregate histograms and generate HTML report
            histogram_aggregate = self.aggregator.aggregate(fl_ctx)

            # Step 6: Send the HTML report back to all sites
            self._broadcast_task(
                task_name=TASK_NAME_ACCEPT_HISTOGRAM_REPORT,
                data=histogram_aggregate,
                result_cb=None,
                fl_ctx=fl_ctx,
                abort_signal=abort_signal,
            )

            logging.info("Histogram compatibility report complete.")
        else:
            logging.info("No compatible columns found — skipping histogram round.")

        logging.info("CSV analysis computation complete.")

    def _accept_site_csv_result(self, client_task: ClientTask, fl_ctx: FLContext) -> bool:
        return self.aggregator.accept(client_task.result, fl_ctx)

    def _accept_site_histogram_result(self, client_task: ClientTask, fl_ctx: FLContext) -> bool:
        return self.aggregator.accept(client_task.result, fl_ctx)

#### End of Computation Author Defined Section ####

#### Framework Helper Methods ####

    def _broadcast_task(self, task_name, data, result_cb, fl_ctx, abort_signal):
        self.broadcast_and_wait(
            task=Task(
                name=task_name,
                data=data,
                props={},
                timeout=self._task_timeout,
                result_received_cb=result_cb,
            ),
            min_responses=self._min_clients,
            wait_time_after_min_received=self._wait_time_after_min_received,
            fl_ctx=fl_ctx,
            abort_signal=abort_signal,
        )

    def _load_and_set_computation_parameters(self, fl_ctx: FLContext) -> None:
        with open(get_parameters_file_path(fl_ctx), 'r') as f:
            fl_ctx.set_prop(
                key="COMPUTATION_PARAMETERS",
                value=json.load(f),
                private=False,
                sticky=True,
            )

#### Framework-Specific Required Methods ####

    def process_result_of_unknown_task(self, task: Task, fl_ctx: FLContext) -> None:
        pass

    def stop_controller(self, fl_ctx: FLContext) -> None:
        pass