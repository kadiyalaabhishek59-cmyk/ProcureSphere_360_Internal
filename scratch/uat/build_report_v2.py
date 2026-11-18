# -*- coding: utf-8 -*-
"""ProcureSphere 360 — Dashboard-wise UAT Report v2 (one sheet per dashboard)."""
import json
import os

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
data = json.load(open(os.path.join(HERE, "uat_detailed.json"), encoding="utf-8"))
CASES = data["results"]
NOW = data["executed_at"]

NAVY = "1B2A4A"; GREEN = "01A982"; LIGHT = "EEF3F8"; GRAY = "595959"
PASS_FILL = PatternFill("solid", fgColor="C6EFCE"); PASS_FONT = Font(name="Arial", size=10, color="006100", bold=True)
FAIL_FILL = PatternFill("solid", fgColor="FFC7CE"); FAIL_FONT = Font(name="Arial", size=10, color="9C0006", bold=True)
WARN_FILL = PatternFill("solid", fgColor="FFEB9C"); WARN_FONT = Font(name="Arial", size=10, color="9C6500", bold=True)
HDR_FILL = PatternFill("solid", fgColor=NAVY)
HDR_FONT = Font(name="Arial", size=10, color="FFFFFF", bold=True)
CAT_FONT = Font(name="Arial", size=9, bold=True, color=NAVY)
BAND_FILL = PatternFill("solid", fgColor=LIGHT)
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
BASE = Font(name="Arial", size=10)
BOLD = Font(name="Arial", size=10, bold=True)
TITLE_FONT = Font(name="Arial", size=18, bold=True, color=NAVY)
SUBTITLE_FONT = Font(name="Arial", size=11, color=GRAY)
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
LEFT = Alignment(horizontal="left", vertical="center", wrap_text=True)
TOP_LEFT = Alignment(horizontal="left", vertical="top", wrap_text=True)

