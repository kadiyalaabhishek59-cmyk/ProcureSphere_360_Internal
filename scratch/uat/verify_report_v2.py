# -*- coding: utf-8 -*-
"""Verify the v2 UAT report workbook against uat_detailed.json ground truth."""
import json
import os
import sys

from openpyxl import load_workbook

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
wb = load_workbook(os.path.join(ROOT, "ProcureSphere360_Dashboard_UAT_Report_v2.xlsx"))
data = json.load(open(os.path.join(HERE, "uat_detailed.json"), encoding="utf-8"))

errors = []
checks = 0

def check(label, ok, detail=""):
    global checks
    checks += 1
    if not ok:
        errors.append(f"{label}: {detail}")

# 1. sheet inventory
expected_sheets = ["Cover", "Executive Summary", "RBAC Access Matrix", "Defects & Observations",
                   "Test Data & Environment", "Sign-off"]
check("sheet count", len(wb.sheetnames) == 20, str(len(wb.sheetnames)))
for s in expected_sheets:
    check(f"sheet present: {s}", s in wb.sheetnames)
dash_sheets = [s for s in wb.sheetnames if " - " in s and s not in ("Defects & Observations", "Test Data & Environment")]
check("14 dashboard sheets", len(dash_sheets) == 14, str(dash_sheets))

# 2. per-sheet case counts and formulas match ground truth
truth = {}
for c in data["results"]:
    t = truth.setdefault(c["dashboard"], {"total": 0, "pass": 0, "fail": 0})
    t["total"] += 1
    t["pass"] += c["result"] == "PASS"
    t["fail"] += c["result"] == "FAIL"

CODE_MAP = {"RD": "Requester Dashboard", "AD": "Department Approver Dashboard",
            "PD": "Procurement Executive Dashboard", "FD": "Finance / AP Dashboard",
            "SD": "Stores / Receiver Dashboard", "LD": "Legal / Contracts Dashboard",
            "MD": "Procurement Manager Dashboard", "AUD": "Compliance / Auditor Dashboard",
            "SA": "Super Admin Dashboard", "VP": "Vendor Portal Dashboard",
            "BP": "Vendor Bid Portal Monitor", "EV": "Evaluation & Award Dashboard",
            "RH": "Reports Hub", "OD": "Organization Dashboard (per org)"}

total_rows = 0
grand_fail = 0
for sheet in dash_sheets:
    code = sheet.split(" - ")[0]
    dash = CODE_MAP[code]
    ws = wb[sheet]
    tcase = truth.get(dash, {"total": 0, "pass": 0, "fail": 0})
    rows = 0
    fails = 0
    ids = []
    for row in ws.iter_rows(min_row=8, max_row=400, max_col=7):
        tc, res = row[0].value, row[5].value
        if tc and str(tc).startswith(code + "-"):
            rows += 1
            ids.append(tc)
            if res == "FAIL":
                fails += 1
            elif res != "PASS":
                errors.append(f"{sheet} {tc}: unexpected result value {res!r}")
    total_rows += rows
    grand_fail += fails
    check(f"{sheet}: row count {rows} == truth {tcase['total']}", rows == tcase["total"], f"got {rows}")
    check(f"{sheet}: FAIL count {fails} == truth {tcase['fail']}", fails == tcase["fail"], f"got {fails}")
    # sequential TC IDs
    exp_ids = [f"{code}-{i:03d}" for i in range(1, rows + 1)]
    check(f"{sheet}: sequential TC IDs", ids == exp_ids, f"first/last mismatch: {ids[:2]}...{ids[-2:]}")
    # summary strip formulas (locate the strip row dynamically)
    strip_f = None
    for rr_ in range(2, 12):
        v = ws.cell(row=rr_, column=2).value
        if isinstance(v, str) and v.startswith("="):
            strip_f = [ws.cell(row=rr_, column=c).value for c in (2, 4, 6, 8)]
            break
    check(f"{sheet}: summary strip has 4 formulas", strip_f is not None and sum(1 for v in strip_f if isinstance(v, str) and v.startswith("=")) == 4, str(strip_f))

