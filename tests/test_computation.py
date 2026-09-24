"""Unit tests for the CSV analyzer computation."""

import logging
import math
import os
import statistics
import tempfile
import unittest

from computation.csv_analysis import analyze_csv_tables
from computation.inputs import load_site_tables, read_csv_tables
from computation.local_math import analyze_csv, compute_histograms
from computation.remote_math import (
    build_bin_config,
    build_global_csv_report,
    build_global_report,
    build_histogram_report,
)
from computation.report import generate_histogram_report_html
from computation.results import build_site_outputs
from computation.spec import SPEC
from computation.types import GlobalCsvRound, HistogramRound, SiteState
from framework.serialization import deserialize_value, serialize_value
from framework.workflow import get_task_names

LOGGER = logging.getLogger("test_computation")
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _write(directory, name, text):
    with open(os.path.join(directory, name), "w", encoding="utf-8") as f:
        f.write(text)


def _round_trip(value, value_type):
    return deserialize_value(serialize_value(value), value_type)


def _run_workflow(site_dirs, **parameters):
    """Run every step in-process, passing payloads through serialization."""
    site_states = {}
    site_results = {}
    for site, data_dir in site_dirs.items():
        tables = load_site_tables(data_dir, **parameters)
        step = analyze_csv(tables, LOGGER, parameters.get("decimal_places", 4))
        site_states[site] = step.state
        site_results[site] = _round_trip(step.payload, dict)

    remote = build_global_csv_report(
        site_results,
        parameters.get("decimal_places", 4),
        parameters.get("num_bins", 10),
    )
    global_round = _round_trip(remote.payload, GlobalCsvRound)

    site_histograms = {}
    for site, data_dir in site_dirs.items():
        state = _round_trip(site_states[site], SiteState)
        step = compute_histograms(global_round, state, data_dir, LOGGER)
        site_states[site] = step.state
        site_histograms[site] = _round_trip(step.payload, dict)

    histogram_round = _round_trip(
        build_histogram_report(
            site_histograms,
            remote.state,
            parameters.get("decimal_places", 4),
            parameters.get("security_level", "low"),
        ),
        HistogramRound,
    )
    return {
        site: build_site_outputs(
            histogram_round, _round_trip(site_states[site], SiteState)
        )
        for site in site_dirs
    }


class WorkflowTests(unittest.TestCase):
    def test_task_names(self):
        self.assertEqual(
            get_task_names(SPEC.workflow),
            ["analyze_csv", "compute_histograms", "build_site_outputs"],
        )

    def test_test_data_produces_every_output(self):
        site_dirs = {
            site: os.path.join(REPO_ROOT, "test_data", site)
            for site in ("site1", "site2", "site3")
        }
        outputs = _run_workflow(site_dirs, decimal_places=4, num_bins=10)
        for files in outputs.values():
            self.assertEqual(
                sorted(files),
                [
                    "global_csv_report.json",
                    "histogram_report.json",
                    "index.html",
                    "local_csv_analysis.json",
                    "local_histograms.json",
                ],
            )
            self.assertTrue(files["index.html"].startswith("<!DOCTYPE html>"))
        report = outputs["site1"]["global_csv_report.json"]
        self.assertEqual(report["site_names"], ["site1", "site2", "site3"])
        self.assertTrue(outputs["site1"]["histogram_report.json"]["columns"])

    def test_no_compatible_columns_still_reports_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            dirs = {"a": os.path.join(tmp, "a"), "b": os.path.join(tmp, "b")}
            for path in dirs.values():
                os.makedirs(path)
            _write(dirs["a"], "x.csv", "only_a\n1\n2\n")
            _write(dirs["b"], "x.csv", "only_b\n3\n4\n")
            outputs = _run_workflow(dirs)
        self.assertEqual(outputs["a"]["local_histograms.json"], {})
        self.assertEqual(outputs["a"]["histogram_report.json"]["columns"], {})
        self.assertIn("Data Structure", outputs["a"]["index.html"])


