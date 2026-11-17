# ProcureSphere 360 — QA Defect Remediation Report
## BUG-008 & BUG-009: Finance Filtering & Requisition Access Remediation

---

### Executive Summary

| Attribute | Details |
| :--- | :--- |
| **Defect IDs** | **BUG-008** & **BUG-009** |
| **Severity / Priority** | HIGH / Critical QA Defect |
| **Target Branch** | `Anil` (synchronized with `origin/dev`) |
| **Target PR** | `Anil` → `dev` |
| **Remediation Status** | **100% Resolved & Verified** |
| **Automated Test Suite** | `tests/test_bug_008_bug_009_remediation.py` (28/28 passed) |
| **Regression Verification** | 128/128 passed (100% clean across all 6 test suites) |
| **Linter & Code Quality** | `ruff check` (0 errors), `git diff --check` (0 whitespace errors) |

---

### Defect 1: BUG-008 — Finance & AP Workspace Filter Failure

#### 1. Issue Description
When accessing the **Finance & AP Workspace** (`/finance/`), selecting a specific Department or Cost Center from the dropdown filters failed to properly filter or caused crashes in the "Pending Match Exceptions" table and metrics.

#### 2. Root Cause Analysis
1. **Query Parameter Naming Mismatch**: The template form used `name="dept"` and `name="cost_center"`, whereas REST API endpoints and integration tests frequently submitted `department`, `department_id`, `cost_center_id`, or `cc`.
2. **Type Casting and Malformed ID Crashes**: Passing a department name (e.g. `"Engineering"`), code (e.g. `"ENG"`), or non-UUID string caused Django ORM to raise `ValidationError: ['“Engineering” is not a valid UUID.']`, leading to an unhandled HTTP 500 error.
3. **Incomplete ORM Join Traversal**: Invoices with purchase orders linked to requisitions whose department was assigned via `cost_center.department_id` rather than directly on `requisition.department_id` were omitted.
4. **Missing REST API Filter Support**: The DRF viewset `MatchExceptionViewSet` (`src/apps/invoices/api_urls.py`) did not support department or cost center query parameters, returning unsorted and unfiltered exceptions.
5. **Template Layout Structure**: `templates/pages/dashboards/finance_dashboard.html` had an unclosed `div.col-12` container and lacked pagination controls for large exception lists.

#### 3. Source Code Modifications
- **`src/apps/core/views.py` (`finance_dashboard_view`)**:
  - Added robust identifier resolution supporting UUIDs, department codes, and department names with safe fallback sentinel UUIDs (`00000000-0000-0000-0000-000000000000`) for non-existent values, eliminating HTTP 500 crashes.
  - Standardized parameter aliases (`dept`, `department`, `department_id`, `cost_center`, `cost_center_id`, `cc`).
  - Added comprehensive join traversals:
    `Q(invoice__po__cost_center__department_id=...) | Q(invoice__po__requisition__department_id=...) | Q(invoice__po__requisition__cost_center__department_id=...)`.
  - Added Django `Paginator` support (10 items/page) to prevent interface degradation.
- **`templates/pages/dashboards/finance_dashboard.html`**:
  - Fixed unclosed container markup.
  - Implemented responsive pagination controls preserving active `dept` and `cost_center` filter parameters across page switches.
- **`src/apps/invoices/api_urls.py` (`MatchExceptionViewSet.get_queryset`)**:
  - Implemented department and cost center filter logic with UUID, code, and name resolution.
  - Added explicit ordering (`.order_by("-created_at")`) to eliminate unordered pagination warnings.

---

### Defect 2: BUG-009 — My Requisitions False Access Denied Error

#### 1. Issue Description
Authorized users encountered a false "Access Denied" (or HTTP 404 / 500 error) when attempting to view requisition details for authorized requisitions, specifically tested with business identifier `PR-2026-00706`.

#### 2. Root Cause Analysis
1. **URL Route Parameter Mismatch**: Requisition routes in `src/apps/requisitions/urls.py` were strictly constrained to `<uuid:pk>`, which immediately rejected business document numbers such as `PR-2026-00706`.
2. **Lookup Validation Crashes**: Calling `PurchaseRequisition.objects.filter(pk=pk)` threw `django.core.exceptions.ValidationError` when `pk` was a human-readable string like `PR-2026-00706`.
3. **Restrictive Requester Scoping**: The requester query filter in `list_view` and `detail_view` restricted requesters strictly to `requester=user`, blocking users from viewing departmental requisitions created by team members within their department or cost center.
4. **Tenant Context Evaluation**: The multi-tenant boundary check failed to resolve organization membership through `user.department.organization` and `cost_center.department.organization` when `user.organization` was null.
5. **API Endpoint Route Handling**: The DRF `PurchaseRequisitionViewSet` lacked business number lookup and proper cross-tenant 404 anti-enumeration protections.

#### 3. Source Code Modifications
- **`src/apps/requisitions/urls.py`**:
  - Changed `requisitions/<uuid:pk>/` to `requisitions/<str:pk>/` across all canonical routes (`detail`, `edit`, `submit`, `cancel`, `approve`, `reject`, `attachments`).
  - Preserved root-level direct fallback converters as `<uuid:pk>` to avoid collision with top-level paths like `/budgets/` or `/invoices/`.
- **`src/apps/requisitions/views.py`**:
  - Introduced `_get_pr_by_pk_or_number(pk, qs=None)` helper to cleanly resolve by UUID or `pr_number` without throwing exceptions.
  - Updated all action views (`detail_view`, `edit_view`, `submit_view`, `approve_view`, `reject_view`, `cancel_view`, `delete_view`, `attachment_download_view`) to utilize `_get_pr_by_pk_or_number`.
  - Expanded `detail_view` access permissions: Requesters can view their own PRs and PRs belonging to their department or cost center, while preserving strict cross-organization tenant boundaries.
  - Updated `list_view` for requesters to include departmental requisitions.