META = {
    "Requester Dashboard": ("RD", "Core Role", "/requester/", "core/views.py :: requester_dashboard_view", "REQUESTER, SUPER_ADMIN", "pages/dashboards/requester_dashboard.html",
        "Purchase requisitions workspace: my-PR KPIs (total / pending approval / approved), recent requisitions with live amounts, notifications and quick actions."),
    "Department Approver Dashboard": ("AD", "Core Role", "/approver/", "core/views.py :: approver_dashboard_view", "DEPT_APPROVER, SUPER_ADMIN", "pages/dashboards/approver_dashboard.html",
        "Departmental approval desk: departmental PR scope, pending approval queue with budget validation, approvals executed, available budget from active fiscal-period budgets."),
    "Procurement Executive Dashboard": ("PD", "Core Role", "/procurement/", "core/views.py :: procurement_dashboard_view", "PROC_EXEC, SUPER_ADMIN", "pages/dashboards/procurement_dashboard.html",
        "HTMX sourcing workspace: vendor qualification, ready PRs, sourcing events, bid comparison, awards pending PO, pending actions + notification feed (polled), bid windows closing, vendor attention list."),
    "Finance / AP Dashboard": ("FD", "Core Role", "/finance/", "core/views.py :: finance_dashboard_view", "FINANCE_AP, SUPER_ADMIN", "pages/dashboards/finance_dashboard.html",
        "AP workspace: open 3-way match exceptions, budget exceptions, finance approval queue, ready-for-payment invoices, committed vs actual spend (SpendLedger), dept/cost-center filters."),
    "Stores / Receiver Dashboard": ("SD", "Core Role", "/stores/", "core/views.py :: stores_dashboard_view -> receipts/views.py :: get_stores_dashboard_data", "STORES_RECEIVER, SUPER_ADMIN", "pages/dashboards/stores_dashboard.html",
        "Goods receipt operations: GRN totals, pending deliveries/inspections/stock handoffs, rejections and returns queues, live operational stages."),
    "Legal / Contracts Dashboard": ("LD", "Core Role", "/legal/", "core/views.py :: legal_dashboard_view -> contracts/views.py :: dashboard_view", "LEGAL_MGR, SUPER_ADMIN", "pages/dashboards/legal_dashboard.html",
        "Contract governance desk: pending legal review, active contracts, 30-day expiry pipeline, total contract value, obligations, milestones, vendor credential verifications."),
    "Procurement Manager Dashboard": ("MD", "Core Role", "/manager/", "core/manager_views.py :: manager_dashboard_view", "PROC_MGR, SUPER_ADMIN", "manager/dashboard.html",
        "Executive governance dashboard: pending awards, PR bottlenecks, budget commitment ratio, avg vendor score, GRN/QC/exception KPIs, manager approval decisions, supplier watchlist."),
    "Compliance / Auditor Dashboard": ("AUD", "Core Role", "/audit/", "audit/views.py :: auditor_dashboard_view", "AUDITOR, SUPER_ADMIN", "audit executive KPI hub (pages/dashboards/auditor_dashboard.html)",
        "Compliance hub: org-scoped append-only audit trail totals, approvals/rejections/logins/exports, open exceptions, suspended vendors, overdue obligations, vendor compliance rate, audit trend + action distribution."),
    "Super Admin Dashboard": ("SA", "Core Role", "/superadmin/", "core/views.py :: superadmin_dashboard_view", "SUPER_ADMIN", "pages/dashboards/superadmin_dashboard.html",
        "Admin control center: org-scoped users, budget allocation, pending transactions (PRs + exceptions), audit logs today, organization cards, RBAC / policies / budgets / audit quick links."),
    "Vendor Portal Dashboard": ("VP", "Vendor Self-Service", "/vendor/", "vendors/vendor_dashboard_views.py :: vendor_dashboard_overview_view", "VENDOR_USER (tenant-isolated)", "pages/dashboards/vendor_dashboard.html",
        "Vendor self-service: active RFQ invitations, bids in draft / submitted, upcoming deadlines, pending clarifications, POs requiring acknowledgement, active POs, KYC status, scorecard factors."),
    "Vendor Bid Portal Monitor": ("BP", "Module", "/sourcing/bid-portal/", "sourcing/views.py :: bid_portal_dashboard_view", "SUPER_ADMIN, PROC_EXEC, PROC_MGR, AUDITOR", "sourcing/bid_portal_dashboard.html",
        "Bid portal monitor: open bid windows, invitations not responded, sealed bids submitted, drafts, amended/withdrawn bids, per-event participation register."),
    "Evaluation & Award Dashboard": ("EV", "Module", "/sourcing/evaluation/", "sourcing/views.py :: evaluation_dashboard_view", "SUPER_ADMIN, PROC_EXEC, PROC_MGR, AUDITOR", "sourcing/evaluation_dashboard.html",
        "Two-envelope evaluation: technical review, commercial review/negotiation, award approval queue, awarded (with/without PO), per-event drill-down and stage filters."),
    "Reports Hub": ("RH", "Module", "/reports/", "reports/views.py :: dashboard_view", "All internal roles (VENDOR_USER excluded)", "pages/reports/dashboard.html",
        "Analytics & exports: 9 mandatory report modules with CSV/XLSX/PDF export formats, user's recent export jobs (RBAC-scoped, audited)."),
    "Organization Dashboard (per org)": ("OD", "Module", "/superadmin/organizations/<org_id>/", "core/superadmin_views.py :: org_dashboard_view", "SUPER_ADMIN", "pages/dashboards/superadmin/org_dashboard.html",
        "Per-organization operational dashboard: master data, users, PR status, approval workflow monitoring, sourcing, vendors, PO/receipts, budget allocations vs spend, invoices, org-scoped audit trail."),
}
ORDER = list(META.keys())
ROLE_ORDER = ["SUPER_ADMIN", "REQUESTER", "DEPT_APPROVER", "PROC_EXEC", "PROC_MGR", "FINANCE_AP", "STORES_RECEIVER", "LEGAL_MGR", "AUDITOR", "VENDOR_USER", "ANONYMOUS"]
CAT_ORDER = ["Page Render", "Content Sections", "KPI Accuracy", "Data Scope & Isolation", "Navigation & Links", "Performance", "HTMX Interactivity", "Access Control"]

def cases_for(dash):
    out = []
    for cat in CAT_ORDER:
        out.extend([c for c in CASES if c["dashboard"] == dash and c["category"] == cat])
    rest = [c for c in CASES if c["dashboard"] == dash and c["category"] not in CAT_ORDER]
    return out + rest

wb = Workbook()

def style_header(ws, row, cols, fill=HDR_FILL, font=HDR_FONT, height=26):
    for c in range(1, cols + 1):
        cell = ws.cell(row=row, column=c)
        cell.fill = fill; cell.font = font; cell.alignment = CENTER; cell.border = BORDER
    ws.row_dimensions[row].height = height

def title_block(ws, title, lines, cols):
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=cols)
    ws.cell(row=1, column=1, value=title).font = TITLE_FONT
    ws.row_dimensions[1].height = 26
    r = 2
    for line in lines:
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=cols)
        c = ws.cell(row=r, column=1, value=line)
        c.font = SUBTITLE_FONT; c.alignment = LEFT
        r += 1
    return r

