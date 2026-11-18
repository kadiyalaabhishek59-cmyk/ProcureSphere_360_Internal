# -*- coding: utf-8 -*-
"""
ProcureSphere 360 — UAT runner for ALL dashboards.
Executes positive (allowed-role), negative (RBAC), anonymous and HTMX-widget
tests against every dashboard using the Django test client on the live
PostgreSQL dev database. GET-only — no business data is mutated.
Results are written to scratch/uat/uat_results.json
"""
import json
import os
import sys
import time
import traceback
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src")))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django

django.setup()

from django.test.utils import setup_test_environment

setup_test_environment()  # enables response.templates / response.context instrumentation

from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import NoReverseMatch, reverse

U = get_user_model()

# ---------------------------------------------------------------- helpers
def try_reverse(name, args=None):
    plain = name.split(":")[-1]  # URL names are flat (no namespaces) in this project
    for candidate in (plain, name):
        try:
            return reverse(candidate, args=args)
        except NoReverseMatch:
            continue
    return None


def templates_of(response):
    try:
        return sorted({t.name for t in response.templates if t.name})
    except Exception:
        return []


def run_case(client, path, follow=True):
    t0 = time.perf_counter()
    response = client.get(path, follow=follow)
    dt = (time.perf_counter() - t0) * 1000.0
    return response, round(dt, 1)


# ---------------------------------------------------------------- matrix
INTERNAL_ROLES = [
    "SUPER_ADMIN", "REQUESTER", "DEPT_APPROVER", "PROC_EXEC", "PROC_MGR",
    "FINANCE_AP", "STORES_RECEIVER", "LEGAL_MGR", "AUDITOR",
]

DASHBOARDS = [
    dict(key="requester", name="Requester Dashboard", path="/requester/", tpl="pages/dashboards/requester_dashboard.html",
         allowed=["REQUESTER", "SUPER_ADMIN"], category="Core Role Dashboard",
         desc="Purchase requisitions overview: KPIs (total/pending/approved PRs), recent requisitions, notifications, quick actions."),
    dict(key="approver", name="Department Approver Dashboard", path="/approver/", tpl="pages/dashboards/approver_dashboard.html",
         allowed=["DEPT_APPROVER", "SUPER_ADMIN"], category="Core Role Dashboard",
         desc="Approval queue: pending approvals, budget availability, approvals executed, requisition chain actions."),
    dict(key="procurement", name="Procurement Executive Dashboard", path="/procurement/", tpl="pages/dashboards/procurement_dashboard.html",
         allowed=["PROC_EXEC", "SUPER_ADMIN"], category="Core Role Dashboard",
         desc="HTMX sourcing workspace: vendor qualification, ready PRs, sourcing events, bid comparison, awards pending PO, notifications."),
    dict(key="finance", name="Finance / AP Dashboard", path="/finance/", tpl="pages/dashboards/finance_dashboard.html",
         allowed=["FINANCE_AP", "SUPER_ADMIN"], category="Core Role Dashboard",
         desc="Invoice & AP workspace: 3-way match exceptions, ready-for-payment, committed/actual spend, invoice queue."),
    dict(key="stores", name="Stores / Receiver Dashboard", path="/stores/", tpl="pages/dashboards/stores_dashboard.html",
         allowed=["STORES_RECEIVER", "SUPER_ADMIN"], category="Core Role Dashboard",
         desc="Goods receipt workspace: GRN totals, pending deliveries, pending inspections, stock handoffs, rejections."),
    dict(key="legal", name="Legal / Contracts Dashboard", path="/legal/", tpl="pages/dashboards/legal_dashboard.html",
         allowed=["LEGAL_MGR", "SUPER_ADMIN"], category="Core Role Dashboard",
         desc="Contract governance: pending legal review, active contracts, expiring contracts, total contract value, milestones/alerts."),
    dict(key="manager", name="Procurement Manager Dashboard", path="/manager/", tpl="manager/dashboard.html",
         allowed=["PROC_MGR", "SUPER_ADMIN"], category="Core Role Dashboard",
         desc="Executive governance: pending approvals oversight, PR aging, sourcing cycle time, spend, vendor risk, scorecards."),
    dict(key="auditor", name="Compliance / Auditor Dashboard", path="/audit/", tpl=None,
         allowed=["AUDITOR", "SUPER_ADMIN"], category="Core Role Dashboard",
         desc="Audit hub: KPI overview, append-only audit trail, approval history, security events, exports (read-only)."),
    dict(key="superadmin", name="Super Admin Dashboard", path="/superadmin/", tpl="pages/dashboards/superadmin_dashboard.html",
         allowed=["SUPER_ADMIN"], category="Core Role Dashboard",
         desc="Admin control center: organizations, users, masters, budgets, policies, audit logs, contact enquiries."),
    dict(key="vendor", name="Vendor Portal Dashboard", path="/vendor/", tpl="pages/dashboards/vendor_dashboard.html",
         allowed=["VENDOR_USER"], category="Vendor Self-Service",
         desc="Vendor self-service: company snapshot, open RFQs/bids, purchase orders, invoices, documents, notifications. SUPER_ADMIN without a vendor tenant is tenant-isolated (403) by design."),
    dict(key="bid_portal", name="Vendor Bid Portal Monitor", path="/sourcing/bid-portal/", tpl="sourcing/bid_portal_dashboard.html",
         allowed=["SUPER_ADMIN", "PROC_EXEC", "PROC_MGR", "AUDITOR"], category="Module Dashboard",
         desc="Sourcing bid portal overview: events, bid window status, bid participation monitor."),
    dict(key="evaluation", name="Evaluation & Award Dashboard", path="/sourcing/evaluation/", tpl="sourcing/evaluation_dashboard.html",
         allowed=["SUPER_ADMIN", "PROC_EXEC", "PROC_MGR", "AUDITOR"], category="Module Dashboard",
         desc="Two-envelope evaluation, commercial comparison, award recommendation/approval, award-to-PO tracking."),
    dict(key="reports", name="Reports Hub", path="/reports/", tpl="pages/reports/dashboard.html",
         allowed=["SUPER_ADMIN", "REQUESTER", "DEPT_APPROVER", "PROC_EXEC", "PROC_MGR", "FINANCE_AP", "STORES_RECEIVER", "LEGAL_MGR", "AUDITOR"],
         category="Module Dashboard",
         desc="Analytics & exports hub: 9 mandatory reports, CSV/XLSX/PDF export jobs, RBAC-scoped."),
    dict(key="org_dashboard", name="Organization Dashboard (per org)", path=None, tpl="pages/dashboards/superadmin/org_dashboard.html",
         allowed=["SUPER_ADMIN"], category="Module Dashboard",
         desc="Per-organization operational dashboard: spend, users, vendors, PR/PO/invoice/contract volumes."),
]

