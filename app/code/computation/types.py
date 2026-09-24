"""Define values exchanged between the CSV analyzer workflow steps.

Per-site analyses, global reports, bin configurations and histogram reports
are plain JSON dictionaries whose layout is the published output format; the
dataclasses here only group them where they cross a step boundary.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class CsvTable:
    """One site-local CSV file, read with :class:`csv.DictReader`."""

    name: str
    fieldnames: List[str]
    rows: List[Dict[str, Optional[str]]]


@dataclass
class GlobalCsvRound:
    """Central result of the first round, sent to every site."""

    global_report: Dict[str, Any]
    bin_config: Dict[str, Any]


@dataclass
class RemoteState:
    """Central state kept between the CSV round and the histogram round."""

    site_results: Dict[str, Dict[str, Any]]
    global_report: Dict[str, Any]


@dataclass
class HistogramRound:
    """Central result of the histogram round, sent to every site."""

    histogram_report: Dict[str, Any]
    html_report: str


@dataclass
class SiteState:
    """Site-local results kept until the final outputs are written."""

    local_csv_analysis: Dict[str, Any]
    global_report: Optional[Dict[str, Any]] = None
    local_histograms: Optional[Dict[str, Any]] = None
