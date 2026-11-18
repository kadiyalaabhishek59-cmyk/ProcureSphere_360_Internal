"""
Benchmark Execution Engine for Localhost and Render.
Performs warm-ups, executes sequential requests with microsecond accuracy,
records raw logs, computes stats, and handles safety constraints.
"""

import time
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Tuple

from .auth import AuthManager
from .payloads import PayloadProvider, is_safety_restricted
from .stats import compute_metrics, compute_differences
from .config import WARMUP_REQUESTS, MEASURED_REQUESTS, REQUEST_TIMEOUT

logger = logging.getLogger("benchmark.runner")


class BenchmarkRunner:
    def __init__(self, auth_mgr: AuthManager, payload_prov: PayloadProvider):
        self.auth_mgr = auth_mgr
        self.payload_prov = payload_prov
        self.raw_logs: List[Dict[str, Any]] = []
        self.cold_start_info: Dict[str, Any] = {}

    def run_single_request(
        self,
        session,
        method: str,
        full_url: str,
        payload: Any = None,
    ) -> Tuple[float, int, float, str]:
        """
        Executes a single HTTP request and measures duration precisely in milliseconds.
        Returns: (duration_ms, status_code, size_kb, error_msg)
        """
        method_upper = method.upper()
        t0 = time.perf_counter()
        status_code = 0
        size_kb = 0.0
        error_msg = ""

        try:
            kwargs = {"timeout": REQUEST_TIMEOUT}
            if payload is not None and method_upper in ["POST", "PUT", "PATCH"]:
                kwargs["json"] = payload

            resp = session.request(method_upper, full_url, **kwargs)
            t1 = time.perf_counter()
            duration_ms = round((t1 - t0) * 1000.0, 2)
            status_code = resp.status_code
            size_kb = round(len(resp.content) / 1024.0, 2)
            if status_code >= 400:
                error_msg = f"HTTP {status_code}: {resp.text[:120].strip()}"
        except Exception as exc:
            t1 = time.perf_counter()
            duration_ms = round((t1 - t0) * 1000.0, 2)
            error_msg = str(exc)

        return duration_ms, status_code, size_kb, error_msg

    def benchmark_target(
        self,
        env: str,
        endpoint_meta: Dict[str, Any],
        method: str,
    ) -> Dict[str, Any]:
        """
        Executes the benchmark for a single endpoint-method combination in one environment.
        """
        path = endpoint_meta["path"]
        role = endpoint_meta["role"]
        module = endpoint_meta["module"]
        base_url = self.auth_mgr.base_urls[env]

        # 1. Check safety restrictions
        restricted, reason = is_safety_restricted(method, path)
        if restricted:
            return {
                "status": "NOT EXECUTED – SAFETY RESTRICTION",
                "avg_ms": 0.0,
                "min_ms": 0.0,
                "max_ms": 0.0,
                "p95_ms": 0.0,
                "p99_ms": 0.0,
                "individual_times": [],
                "status_code": 0,
                "size_kb": 0.0,
                "success_count": 0,
                "fail_count": 0,
                "error": reason,
            }

        # 2. Resolve parameters ({id}, {vendor_id}, etc.)
        resolved_path = self.payload_prov.resolve_path(path, env)
        if "{" in resolved_path and "}" in resolved_path:
            return {
                "status": "BLOCKED",
                "avg_ms": 0.0,
                "min_ms": 0.0,
                "max_ms": 0.0,
                "p95_ms": 0.0,
                "p99_ms": 0.0,
                "individual_times": [],
                "status_code": 0,
                "size_kb": 0.0,
                "success_count": 0,
                "fail_count": 0,
                "error": f"Prerequisite record not found in database for path parameter: {resolved_path}",
            }

        full_url = f"{base_url}{resolved_path}"
        session = self.auth_mgr.get_session(env, role)
        payload = self.payload_prov.get_payload(method, path, env)

        # 3. Warm-up request
        for _ in range(WARMUP_REQUESTS):
            self.run_single_request(session, method, full_url, payload)

        # 4. Measured sequential requests
        durations = []
        status_codes = []
        sizes = []
        errors = []

        for req_idx in range(1, MEASURED_REQUESTS + 1):
            ts = datetime.now(timezone.utc).isoformat()
            duration_ms, status_code, size_kb, err = self.run_single_request(
                session, method, full_url, payload
            )

            durations.append(duration_ms)
            status_codes.append(status_code)
            sizes.append(size_kb)
            if err:
                errors.append(err)

            outcome = "SUCCESS" if 200 <= status_code < 400 else "FAILED"
            self.raw_logs.append({
                "timestamp": ts,
                "environment": env.upper(),
                "endpoint": path,
                "resolved_url": full_url,
                "method": method,
                "module": module,
                "role": role,
                "request_num": req_idx,
                "status_code": status_code,
                "response_time_ms": duration_ms,
                "response_size_kb": size_kb,
                "outcome": outcome,
                "error": err,
            })

        metrics = compute_metrics(durations)
        success_count = sum(1 for sc in status_codes if 200 <= sc < 400)
        fail_count = len(status_codes) - success_count
        dominant_status = status_codes[-1] if status_codes else 0
        avg_size = round(sum(sizes) / len(sizes), 2) if sizes else 0.0

        exec_status = "SUCCESS" if fail_count == 0 else ("PARTIAL" if success_count > 0 else "FAILED")

        return {
            "status": exec_status,
            "avg_ms": metrics["avg_ms"],
            "min_ms": metrics["min_ms"],
            "max_ms": metrics["max_ms"],
            "p95_ms": metrics["p95_ms"],
            "p99_ms": metrics["p99_ms"],
            "individual_times": durations,
            "status_code": dominant_status,
            "size_kb": avg_size,
            "success_count": success_count,
            "fail_count": fail_count,
            "error": "; ".join(set(errors)) if errors else "",
        }

    def run_all(
        self,
        inventory: List[Dict[str, Any]],
        progress_callback=None,
    ) -> List[Dict[str, Any]]:
        """
        Executes the benchmark across both Localhost and Render for all discovered combinations.
        """
        # Pre-fetch IDs in both environments
        local_admin_session = self.auth_mgr.get_session("local", "Super Admin")
        render_admin_session = self.auth_mgr.get_session("render", "Super Admin")

        logger.info("Pre-fetching entity IDs for parameter resolution...")
        self.payload_prov.fetch_environment_ids("local", local_admin_session, self.auth_mgr.base_urls["local"])
        self.payload_prov.fetch_environment_ids("render", render_admin_session, self.auth_mgr.base_urls["render"])

        # Check Render Cold Start
        logger.info("Assessing Render initial response and potential cold-start...")
        self.cold_start_info = self.auth_mgr.warm_up_render()
        logger.info(f"Render cold start check: {self.cold_start_info}")

        results = []
        total_tests = sum(len(item["methods"]) for item in inventory)
        current = 0

        for item in inventory:
            for method in item["methods"]:
                current += 1
                if progress_callback:
                    progress_callback(current, total_tests, item["path"], method)

                # Benchmark Localhost
                local_res = self.benchmark_target("local", item, method)

                # Benchmark Render
                render_res = self.benchmark_target("render", item, method)

                # Compute Differences
                diff_ms, pct_diff = compute_differences(local_res["avg_ms"], render_res["avg_ms"])

                # Overall Test Status
                if local_res["status"].startswith("NOT EXECUTED") or render_res["status"].startswith("NOT EXECUTED"):
                    overall_status = "NOT EXECUTED – SAFETY RESTRICTION"
                elif local_res["status"] == "BLOCKED" or render_res["status"] == "BLOCKED":
                    overall_status = "BLOCKED"
                elif local_res["status"] == "SUCCESS" and render_res["status"] == "SUCCESS":
                    overall_status = "SUCCESS"
                else:
                    overall_status = "FAILED"

                combined = {
                    "module": item["module"],
                    "endpoint": item["path"],
                    "method": method,
                    "role": item["role"],
                    "view_name": item["view_name"],
                    "source_file": item["source_file"],
                    "test_status": overall_status,
                    # Localhost metrics
                    "local_status": local_res["status"],
                    "local_avg_ms": local_res["avg_ms"],
                    "local_min_ms": local_res["min_ms"],
                    "local_max_ms": local_res["max_ms"],
                    "local_p95_ms": local_res["p95_ms"],
                    "local_p99_ms": local_res["p99_ms"],
                    "local_individual_ms": local_res["individual_times"],
                    "local_size_kb": local_res["size_kb"],
                    "local_http_status": local_res["status_code"],
                    "local_success_count": local_res["success_count"],
                    "local_fail_count": local_res["fail_count"],
                    "local_error": local_res["error"],
                    # Render metrics
                    "render_status": render_res["status"],
                    "render_avg_ms": render_res["avg_ms"],
                    "render_min_ms": render_res["min_ms"],
                    "render_max_ms": render_res["max_ms"],
                    "render_p95_ms": render_res["p95_ms"],
                    "render_p99_ms": render_res["p99_ms"],
                    "render_individual_ms": render_res["individual_times"],
                    "render_size_kb": render_res["size_kb"],
                    "render_http_status": render_res["status_code"],
                    "render_success_count": render_res["success_count"],
                    "render_fail_count": render_res["fail_count"],
                    "render_error": render_res["error"],
                    # Comparison
                    "diff_ms": diff_ms,
                    "pct_diff": pct_diff,
                }
                results.append(combined)

        return results
