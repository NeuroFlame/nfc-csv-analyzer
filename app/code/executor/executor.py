import logging
import json
import os

from nvflare.apis.executor import Executor
from nvflare.apis.fl_context import FLContext
from nvflare.apis.shareable import Shareable
from nvflare.apis.signal import Signal
from _utils.utils import get_data_directory_path, get_output_directory_path
from .csv_analysis import analyze_csv_locally
from .histogram import compute_local_histograms

TASK_NAME_ANALYZE_CSV = "ANALYZE_CSV"
TASK_NAME_ACCEPT_GLOBAL_REPORT = "ACCEPT_GLOBAL_REPORT"
TASK_NAME_COMPUTE_HISTOGRAMS = "COMPUTE_HISTOGRAMS"
TASK_NAME_ACCEPT_HISTOGRAM_REPORT = "ACCEPT_HISTOGRAM_REPORT"


class MyExecutor(Executor):
    def execute(
        self,
        task_name: str,
        shareable: Shareable,
        fl_ctx: FLContext,
        abort_signal: Signal,
    ) -> Shareable:

        logging.info(f"Task Name: {task_name}")

        if task_name == TASK_NAME_ANALYZE_CSV:
            data_dir = get_data_directory_path(fl_ctx)
            computation_parameters = get_computation_parameters(fl_ctx)
            decimal_places = computation_parameters.get("decimal_places", 4)

            logging.info(f"Analyzing CSV data in: {data_dir}")
            local_result = analyze_csv_locally(data_dir, decimal_places)

            save_results_to_file(local_result, "local_csv_analysis.json", fl_ctx)

            result_shareable = Shareable()
            result_shareable["result"] = local_result
            return result_shareable

        if task_name == TASK_NAME_ACCEPT_GLOBAL_REPORT:
            global_report = shareable["global_report"]
            save_results_to_file(global_report, "global_csv_report.json", fl_ctx)
            return Shareable()

        if task_name == TASK_NAME_COMPUTE_HISTOGRAMS:
            data_dir = get_data_directory_path(fl_ctx)
            bin_config = shareable["bin_config"]

            logging.info(f"Computing histograms in: {data_dir}")
            local_histograms = compute_local_histograms(data_dir, bin_config)

            save_results_to_file(local_histograms, "local_histograms.json", fl_ctx)

            result_shareable = Shareable()
            result_shareable["histograms"] = local_histograms
            return result_shareable

        if task_name == TASK_NAME_ACCEPT_HISTOGRAM_REPORT:
            # Server sends back the final HTML report as a string
            html_report = shareable["html_report"]
            histogram_report = shareable["histogram_report"]
            save_results_to_file(histogram_report, "histogram_report.json", fl_ctx)
            save_html_to_file(html_report, "index.html", fl_ctx)
            return Shareable()

        logging.warning(f"Unknown task: {task_name}")
        return Shareable()


def get_computation_parameters(fl_ctx: FLContext):
    return fl_ctx.get_peer_context().get_prop(
        "COMPUTATION_PARAMETERS",
        {"decimal_places": 4}
    )


def save_html_to_file(html: str, file_name: str, fl_ctx: FLContext):
    output_dir = get_output_directory_path(fl_ctx)
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, file_name)
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        logging.info(f"HTML report saved to: {out_path}")
    except Exception as e:
        raise RuntimeError(f"Failed to save HTML to {file_name}: {e}")


def save_results_to_file(results: dict, file_name: str, fl_ctx: FLContext):
    output_dir = get_output_directory_path(fl_ctx)
    logging.info(f"Saving results to: {output_dir}")
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, file_name)
    try:
        with open(out_path, "w") as f:
            json.dump(results, f, indent=4)
        logging.info(f"Results saved to: {out_path}")
    except Exception as e:
        raise RuntimeError(f"Failed to save results to {file_name}: {e}")
