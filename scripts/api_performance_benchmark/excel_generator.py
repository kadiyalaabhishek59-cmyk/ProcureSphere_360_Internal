"""
Comprehensive Excel Report Generator for ProcureSphere 360 API Benchmark.
Generates an 11-sheet workbook strictly using milliseconds (ms) with professional styling and charts.
"""

import os
from datetime import datetime, timezone
from typing import List, Dict, Any

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.chart import BarChart, Reference, Series

from .stats import compute_metrics


def style_header_row(ws, row_idx: int, col_count: int, bg_color: str = "1E3A8A", text_color: str = "FFFFFF"):
    fill = PatternFill(start_color=bg_color, end_color=bg_color, fill_type="solid")
    font = Font(name="Calibri", size=11, bold=True, color=text_color)
    alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin = Side(border_style="thin", color="CCCCCC")
    border = Border(top=thin, left=thin, right=thin, bottom=thin)

    ws.row_dimensions[row_idx].height = 28
    for col in range(1, col_count + 1):
        cell = ws.cell(row=row_idx, column=col)
        cell.fill = fill
        cell.font = font
        cell.alignment = alignment
        cell.border = border


def apply_cell_border(cell):
    thin = Side(border_style="thin", color="E0E0E0")
    cell.border = Border(top=thin, left=thin, right=thin, bottom=thin)


def auto_fit_columns(ws, min_width: int = 12, max_width: int = 55):
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            val_str = str(cell.value or "")
            if "\n" in val_str:
                val_str = max(val_str.split("\n"), key=len)
            max_len = max(max_len, len(val_str))
        width = max(max_len + 3, min_width)
        ws.column_dimensions[col_letter].width = min(width, max_width)


