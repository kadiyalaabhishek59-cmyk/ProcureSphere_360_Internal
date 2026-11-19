# ProcureSphere 360 — Master Engineering Remediation Execution Summary

> **Document Reference:** PS360-QA-REMED-2026-FINAL  
> **Date:** November 18, 2026  
> **Target Branch:** `feature/integration-defects-remediation`  
> **Repository:** `c:\Users\ABC\ProcureSphere_360_Internal`  
> **Status:** **ALL DEFECTS RESOLVED — 100% PASS (54/54 TESTS VERIFIED)**

---

## 1. Executive Summary

This engineering remediation was executed under the Senior Software Architect and QA Lead directive to permanently resolve all six confirmed functional defects identified in the Functional Testing Report, correct faulty regression assertions, eliminate type discrepancies, verify database consistency, and prove resolution through real automated test execution.

Every defect was traced to its technical root cause in the backend architecture, services, permissions, and selectors. All fixes were implemented strictly within domain services and backend API layers without mock functionality. Full backward compatibility, existing API contracts, and business workflows were preserved.

Across **5 test suites** and **54 automated regression test cases**, the test pass rate is **100% (54 passed, 0 failed)**.

---

## 2. Defect Remediation & Technical Root-Cause Breakdown

### DEF-002 & DEF-022: Budget Limit Not Enforced on Requisition Submission
- **Severity:** Critical
- **Observed Failure:** When a purchase requisition exceeded the available approved budget of its cost center, the normal submission either improperly proceeded or caught `BudgetOverrunException` and converted the requisition to `STATUS_BUDGET_REVIEW` instead of enforcing a fail-closed rejection.
- **Root Cause:** In `src/apps/requisitions/services.py`, `submit_purchase_requisition_service()` caught `BudgetOverrunException` and set `requisition.status = PurchaseRequisition.STATUS_BUDGET_REVIEW` unconditionally, allowing normal submissions to bypass budget limits and initiate approval workflows.
- **Remediation Implemented:**
  1. Updated `submit_purchase_requisition_service()` to accept an explicit `allow_budget_exception: bool = False` flag.
  2. For normal submissions (`allow_budget_exception=False`), any budget overrun (whether `allow_overspend` is enabled or disabled) immediately raises a `ValidationError` with a clear message: `"Insufficient budget for Cost Center '<CC>'. Requested: $<Amount>. Requisition submission rejected under fail-closed budget policy."`
  3. The Requisition API endpoint catches this validation error and returns **HTTP 400 Bad Request**.
  4. The purchase requisition remains in **`STATUS_DRAFT`**.
  5. Zero `BudgetReservation` records and zero `ApprovalAction` records are created.
  6. Database atomicity guarantees complete rollback if any validation fails.
  7. Valid submissions within available budget continue to proceed smoothly to `STATUS_MANAGER_REVIEW` with atomic budget reservations.
- **Files Modified:**
  - `src/apps/requisitions/services.py`
  - `src/apps/requisitions/api_urls.py`
- **Verification Tests:**
  - `tests/test_master_engineering_remediation_defects.py::test_def_002_022_budget_limit_fail_closed_submission` (**PASSED**)
  - `tests/test_all_28_excel_defects_retest.py::test_tc_req_085_bud_045_def_002_022_budget_overspend_blocked` (**PASSED**)

---

### DEF-010: Manager Approval Desk Unusable / Hardcoded 403 Forbidden
- **Severity:** High
- **Observed Failure:** Authorized Procurement Managers accessing the Manager Approval Desk were blocked from approving purchase requisitions and purchase order amendments with HTTP 403 Forbidden. Approval UI flags were hardcoded to `False`. Previous test assertions falsely asserted that Procurement Managers should receive HTTP 403.
- **Root Cause:**
  - In `src/apps/core/manager_api_views.py`:
    - `can_approve_pr = False` and `'can_approve': False` were hardcoded in `ManagerApprovalsAPIView`.
    - `ManagerApprovalActionAPIView` contained artificial blocks explicitly returning `HTTP 403 FORBIDDEN` for `Role.PROC_MGR` claiming "Procurement Managers maintain approval oversight only".
  - In `tests/test_all_28_excel_defects_retest.py`: line 214 falsely asserted `res.status_code == 403`.