ALL_ROLES = INTERNAL_ROLES + ["VENDOR_USER"]

# ---------------------------------------------------------------- user map
users = {}
from apps.accounts.models import Role  # noqa: E402

role_rows = {r.code: r for r in Role.objects.all()}
for role in ALL_ROLES:
    qs = U.objects.filter(role__code=role).order_by("id")
    # prefer canonical demo accounts when present
    preferred = {
        "SUPER_ADMIN": "admin@hpe.com",
        "REQUESTER": "requester@hpe.com",
        "DEPT_APPROVER": "approver@hpe.com",
        "PROC_EXEC": "procexec@hpe.com",
        "PROC_MGR": "procmgr@hpe.com",
        "FINANCE_AP": "finance@hpe.com",
        "STORES_RECEIVER": "receiver@hpe.com",
        "LEGAL_MGR": "legal@hpe.com",
        "AUDITOR": "auditor@hpe.com",
        "VENDOR_USER": "vendoruser@cisco.com",
    }.get(role)
    user = None
    if preferred:
        user = U.objects.filter(email=preferred).first()
        if user is None or (user.role_code != role):
            user = U.objects.filter(role__code=role).order_by("id").first()
    else:
        user = U.objects.filter(role__code=role).order_by("id").first()
    users[role] = user
missing = [r for r in ALL_ROLES if r not in role_rows or users.get(r) is None]

# ---------------------------------------------------------------- org dashboard path
org_path = None
org_label = "n/a"
try:
    from apps.organization.models import Organization
    org = Organization.objects.first()
    if org:
        org_path = try_reverse("superadmin:org_dashboard", args=[org.pk])
        org_label = f"{org.name} ({org.code})"
except Exception:
    try:
        from apps.core.superadmin_views import org_dashboard_view  # noqa
        from django.apps import apps as dj_apps
        for m in ("Organization", "Org", "TenantOrganization"):
            for mdl in dj_apps.get_models():
                if mdl.__name__ == m:
                    o = mdl.objects.first()
                    org_path = try_reverse("superadmin:org_dashboard", args=[o.pk])
                    org_label = f"{o}"
    except Exception:
        pass
for d in DASHBOARDS:
    if d["key"] == "org_dashboard":
        d["path"] = org_path or "/superadmin/organizations/missing/"

# ---------------------------------------------------------------- sourcing event for compare widget
event_id = None
try:
    from apps.sourcing.models import SourcingEvent
    ev = SourcingEvent.objects.first()
    event_id = ev.pk if ev else None
except Exception:
    pass

# ---------------------------------------------------------------- client
client = Client()

