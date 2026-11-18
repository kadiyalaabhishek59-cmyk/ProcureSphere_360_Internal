"""
Payload configuration, URL parameter resolution, and safety guardrails.
"""

import logging
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger("benchmark.payloads")

# Endpoints that are destructive or state-corrupting on live/production systems
UNSAFE_PATTERNS = [
    # Any DELETE on core master/transactional data
    ("DELETE", "/api/v1/organization/"),
    ("DELETE", "/api/v1/accounts/"),
    ("DELETE", "/api/v1/auth/"),
    ("DELETE", "/api/v1/vendors/"),
    ("DELETE", "/api/v1/requisitions/"),
    ("DELETE", "/api/v1/orders/"),
    ("DELETE", "/api/v1/purchase-orders/"),
    ("DELETE", "/api/v1/contracts/"),
    ("DELETE", "/api/v1/invoices/"),
    ("DELETE", "/api/v1/budgets/"),
    ("DELETE", "/api/v1/receipts/"),
    ("DELETE", "/api/v1/approvals/"),
    ("DELETE", "/api/v1/sourcing/"),
    ("DELETE", "/api/v1/sourcing-events/"),
    # State transitions that cancel, terminate, or corrupt existing workflows
    ("POST", "/terminate/"),
    ("POST", "/cancel/"),
    ("POST", "/reject/"),
    ("POST", "/close/"),
    ("POST", "/suspend/"),
    ("POST", "/blacklist/"),
    ("POST", "/amend/"),
    ("PUT", "/api/v1/organization/entities/"),
    ("PUT", "/api/v1/contracts/"),
    ("PUT", "/api/v1/orders/"),
    ("PUT", "/api/v1/purchase-orders/"),
    ("PUT", "/api/v1/invoices/"),
    ("PATCH", "/api/v1/organization/entities/"),
    ("PATCH", "/api/v1/contracts/"),
    ("PATCH", "/api/v1/orders/"),
    ("PATCH", "/api/v1/purchase-orders/"),
    ("PATCH", "/api/v1/invoices/"),
]


def is_safety_restricted(method: str, path: str) -> Tuple[bool, str]:
    """Check if an endpoint-method combination should be restricted for safety."""
    method_upper = method.upper()
    if method_upper in ["GET", "HEAD", "OPTIONS"]:
        return False, ""

    for u_method, u_path in UNSAFE_PATTERNS:
        if method_upper == u_method and u_path in path:
            return (
                True,
                f"Production safety restriction: {method_upper} operation on live procurement path '{path}' would alter or delete production data records.",
            )

    return False, ""