def widths(ws, ws_widths):
    for i, w in enumerate(ws_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

# ============================================================ COVER
ws = wb.active; ws.title = "Cover"; ws.sheet_view.showGridLines = False
widths(ws, [30, 62, 26, 20, 20, 20])
ws.merge_cells("A1:F1"); ws["A1"] = "PROCURESPHERE 360 — DASHBOARD-WISE UAT REPORT"
ws["A1"].font = Font(name="Arial", size=22, bold=True, color=NAVY)
ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
ws.row_dimensions[1].height = 40
ws.merge_cells("A2:F2"); ws["A2"] = "User Acceptance Test — every dashboard, tested dashboard-wise with KPI validation against live PostgreSQL data"
ws["A2"].font = Font(name="Arial", size=12, bold=True, color=GREEN); ws["A2"].alignment = Alignment(horizontal="center")
ws.merge_cells("A3:F3"); ws["A3"] = "Enterprise Procurement, Vendor & Contract Management ERP  |  HPE-PRD-2026-PROC01"
ws["A3"].font = SUBTITLE_FONT; ws["A3"].alignment = Alignment(horizontal="center")
r = 5
ws.cell(row=r, column=1, value="DOCUMENT CONTROL").font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=6); ws.cell(row=r, column=1).fill = HDR_FILL; ws.cell(row=r, column=1).alignment = LEFT
doc = [
    ("Report ID / Version", "UAT-PS360-DASH-2026-001  |  Version 2.0 (dashboard-wise retest)"),
    ("Execution Date", NOW),
    ("Executed By", "Automated UAT agent — Django test client (force_login), read-only GET requests"),
    ("Environment", data["env"]),
    ("Test Approach", "Per dashboard: page render, content sections, KPI accuracy (independently recomputed from PostgreSQL), data-scope/IDOR checks, navigation links, performance, HTMX interactivity, and full role-based access control matrix"),
    ("Scope", "14 dashboards  x  10 roles + anonymous  |  345 detailed test cases (retest round)"),
    ("Round 1 (initial pass)", "154 access/render cases — 0 defects"),
    ("Round 2 (this report)", "345 detailed cases — 344 PASS, 1 FAIL (DEF-002, Low)"),
    ("Overall Verdict", "ACCEPTED — 1 Low-severity UI defect logged for backlog; no functional, RBAC, data-integrity or security defects"),
]
for label, val in doc:
    r += 1
    ws.cell(row=r, column=1, value=label).font = BOLD
    ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=6)
    ws.cell(row=r, column=2, value=val).font = BASE
    for c in range(1, 7):
        ws.cell(row=r, column=c).border = BORDER
    ws.cell(row=r, column=1).fill = PatternFill("solid", fgColor=LIGHT)
    ws.cell(row=r, column=1).alignment = TOP_LEFT
    ws.cell(row=r, column=2).alignment = TOP_LEFT
r += 2
ws.cell(row=r, column=1, value="HOW TO READ THIS WORKBOOK").font = BOLD
r += 1
guide = [
    "Executive Summary — rollup of all 14 dashboards with formula-driven pass rates.",
    "One sheet per dashboard (RD/AD/PD/FD/SD/LD/MD/AUD/SA/VP/BP/EV/RH/OD) — every test case with expected vs actual evidence.",
    "RBAC Access Matrix — verified allow/block outcome for every dashboard x role combination.",
    "Defects & Observations — 1 Low defect (DEF-002) + by-design confirmations.",
    "Test Data & Environment — live DB snapshot; Sign-off — acceptance signatures.",
]
for g in guide:
    ws.cell(row=r, column=1, value="•  " + g).font = BASE
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=6)
    r += 1
r += 1
legend = [("PASS — requirement met, evidence captured", PASS_FILL, PASS_FONT),
          ("FAIL — defect logged (see Defects & Observations)", FAIL_FILL, FAIL_FONT)]
for text, fill, font in legend:
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=3)
    cell = ws.cell(row=r, column=1, value=text); cell.fill = fill; cell.font = font; cell.alignment = LEFT
    for c in range(1, 4):
        ws.cell(row=r, column=c).border = BORDER
    r += 1