results = []          # every test case
widgets = []          # htmx widget tests
tc_no = [0]

def add(dashboard, name, ttype, role, user_email, url, expected, actual_status, passed, detail, duration, templates, ctx=None):
    tc_no[0] += 1
    results.append({
        "tc_id": f"UAT-{tc_no[0]:03d}",
        "dashboard": dashboard,
        "test_type": ttype,
        "role": role,
        "user": user_email or "anonymous",
        "url": url,
        "expected": expected,
        "actual_status": actual_status,
        "result": "PASS" if passed else "FAIL",
        "detail": detail,
        "duration_ms": duration,
        "templates": templates,
        "context": ctx or {},
    })


def context_evidence(response, keys=("metrics",)):
    ev = {}
    if response is None:
        return ev
    try:
        ctx = response.context
        if ctx:
            for k in keys:
                if k in ctx:
                    v = ctx[k]
                    if isinstance(v, dict):
                        ev[k] = {kk: (str(vv)[:40]) for kk, vv in list(v.items())[:12]}
                    else:
                        ev[k] = str(v)[:60]
    except Exception:
        pass
    return ev


# ================================================================ DASHBOARD MATRIX
for d in DASHBOARDS:
    path = d["path"]
    if not path:
        add(d["name"], "Dashboard reachable", "Positive", "SUPER_ADMIN", "", "n/a", "URL resolvable", "SKIPPED", False,
            "Dashboard URL could not be resolved (missing org?) — needs manual verification", 0, [])
        continue

    # --- positive: every allowed role
    for role in d["allowed"]:
        u = users.get(role)
        if u is None:
            add(d["name"], f"Render for {role}", "Positive", role, "NO SEEDED USER", path,
                "HTTP 200 + dashboard template", "SKIPPED", False, f"No user with role {role} in DB — seed_demo_data needed", 0, [])
            continue
        client.force_login(u)
        response, dt = run_case(client, path)
        tpls = templates_of(response)
        ok = response.status_code == 200 and (d["tpl"] is None or d["tpl"] in tpls) and "Server Exception" not in response.content.decode("utf-8", "ignore")
        detail = f"HTTP {response.status_code}; rendered templates: {', '.join(tpls[:4])}"
        if d["tpl"] and d["tpl"] not in tpls and response.status_code == 200:
            detail += f" — EXPECTED TEMPLATE '{d['tpl']}' NOT RENDERED"
        add(d["name"], f"Render for {role}", "Positive", role, u.email, path,
            "HTTP 200 + dashboard template + no server error", response.status_code, ok, detail, dt, tpls,
            context_evidence(response))
        client.logout()

    # --- negative: every disallowed role
    for role in ALL_ROLES:
        if role in d["allowed"]:
            continue
        u = users.get(role)
        if u is None:
            continue
        client.force_login(u)
        response, dt = run_case(client, path)
        tpls = templates_of(response)
        content = response.content.decode("utf-8", "ignore")
        # Pass if the dashboard itself was NOT served (403, or redirected elsewhere w/o dashboard template)
        served = d["tpl"] in tpls if d["tpl"] else ("audit" in path and response.status_code == 200 and "audit" in (response.request["PATH_INFO"]))
        ok = (response.status_code == 403) or (not served)
        detail = f"HTTP {response.status_code}; landed on: {', '.join(tpls[:3]) or '(no template)'}"
        if not ok:
            detail += " — DASHBOARD CONTENT SERVED TO UNAUTHORIZED ROLE"
        add(d["name"], f"RBAC block for {role}", "Negative (RBAC)", role, u.email, path,
            "HTTP 403/redirect — dashboard NOT served", response.status_code, ok, detail, dt, tpls)
        client.logout()

    # --- anonymous
    response, dt = run_case(client, path)
    tpls = templates_of(response)
    content = response.content.decode("utf-8", "ignore")
    login_redirect = any("login" in (t or "").lower() for t in tpls) or response.status_code in (301, 302)
    ok = login_redirect and (d["tpl"] is None or d["tpl"] not in tpls)
    add(d["name"], "Anonymous access blocked", "Negative (Auth)", "ANONYMOUS", "anonymous", path,
        "Redirect to login — dashboard NOT served", response.status_code, ok,
        f"HTTP {response.status_code}; landed on: {', '.join(tpls[:3]) or '(no template)'}", dt, tpls)