class InputTests(unittest.TestCase):
    def test_requires_csv_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(tmp, "notes.txt", "x")
            with self.assertRaises(FileNotFoundError):
                read_csv_tables(tmp)

    def test_reads_files_in_sorted_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(tmp, "b.csv", "x\n1\n")
            _write(tmp, "a.CSV", "﻿y\n2\n")
            tables = read_csv_tables(tmp)
        self.assertEqual([t.name for t in tables], ["a.CSV", "b.csv"])
        self.assertEqual(tables[0].fieldnames, ["y"])

    def test_rejects_invalid_parameters(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(tmp, "a.csv", "x\n1\n")
            for bad in (
                {"num_bins": 0},
                {"num_bins": 2.5},
                {"decimal_places": -1},
                {"decimal_places": True},
                {"security_level": "medium"},
            ):
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    load_site_tables(tmp, **bad)


class LocalMathTests(unittest.TestCase):
    def test_row_aligned_files_merge_side_by_side(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(tmp, "covariates.csv", "age,sex\n30,0\n40,1\n")
            _write(tmp, "data.csv", "roi\n1.5\n2.5\n")
            result = analyze_csv_tables(read_csv_tables(tmp), 4, LOGGER)
        self.assertEqual(result["total_rows"], 2)
        self.assertEqual(result["total_columns"], 3)
        self.assertEqual(result["column_stats"]["sex"]["inferred_type"], "boolean")
        self.assertIn("age|||roi", result["cross_products"])

    def test_same_schema_files_stack(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(tmp, "a.csv", "age\n30\n")
            _write(tmp, "b.csv", "age\n40\nabc\n")
            result = analyze_csv_tables(read_csv_tables(tmp), 4, LOGGER)
        self.assertEqual(result["total_rows"], 3)
        age = result["column_stats"]["age"]
        self.assertEqual(age["inferred_type"], "string")
        self.assertEqual(age["unique_values"], ["30", "40", "abc"])


class RemoteMathTests(unittest.TestCase):
    def test_pooled_statistics_match_direct_computation(self):
        site_values = {"s1": [1.0, 2.0, 3.0, 10.0], "s2": [4.0, 5.0], "s3": [7.5]}
        site_results = {}
        for site, values in site_values.items():
            with tempfile.TemporaryDirectory() as tmp:
                _write(tmp, "d.csv", "v\n" + "\n".join(map(str, values)) + "\n")
                site_results[site] = analyze_csv_tables(read_csv_tables(tmp), 10)

        stats = build_global_report(site_results, 10)["column_stats"]["v"]
        all_values = [v for values in site_values.values() for v in values]
        self.assertAlmostEqual(stats["global_mean"], statistics.mean(all_values))
        self.assertEqual((stats["global_min"], stats["global_max"]), (1.0, 10.0))

    def test_pooled_std_dev_matches_sample_std_dev(self):
        site_values = {"s1": [1.0, 2.0, 3.0, 10.0], "s2": [4.0, 5.0], "s3": [7.5]}
        site_results = {}
        for site, values in site_values.items():
            with tempfile.TemporaryDirectory() as tmp:
                _write(tmp, "d.csv", "v\n" + "\n".join(map(str, values)) + "\n")
                site_results[site] = analyze_csv_tables(read_csv_tables(tmp), 10)

        stats = build_global_report(site_results, 10)["column_stats"]["v"]
        all_values = [v for values in site_values.values() for v in values]
        self.assertAlmostEqual(
            stats["global_std_dev"], statistics.stdev(all_values), places=6
        )
        self.assertAlmostEqual(
            stats["global_variance"], statistics.variance(all_values), places=6
        )

    def test_bin_config_uses_only_universal_columns(self):
        report = {
            "column_stats": {
                "age": {"inferred_type": "number", "global_min": 0, "global_max": 10},
                "flat": {"inferred_type": "number", "global_min": 5, "global_max": 5},
                "sex": {"inferred_type": "boolean", "unique_values_union": ["0", "1"]},
                "partial": {
                    "inferred_type": "number",
                    "global_min": 0,
                    "global_max": 1,
                },
            },
            "column_parallelism": {"universal_columns": ["age", "flat", "sex"]},
        }
        config = build_bin_config(report, num_bins=5)
        self.assertEqual(sorted(config), ["age", "sex"])
        self.assertEqual(config["age"]["edges"], [0, 2, 4, 6, 8, 10])
        self.assertEqual(config["sex"], {"edges": ["0", "1"], "type": "categorical"})

    def test_high_security_hides_descriptive_statistics(self):
        report = {"column_parallelism": {"all_sites": ["s1"]}, "column_stats": {}}
        hist = {"sites": ["s1"], "columns": {}}
        low = generate_histogram_report_html(hist, report, security_level="low")
        high = generate_histogram_report_html(hist, report, security_level="high")
        self.assertIn("Global Descriptive Statistics", low)
        self.assertNotIn("Global Descriptive Statistics", high)

    def test_chi_squared_p_value_is_a_probability(self):
        site_histograms = {
            "s1": {"x": {"edges": [0, 1, 2], "counts": [10, 0], "missing": 0}},
            "s2": {"x": {"edges": [0, 1, 2], "counts": [0, 10], "missing": 0}},
        }
        remote = build_global_csv_report({"s1": {}, "s2": {}})
        result = build_histogram_report(site_histograms, remote.state)
        chi = result.histogram_report["columns"]["x"]["chi_squared"]
        self.assertTrue(0 <= chi["p_value"] < 0.05)
        self.assertFalse(math.isnan(chi["statistic"]))


if __name__ == "__main__":
    unittest.main()