# 3. ground truth totals
check("grand total rows == 345", total_rows == 345, str(total_rows))
check("grand total FAILs == 1", grand_fail == 1, str(grand_fail))

# 4. MD sheet contains the DEF-002 FAIL row
ws = wb["MD - Core Role"]
fail_rows = [r for r in ws.iter_rows(min_row=8, max_row=400, max_col=7) if r[5].value == "FAIL"]
check("MD: exactly 1 FAIL row", len(fail_rows) == 1, str(len(fail_rows)))
if fail_rows:
    row = fail_rows[0]
    txt = " ".join(str(row[i].value) for i in range(7))
    check("MD FAIL row is breadcrumb case", "readcrumb" in txt and "DEF-002" in txt, txt[:120])
    check("MD FAIL row red styling", row[5].fill.fgColor.rgb in ("00FFC7CE", "FFC7CE"), str(row[5].fill.fgColor.rgb))

# 5. Executive Summary formulas
ws = wb["Executive Summary"]
n_formula_rows = 0
for r in range(5, 25):
    f6 = ws.cell(row=r, column=6).value
    if isinstance(f6, str) and "COUNTIF" in f6:
        n_formula_rows += 1
        g = ws.cell(row=r, column=7).value
        h = ws.cell(row=r, column=8).value
        check(f"ExecSummary row {r}: COUNTIF formulas", isinstance(g, str) and "COUNTIF" in g and isinstance(h, str) and "COUNTIF" in h, f"{g} / {h}")
        i = ws.cell(row=r, column=9).value
        check(f"ExecSummary row {r}: pass-rate formula", isinstance(i, str) and "IFERROR" in i, str(i))
check("ExecSummary: 14 dashboard rows with formulas", n_formula_rows == 14, str(n_formula_rows))
tot_row = None
for r in range(5, 30):
    if ws.cell(row=r, column=3).value == "TOTAL — ALL DASHBOARDS":
        tot_row = r
        break
check("ExecSummary: TOTAL row present", tot_row is not None)
if tot_row:
    check("ExecSummary: TOTAL uses SUM", "SUM" in str(ws.cell(row=tot_row, column=6).value), str(ws.cell(row=tot_row, column=6).value))

# 6. RBAC matrix: 14 rows x 11 role columns
ws = wb["RBAC Access Matrix"]
rbac_rows = 0
for r in range(4, 40):
    v = ws.cell(row=r, column=1).value
    if v and isinstance(v, str) and v in CODE_MAP.values():
        rbac_rows += 1
check("RBAC: 14 dashboard rows", rbac_rows == 14, str(rbac_rows))

# 7. Defects sheet: DEF-002 + OBS-001..004
ws = wb["Defects & Observations"]
ids = [ws.cell(row=r, column=1).value for r in range(4, 12)]
found = [i for i in ids if i]
check("Defects: DEF-002 present", "DEF-002" in found, str(found))
for o in ["OBS-001", "OBS-002", "OBS-003", "OBS-004"]:
    check(f"Defects: {o} present", o in found, str(found))

# 8. fonts Arial
non_arial = []
for sheet in wb.sheetnames:
    for row in wb[sheet].iter_rows():
        for cell in row:
            if cell.value is not None and cell.font and cell.font.name and cell.font.name != "Arial" and cell.font.name != "Consolas":
                non_arial.append((sheet, cell.coordinate, cell.font.name))
                break
check("fonts: no non-Arial body fonts (Consolas code style allowed)", len(non_arial) == 0, str(non_arial[:5]))

print(f"Verification complete: {checks} checks, {len(errors)} errors")
for e in errors:
    print("  ERROR:", e)
if not errors:
    print("ALL CHECKS PASSED")