# ================================================================ HTMX WIDGETS (Procurement workspace)
WIDGETS = [
    ("Vendor Qualification tab", "vendors:vendors_qualification_tab", None),
    ("Ready-PRs tab", "sourcing:sourcing_ready_prs_tab", None),
    ("Sourcing Events tab", "sourcing:sourcing_events_tab", None),
    ("Awards Pending PO tab", "orders:orders_awards_pending_tab", None),
    ("Pending Actions widget", "notifications:proc_exec_pending_actions", None),
    ("Notifications Feed widget", "notifications:proc_exec_notifications_feed", None),
    ("Bid Comparison fragment", "sourcing:evaluation_compare_htmx", [event_id] if event_id else None),
]
proc_user = users.get("PROC_EXEC")
neg_user = users.get("REQUESTER")
for wname, wurlname, wargs in WIDGETS:
    url = try_reverse(wurlname, args=wargs)
    if not url:
        widgets.append({"widget": wname, "url_name": wurlname, "url": "UNRESOLVABLE",
                        "proc_exec_result": "SKIP", "negative_result": "SKIP", "note": "reverse() failed"})
        continue
    row = {"widget": wname, "url_name": wurlname, "url": url}
    # positive as PROC_EXEC
    if proc_user:
        client.force_login(proc_user)
        response, dt = run_case(client, url)
        ok = response.status_code in (200, 204) and "Server Exception" not in response.content.decode("utf-8", "ignore")
        row["proc_exec_result"] = f"PASS (HTTP {response.status_code}, {dt} ms)" if ok else f"FAIL (HTTP {response.status_code}, {dt} ms)"
        row["proc_exec_status"] = response.status_code
        row["proc_exec_ms"] = dt
    else:
        row["proc_exec_result"] = "SKIP (no PROC_EXEC user)"
    # negative as REQUESTER
    if neg_user:
        client.force_login(neg_user)
        response, dt = run_case(client, url)
        ok = response.status_code in (403, 302, 301, 404)
        row["negative_result"] = f"PASS (HTTP {response.status_code} — blocked)" if ok else f"FAIL (HTTP {response.status_code} — leaked)"
        row["negative_status"] = response.status_code
    else:
        row["negative_result"] = "SKIP"
    client.logout()
    widgets.append(row)

# ================================================================ DATA CONTEXT (evidence of real data)
def safe_count(model_path):
    try:
        app, mdl = model_path.split(".")
        m = django.apps.apps.get_model(app, mdl)
        return m.objects.count()
    except Exception:
        return None

data_counts = {}
for label, mp in [
    ("Users", "core.User"),
    ("Organizations", "organization.Organization"),
    ("Departments", "organization.Department"),
    ("Cost Centers", "organization.CostCenter"),
    ("Vendors", "vendors.Vendor"),
    ("Vendor Risk Records", "vendors.VendorRiskRecord"),
    ("Purchase Requisitions", "requisitions.PurchaseRequisition"),
    ("Sourcing Events", "sourcing.SourcingEvent"),
    ("Vendor Bids", "sourcing.VendorBid"),
    ("Purchase Orders", "orders.PurchaseOrder"),
    ("Goods Receipts (GRN)", "receipts.GoodsReceipt"),
    ("Supplier Invoices", "invoices.SupplierInvoice"),
    ("Match Exceptions", "invoices.MatchException"),
    ("Contracts", "contracts.Contract"),
    ("Budgets", "budgets.Budget"),
    ("Budget Reservations", "budgets.BudgetReservation"),
    ("Vendor Scorecards", "scorecards.VendorScorecard"),
    ("Notifications", "notifications.Notification"),
    ("Audit Log Entries", "audit.AuditLog"),
    ("Export Jobs", "reports.ExportJob"),
    ("Approval Actions", "approvals.ApprovalAction"),
]:
    data_counts[label] = safe_count(mp)

# ================================================================= SAVE
env_info = {
    "executed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "database": "PostgreSQL dev (127.0.0.1:15432/procuresphere_db)",
    "settings": "config.settings.dev (Django 4.2.30)",
    "client": "Django test client (force_login), GET-only",
    "missing_role_users": missing,
    "org_dashboard_org": org_label,
    "total_users_in_db": U.objects.count(),
}
out = {"env": env_info, "results": results, "widgets": widgets, "data_counts": data_counts}
outdir = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(outdir, "uat_results.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, indent=2, default=str)

# console summary
passes = sum(1 for r in results if r["result"] == "PASS")
fails = [r for r in results if r["result"] == "FAIL"]
print(f"\n=== UAT EXECUTION COMPLETE ===")
print(f"Total cases: {len(results)}  PASS: {passes}  FAIL: {len(fails)}")
for r in fails:
    print(f"  FAIL {r['tc_id']} | {r['dashboard']} | {r['test_type']} | {r['role']} | HTTP {r['actual_status']} | {r['detail'][:110]}")
wp = sum(1 for w in widgets if str(w.get("proc_exec_result", "")).startswith("PASS"))
print(f"Widget tests: {len(widgets)}  widget PASS: {wp}")
