"""
Complete API Endpoint Discovery Engine for ProcureSphere 360.
Traverses Django URL patterns, views, viewsets, actions, and drf-spectacular schemas.
"""

import os
import sys
import re
import inspect
from typing import List, Dict, Any

from .payloads import is_safety_restricted


def discover_all_endpoints() -> List[Dict[str, Any]]:
    """
    Introspects 100% of registered API endpoints across all application modules.
    Returns a normalized inventory of endpoints with supported methods, roles, and metadata.
    """
    import django
    from django.urls import get_resolver
    from rest_framework.views import APIView
    from rest_framework.viewsets import ViewSetMixin

    resolver = get_resolver()

    def walk_patterns(patterns, prefix=""):
        items = []
        for p in patterns:
            if hasattr(p, "url_patterns"):
                items.extend(walk_patterns(p.url_patterns, prefix + str(p.pattern)))
            else:
                items.append((prefix + str(p.pattern), p.callback, p))
        return items

    raw_routes = walk_patterns(resolver.url_patterns)

    inventory = []
    seen = set()

    for raw_path, cb, pat in raw_routes:
        # Ignore format suffix regexes (.json, .yaml, etc.)
        if r"\.(?P<format>" in raw_path or "<drf_format_suffix:format>" in raw_path:
            continue

        # Keep all API, manager API, health, readyz, schema, and docs routes
        if not any(k in raw_path for k in ["api/", "health", "readyz", "schema", "docs"]):
            continue

        # Skip generic fallback 404 handlers
        if "custom_api_404_view" in str(cb) or "api_not_found" in str(getattr(pat, "name", "")):
            continue

        # Path normalization: strip regex symbols and convert parameter markers to {name}
        clean = raw_path.replace("^", "").replace("$", "")
        clean = re.sub(r"\(\?P<([a-zA-Z0-9_]+)>[^)]+\)", r"{\1}", clean)
        clean = re.sub(r"<[a-zA-Z0-9_]+:([a-zA-Z0-9_]+)>", r"{\1}", clean)
        if not clean.startswith("/"):
            clean = "/" + clean
        if (
            not clean.endswith("/")
            and not clean.endswith("schema")
            and not clean.endswith("docs")
            and not clean.endswith("readyz")
            and not clean.endswith("health")
        ):
            clean = clean + "/"

        cls = getattr(cb, "cls", None)
        actions = getattr(cb, "actions", None)

        methods = []
        if actions:
            methods = [m.upper() for m in actions.keys()]
        elif cls and issubclass(cls, APIView):
            for m in ["get", "post", "put", "patch", "delete", "head", "options"]:
                if hasattr(cls, m) and m in getattr(cls, "http_method_names", []):
                    methods.append(m.upper())
        else:
            methods = ["GET", "HEAD"]

        # Ensure methods is not empty
        if not methods:
            methods = ["GET"]

        # Module mapping
        mod = getattr(cls or cb, "__module__", "core")
        if "accounts" in mod:
            module = "Authentication & RBAC"
            default_role = "Super Admin"
        elif "approvals" in mod:
            module = "Approval Policy Engine"
            default_role = "Department Approver"
        elif "audit" in mod:
            module = "Audit & Compliance"
            default_role = "Auditor"
        elif "budgets" in mod:
            module = "Budget & Spend"
            default_role = "Finance"
        elif "contracts" in mod:
            module = "Contract Lifecycle"
            default_role = "Legal"
        elif "invoices" in mod:
            module = "Invoice & 3-Way Match"
            default_role = "Finance"
        elif "notifications" in mod:
            module = "Notifications & Escalation"
            default_role = "Requester"
        elif "orders" in mod:
            module = "Purchase Orders"
            default_role = "Procurement Executive"
        elif "organization" in mod:
            module = "Organization & Cost Center"
            default_role = "Super Admin"
        elif "receipts" in mod:
            module = "Goods Receipts & Inspection"
            default_role = "Stores"
        elif "reports" in mod:
            module = "Reporting & Analytics"
            default_role = "Procurement Manager"
        elif "requisitions" in mod:
            module = "Purchase Requisitions"
            default_role = "Requester"
        elif "scorecards" in mod:
            module = "Supplier Performance Scorecards"
            default_role = "Procurement Manager"
        elif "sourcing" in mod:
            module = "RFQ/RFP Sourcing & Bids"
            default_role = "Procurement Executive"
        elif "vendors" in mod:
            module = "Vendor Master & Risk"
            default_role = "Procurement Executive"
        elif "manager" in mod or "core.manager" in mod:
            module = "Executive & Procurement Management"
            default_role = "Procurement Manager"
        else:
            module = "System & Health"
            default_role = "Anonymous"

        # Explicit role overrides for specific endpoints
        if clean in [
            "/api/v1/auth/login/",
            "/api/v1/auth/token/",
            "/health",
            "/readyz",
            "/health/",
            "/api/v1/health/",
            "/api/schema",
            "/api/schema/",
            "/api/docs",
            "/api/docs/",
            "/api/v1/schema",
            "/api/v1/schema/",
            "/api/v1/docs",
            "/api/v1/docs/",
        ]:
            default_role = "Anonymous"
        elif "/bids/" in clean and ("/my-bids/" in clean or "/submit/" in clean):
            default_role = "Vendor"

        view_name = cls.__name__ if cls else getattr(cb, "__name__", str(cb))

        try:
            source_file = inspect.getsourcefile(cls or cb) or ""
            source_file = os.path.relpath(source_file, os.getcwd()) if source_file else ""
        except Exception:
            source_file = ""

        # Deduplicate identical canonical paths and methods
        key = (clean, view_name)
        if key in seen:
            continue
        seen.add(key)

        inventory.append({
            "path": clean,
            "raw_path": raw_path,
            "view_name": view_name,
            "methods": methods,
            "module": module,
            "role": default_role,
            "source_file": source_file,
            "docstring": getattr(cls or cb, "__doc__", "") or "",
        })

    return inventory
