"""Declare the federated CSV analyzer workflow."""

from framework import (
    ComputationSpec,
    local_step,
    remote_step,
    site_output_step,
    stepped_workflow,
)

from .inputs import load_site_tables
from .local_math import analyze_csv, compute_histograms
from .remote_math import build_global_csv_report, build_histogram_report
from .results import build_site_outputs

SPEC = ComputationSpec(
    workflow=stepped_workflow(
        local_step(fn=analyze_csv, input_fn=load_site_tables),
        remote_step(fn=build_global_csv_report),
        local_step(fn=compute_histograms),
        remote_step(fn=build_histogram_report),
        site_output_step(fn=build_site_outputs),
    ),
)