class ExcelReportGenerator:
    def __init__(self, filename: str):
        self.filename = filename
        self.wb = openpyxl.Workbook()
        # Remove default sheet
        default_sheet = self.wb.active
        self.wb.remove(default_sheet)

    def generate(
        self,
        inventory: List[Dict[str, Any]],
        results: List[Dict[str, Any]],
        raw_logs: List[Dict[str, Any]],
        cold_start_info: Dict[str, Any],
    ):
        """Generates all 11 required worksheets and saves the workbook."""
        self._build_sheet1_executive_summary(inventory, results, cold_start_info)
        self._build_sheet2_endpoint_inventory(inventory)
        self._build_sheet3_detailed_comparison(results)
        self._build_sheet4_localhost_detailed(raw_logs)
        self._build_sheet5_render_detailed(raw_logs)
        self._build_sheet6_method_analysis(results)
        self._build_sheet7_module_analysis(results)
        self._build_sheet8_slow_endpoints(results)
        self._build_sheet9_failed_blocked(results)
        self._build_sheet10_individual_logs(raw_logs)
        self._build_sheet11_charts(results)

        try:
            self.wb.save(self.filename)
        except PermissionError:
            # Fallback if primary file is opened by another application
            fallback = self.filename.replace(".xlsx", "_latest.xlsx")
            self.wb.save(fallback)
            self.filename = fallback
        return self.filename

    def _build_sheet1_executive_summary(self, inventory, results, cold_start_info):
        ws = self.wb.create_sheet("Executive Summary")
        ws.views.sheetView[0].showGridLines = True

        # Title
        ws.merge_cells("A1:H1")
        title_cell = ws["A1"]
        title_cell.value = "ProcureSphere 360 – API Performance Benchmark Executive Summary"
        title_cell.font = Font(name="Calibri", size=16, bold=True, color="1E3A8A")
        title_cell.alignment = Alignment(horizontal="left", vertical="center")
        ws.row_dimensions[1].height = 35

        # Subtitle
        ws.merge_cells("A2:H2")
        ws["A2"].value = f"Execution Timestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} | Strict Milliseconds (ms) Metrics | No Category Classifications"
        ws["A2"].font = Font(name="Calibri", size=10, italic=True, color="475569")
        ws.row_dimensions[2].height = 20

        # High-level Statistics calculation
        total_discovered_endpoints = len(inventory)
        total_combinations = len(results)
        tested_combinations = sum(1 for r in results if r["test_status"] in ["SUCCESS", "FAILED", "PARTIAL"])
        successful_combinations = sum(1 for r in results if r["test_status"] == "SUCCESS")
        failed_combinations = sum(1 for r in results if r["test_status"] == "FAILED")
        blocked_combinations = sum(1 for r in results if r["test_status"] == "BLOCKED")
        skipped_safety = sum(1 for r in results if r["test_status"].startswith("NOT EXECUTED"))

        valid_local_avgs = [r["local_avg_ms"] for r in results if r["local_avg_ms"] > 0]
        valid_render_avgs = [r["render_avg_ms"] for r in results if r["render_avg_ms"] > 0]

        local_overall_avg = round(sum(valid_local_avgs) / len(valid_local_avgs), 2) if valid_local_avgs else 0.0
        render_overall_avg = round(sum(valid_render_avgs) / len(valid_render_avgs), 2) if valid_render_avgs else 0.0

        local_overall_p95 = round(compute_metrics(valid_local_avgs)["p95_ms"], 2) if valid_local_avgs else 0.0
        render_overall_p95 = round(compute_metrics(valid_render_avgs)["p95_ms"], 2) if valid_render_avgs else 0.0

        local_overall_p99 = round(compute_metrics(valid_local_avgs)["p99_ms"], 2) if valid_local_avgs else 0.0
        render_overall_p99 = round(compute_metrics(valid_render_avgs)["p99_ms"], 2) if valid_render_avgs else 0.0

        # Fastest and Slowest endpoint on Render
        executed_on_render = [r for r in results if r["render_avg_ms"] > 0]
        executed_on_render_sorted = sorted(executed_on_render, key=lambda x: x["render_avg_ms"])
        fastest_ep = executed_on_render_sorted[0] if executed_on_render_sorted else None
        slowest_ep = executed_on_render_sorted[-1] if executed_on_render_sorted else None

        # Section 1: Benchmark Summary Table
        summary_rows = [
            ("Total Discovered API Endpoints", total_discovered_endpoints),
            ("Total Endpoint-Method Combinations", total_combinations),
            ("Total Tested Combinations", tested_combinations),
            ("Total Successful Combinations", successful_combinations),
            ("Total Failed Combinations", failed_combinations),
            ("Total Blocked Combinations", blocked_combinations),
            ("Total Skipped (Safety Restriction)", skipped_safety),
            ("Localhost Overall Average Latency (ms)", local_overall_avg),
            ("Render Overall Average Latency (ms)", render_overall_avg),
            ("Localhost P95 Latency (ms)", local_overall_p95),
            ("Render P95 Latency (ms)", render_overall_p95),
            ("Localhost P99 Latency (ms)", local_overall_p99),
            ("Render P99 Latency (ms)", render_overall_p99),
            ("Overall Latency Difference: Render - Local (ms)", round(render_overall_avg - local_overall_avg, 2)),
            (
                "Overall Latency Difference (%)",
                round(((render_overall_avg - local_overall_avg) / local_overall_avg * 100.0), 2)
                if local_overall_avg > 0
                else 0.0,
            ),
            (
                "Fastest Endpoint (Render)",
                f"{fastest_ep['method']} {fastest_ep['endpoint']} ({fastest_ep['render_avg_ms']:.2f} ms)"
                if fastest_ep
                else "N/A",
            ),
            (
                "Slowest Endpoint (Render)",
                f"{slowest_ep['method']} {slowest_ep['endpoint']} ({slowest_ep['render_avg_ms']:.2f} ms)"
                if slowest_ep
                else "N/A",
            ),
            (
                "Render Cold-Start Initial Request (ms)",
                f"{cold_start_info.get('first_request_ms', 0.0):.2f} ms (Status: {cold_start_info.get('status_code', 'N/A')})",
            ),
        ]

        ws["A4"] = "Benchmark Scope & Key Numerical Metrics"
        ws["A4"].font = Font(name="Calibri", size=13, bold=True, color="1E3A8A")

        row = 5
        for label, val in summary_rows:
            ws.cell(row=row, column=1, value=label).font = Font(name="Calibri", size=11, bold=True)
            val_cell = ws.cell(row=row, column=2, value=val)
            val_cell.font = Font(name="Calibri", size=11)
            if isinstance(val, (int, float)):
                val_cell.number_format = "#,##0.00" if isinstance(val, float) else "#,##0"
                val_cell.alignment = Alignment(horizontal="right")
            apply_cell_border(ws.cell(row=row, column=1))
            apply_cell_border(val_cell)
            row += 1

        # Section 2: Top 20 Slowest Endpoints on Render
        row += 2
        ws.cell(row=row, column=1, value="Top 20 Slowest Endpoints on Render (Ranked by Measured Response Time)").font = (
            Font(name="Calibri", size=13, bold=True, color="1E3A8A")
        )
        row += 1

        top_headers = [
            "Rank",
            "Module",
            "Endpoint Path",
            "Method",
            "Localhost Avg (ms)",
            "Render Avg (ms)",
            "Difference (ms)",
            "Difference (%)",
        ]
        for c_idx, h in enumerate(top_headers, 1):
            ws.cell(row=row, column=c_idx, value=h)
        style_header_row(ws, row, len(top_headers), bg_color="0F172A")
        header_row_idx = row

        top20_slowest = sorted(executed_on_render, key=lambda x: x["render_avg_ms"], reverse=True)[:20]
        for idx, item in enumerate(top20_slowest, 1):
            row += 1
            ws.cell(row=row, column=1, value=idx).alignment = Alignment(horizontal="center")
            ws.cell(row=row, column=2, value=item["module"])
            ws.cell(row=row, column=3, value=item["endpoint"])
            ws.cell(row=row, column=4, value=item["method"]).alignment = Alignment(horizontal="center")

            c_loc = ws.cell(row=row, column=5, value=item["local_avg_ms"])
            c_loc.number_format = "#,##0.00"
            c_loc.alignment = Alignment(horizontal="right")

            c_ren = ws.cell(row=row, column=6, value=item["render_avg_ms"])
            c_ren.number_format = "#,##0.00"
            c_ren.alignment = Alignment(horizontal="right")

            c_diff = ws.cell(row=row, column=7, value=item["diff_ms"])
            c_diff.number_format = "#,##0.00"
            c_diff.alignment = Alignment(horizontal="right")

            c_pct = ws.cell(row=row, column=8, value=item["pct_diff"])
            c_pct.number_format = "#,##0.00"
            c_pct.alignment = Alignment(horizontal="right")

            for col in range(1, 9):
                apply_cell_border(ws.cell(row=row, column=col))

        auto_fit_columns(ws)

    def _build_sheet2_endpoint_inventory(self, inventory):
        ws = self.wb.create_sheet("Endpoint Inventory")
        ws.views.sheetView[0].showGridLines = True

        headers = [
            "Module",
            "Endpoint Path",
            "Supported HTTP Methods",
            "Authentication Requirement",
            "Required Role",
            "View Class / Handler",
            "Source File",
            "Testability Status",
        ]
        for c_idx, h in enumerate(headers, 1):
            ws.cell(row=1, column=c_idx, value=h)
        style_header_row(ws, 1, len(headers), bg_color="1E3A8A")

        row = 1
        for item in inventory:
            row += 1
            methods_str = ", ".join(item["methods"])
            auth_req = "No (Public)" if item["role"] == "Anonymous" else "Yes (Session / RBAC)"
            testability = "Executable" if any(m in ["GET", "POST"] for m in item["methods"]) else "Restricted / Safe Mode"

            ws.cell(row=row, column=1, value=item["module"])
            ws.cell(row=row, column=2, value=item["path"])
            ws.cell(row=row, column=3, value=methods_str).alignment = Alignment(horizontal="center")
            ws.cell(row=row, column=4, value=auth_req).alignment = Alignment(horizontal="center")
            ws.cell(row=row, column=5, value=item["role"])
            ws.cell(row=row, column=6, value=item["view_name"])
            ws.cell(row=row, column=7, value=item["source_file"])
            ws.cell(row=row, column=8, value=testability).alignment = Alignment(horizontal="center")

            for col in range(1, len(headers) + 1):
                apply_cell_border(ws.cell(row=row, column=col))

        auto_fit_columns(ws)

    def _build_sheet3_detailed_comparison(self, results):
        ws = self.wb.create_sheet("Detailed Comparison")
        ws.views.sheetView[0].showGridLines = True

        headers = [
            "Module",
            "Endpoint Path",
            "HTTP Method",
            "User Role",
            "Localhost Avg (ms)",
            "Render Avg (ms)",
            "Localhost Min (ms)",
            "Render Min (ms)",
            "Localhost Max (ms)",
            "Render Max (ms)",
            "Localhost P95 (ms)",
            "Render P95 (ms)",
            "Localhost P99 (ms)",
            "Render P99 (ms)",
            "Difference (ms)",
            "Difference (%)",
            "Local Size (KB)",
            "Render Size (KB)",
            "Local HTTP Status",
            "Render HTTP Status",
            "Execution Status",
            "Error Details",
        ]

        for c_idx, h in enumerate(headers, 1):
            ws.cell(row=1, column=c_idx, value=h)
        style_header_row(ws, 1, len(headers), bg_color="1E3A8A")

        row = 1
        for item in results:
            row += 1
            ws.cell(row=row, column=1, value=item["module"])
            ws.cell(row=row, column=2, value=item["endpoint"])
            ws.cell(row=row, column=3, value=item["method"]).alignment = Alignment(horizontal="center")
            ws.cell(row=row, column=4, value=item["role"])

            num_cols = [
                (5, item["local_avg_ms"]),
                (6, item["render_avg_ms"]),
                (7, item["local_min_ms"]),
                (8, item["render_min_ms"]),
                (9, item["local_max_ms"]),
                (10, item["render_max_ms"]),
                (11, item["local_p95_ms"]),
                (12, item["render_p95_ms"]),
                (13, item["local_p99_ms"]),
                (14, item["render_p99_ms"]),
                (15, item["diff_ms"]),
                (16, item["pct_diff"]),
                (17, item["local_size_kb"]),
                (18, item["render_size_kb"]),
            ]
            for col_idx, val in num_cols:
                c = ws.cell(row=row, column=col_idx, value=val)
                c.number_format = "#,##0.00"
                c.alignment = Alignment(horizontal="right")

            ws.cell(row=row, column=19, value=item["local_http_status"]).alignment = Alignment(horizontal="center")
            ws.cell(row=row, column=20, value=item["render_http_status"]).alignment = Alignment(horizontal="center")
            ws.cell(row=row, column=21, value=item["test_status"]).alignment = Alignment(horizontal="center")
            
            err_msg = item["render_error"] or item["local_error"] or ""
            ws.cell(row=row, column=22, value=err_msg)

            for col in range(1, len(headers) + 1):
                apply_cell_border(ws.cell(row=row, column=col))

        auto_fit_columns(ws)

    def _build_sheet4_localhost_detailed(self, raw_logs):
        ws = self.wb.create_sheet("Localhost Detailed")
        ws.views.sheetView[0].showGridLines = True

        headers = [
            "Timestamp",
            "Endpoint",
            "Method",
            "Module",
            "User Role",
            "Request #",
            "HTTP Status",
            "Response Time (ms)",
            "Response Size (KB)",
            "Outcome",
            "Error Details",
        ]
        for c_idx, h in enumerate(headers, 1):
            ws.cell(row=1, column=c_idx, value=h)
        style_header_row(ws, 1, len(headers), bg_color="0369A1")

        row = 1
        local_logs = [log for log in raw_logs if log["environment"] == "LOCAL"]
        for log in local_logs:
            row += 1
            ws.cell(row=row, column=1, value=log["timestamp"])
            ws.cell(row=row, column=2, value=log["endpoint"])
            ws.cell(row=row, column=3, value=log["method"]).alignment = Alignment(horizontal="center")
            ws.cell(row=row, column=4, value=log["module"])
            ws.cell(row=row, column=5, value=log["role"])
            ws.cell(row=row, column=6, value=log["request_num"]).alignment = Alignment(horizontal="center")
            ws.cell(row=row, column=7, value=log["status_code"]).alignment = Alignment(horizontal="center")

            c_time = ws.cell(row=row, column=8, value=log["response_time_ms"])
            c_time.number_format = "#,##0.00"
            c_time.alignment = Alignment(horizontal="right")

            c_size = ws.cell(row=row, column=9, value=log["response_size_kb"])
            c_size.number_format = "#,##0.00"
            c_size.alignment = Alignment(horizontal="right")

            ws.cell(row=row, column=10, value=log["outcome"]).alignment = Alignment(horizontal="center")
            ws.cell(row=row, column=11, value=log["error"])

            for col in range(1, len(headers) + 1):
                apply_cell_border(ws.cell(row=row, column=col))

        auto_fit_columns(ws)

    def _build_sheet5_render_detailed(self, raw_logs):
        ws = self.wb.create_sheet("Render Detailed")
        ws.views.sheetView[0].showGridLines = True

        headers = [
            "Timestamp",
            "Endpoint",
            "Method",
            "Module",
            "User Role",
            "Request #",
            "HTTP Status",
            "Response Time (ms)",
            "Response Size (KB)",
            "Outcome",
            "Error Details",
        ]
        for c_idx, h in enumerate(headers, 1):
            ws.cell(row=1, column=c_idx, value=h)
        style_header_row(ws, 1, len(headers), bg_color="4338CA")

        row = 1
        render_logs = [log for log in raw_logs if log["environment"] == "RENDER"]
        for log in render_logs:
            row += 1
            ws.cell(row=row, column=1, value=log["timestamp"])
            ws.cell(row=row, column=2, value=log["endpoint"])
            ws.cell(row=row, column=3, value=log["method"]).alignment = Alignment(horizontal="center")
            ws.cell(row=row, column=4, value=log["module"])
            ws.cell(row=row, column=5, value=log["role"])
            ws.cell(row=row, column=6, value=log["request_num"]).alignment = Alignment(horizontal="center")
            ws.cell(row=row, column=7, value=log["status_code"]).alignment = Alignment(horizontal="center")

            c_time = ws.cell(row=row, column=8, value=log["response_time_ms"])
            c_time.number_format = "#,##0.00"
            c_time.alignment = Alignment(horizontal="right")

            c_size = ws.cell(row=row, column=9, value=log["response_size_kb"])
            c_size.number_format = "#,##0.00"
            c_size.alignment = Alignment(horizontal="right")

            ws.cell(row=row, column=10, value=log["outcome"]).alignment = Alignment(horizontal="center")
            ws.cell(row=row, column=11, value=log["error"])

            for col in range(1, len(headers) + 1):
                apply_cell_border(ws.cell(row=row, column=col))

        auto_fit_columns(ws)

    def _build_sheet6_method_analysis(self, results):
        ws = self.wb.create_sheet("HTTP Method Analysis")
        ws.views.sheetView[0].showGridLines = True

        headers = [
            "HTTP Method",
            "Total Combinations",
            "Tested Combinations",
            "Localhost Avg (ms)",
            "Render Avg (ms)",
            "Localhost Min (ms)",
            "Render Min (ms)",
            "Localhost Max (ms)",
            "Render Max (ms)",
            "Localhost P95 (ms)",
            "Render P95 (ms)",
            "Difference (ms)",
            "Difference (%)",
        ]
        for c_idx, h in enumerate(headers, 1):
            ws.cell(row=1, column=c_idx, value=h)
        style_header_row(ws, 1, len(headers), bg_color="1E3A8A")

        methods = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
        row = 1
        for m in methods:
            items = [r for r in results if r["method"] == m]
            if not items:
                continue

            row += 1
            total_count = len(items)
            tested = [r for r in items if r["test_status"] in ["SUCCESS", "FAILED", "PARTIAL"]]
            tested_count = len(tested)

            loc_times = [r["local_avg_ms"] for r in tested if r["local_avg_ms"] > 0]
            ren_times = [r["render_avg_ms"] for r in tested if r["render_avg_ms"] > 0]

            loc_metrics = compute_metrics(loc_times)
            ren_metrics = compute_metrics(ren_times)

            diff_ms = round(ren_metrics["avg_ms"] - loc_metrics["avg_ms"], 2)
            pct_diff = (
                round(((ren_metrics["avg_ms"] - loc_metrics["avg_ms"]) / loc_metrics["avg_ms"]) * 100.0, 2)
                if loc_metrics["avg_ms"] > 0
                else 0.0
            )

            ws.cell(row=row, column=1, value=m).alignment = Alignment(horizontal="center")
            ws.cell(row=row, column=2, value=total_count).alignment = Alignment(horizontal="right")
            ws.cell(row=row, column=3, value=tested_count).alignment = Alignment(horizontal="right")

            num_cols = [
                (4, loc_metrics["avg_ms"]),
                (5, ren_metrics["avg_ms"]),
                (6, loc_metrics["min_ms"]),
                (7, ren_metrics["min_ms"]),
                (8, loc_metrics["max_ms"]),
                (9, ren_metrics["max_ms"]),
                (10, loc_metrics["p95_ms"]),
                (11, ren_metrics["p95_ms"]),
                (12, diff_ms),
                (13, pct_diff),
            ]
            for col_idx, val in num_cols:
                c = ws.cell(row=row, column=col_idx, value=val)
                c.number_format = "#,##0.00"
                c.alignment = Alignment(horizontal="right")

            for col in range(1, len(headers) + 1):
                apply_cell_border(ws.cell(row=row, column=col))

        auto_fit_columns(ws)

    def _build_sheet7_module_analysis(self, results):
        ws = self.wb.create_sheet("Module-Wise Analysis")
        ws.views.sheetView[0].showGridLines = True

        headers = [
            "Application Module",
            "Endpoint Count",
            "Tested Count",
            "Localhost Avg (ms)",
            "Render Avg (ms)",
            "Localhost P95 (ms)",
            "Render P95 (ms)",
            "Difference (ms)",
            "Difference (%)",
        ]
        for c_idx, h in enumerate(headers, 1):
            ws.cell(row=1, column=c_idx, value=h)
        style_header_row(ws, 1, len(headers), bg_color="1E3A8A")

        modules = sorted(list(set(r["module"] for r in results)))
        row = 1
        for mod in modules:
            items = [r for r in results if r["module"] == mod]
            row += 1

            total_count = len(items)
            tested = [r for r in items if r["test_status"] in ["SUCCESS", "FAILED", "PARTIAL"]]
            tested_count = len(tested)

            loc_times = [r["local_avg_ms"] for r in tested if r["local_avg_ms"] > 0]
            ren_times = [r["render_avg_ms"] for r in tested if r["render_avg_ms"] > 0]

            loc_metrics = compute_metrics(loc_times)
            ren_metrics = compute_metrics(ren_times)

            diff_ms = round(ren_metrics["avg_ms"] - loc_metrics["avg_ms"], 2)
            pct_diff = (
                round(((ren_metrics["avg_ms"] - loc_metrics["avg_ms"]) / loc_metrics["avg_ms"]) * 100.0, 2)
                if loc_metrics["avg_ms"] > 0
                else 0.0
            )

            ws.cell(row=row, column=1, value=mod)
            ws.cell(row=row, column=2, value=total_count).alignment = Alignment(horizontal="right")
            ws.cell(row=row, column=3, value=tested_count).alignment = Alignment(horizontal="right")

            num_cols = [
                (4, loc_metrics["avg_ms"]),
                (5, ren_metrics["avg_ms"]),
                (6, loc_metrics["p95_ms"]),
                (7, ren_metrics["p95_ms"]),
                (8, diff_ms),
                (9, pct_diff),
            ]
            for col_idx, val in num_cols:
                c = ws.cell(row=row, column=col_idx, value=val)
                c.number_format = "#,##0.00"
                c.alignment = Alignment(horizontal="right")

            for col in range(1, len(headers) + 1):
                apply_cell_border(ws.cell(row=row, column=col))

        auto_fit_columns(ws)

    def _build_sheet8_slow_endpoints(self, results):
        ws = self.wb.create_sheet("Slow Endpoints")
        ws.views.sheetView[0].showGridLines = True

        headers = [
            "Endpoint Path",
            "Method",
            "Module",
            "Localhost Avg (ms)",
            "Render Avg (ms)",
            "Localhost P95 (ms)",
            "Render P95 (ms)",
            "Localhost Max (ms)",
            "Render Max (ms)",
            "Difference (ms)",
            "Suspected Bottleneck",
            "Recommended Investigation",
        ]
        for c_idx, h in enumerate(headers, 1):
            ws.cell(row=1, column=c_idx, value=h)
        style_header_row(ws, 1, len(headers), bg_color="B91C1C")

        # Sort by Render average descending
        executed = [r for r in results if r["render_avg_ms"] > 0]
        sorted_slow = sorted(executed, key=lambda x: x["render_avg_ms"], reverse=True)

        row = 1
        for item in sorted_slow:
            row += 1
            ws.cell(row=row, column=1, value=item["endpoint"])
            ws.cell(row=row, column=2, value=item["method"]).alignment = Alignment(horizontal="center")
            ws.cell(row=row, column=3, value=item["module"])

            num_cols = [
                (4, item["local_avg_ms"]),
                (5, item["render_avg_ms"]),
                (6, item["local_p95_ms"]),
                (7, item["render_p95_ms"]),
                (8, item["local_max_ms"]),
                (9, item["render_max_ms"]),
                (10, item["diff_ms"]),
            ]
            for col_idx, val in num_cols:
                c = ws.cell(row=row, column=col_idx, value=val)
                c.number_format = "#,##0.00"
                c.alignment = Alignment(horizontal="right")

            # Determine suspected bottleneck based on measurements
            diff = item["diff_ms"]
            loc = item["local_avg_ms"]
            ren = item["render_avg_ms"]
            if loc > 150.0:
                bottleneck = "ORM query complexity / aggregation / N+1 database queries"
                recommendation = "Inspect Django ORM queries using assertNumQueries; add select_related or prefetch_related."
            elif diff > 300.0:
                bottleneck = "Network round-trip latency & Render reverse-proxy TLS overhead"
                recommendation = "Profile network round-trip timing and consider CDN or HTTP connection reuse."
            elif ren > 200.0:
                bottleneck = "Serialization overhead on large JSON result payloads"
                recommendation = "Verify pagination limit and defer non-essential serializer fields."
            else:
                bottleneck = "Standard network transit difference between cloud hosting and loopback"
                recommendation = "Monitor performance under multi-user concurrency."

            ws.cell(row=row, column=11, value=bottleneck)
            ws.cell(row=row, column=12, value=recommendation)

            for col in range(1, len(headers) + 1):
                apply_cell_border(ws.cell(row=row, column=col))

        auto_fit_columns(ws)

    def _build_sheet9_failed_blocked(self, results):
        ws = self.wb.create_sheet("Failed & Blocked Tests")
        ws.views.sheetView[0].showGridLines = True

        headers = [
            "Endpoint Path",
            "Method",
            "Module",
            "User Role",
            "Test Execution Status",
            "Local HTTP Status",
            "Render HTTP Status",
            "Error Details",
            "Root Cause Category",
            "Recommended Next Action",
        ]
        for c_idx, h in enumerate(headers, 1):
            ws.cell(row=1, column=c_idx, value=h)
        style_header_row(ws, 1, len(headers), bg_color="475569")

        non_success = [r for r in results if r["test_status"] != "SUCCESS"]
        row = 1
        for item in non_success:
            row += 1
            ws.cell(row=row, column=1, value=item["endpoint"])
            ws.cell(row=row, column=2, value=item["method"]).alignment = Alignment(horizontal="center")
            ws.cell(row=row, column=3, value=item["module"])
            ws.cell(row=row, column=4, value=item["role"])
            ws.cell(row=row, column=5, value=item["test_status"]).alignment = Alignment(horizontal="center")
            ws.cell(row=row, column=6, value=item["local_http_status"]).alignment = Alignment(horizontal="center")
            ws.cell(row=row, column=7, value=item["render_http_status"]).alignment = Alignment(horizontal="center")

            err = item["render_error"] or item["local_error"] or ""
            ws.cell(row=row, column=8, value=err)

            if item["test_status"].startswith("NOT EXECUTED"):
                cause = "Safety Guardrail"
                action = "Execute exclusively in ephemeral staging/test databases with disposable records."
            elif item["test_status"] == "BLOCKED":
                cause = "Missing Prerequisite Record"
                action = "Seed target entity record in environment before running detail/nested route."
            elif "401" in err or "403" in err:
                cause = "Authentication / RBAC Permission"
                action = "Verify role assignment and token authorization for specific role."
            else:
                cause = "Application / Validation"
                action = "Inspect request payload schema and server-side validation rules."

            ws.cell(row=row, column=9, value=cause)
            ws.cell(row=row, column=10, value=action)

            for col in range(1, len(headers) + 1):
                apply_cell_border(ws.cell(row=row, column=col))

        auto_fit_columns(ws)

    def _build_sheet10_individual_logs(self, raw_logs):
        ws = self.wb.create_sheet("Individual Request Logs")
        ws.views.sheetView[0].showGridLines = True

        headers = [
            "Timestamp (UTC)",
            "Environment",
            "Endpoint Path",
            "HTTP Method",
            "Application Module",
            "User Role",
            "Request #",
            "HTTP Status Code",
            "Response Time (ms)",
            "Response Size (KB)",
            "Request Outcome",
            "Error Details",
        ]
        for c_idx, h in enumerate(headers, 1):
            ws.cell(row=1, column=c_idx, value=h)
        style_header_row(ws, 1, len(headers), bg_color="1E3A8A")

        row = 1
        for log in raw_logs:
            row += 1
            ws.cell(row=row, column=1, value=log["timestamp"])
            ws.cell(row=row, column=2, value=log["environment"]).alignment = Alignment(horizontal="center")
            ws.cell(row=row, column=3, value=log["endpoint"])
            ws.cell(row=row, column=4, value=log["method"]).alignment = Alignment(horizontal="center")
            ws.cell(row=row, column=5, value=log["module"])
            ws.cell(row=row, column=6, value=log["role"])
            ws.cell(row=row, column=7, value=log["request_num"]).alignment = Alignment(horizontal="center")
            ws.cell(row=row, column=8, value=log["status_code"]).alignment = Alignment(horizontal="center")

            c_time = ws.cell(row=row, column=9, value=log["response_time_ms"])
            c_time.number_format = "#,##0.00"
            c_time.alignment = Alignment(horizontal="right")

            c_size = ws.cell(row=row, column=10, value=log["response_size_kb"])
            c_size.number_format = "#,##0.00"
            c_size.alignment = Alignment(horizontal="right")

            ws.cell(row=row, column=11, value=log["outcome"]).alignment = Alignment(horizontal="center")
            ws.cell(row=row, column=12, value=log["error"])

            for col in range(1, len(headers) + 1):
                apply_cell_border(ws.cell(row=row, column=col))

        auto_fit_columns(ws)

    def _build_sheet11_charts(self, results):
        ws = self.wb.create_sheet("Performance Charts")
        ws.views.sheetView[0].showGridLines = True

        ws["A1"] = "ProcureSphere 360 – API Performance Benchmark Charts"
        ws["A1"].font = Font(name="Calibri", size=16, bold=True, color="1E3A8A")
        ws["A2"] = "All response times, latencies, and differences are strictly displayed in milliseconds (ms)."
        ws["A2"].font = Font(name="Calibri", size=11, italic=True, color="475569")

        sheet1 = self.wb["Executive Summary"]
        sheet6 = self.wb["HTTP Method Analysis"]
        sheet7 = self.wb["Module-Wise Analysis"]

        # Chart 1: Localhost vs Render Average Response Time by Module
        chart1 = BarChart()
        chart1.type = "col"
        chart1.style = 10
        chart1.title = "1. Localhost vs Render Average Response Time by Module (ms)"
        chart1.y_axis.title = "Response Time (ms)"
        chart1.x_axis.title = "Application Module"
        chart1.width = 17
        chart1.height = 11

        data1 = Reference(sheet7, min_col=4, min_row=1, max_col=5, max_row=sheet7.max_row)
        cats1 = Reference(sheet7, min_col=1, min_row=2, max_row=sheet7.max_row)
        chart1.add_data(data1, titles_from_data=True)
        chart1.set_categories(cats1)
        ws.add_chart(chart1, "B4")

        # Chart 2: Localhost vs Render P95 Latency by Module
        chart2 = BarChart()
        chart2.type = "col"
        chart2.style = 11
        chart2.title = "2. Localhost vs Render P95 Latency by Module (ms)"
        chart2.y_axis.title = "P95 Latency (ms)"
        chart2.x_axis.title = "Application Module"
        chart2.width = 17
        chart2.height = 11

        data2 = Reference(sheet7, min_col=6, min_row=1, max_col=7, max_row=sheet7.max_row)
        chart2.add_data(data2, titles_from_data=True)
        chart2.set_categories(cats1)
        ws.add_chart(chart2, "L4")

        # Chart 3: HTTP Method-Wise Response Time Comparison
        chart3 = BarChart()
        chart3.type = "col"
        chart3.style = 12
        chart3.title = "3. HTTP-Method-Wise Response Time Comparison (ms)"
        chart3.y_axis.title = "Response Time (ms)"
        chart3.x_axis.title = "HTTP Method"
        chart3.width = 17
        chart3.height = 11

        data3 = Reference(sheet6, min_col=4, min_row=1, max_col=5, max_row=sheet6.max_row)
        cats3 = Reference(sheet6, min_col=1, min_row=2, max_row=sheet6.max_row)
        chart3.add_data(data3, titles_from_data=True)
        chart3.set_categories(cats3)
        ws.add_chart(chart3, "B20")

        # Chart 4: Module-Wise Response Time Difference (Render - Localhost)
        chart4 = BarChart()
        chart4.type = "col"
        chart4.style = 13
        chart4.title = "4. Localhost vs Render Latency Difference by Module (ms)"
        chart4.y_axis.title = "Difference: Render - Local (ms)"
        chart4.x_axis.title = "Application Module"
        chart4.width = 17
        chart4.height = 11

        data4 = Reference(sheet7, min_col=8, min_row=1, max_col=8, max_row=sheet7.max_row)
        chart4.add_data(data4, titles_from_data=True)
        chart4.set_categories(cats1)
        chart4.legend = None
        ws.add_chart(chart4, "L20")

        # Chart 5: Top 20 Slowest Endpoints on Render
        chart5 = BarChart()
        chart5.type = "bar"
        chart5.style = 14
        chart5.title = "5. Top 20 Slowest Endpoints on Render (ms)"
        chart5.x_axis.title = "Response Time (ms)"
        chart5.y_axis.title = "Endpoint"
        chart5.width = 17
        chart5.height = 14

        top20_header_row = 26
        for r in range(1, 40):
            if sheet1.cell(row=r, column=1).value == "Rank":
                top20_header_row = r
                break

        max_top20_row = min(top20_header_row + 20, sheet1.max_row)
        data5 = Reference(sheet1, min_col=6, min_row=top20_header_row, max_col=6, max_row=max_top20_row)
        cats5 = Reference(sheet1, min_col=3, min_row=top20_header_row + 1, max_row=max_top20_row)
        chart5.add_data(data5, titles_from_data=True)
        chart5.set_categories(cats5)
        chart5.legend = None
        ws.add_chart(chart5, "B36")

        # Chart 6: HTTP Method Difference (Render - Localhost)
        chart6 = BarChart()
        chart6.type = "col"
        chart6.style = 15
        chart6.title = "6. Localhost vs Render Latency Difference by HTTP Method (ms)"
        chart6.y_axis.title = "Difference: Render - Local (ms)"
        chart6.x_axis.title = "HTTP Method"
        chart6.width = 17
        chart6.height = 14

        data6 = Reference(sheet6, min_col=12, min_row=1, max_col=12, max_row=sheet6.max_row)
        chart6.add_data(data6, titles_from_data=True)
        chart6.set_categories(cats3)
        chart6.legend = None
        ws.add_chart(chart6, "L36")
