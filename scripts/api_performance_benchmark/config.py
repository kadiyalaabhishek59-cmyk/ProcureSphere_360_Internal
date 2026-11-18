"""
ProcureSphere 360 API Performance Benchmark Configuration.
"""

import os
from pathlib import Path

_curr = Path(__file__).resolve()
BASE_DIR = _curr.parents[3]
for parent in _curr.parents:
    if (parent / "manage.py").exists():
        BASE_DIR = parent
        break
LOCAL_BASE_URL = os.environ.get("BENCHMARK_LOCAL_URL", "http://127.0.0.1:8000")
RENDER_BASE_URL = os.environ.get(
    "BENCHMARK_RENDER_URL", "https://procuresphere-360-internal-yre4.onrender.com"
)

WARMUP_REQUESTS = int(os.environ.get("BENCHMARK_WARMUP", "1"))
MEASURED_REQUESTS = int(os.environ.get("BENCHMARK_MEASURED", "5"))
REQUEST_TIMEOUT = float(os.environ.get("BENCHMARK_TIMEOUT", "25.0"))

DEFAULT_PASSWORD = os.environ.get("BENCHMARK_PASSWORD", "Password123!")

ROLE_CREDENTIALS = {
    "Super Admin": {
        "email": os.environ.get("BENCHMARK_ADMIN_EMAIL", "admin@hpe.com"),
        "password": DEFAULT_PASSWORD,
    },
    "Requester": {
        "email": os.environ.get("BENCHMARK_REQUESTER_EMAIL", "requester@hpe.com"),
        "password": DEFAULT_PASSWORD,
    },
    "Department Approver": {
        "email": os.environ.get("BENCHMARK_APPROVER_EMAIL", "approver@hpe.com"),
        "password": DEFAULT_PASSWORD,
    },
    "Budget Approver": {
        "email": os.environ.get("BENCHMARK_BUDGET_EMAIL", "approver@hpe.com"),
        "password": DEFAULT_PASSWORD,
    },
    "Procurement Executive": {
        "email": os.environ.get("BENCHMARK_PROCEXEC_EMAIL", "procexec@hpe.com"),
        "password": DEFAULT_PASSWORD,
    },
    "Procurement Manager": {
        "email": os.environ.get("BENCHMARK_PROCMGR_EMAIL", "procmgr@hpe.com"),
        "password": DEFAULT_PASSWORD,
    },
    "Finance": {
        "email": os.environ.get("BENCHMARK_FINANCE_EMAIL", "finance@hpe.com"),
        "password": DEFAULT_PASSWORD,
    },
    "Stores": {
        "email": os.environ.get("BENCHMARK_STORES_EMAIL", "receiver@hpe.com"),
        "password": DEFAULT_PASSWORD,
    },
    "Legal": {
        "email": os.environ.get("BENCHMARK_LEGAL_EMAIL", "legal@hpe.com"),
        "password": DEFAULT_PASSWORD,
    },
    "Auditor": {
        "email": os.environ.get("BENCHMARK_AUDITOR_EMAIL", "auditor@hpe.com"),
        "password": DEFAULT_PASSWORD,
    },
    "Vendor": {
        "email": os.environ.get("BENCHMARK_VENDOR_EMAIL", "vendoruser@cisco.com"),
        "password": DEFAULT_PASSWORD,
    },
}

REPORT_FILENAME = "ProcureSphere360_API_Performance_Benchmark_Localhost_vs_Render.xlsx"
