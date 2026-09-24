"""Site-side steps of the CSV analyzer workflow."""

import logging
from typing import Any, Dict, List

from framework import with_state

from .csv_analysis import analyze_csv_tables
from .histograms import compute_local_histograms
from .inputs import read_csv_tables
from .types import CsvTable, GlobalCsvRound, SiteState


def analyze_csv(
    tables: List[CsvTable], logger: logging.Logger, decimal_places: int = 4
):
    """Summarize the site's CSV columns with shareable sufficient statistics."""
    logger.info("Analyzing %d CSV file(s)", len(tables))
    local_result = analyze_csv_tables(tables, decimal_places, logger)
    return with_state(local_result, SiteState(local_csv_analysis=local_result))


def compute_histograms(
    global_round: GlobalCsvRound,
    state: SiteState,
    data_dir: str,
    logger: logging.Logger,
):
    """Count the site's values in the centrally chosen histogram bins."""
    bin_config = global_round.bin_config
    if bin_config:
        logger.info("Computing histograms for %d column(s)", len(bin_config))
        local_histograms: Dict[str, Any] = compute_local_histograms(
            read_csv_tables(data_dir), bin_config
        )
    else:
        logger.info("No compatible columns found; skipping histograms")
        local_histograms = {}

    return with_state(
        local_histograms,
        SiteState(
            local_csv_analysis=state.local_csv_analysis,
            global_report=global_round.global_report,
            local_histograms=local_histograms,
        ),
    )
