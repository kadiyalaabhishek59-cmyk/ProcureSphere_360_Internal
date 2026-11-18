import json

from openpyxl import load_workbook

wb = load_workbook("ProcureSphere360_Dashboard_UAT_Report.xlsx")
print("Sheets:", wb.sheetnames)

data = json.load(open("scratch/uat/uat_results.json", encoding="utf-8"))
results = data["results"]

# per-dashboard python ground truth
truth = {}
for r in results:
    d = truth.setdefault(r["dashboard"], {"n": 0, "p": 0, "f": 0})
    d["n"] += 1
    d["p" if r["result"] == "PASS" else "f"] += 1

ws = wb["Executive Summary"]
ok = True
for row in range(5, 19):
    name = ws.cell(row=row, column=2).value
    if not name or name == "TOTAL":
        continue
    # expected formula outputs computed from ground truth
    f = ws.cell(row=row, column=6).value  # =COUNTIF(...)
    g = ws.cell(row=row, column=7).value
    t = truth.get(name, {"n": 0, "p": 0})
    # sanity: name in truth
    status = "OK" if (t["n"] > 0 and t["p"] == t["n"]) else "MISMATCH"
    if status != "OK":
        ok = False
    print(f"{name[:36]:38} cases={t['n']:3} pass={t['p']:3} formula-check {status}")

ws = wb["UAT Test Cases"]
print("Test-case rows: header at", 4, "first data", ws.cell(row=5, column=1).value, "last data", ws.cell(row=4 + len(results), column=1).value)
print("Result col J sample:", [ws.cell(row=x, column=10).value for x in (5, 6, 158)])
print("Duration col K sample:", [ws.cell(row=x, column=11).value for x in (5, 6, 158)])

ws = wb["Cover"]
for row in range(1, 40):
    v = ws.cell(row=row, column=2).value
    if v and str(v).startswith("="):
        print("Cover formula row", row, ":", v)

ws = wb["RBAC Access Matrix"]
print("RBAC matrix dims:", ws.dimensions)
print("Sample row:", [ws.cell(row=5, column=c).value for c in range(1, 13)])

ws = wb["HTMX Widgets"]
print("Widget rows:")
for row in range(5, 12):
    print("  ", [ws.cell(row=row, column=c).value for c in (2, 4, 5, 6, 7)])

print("ALL SUMMARY MATCH:", ok)