# ============================================================ EXEC SUMMARY
ws = wb.create_sheet("Executive Summary"); ws.sheet_view.showGridLines = False
headers = ["#", "Sheet", "Dashboard", "Category", "Primary URL", "Test Cases", "Passed", "Failed", "Pass Rate", "Verdict", "Key Findings"]
widths(ws, [5, 26, 34, 14, 30, 11, 9, 9, 11, 12, 58])
ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
ws.cell(row=1, column=1, value="EXECUTIVE SUMMARY — DASHBOARD-WISE UAT ROLLUP").font = Font(name="Arial", size=14, bold=True, color=NAVY)
ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(headers))
ws.cell(row=2, column=1, value=f"Retest round executed {NOW}  |  345 cases  |  live PostgreSQL (HPE-GLOBAL demo data)  |  read-only").font = SUBTITLE_FONT
r = 4
for i, h in enumerate(headers, 1):
    ws.cell(row=r, column=i, value=h)
style_header(ws, r, len(headers), height=30)
ws.freeze_panes = "A5"
r = 5
FINDINGS = {
    "Requester Dashboard": "All KPIs match DB ground truth; own-data-only verified (IDOR scan clean).",
    "Department Approver Dashboard": "Department scope, pending queue and budget KPIs validated against recomputed budgets.",
    "Procurement Executive Dashboard": "All 7 HTMX widgets load; role-blocked for unauthorized roles; cross-user isolation verified.",
    "Finance / AP Dashboard": "Match exceptions, ready-for-payment and SpendLedger committed/actual sums match DB to the cent.",
    "Stores / Receiver Dashboard": "GRN/delivery/inspection KPIs match DB; GRN list org-scoped.",
    "Legal / Contracts Dashboard": "Contract metrics (active, legal review, expiry pipeline, value) match DB.",
    "Procurement Manager Dashboard": "DEF-002: breadcrumb block defined by 13 Manager templates is never rendered by base layout (cosmetic). All KPIs pass.",
    "Compliance / Auditor Dashboard": "Audit KPIs verified ORG-SCOPED by design (multi-tenant isolation); read-only posture confirmed.",
    "Super Admin Dashboard": "Users, budget allocation, pending transactions, audits-today match DB (±1 session-noise tolerance).",
    "Vendor Portal Dashboard": "Tenant isolation verified: POs vendor-owned only, no competitor names rendered, sealed-bid privacy intact.",
    "Vendor Bid Portal Monitor": "Portal metrics scope-accurate (published/bid-window events); role guards verified.",
    "Evaluation & Award Dashboard": "Stage counts (technical/commercial/approval/awarded) match DB; derived metric consistent.",
    "Reports Hub": "9 mandatory report modules present with CSV/XLSX/PDF; vendor users excluded; exports user-scoped.",
    "Organization Dashboard (per org)": "Org identity, user counts and all sections render; org-scoped.",
}
for idx, name in enumerate(ORDER, 1):
    code = META[name][0]
    sheet_name = f"{code} - {META[name][1]}"
    ws.cell(row=r, column=1, value=idx).font = BASE
    ws.cell(row=r, column=2, value=sheet_name).font = Font(name="Arial", size=10, bold=True, color=NAVY)
    ws.cell(row=r, column=3, value=name)
    ws.cell(row=r, column=4, value=META[name][1])
    ws.cell(row=r, column=5, value=META[name][2]).font = Font(name="Consolas", size=9)
    ws.cell(row=r, column=6, value=f"=COUNTIF('{sheet_name}'!$F$8:$F$300,\"*\")").font = BASE
    ws.cell(row=r, column=7, value=f"=COUNTIF('{sheet_name}'!$F$8:$F$300,\"PASS\")").font = BASE
    ws.cell(row=r, column=8, value=f"=COUNTIF('{sheet_name}'!$F$8:$F$300,\"FAIL\")").font = BASE
    ws.cell(row=r, column=9, value=f"=IFERROR($G{r}/$F{r},0)").font = BASE
    ws.cell(row=r, column=9).number_format = "0.0%"
    ws.cell(row=r, column=10, value=f"=IF($H{r}=0,\"PASS\",\"ATTN\")").font = BASE
    ws.cell(row=r, column=11, value=FINDINGS.get(name, "")).font = Font(name="Arial", size=9, color=GRAY)
    ws.cell(row=r, column=11).alignment = TOP_LEFT
    fails = sum(1 for c in cases_for(name) if c["result"] == "FAIL")
    vcell = ws.cell(row=r, column=10)
    vcell.fill = PASS_FILL if fails == 0 else FAIL_FILL
    vcell.font = PASS_FONT if fails == 0 else FAIL_FONT
    for c in (3, 4):  # name + category cells have no explicit font yet
        ws.cell(row=r, column=c).font = BASE
    for c in range(1, len(headers) + 1):
        cell = ws.cell(row=r, column=c); cell.border = BORDER
        if c not in (3, 5, 11):
            cell.alignment = CENTER
    r += 1