- **Remediation Implemented:**
  1. Removed the artificial HTTP 403 blocking checks for `Role.PROC_MGR` in `ManagerApprovalActionAPIView` for both Purchase Requisitions and PO Amendments.
  2. In `ManagerApprovalsAPIView`, set `can_approve_pr = True` and `can_reject_pr = True`, and `'can_approve': True` for pending PO amendments.
  3. Wired direct execution to `approve_purchase_requisition_service()`, `reject_purchase_requisition_service()`, `approve_po_amendment_service()`, and `reject_po_amendment_service()`, returning **HTTP 200 OK** with `success: True`, updated status, and audit trail.
  4. Preserved strict **HTTP 403 Forbidden** for unauthorized roles (e.g. Requester, Stores Receiver, Vendor User).
  5. Corrected the regression test assertion to verify that authorized Procurement Managers receive **HTTP 200 OK** and successfully transition requisitions to `STATUS_APPROVED`, while unauthorized users receive **HTTP 403 Forbidden**.
- **Files Modified:**
  - `src/apps/core/manager_api_views.py`
  - `tests/test_all_28_excel_defects_retest.py`
- **Verification Tests:**
  - `tests/test_master_engineering_remediation_defects.py::test_def_010_manager_approval_desk_usable` (**PASSED**)
  - `tests/test_all_28_excel_defects_retest.py::test_tc_mgr_003_037_def_010_manager_approval_desk` (**PASSED**)

---

### DEF-011: Cross-Organization Budget Maintenance Failure by Super Admin
- **Severity:** High
- **Observed Failure:** Super Admin could not read, PATCH, or PUT budgets belonging to other organizations.
- **Root Cause:** `scope_budgets_queryset()` in `src/apps/budgets/selectors.py` and `CanManageBudget` in `src/apps/budgets/api_urls.py` required explicit verification of global Super Admin management while maintaining strict tenant isolation for regular users.
- **Remediation Implemented:**
  1. Enforced global bypass in `scope_budgets_queryset()` for `request.user.is_superuser` and `role_code == Role.SUPER_ADMIN`.
  2. In `CanManageBudget`, verified that Super Admin is authorized for all methods (GET, POST, PUT, PATCH, DELETE) across all organizations.
  3. Ensured database persistence of updated `allocated_amount`, `available_amount`, and `allow_overspend` flags on cross-organization updates.
  4. Verified that non-admin users (e.g. Finance AP from Organization A) attempting to access or modify Organization B's budget receive **HTTP 404 Not Found**, ensuring zero cross-tenant leakage.
- **Files Modified:**
  - `src/apps/budgets/selectors.py`
  - `src/apps/budgets/api_urls.py`
- **Verification Tests:**
  - `tests/test_master_engineering_remediation_defects.py::test_def_011_cross_org_budget_update_superadmin` (**PASSED**)
  - `tests/test_all_28_excel_defects_retest.py::test_tc_bud_013_def_011_superadmin_cross_org_budget_patch` (**PASSED**)

---

### DEF-019: Goods Receipt PUT Full Update Failure
- **Severity:** Medium
- **Observed Failure:** Executing a full HTTP PUT update on an existing goods receipt failed with false PO status validation errors (claiming the PO was not in `ISSUED` status because goods receipts had already moved the PO to `PARTIAL_RECEIPT` or `COMPLETED`) or triggered duplicate receipt-number validation against itself.
- **Root Cause:** `GoodsReceiptSerializer.validate()` in `src/apps/receipts/api_urls.py` validated PO status as if recording a brand-new receipt, and failed to exclude `self.instance.pk` during duplicate GRN and delivery note uniqueness checks.
- **Remediation Implemented:**
  1. Scoped the PO status check to new PO associations only (`is_new_po = not self.instance or ("po" in attrs and attrs["po"] != self.instance.po)`).
  2. For existing receipts where the PO remains unchanged, bypassed the initial `ISSUED` requirement, allowing updates (e.g., delivery notes, remarks, item quantities) on receipts for `PARTIAL_RECEIPT` or `COMPLETED` purchase orders.
  3. Explicitly excluded `self.instance.pk` from unique checks (`qs_grn.exclude(pk=self.instance.pk)` and `qs_dn.exclude(pk=self.instance.pk)`).
  4. The PUT endpoint returns **HTTP 200 OK** with refreshed database persistence.
- **Files Modified:**
  - `src/apps/receipts/api_urls.py`
- **Verification Tests:**
  - `tests/test_master_engineering_remediation_defects.py::test_def_019_goods_receipt_put_update` (**PASSED**)
  - `tests/test_all_28_excel_defects_retest.py::test_tc_grn_007_def_019_goods_receipt_put_update` (**PASSED**)

---

### DEF-023: Role-Based Access Control Read Permission Mismatches
- **Severity:** High
- **Observed Failure:** Inconsistencies between endpoint behavior and the official `docs/rbac_matrix.md`:
  - Stores Receiver and Legal Manager could read purchase requisitions.
  - Stores Receiver was blocked from reading purchase orders.
  - Vendor User was blocked from reading their own contracts.
  - Super Admin was allowed to access manager-only operational KPIs (`/api/v1/manager/kpis/`).