class PayloadProvider:
    def __init__(self):
        self.cached_ids: Dict[str, Dict[str, str]] = {
            "local": {},
            "render": {},
        }

    def fetch_environment_ids(self, env: str, session, base_url: str):
        """Pre-fetch existing entity IDs from the target environment for detail endpoints."""
        endpoints_to_query = [
            ("organization_id", "/api/v1/organization/entities/"),
            ("department_id", "/api/v1/organization/departments/"),
            ("cost_center_id", "/api/v1/organization/cost-centers/"),
            ("user_id", "/api/v1/accounts/users/"),
            ("role_id", "/api/v1/accounts/roles/"),
            ("vendor_id", "/api/v1/vendors/"),
            ("requisition_id", "/api/v1/requisitions/"),
            ("order_id", "/api/v1/orders/"),
            ("sourcing_event_id", "/api/v1/sourcing-events/"),
            ("receipt_id", "/api/v1/receipts/"),
            ("invoice_id", "/api/v1/invoices/"),
            ("contract_id", "/api/v1/contracts/"),
            ("budget_id", "/api/v1/budgets/"),
            ("scorecard_id", "/api/v1/scorecards/"),
            ("notification_id", "/api/v1/notifications/"),
            ("policy_id", "/api/v1/approvals/policies/"),
            ("step_id", "/api/v1/approvals/steps/"),
            ("action_id", "/api/v1/approvals/actions/"),
        ]

        for key, ep in endpoints_to_query:
            try:
                url = f"{base_url}{ep}"
                r = session.get(url, timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    results = data.get("results", []) if isinstance(data, dict) else data
                    if results and isinstance(results, list) and len(results) > 0:
                        first_item = results[0]
                        if isinstance(first_item, dict):
                            self.cached_ids[env][key] = str(
                                first_item.get("id") or first_item.get("pk") or ""
                            )
            except Exception as e:
                logger.warning(f"Could not prefetch {key} for {env}: {e}")

    def resolve_path(self, path: str, env: str) -> str:
        """Replace path parameter placeholders like {id}, {pk}, {vendor_id} with real IDs."""
        resolved = path
        ids = self.cached_ids.get(env, {})

        # Mapping of placeholders to resource keys
        param_map = {
            "{id}": "requisition_id",
            "{pk}": "requisition_id",
            "{vendor_id}": "vendor_id",
            "{event_id}": "sourcing_event_id",
            "{order_id}": "order_id",
            "{grn_id}": "receipt_id",
            "{invoice_id}": "invoice_id",
            "{contract_id}": "contract_id",
            "{budget_id}": "budget_id",
            "{notification_id}": "notification_id",
            "{org_id}": "organization_id",
        }

        # Context-aware path parameter replacement
        if "/vendors/" in path:
            param_map["{id}"] = "vendor_id"
            param_map["{pk}"] = "vendor_id"
        elif "/orders/" in path or "/purchase-orders/" in path:
            param_map["{id}"] = "order_id"
            param_map["{pk}"] = "order_id"
        elif "/organization/entities/" in path:
            param_map["{id}"] = "organization_id"
            param_map["{pk}"] = "organization_id"
        elif "/organization/departments/" in path:
            param_map["{id}"] = "department_id"
            param_map["{pk}"] = "department_id"
        elif "/organization/cost-centers/" in path:
            param_map["{id}"] = "cost_center_id"
            param_map["{pk}"] = "cost_center_id"
        elif "/contracts/" in path:
            param_map["{id}"] = "contract_id"
            param_map["{pk}"] = "contract_id"
        elif "/invoices/" in path:
            param_map["{id}"] = "invoice_id"
            param_map["{pk}"] = "invoice_id"
        elif "/receipts/" in path:
            param_map["{id}"] = "receipt_id"
            param_map["{pk}"] = "receipt_id"
        elif "/budgets/" in path:
            param_map["{id}"] = "budget_id"
            param_map["{pk}"] = "budget_id"
        elif "/scorecards/" in path:
            param_map["{id}"] = "scorecard_id"
            param_map["{pk}"] = "scorecard_id"
        elif "/notifications/" in path:
            param_map["{id}"] = "notification_id"
            param_map["{pk}"] = "notification_id"
        elif "/users/" in path or "/accounts/users/" in path:
            param_map["{id}"] = "user_id"
            param_map["{pk}"] = "user_id"
        elif "/roles/" in path or "/accounts/roles/" in path:
            param_map["{id}"] = "role_id"
            param_map["{pk}"] = "role_id"
        elif "/approvals/policies/" in path:
            param_map["{id}"] = "policy_id"
            param_map["{pk}"] = "policy_id"
        elif "/approvals/steps/" in path:
            param_map["{id}"] = "step_id"
            param_map["{pk}"] = "step_id"
        elif "/approvals/actions/" in path:
            param_map["{id}"] = "action_id"
            param_map["{pk}"] = "action_id"
        elif "/sourcing/" in path or "/sourcing-events/" in path:
            param_map["{id}"] = "sourcing_event_id"
            param_map["{pk}"] = "sourcing_event_id"

        for placeholder, key in param_map.items():
            if placeholder in resolved:
                val = ids.get(key)
                if val:
                    resolved = resolved.replace(placeholder, val)

        return resolved

    def get_payload(self, method: str, path: str, env: str) -> Optional[Dict[str, Any]]:
        """Return safe, valid test payloads for POST/PUT/PATCH."""
        method_upper = method.upper()
        if method_upper in ["GET", "HEAD", "OPTIONS"]:
            return None

        # Auth endpoints
        if "/auth/login/" in path or "/auth/token/" in path:
            return {"email": "admin@hpe.com", "password": "Password123!"}
        if "/auth/token/refresh/" in path:
            return {"refresh": "dummy_or_active_refresh_token"}
        if "/auth/logout/" in path:
            return {}

        # Export & Search endpoints
        if "/export/" in path:
            return {"format": "xlsx", "date_range": "30d"}

        # Notifications
        if "/mark-all-read/" in path or "/read/" in path:
            return {}

        # Safe default payload
        return {}