tot = r
ws.cell(row=tot, column=3, value="TOTAL — ALL DASHBOARDS").font = Font(name="Arial", size=10, bold=True, color="FFFFFF")
for col, L in ((6, "F"), (7, "G"), (8, "H")):
    ws.cell(row=tot, column=col, value=f"=SUM({L}5:{L}{tot-1})")
ws.cell(row=tot, column=9, value=f"=IFERROR($G{tot}/$F{tot},0)").number_format = "0.0%"
ws.cell(row=tot, column=10, value=f"=IF($H{tot}=0,\"PASS\",\"ATTN\")")
for c in range(1, len(headers) + 1):
    cell = ws.cell(row=tot, column=c)
    cell.fill = HDR_FILL; cell.font = Font(name="Arial", size=10, bold=True, color="FFFFFF")
    cell.border = BORDER; cell.alignment = CENTER if c != 3 else LEFT
ws.cell(row=tot, column=10).fill = PatternFill("solid", fgColor="006100")
ws.cell(row=tot, column=10).font = Font(name="Arial", size=10, bold=True, color="FFFFFF")
COVER_TOT_ROW = tot

# ============================================================ DASHBOARD SHEETS
for name in ORDER:
    code, cat, url, view, roles, tpl, desc = META[name]
    rows = cases_for(name)
    ws = wb.create_sheet(f"{code} - {cat}")
    ws.sheet_view.showGridLines = False
    ncols = 7
    r = title_block(ws, f"{code} · {name}", [
        f"Module: {cat}   |   URL: {url}   |   View: {view}",
        f"Roles allowed (backend-enforced): {roles}   |   Template: {tpl}",
        f"Executed: {NOW}   |   {data['env']}   |   read-only GET",
    ], ncols)
    # description strip
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=ncols)
    dcell = ws.cell(row=r, column=1, value="Purpose: " + desc)
    dcell.font = Font(name="Arial", size=9, italic=True, color=GRAY); dcell.alignment = TOP_LEFT
    ws.row_dimensions[r].height = 26
    r += 1
    # summary strip with formulas
    first_data = r + 3
    labels = ["Test Cases", "Passed", "Failed", "Pass Rate"]
    formulas = [f"=COUNTA($A$8:$A$300)",
                f"=COUNTIF($F$8:$F$300,\"PASS\")",
                f"=COUNTIF($F$8:$F$300,\"FAIL\")",
                f"=IFERROR(COUNTIF($F$8:$F$300,\"PASS\")/COUNTA($A$8:$A$300),0)"]
    strip_row = r
    for i, (lab, f) in enumerate(zip(labels, formulas)):
        col = 1 + i * 2
        lab_cell = ws.cell(row=strip_row, column=col, value=lab)
        lab_cell.font = BOLD
        lab_cell.alignment = Alignment(horizontal="right", vertical="center")
        v = ws.cell(row=strip_row, column=col + 1, value=f)
        v.font = Font(name="Arial", size=11, bold=True, color="006100")
        v.alignment = CENTER
        if lab == "Pass Rate":
            v.number_format = "0.0%"
        ws.cell(row=strip_row, column=col).border = BORDER
        v.border = BORDER
    r += 2
    hdr = ["TC ID", "Category", "Test Case", "Expected Result", "Actual Result", "Result", "Evidence / Notes"]
    for i, h in enumerate(hdr, 1):
        ws.cell(row=r, column=i, value=h)
    style_header(ws, r, ncols)
    ws.freeze_panes = f"A{r+1}"
    r += 1
    data_start = r
    prev_cat = None
    for i, t in enumerate(rows, 1):
        tc_id = f"{code}-{i:03d}"
        ws.cell(row=r, column=1, value=tc_id).font = Font(name="Consolas", size=9)
        ws.cell(row=r, column=2, value=t["category"]).font = CAT_FONT
        ws.cell(row=r, column=3, value=t["name"]).alignment = LEFT
        ws.cell(row=r, column=4, value=t["expected"]).alignment = LEFT
        ws.cell(row=r, column=5, value=t["actual"]).alignment = LEFT
        for c in (3, 4, 5):
            ws.cell(row=r, column=c).font = BASE
        ws.cell(row=r, column=6, value=t["result"])
        ws.cell(row=r, column=7, value=t["evidence"]).font = Font(name="Arial", size=9, color=GRAY)
        ws.cell(row=r, column=7).alignment = TOP_LEFT
        res = ws.cell(row=r, column=6)
        if t["result"] == "PASS":
            res.fill = PASS_FILL; res.font = PASS_FONT
        else:
            res.fill = FAIL_FILL; res.font = FAIL_FONT
        for c in range(1, ncols + 1):
            cell = ws.cell(row=r, column=c); cell.border = BORDER
            if c in (1, 2, 6):
                cell.alignment = CENTER
        if t["category"] != prev_cat and prev_cat is not None:
            for c in range(1, ncols + 1):
                ws.cell(row=r, column=c).border = Border(left=THIN, right=THIN, bottom=THIN, top=Side(style="medium", color=NAVY))
        prev_cat = t["category"]
        r += 1
    ws.auto_filter.ref = f"A{data_start-1}:G{r-1}"
    widths(ws, [10, 19, 44, 30, 30, 9, 58])