- **Root Cause:** Inconsistent permission classes and queryset scoping logic across requisitions, orders, contracts, and manager desk views.
- **Remediation Implemented:**
  1. **Requisitions (`/api/v1/requisitions/`):** Removed `Role.STORES_RECEIVER` and `Role.LEGAL_MGR` from the authorized list in `get_queryset()` and enforced rejection in `CanCreateRequisitionPermission` (`has_permission` returns `False`). Both roles receive **HTTP 403 Forbidden**.
  2. **Purchase Orders (`/api/v1/orders/`):** In `CanManagePurchaseOrder`, explicitly granted read access for `Role.STORES_RECEIVER` on safe methods (`GET`). Stores Receiver receives **HTTP 200 OK** to inspect incoming POs.
  3. **Contracts (`/api/v1/contracts/`):** In `CanViewContract`, verified that `Role.LEGAL_MGR` and `Role.VENDOR_USER` have permission on safe methods. Vendor users see their own vendor-scoped contracts (**HTTP 200 OK**) and cannot see competitors' contracts.
  4. **Manager KPIs (`/api/v1/manager/kpis/`):** In `ManagerKPIsAPIView.get()`, strictly enforced `if role_code != Role.PROC_MGR: return 403 FORBIDDEN`. `SUPER_ADMIN` receives **HTTP 403 Forbidden** because operational manager KPIs are strictly reserved for operational Procurement Managers.
- **Files Modified:**
  - `src/apps/requisitions/api_urls.py`
  - `src/apps/orders/api_urls.py`
  - `src/apps/contracts/permissions.py`
  - `src/apps/core/manager_api_views.py`
- **Verification Tests:**
  - `tests/test_master_engineering_remediation_defects.py::test_def_023_rbac_matrix_compliance` (**PASSED**)
  - `tests/test_all_28_excel_defects_retest.py::test_tc_req_061_062_def_023_stores_and_legal_denied_requisitions` (**PASSED**)
  - `tests/test_all_28_excel_defects_retest.py::test_tc_po_094_def_023_stores_receiver_can_read_orders` (**PASSED**)
  - `tests/test_all_28_excel_defects_retest.py::test_tc_con_074_def_023_vendor_user_can_read_contracts` (**PASSED**)
  - `tests/test_all_28_excel_defects_retest.py::test_tc_mgr_069_def_023_super_admin_denied_manager_kpis` (**PASSED**)

---

### Codebase Health & Integration Remediation (Reports & Approvals)
- **Resolved Issues:**
  1. **Reports Service Typing & Pylance Squiggly:** In `src/apps/reports/services.py`, typed `REPORT_DISPATCHER: dict[str, Any]` and forwarded parameters via `kwargs = {"user": job.requested_by}; data = report_fn(**kwargs)` to eliminate static type checker warnings while maintaining seamless dynamic dispatch across all 13 report generators.
  2. **DEF-001 (TC-APR-008):** In `src/apps/approvals/api_urls.py`, fixed `ApprovalActionViewSet` to convert `target_object_id` to string, ensuring cross-model UUID and integer lookups return exact filtered action histories without data pollution.
  3. **DEF-002 (TC-RPT-005):** In `src/apps/reports/services.py`, reconciled `total_spend` strictly against `SupplierInvoice.STATUS_PAID` and `SpendLedger.ENTRY_ACTUAL`, completely excluding unpaid, draft, and exception invoices.
- **Files Modified:**
  - `src/apps/reports/services.py`
  - `src/apps/approvals/api_urls.py`

---

## 3. Comprehensive Regression Test Execution Summary

The entire regression suite was executed via pytest against an isolated test database. All 54 tests passed with zero failures:

```
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-9.1.1, pluggy-1.6.0
django: version: 5.2.17, settings: config.settings.test (from ini)
rootdir: C:\Users\ABC\ProcureSphere_360_Internal
collected 54 items

tests/test_master_engineering_remediation_defects.py::test_def_002_022_budget_limit_fail_closed_submission PASSED [  1%]
tests/test_master_engineering_remediation_defects.py::test_def_010_manager_approval_desk_usable PASSED [  3%]
tests/test_master_engineering_remediation_defects.py::test_def_011_cross_org_budget_update_superadmin PASSED [  5%]
tests/test_master_engineering_remediation_defects.py::test_def_019_goods_receipt_put_update PASSED [  7%]
tests/test_master_engineering_remediation_defects.py::test_def_023_rbac_matrix_compliance PASSED [  9%]
tests/test_all_28_excel_defects_retest.py::test_tc_apr_005_proc_mgr_approves_pending_action PASSED [ 11%]
tests/test_all_28_excel_defects_retest.py::test_tc_bud_013_def_011_superadmin_cross_org_budget_patch PASSED [ 12%]
tests/test_all_28_excel_defects_retest.py::test_tc_mgr_003_037_def_010_manager_approval_desk PASSED [ 14%]
tests/test_all_28_excel_defects_retest.py::test_tc_grn_007_def_019_goods_receipt_put_update PASSED [ 16%]
tests/test_all_28_excel_defects_retest.py::test_tc_req_013_014_017_018_requisition_actions_by_proc_mgr PASSED [ 18%]
tests/test_all_28_excel_defects_retest.py::test_tc_src_087_sourcing_list_vs_detail_representation PASSED [ 20%]
tests/test_all_28_excel_defects_retest.py::test_tc_ven_029_vendor_list_vs_detail_representation PASSED [ 22%]
tests/test_all_28_excel_defects_retest.py::test_tc_ven_063_vendor_legal_name_unicode_and_script PASSED [ 24%]
tests/test_all_28_excel_defects_retest.py::test_tc_org_044_organization_code_hyphen_underscore PASSED [ 25%]
tests/test_all_28_excel_defects_retest.py::test_tc_con_053_contract_unique_title_ignores_terminated_and_draft PASSED [ 27%]
tests/test_all_28_excel_defects_retest.py::test_tc_req_061_062_def_023_stores_and_legal_denied_requisitions PASSED [ 29%]
tests/test_all_28_excel_defects_retest.py::test_tc_po_094_def_023_stores_receiver_can_read_orders PASSED [ 31%]
tests/test_all_28_excel_defects_retest.py::test_tc_con_074_def_023_vendor_user_can_read_contracts PASSED [ 33%]
tests/test_all_28_excel_defects_retest.py::test_tc_mgr_069_def_023_super_admin_denied_manager_kpis PASSED [ 35%]
tests/test_all_28_excel_defects_retest.py::test_tc_ven_108_empty_search_equals_unfiltered_count PASSED [ 37%]
tests/test_all_28_excel_defects_retest.py::test_tc_req_085_bud_045_def_002_022_budget_overspend_blocked PASSED [ 38%]
tests/test_all_28_excel_defects_retest.py::test_tc_grn_049_duplicate_grn_number_handled PASSED [ 40%]
tests/test_all_28_excel_defects_retest.py::test_tc_grn_052_rejected_quantity_default_reason PASSED [ 42%]
tests/test_all_28_excel_defects_retest.py::test_tc_wf_001_procure_to_pay_happy_path PASSED [ 44%]
tests/test_all_28_excel_defects_retest.py::test_tc_apr_060_super_admin_cross_org_pr_creation PASSED [ 46%]
tests/test_all_28_excel_defects_retest.py::test_tc_ui_010_auditor_dashboard_redirect PASSED [ 48%]
tests/test_cir_integration_defects_def001_def002.py::test_cir_def001_tc_apr_008_approval_actions_target_object_id_filtering PASSED [ 50%]
tests/test_cir_integration_defects_def001_def002.py::test_cir_def002_tc_rpt_005_dashboard_total_spend_reconciliation PASSED [ 51%]
tests/test_targeted_defects_def001_to_def004.py::test_def_001_approver_dashboard_no_attribute_error_and_budget_calculation PASSED [ 53%]
tests/test_targeted_defects_def001_to_def004.py::test_def_002_approver_queue_currency_and_urgency_mapping PASSED [ 55%]
tests/test_targeted_defects_def001_to_def004.py::test_def_003_approvals_actions_target_object_id_filtering PASSED [ 57%]
tests/test_targeted_defects_def001_to_def004.py::test_def_004_reports_dashboard_total_spend_excludes_unpaid_and_exception_invoices PASSED [ 59%]
tests/test_verify_excel_report_defects.py::test_def_001_brute_force_lockout_enforced PASSED [ 61%]
tests/test_verify_excel_report_defects.py::test_def_002_invoices_rbac_requester_dept_approver_legal_denied_403 PASSED [ 62%]
tests/test_verify_excel_report_defects.py::test_def_003_org_creation_writes_audit_entry PASSED [ 64%]
tests/test_verify_excel_report_defects.py::test_def_004_approval_actions_filter_target_object_id PASSED [ 66%]
tests/test_verify_excel_report_defects.py::test_def_005_vendor_kyc_approval_audited PASSED [ 68%]
tests/test_verify_excel_report_defects.py::test_def_006_requisition_without_lines_rejected_400 PASSED [ 70%]
tests/test_verify_excel_report_defects.py::test_def_007_requisition_cost_center_department_mismatch_rejected_400 PASSED [ 72%]
tests/test_verify_excel_report_defects.py::test_def_008_pr_submission_writes_submit_audit PASSED [ 74%]
tests/test_verify_excel_report_defects.py::test_def_009_po_approval_creates_approval_action_row PASSED [ 75%]
tests/test_verify_excel_report_defects.py::test_def_010_duplicate_po_number_returns_400_not_500 PASSED [ 77%]
tests/test_verify_excel_report_defects.py::test_def_011_duplicate_grn_number_rejected_400 PASSED [ 79%]
tests/test_verify_excel_report_defects.py::test_def_012_goods_receipt_creates_notification PASSED [ 81%]
tests/test_verify_excel_report_defects.py::test_def_013_dashboard_total_spend_equals_paid_invoices PASSED [ 83%]
tests/test_verify_excel_report_defects.py::test_def_014_audit_entries_store_ip_and_request_id PASSED [ 85%]
tests/test_verify_excel_report_defects.py::test_def_015_failed_login_creates_audit_log_visible_to_auditor PASSED [ 87%]
tests/test_verify_excel_report_defects.py::test_def_016_finance_dashboard_bug_fixes PASSED [ 88%]
tests/test_verify_excel_report_defects.py::test_def_017_match_exception_resolution_notes_validation PASSED [ 90%]
tests/test_verify_excel_report_defects.py::test_def_018_payment_reference_utr_validation PASSED [ 92%]
tests/test_verify_excel_report_defects.py::test_def_020_invoice_number_format_validation PASSED [ 94%]
tests/test_verify_excel_report_defects.py::test_bug_008_finance_dashboard_filtering_dept_and_cost_center PASSED [ 96%]
tests/test_verify_excel_report_defects.py::test_bug_009_requisition_detail_authorized_access PASSED [ 98%]
tests/test_verify_excel_report_defects.py::test_def_019_modal_overflow_hidden_on_body PASSED [100%]

====================== 54 passed in 24.83s =======================
```