- **`src/apps/requisitions/api_urls.py` (`PurchaseRequisitionViewSet`)**:
  - Updated `get_queryset()` to include departmental PRs for requesters.
  - Overrode `get_object()` to support both UUID and `pr_number` lookups.
  - Implemented anti-IDOR protection: queries for requisitions outside the user's organization return HTTP 404 (preventing cross-tenant existence enumeration).

---

### Automated Verification & Test Coverage Matrix

A dedicated test suite was implemented in `tests/test_bug_008_bug_009_remediation.py` comprising 28 comprehensive test scenarios:

#### BUG-008 Test Coverage (15 Scenarios)
| # | Test Method | Verification Scope | Status |
| :--- | :--- | :--- | :--- |
| 1 | `test_bug008_01_default_all_departments_and_cost_centers` | All departments and cost centers shown by default | **PASSED** |
| 2 | `test_bug008_02_specific_department_only` | Filter by specific department | **PASSED** |
| 3 | `test_bug008_03_specific_cost_center_only` | Filter by specific cost center | **PASSED** |
| 4 | `test_bug008_04_specific_department_and_specific_cost_center` | Filter by both department and cost center | **PASSED** |
| 5 | `test_bug008_05_department_with_no_matching_exceptions` | Empty state when department has no exceptions | **PASSED** |
| 6 | `test_bug008_06_cost_center_with_no_matching_exceptions` | Empty state when cost center has no exceptions | **PASSED** |
| 7 | `test_bug008_07_resetting_filters_restores_default_results` | Filter reset restores complete list | **PASSED** |
| 8 | `test_bug008_08_changing_department_while_retaining_cost_center` | Department change cross-checked with cost center | **PASSED** |
| 9 | `test_bug008_09_changing_cost_center_while_retaining_department` | Cost center change cross-checked with department | **PASSED** |
| 10 | `test_bug008_10_invalid_department_identifiers_handled_gracefully` | Non-existent/invalid dept returns clean empty state, no 500 | **PASSED** |
| 11 | `test_bug008_11_invalid_cost_center_identifiers_handled_gracefully` | Non-existent/invalid CC returns clean empty state, no 500 | **PASSED** |
| 12 | `test_bug008_12_unauthorized_access_restricted_from_finance_dashboard` | RBAC restriction for non-finance users | **PASSED** |
| 13 | `test_bug008_13_api_exceptions_endpoint_filtering_and_error_handling` | REST API filtering by dept, CC, and status | **PASSED** |
| 14 | `test_bug008_14_pagination_with_active_filters` | Pagination controls preserve filter state | **PASSED** |
| 15 | `test_bug008_15_returned_records_match_requested_scope_strictly` | Strict scope verification matching filter | **PASSED** |

#### BUG-009 Test Coverage (13 Scenarios)
| # | Test Method | Verification Scope | Status |
| :--- | :--- | :--- | :--- |
| 16 | `test_bug009_01_authorized_requester_opens_own_requisition` | Requester accesses own requisition | **PASSED** |
| 17 | `test_bug009_02_authorized_department_member_opens_permitted_requisition` | Colleague in same department accesses PR | **PASSED** |
| 18 | `test_bug009_03_authorized_role_based_users_retain_access` | Procurement Manager / Superadmin accesses PR | **PASSED** |
| 19 | `test_bug009_04_unauthorized_user_blocked_from_other_department_pr` | Other department user blocked (HTTP 403) | **PASSED** |
| 20 | `test_bug009_05_unauthenticated_user_blocked` | Unauthenticated user redirected to login | **PASSED** |
| 21 | `test_bug009_06_nonexistent_requisition_returns_404` | Non-existent UUID or PR number returns HTTP 404 | **PASSED** |
| 22 | `test_bug009_07_pr_number_handling_pr_2026_00706` | URL access via `PR-2026-00706` succeeds (HTTP 200) | **PASSED** |
| 23 | `test_bug009_08_valid_database_primary_key_handling` | URL access via UUID primary key succeeds (HTTP 200) | **PASSED** |
| 24 | `test_bug009_09_correct_requisition_information_in_response` | Header, status, and metadata correctly rendered | **PASSED** |
| 25 | `test_bug009_10_correct_line_items_in_response` | Line items and amounts accurately rendered | **PASSED** |
| 26 | `test_bug009_11_existing_requisition_listing_continues_working` | Listing view renders with correct items | **PASSED** |
| 27 | `test_bug009_12_existing_approval_workflows_continue_working` | Approver can approve/reject via new URL pattern | **PASSED** |
| 28 | `test_bug009_13_identifier_manipulation_cannot_bypass_authorization` | Anti-IDOR & cross-tenant security enforcement | **PASSED** |

---

### Regression Verification Suite (128 Tests Passed)

To ensure zero regressions across all modules, all core test suites were executed simultaneously:

```
collected 128 items
tests/test_verify_excel_report_defects.py ......................   [ 17%]
tests/test_all_smoke_defects_remediated.py ............................... [ 41%]
tests/test_phase1_critical_backend_fixes.py ...............       [ 53%]
tests/test_phase2_comprehensive_qa_remediation.py ........................ [ 72%]
tests/test_manager_policy_exceptions_workflow.py ........         [ 78%]
tests/test_bug_008_bug_009_remediation.py ............................    [100%]

============================ 128 passed in 30.65s =============================
```