# ============================================================ RBAC MATRIX
ws = wb.create_sheet("RBAC Access Matrix"); ws.sheet_view.showGridLines = False
headers = ["Dashboard"] + ROLE_ORDER
ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
ws.cell(row=1, column=1, value="RBAC ACCESS MATRIX — VERIFIED OUTCOMES (backend-enforced)").font = Font(name="Arial", size=14, bold=True, color=NAVY)
widths(ws, [32] + [15] * len(ROLE_ORDER))
r = 3
for i, h in enumerate(headers, 1):
    ws.cell(row=r, column=i, value=h)
style_header(ws, r, len(headers), height=32)
ws.freeze_panes = "B4"
r = 4
for name in ORDER:
    ws.cell(row=r, column=1, value=name).font = BOLD
    ws.cell(row=r, column=1).alignment = LEFT
    ac = [c for c in CASES if c["dashboard"] == name and c["category"] == "Access Control"]
    for ci, role in enumerate(ROLE_ORDER, start=2):
        cell = ws.cell(row=r, column=ci); cell.alignment = CENTER; cell.border = BORDER
        row_match = [c for c in ac if role.lower() in c["name"].lower()]
        if row_match:
            c0 = row_match[0]
            if c0["name"].startswith("Authorized"):
                cell.value = "ALLOWED (200)"; cell.fill = PASS_FILL; cell.font = Font(name="Arial", size=9, color="006100", bold=True)
            elif c0["name"].startswith("Unauthorized"):
                cell.value = f"BLOCKED ({'403' if '403' in c0['evidence'] or 'Forbidden' in c0['evidence'] else '302'})"
                cell.fill = FAIL_FILL; cell.font = Font(name="Arial", size=9, color="9C0006", bold=True)
            else:
                cell.value = "LOGIN REDIRECT"; cell.fill = PatternFill("solid", fgColor="D9D9D9")
                cell.font = Font(name="Arial", size=9, color=GRAY, bold=True)
        else:
            cell.value = "—"; cell.font = Font(name="Arial", size=9, color=GRAY)
    r += 1
r += 1
ws.merge_cells(start_row=r, start_column=1, end_row=r + 1, end_column=len(headers))
ws.cell(row=r, column=1, value="ALLOWED (200): role authorized by the view guard. BLOCKED (403): PermissionDenied raised at backend — no dashboard content served. LOGIN REDIRECT: unauthenticated request sent to /login/. Every cell is backed by a test case on the corresponding dashboard sheet (category 'Access Control').").font = Font(name="Arial", size=9, italic=True, color=GRAY)
ws.cell(row=r, column=1).alignment = TOP_LEFT

# ============================================================ DEFECTS
ws = wb.create_sheet("Defects & Observations"); ws.sheet_view.showGridLines = False
headers = ["ID", "Type", "Severity", "Dashboard / Area", "Description", "Evidence", "Recommended Action", "Status"]
ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
ws.cell(row=1, column=1, value="DEFECTS & OBSERVATIONS").font = Font(name="Arial", size=14, bold=True, color=NAVY)
widths(ws, [10, 13, 11, 24, 62, 30, 50, 14])
r = 3
for i, h in enumerate(headers, 1):
    ws.cell(row=r, column=i, value=h)
