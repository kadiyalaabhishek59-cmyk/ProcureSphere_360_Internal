"""
Main orchestrator for ProcureSphere 360 API Performance Benchmark (Localhost vs Render).
"""

import os
import sys
import argparse
import logging
from pathlib import Path

# Locate project root containing manage.py
_curr = Path(__file__).resolve()
BASE_DIR = _curr.parents[3]
for parent in _curr.parents:
    if (parent / "manage.py").exists():
        BASE_DIR = parent
        break

SRC_DIR = BASE_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django

try:
    django.setup()
except Exception as e:
    pass

from backend.scripts.api_performance_benchmark.config import (
    LOCAL_BASE_URL,
    RENDER_BASE_URL,
    REPORT_FILENAME,
)
from backend.scripts.api_performance_benchmark.auth import AuthManager
from backend.scripts.api_performance_benchmark.payloads import PayloadProvider
from backend.scripts.api_performance_benchmark.discovery import discover_all_endpoints
from backend.scripts.api_performance_benchmark.runner import BenchmarkRunner
from backend.scripts.api_performance_benchmark.excel_generator import ExcelReportGenerator

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s [%(name)s]: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("benchmark.main")


def main():
    parser = argparse.ArgumentParser(
        description="ProcureSphere 360 API Performance Benchmark (Localhost vs Render)"
    )
    parser.add_argument(
        "--output",
        default=REPORT_FILENAME,
        help=f"Output Excel file name (default: {REPORT_FILENAME})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit number of endpoints tested (0 for all endpoints)",
    )
    parser.add_argument(
        "--from-cache",
        action="store_true",
        help="Regenerate Excel report from existing cached benchmark results",
    )
    args = parser.parse_args()

    print("=" * 80)
    print("PROCURESPHERE 360 – API PERFORMANCE BENCHMARK (LOCALHOST VS RENDER)")
    print(f"Localhost URL : {LOCAL_BASE_URL}")
    print(f"Render URL    : {RENDER_BASE_URL}")
    print("=" * 80)

    cache_file = BASE_DIR / "benchmark_results_cache.json"
    logs_cache_file = BASE_DIR / "benchmark_raw_logs.json"
    cold_start_file = BASE_DIR / "benchmark_cold_start.json"

    # 1. Discovery
    logger.info("Discovering all registered API endpoints across the codebase...")
    inventory = discover_all_endpoints()
    total_endpoints = len(inventory)
    total_combos = sum(len(item["methods"]) for item in inventory)
    logger.info(f"Discovered {total_endpoints} API endpoints with {total_combos} method combinations.")

    if args.from_cache and cache_file.exists() and logs_cache_file.exists():
        import json
        logger.info(f"Loading cached benchmark data from {cache_file}...")
        with open(cache_file, "r") as f:
            results = json.load(f)
        with open(logs_cache_file, "r") as f:
            raw_logs = json.load(f)
        cold_start_info = {}
        if cold_start_file.exists():
            with open(cold_start_file, "r") as f:
                cold_start_info = json.load(f)
    else:
        if args.limit > 0:
            inventory = inventory[: args.limit]
            logger.info(f"Limiting benchmark run to first {len(inventory)} endpoints as requested.")

        # 2. Benchmark Initialization
        auth_mgr = AuthManager()
        payload_prov = PayloadProvider()
        runner = BenchmarkRunner(auth_mgr, payload_prov)

        # 3. Execution
        logger.info("Beginning benchmark execution across Localhost and Render...")

        def progress_callback(current, total, path, method):
            if current % 10 == 0 or current == total or current == 1:
                print(f"[{current}/{total}] Testing {method} {path}")

        results = runner.run_all(inventory, progress_callback=progress_callback)
        raw_logs = runner.raw_logs
        cold_start_info = runner.cold_start_info

        # Cache results to disk immediately
        import json
        with open(cache_file, "w") as f:
            json.dump(results, f, indent=2)
        with open(logs_cache_file, "w") as f:
            json.dump(raw_logs, f, indent=2)
        with open(cold_start_file, "w") as f:
            json.dump(cold_start_info, f, indent=2)
        logger.info(f"Saved benchmark results cache to {cache_file}")

    # 4. Excel Generation
    logger.info("Generating comprehensive Excel workbook...")
    out_path = Path(args.output).resolve()
    generator = ExcelReportGenerator(str(out_path))
    generator.generate(inventory, results, raw_logs, cold_start_info)

    # Also save to root if different
    root_report = BASE_DIR / REPORT_FILENAME
    if out_path != root_report:
        import shutil
        shutil.copyfile(out_path, root_report)

    # 5. Summary Output
    executed = [r for r in results if r["render_avg_ms"] > 0 and r["local_avg_ms"] > 0]
    loc_avgs = [r["local_avg_ms"] for r in executed]
    ren_avgs = [r["render_avg_ms"] for r in executed]

    overall_loc = round(sum(loc_avgs) / len(loc_avgs), 2) if loc_avgs else 0.0
    overall_ren = round(sum(ren_avgs) / len(ren_avgs), 2) if ren_avgs else 0.0

    print("\n" + "=" * 80)
    print("BENCHMARK COMPLETED SUCCESSFULLY!")
    print(f"Excel Report Path : {out_path}")
    print(f"Total Combinations: {len(results)}")
    print(f"Successful Tests  : {sum(1 for r in results if r['test_status'] == 'SUCCESS')}")
    print(f"Safety Restricted : {sum(1 for r in results if r['test_status'].startswith('NOT EXECUTED'))}")
    print(f"Blocked Tests     : {sum(1 for r in results if r['test_status'] == 'BLOCKED')}")
    print(f"Localhost Avg (ms): {overall_loc:.2f} ms")
    print(f"Render Avg (ms)   : {overall_ren:.2f} ms")
    print(f"Difference (ms)   : {round(overall_ren - overall_loc, 2):.2f} ms")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
