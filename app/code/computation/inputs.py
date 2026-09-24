"""Load and validate site-local CSV files and computation parameters."""

import csv
import os
from typing import List

from .types import CsvTable

SECURITY_LEVELS = ("low", "high")


def validate_parameters(
    decimal_places: int = 4, num_bins: int = 10, security_level: str = "low"
) -> None:
    """Reject computation parameters the analysis cannot honor."""
    if isinstance(decimal_places, bool) or not isinstance(decimal_places, int):
        raise ValueError(f"decimal_places must be an integer, got {decimal_places!r}")
    if decimal_places < 0:
        raise ValueError(f"decimal_places must be >= 0, got {decimal_places}")
    if isinstance(num_bins, bool) or not isinstance(num_bins, int) or num_bins < 1:
        raise ValueError(f"num_bins must be a positive integer, got {num_bins!r}")
    if security_level not in SECURITY_LEVELS:
        raise ValueError(
            f"security_level must be one of {SECURITY_LEVELS}, got {security_level!r}"
        )


def read_csv_tables(data_dir: str) -> List[CsvTable]:
    """Read every CSV file in ``data_dir`` in sorted filename order."""
    csv_files = sorted(f for f in os.listdir(data_dir) if f.lower().endswith(".csv"))
    if not csv_files:
        raise FileNotFoundError(f"No CSV files found in {data_dir}")

    tables = []
    for file_name in csv_files:
        file_path = os.path.join(data_dir, file_name)
        with open(file_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            tables.append(
                CsvTable(name=file_name, fieldnames=reader.fieldnames or [], rows=rows)
            )
    return tables


def load_site_tables(
    data_dir: str,
    decimal_places: int = 4,
    num_bins: int = 10,
    security_level: str = "low",
) -> List[CsvTable]:
    """Validate parameters, then load the site's CSV files for the first step."""
    validate_parameters(decimal_places, num_bins, security_level)
    return read_csv_tables(data_dir)