style_header(ws, r, len(headers))
rows = [
    ("DEF-002", "Defect", "Low", "Procurement Manager Dashboard (all 13 Manager pages)",
     "Breadcrumb trail never renders: dashboard.html (and the other 12 Manager templates) define {% block manager_breadcrumbs %}, but templates/manager/base_manager.html contains no breadcrumb section, so the block is silently ignored. The '{% block mobile_page_title %}' child block is likewise not referenced by the parent layout. Cosmetic only — page headings, KPIs and navigation are unaffected.",
     "MD sheet — case 'Breadcrumb trail renders'; base_manager.html blocks: title/navbar/layout/manager_content only",
     "Add a breadcrumb header area to base_manager.html that renders {% block manager_breadcrumbs %} (and reference mobile_page_title), or remove the dead block definitions from the child templates.", "Open (Low)"),
    ("OBS-001", "Observation", "Low", "HTMX Notification widgets (Procurement workspace)",
     "Pending-Actions and Notification-Feed HTMX endpoints return HTTP 200 to any authenticated role (not role-restricted like the other five widgets). Verified recipient-scoped: a REQUESTER receives only their own (empty) state — zero cross-user data. No disclosure; hardening advisable for consistency with AGENTS.md Rule 2.",
     "PD sheet — widget isolation case; direct cross-user fetch comparison", "Apply the same procurement-role guard used by the other HTMX tabs to the two notification endpoints.", "Open (Low)"),
    ("OBS-002", "Observation", "Info", "Vendor Portal Dashboard",
     "SUPER_ADMIN (org administrator, no vendor tenant) receives HTTP 403 on /vendor/ — correct tenant isolation; the vendor portal is scoped strictly to vendor-tenant users. Documented to prevent misclassification as a defect.",
     "VP sheet — Access Control matrix", "None — behavior by design; keep regression-covered.", "Closed (By Design)"),
    ("OBS-003", "Observation", "Info", "Compliance / Auditor Dashboard",
     "Audit KPIs are ORG-SCOPED by design: the dashboard reports 1,349 audit entries for HPE-GLOBAL while the global pool is 1,614 (vendor-portal users without org membership and platform rows excluded by get_scoped_audit_logs_queryset). Multi-tenant isolation working as specified.",
     "AUD sheet — org-scoping verification case", "None — isolation rule verified and desirable.", "Closed (By Design)"),
    ("OBS-004", "Observation", "Info", "Reports Hub",
     "All 9 mandatory PRD report modules are exposed with CSV/XLSX/PDF export formats; export jobs are user-scoped and vendor users are blocked from the hub entirely.",
     "RH sheet — report selector case", "None.", "Closed (By Design)"),
]
r = 4
for row_data in rows:
    for c, val in enumerate(row_data, 1):
        cell = ws.cell(row=r, column=c, value=val)
        cell.border = BORDER; cell.font = BASE
        cell.alignment = TOP_LEFT if c in (5, 6, 7) else CENTER
    sev = row_data[2]
    sc = ws.cell(row=r, column=3)
    if sev == "Low":
        sc.fill = WARN_FILL; sc.font = WARN_FONT
    elif sev == "Info":
        sc.fill = BAND_FILL; sc.font = BOLD
    ws.row_dimensions[r].height = 64
    r += 1

# ============================================================ TEST DATA & ENV
ws = wb.create_sheet("Test Data & Environment"); ws.sheet_view.showGridLines = False
ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=4)
ws.cell(row=1, column=1, value="TEST DATA & ENVIRONMENT").font = Font(name="Arial", size=14, bold=True, color=NAVY)
widths(ws, [32, 58, 30, 16])
r = 3
ws.cell(row=r, column=1, value="ENVIRONMENT").font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=2); ws.cell(row=r, column=1).fill = HDR_FILL; ws.cell(row=r, column=1).alignment = LEFT
r += 1
for label, val in [("Execution timestamp", NOW), ("Database", "PostgreSQL 127.0.0.1:15432 / procuresphere_db (live demo data)"),
                   ("Application", "Django 4.2.30 LTS + DRF, HTMX, Celery — config.settings.dev"),
                   ("Test client", "Django test client, force_login sessions, GET-only (no data mutation)"),
                   ("Organization under test", data["org"]),
                   ("Role coverage", "All 10 roles present with seeded demo users")]:
    ws.cell(row=r, column=1, value=label).font = BOLD
    ws.cell(row=r, column=2, value=val).font = BASE
    for c in (1, 2):
        ws.cell(row=r, column=c).border = BORDER; ws.cell(row=r, column=c).alignment = LEFT
    ws.cell(row=r, column=1).fill = PatternFill("solid", fgColor=LIGHT)
    r += 1
r += 1
ws.cell(row=r, column=1, value="LIVE DATA SNAPSHOT AT EXECUTION").font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=4); ws.cell(row=r, column=1).fill = HDR_FILL; ws.cell(row=r, column=1).alignment = LEFT
r += 1
for c, h in enumerate(["Entity", "Records", "Entity", "Records"], 1):
    ws.cell(row=r, column=c, value=h)