---

## 4. Phase 7 Deliverables Index

All requested deliverables have been generated in the `QA_REMEDIATION_RESULTS/` directory:

| Deliverable File | Format | Description |
|---|---|---|
| [Defect_Remediation_Report.xlsx](file:///c:/Users/ABC/ProcureSphere_360_Internal/QA_REMEDIATION_RESULTS/Defect_Remediation_Report.xlsx) | Excel (.xlsx) | Detailed breakdown of DEF-002, DEF-010, DEF-011, DEF-019, DEF-022, and DEF-023: Root causes, remediation steps, modified files, test mappings, and resolution status. |
| [Complete_Regression_Test_Report.xlsx](file:///c:/Users/ABC/ProcureSphere_360_Internal/QA_REMEDIATION_RESULTS/Complete_Regression_Test_Report.xlsx) | Excel (.xlsx) | Full regression execution evidence covering all 54 executed test cases, test functions, domain assertions, execution durations, and PASSED status. |
| [RBAC_Permission_Matrix.xlsx](file:///c:/Users/ABC/ProcureSphere_360_Internal/QA_REMEDIATION_RESULTS/RBAC_Permission_Matrix.xlsx) | Excel (.xlsx) | Comprehensive matrix cross-referencing all 10 system roles against core modules, read/write permissions, scoping rules, and DEF-023 compliance notes. |
| [Remediation_Execution_Summary.md](file:///c:/Users/ABC/ProcureSphere_360_Internal/QA_REMEDIATION_RESULTS/Remediation_Execution_Summary.md) | Markdown (.md) | Executive summary, root-cause analyses, verification results, and architecture governance statement. |

---

## 5. Architectural & Governance Attestation

1. **Strict Git Discipline Observed:** Zero `git` mutations (commit, checkout, reset, push) were performed in this session, honoring the user constraint.
2. **Zero Mock Functionality:** All fixes interact with real normalized models, Django services, and DRF viewsets persisted to the database.
3. **Fail-Closed Security:** Requisitions exceeding budget fail closed immediately with HTTP 400. RBAC permissions are enforced server-side.
4. **Tenant Isolation:** Cross-organization budget maintenance is strictly limited to Super Admins; standard users are blocked with HTTP 404 from other organizations' data.
5. **No Regressions:** All 28 original defects, integration defects, and new remediation tests pass cleanly.
