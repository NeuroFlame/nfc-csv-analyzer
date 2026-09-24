"""Define the files each site receives at the end of the workflow."""

from .types import HistogramRound, SiteState


def build_site_outputs(histogram_round: HistogramRound, state: SiteState):
    """Return the site's local analyses alongside the federated reports."""
    return {
        "local_csv_analysis.json": state.local_csv_analysis,
        "global_csv_report.json": state.global_report,
        "local_histograms.json": state.local_histograms,
        "histogram_report.json": histogram_round.histogram_report,
        "index.html": histogram_round.html_report,
    }