style_header(ws, r, 4, height=20)
items = [("Purchase Requisitions", 3), ("Sourcing Events", 17), ("Vendor Bids", 13), ("Purchase Orders", 5),
         ("Goods Receipts (GRN)", 5), ("Supplier Invoices", 6), ("Match Exceptions", 4), ("Contracts", 1),
         ("Budgets", 1), ("Budget Reservations", 3), ("Vendors", 8), ("Organizations", 1),
         ("Departments", 2), ("Cost Centers", 1), ("Notifications", 206), ("Audit Log Entries", "1,614 (global) / 1,349 (org-scoped)"),
         ("Approval Actions", 5), ("Vendor Scorecards", "live")]
half = (len(items) + 1) // 2
r += 1
for i in range(half):
    lft = items[i]; rgt = items[i + half] if i + half < len(items) else ("", "")
    ws.cell(row=r, column=1, value=lft[0]).font = BASE
    ws.cell(row=r, column=2, value=str(lft[1])).font = BASE
    ws.cell(row=r, column=3, value=rgt[0]).font = BASE
    ws.cell(row=r, column=4, value=str(rgt[1])).font = BASE
    for c in range(1, 5):
        ws.cell(row=r, column=c).border = BORDER
        if c in (2, 4):
            ws.cell(row=r, column=c).alignment = CENTER
    if i % 2 == 1:
        for c in range(1, 5):
            ws.cell(row=r, column=c).fill = BAND_FILL
    r += 1
r += 1
ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=4)
ws.cell(row=r, column=1, value="Source: live PostgreSQL queries at execution time (read-only). UAT executed GET requests only — no business data created, modified or deleted. Audit-log counts naturally grow as the UAT session authenticates users (audited by design).").font = Font(name="Arial", size=9, italic=True, color=GRAY)

# ============================================================ SIGN-OFF
ws = wb.create_sheet("Sign-off"); ws.sheet_view.showGridLines = False
ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=6)
ws.cell(row=1, column=1, value="UAT SIGN-OFF").font = Font(name="Arial", size=14, bold=True, color=NAVY)
widths(ws, [28, 34, 34, 18, 14, 30])
r = 3
ws.cell(row=r, column=1, value="ACCEPTANCE STATEMENT").font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=6); ws.cell(row=r, column=1).fill = HDR_FILL; ws.cell(row=r, column=1).alignment = LEFT
r += 1
stmt = ("All 14 ProcureSphere 360 dashboards were re-tested dashboard-wise on the live PostgreSQL environment across 345 detailed "
        "test cases covering: authorized rendering, backend RBAC for every role, anonymous protection, content-section presence, KPI "
        "accuracy against independently recomputed database ground truth, data-scope/IDOR checks, navigation, performance and HTMX "
        "interactivity. 344/345 passed. One Low-severity cosmetic defect (DEF-002, Manager breadcrumbs) and one Low hardening "
        "observation (OBS-001) are logged for backlog. No functional, RBAC, data-integrity, or security defects. "
        "RECOMMENDATION: ACCEPT for release with DEF-002/OBS-001 scheduled for the next iteration.")
ws.merge_cells(start_row=r, start_column=1, end_row=r + 3, end_column=6)
ws.cell(row=r, column=1, value=stmt).alignment = TOP_LEFT; ws.cell(row=r, column=1).font = BASE
for rr in range(r, r + 4):
    for c in range(1, 7):
        ws.cell(row=rr, column=c).border = BORDER
r += 5
for c, h in enumerate(["Role", "Name", "Signature", "Date", "Verdict", "Comments"], 1):
    ws.cell(row=r, column=c, value=h)
style_header(ws, r, 6, height=22)
for role in ["Prepared by (QA / Test Lead)", "Reviewed by (Technical Lead)", "Approved by (Project Sponsor)", "Acknowledged by (Product Owner)"]:
    r += 1
    ws.cell(row=r, column=1, value=role).font = BOLD
    for c in range(1, 7):
        ws.cell(row=r, column=c).border = BORDER; ws.cell(row=r, column=c).alignment = LEFT
    ws.row_dimensions[r].height = 26
r += 2
ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=6)
ws.cell(row=r, column=1, value="Distribution: HPE Team (PRD authority), VPD Technologies development team, docs/review_evidence/. Raw execution evidence: scratch/uat/uat_detailed.json + run_uat_detailed.py (repeatable).").font = Font(name="Arial", size=9, italic=True, color=GRAY)

out = os.path.join(ROOT, "ProcureSphere360_Dashboard_UAT_Report_v2.xlsx")
wb.save(out)
print("Saved:", out)
print("Sheets:", wb.sheetnames)
