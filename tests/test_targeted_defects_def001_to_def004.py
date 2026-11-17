"""
Targeted Regression Test Suite for Defect Remediation: DEF-001 through DEF-004.

Scope:
- DEF-001: Approver Dashboard Budget actual_spend AttributeError fixed.
           GET /api/v1/approver/dashboard/ returns HTTP 200 with available_budget calculated.
- DEF-002: Approver Queue PurchaseRequisition currency AttributeError fixed.
           GET /api/v1/approver/queue/ returns HTTP 200 with currency and urgency mapped safely.
- DEF-003: Approvals Actions target_object_id filter applied at database level.
           GET /api/v1/approvals/actions/?target_object_id=<id> filters accurately.
- DEF-004: Reports Dashboard total_spend strictly aggregates paid supplier invoices.
           GET /api/v1/reports/dashboard/summary/ excludes unpaid and exception invoices from total_spend.
"""

import uuid
from decimal import Decimal
import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.approvals.models import ApprovalAction, ApprovalPolicy, ApprovalStep
from apps.budgets.models import Budget, SpendLedger
from apps.invoices.models import SupplierInvoice
from apps.orders.models import POLine, PurchaseOrder
from apps.organization.models import CostCenter, Department, FiscalPeriod, Organization
from apps.requisitions.models import PRLine, PurchaseRequisition
from apps.vendors.models import Vendor, VendorCategory


@pytest.fixture
def targeted_test_data(db):
    # Base Organization & Departments
    org = Organization.objects.create(name="Targeted Test Org", code="TTO1")
    dept = Department.objects.create(name="Finance & Ops", code="FOP1", organization=org)
    cc = CostCenter.objects.create(name="FOP Cost Center", code="CC-FOP-01", department=dept)

    # Roles
    super_role, _ = Role.objects.get_or_create(code=Role.SUPER_ADMIN, defaults={"name": "Super Admin"})
    approver_role, _ = Role.objects.get_or_create(code=Role.DEPT_APPROVER, defaults={"name": "Dept Approver"})
    req_role, _ = Role.objects.get_or_create(code=Role.REQUESTER, defaults={"name": "Requester"})
    proc_mgr_role, _ = Role.objects.get_or_create(code=Role.PROC_MGR, defaults={"name": "Procurement Manager"})

    # Users
    admin_user = User.objects.create_superuser(
        email="targeted_admin@example.com",
        password="Pass123!Secure",
        role=super_role
    )
    approver_user = User.objects.create_user(
        email="targeted_approver@example.com",
        password="Pass123!Secure",
        role=approver_role,
        department=dept
    )
    approver_user.organization = org
    approver_user.save()

    requester_user = User.objects.create_user(
        email="targeted_requester@example.com",
        password="Pass123!Secure",
        role=req_role,
        department=dept
    )
    requester_user.organization = org
    requester_user.save()

    proc_mgr_user = User.objects.create_user(
        email="targeted_procmgr@example.com",
        password="Pass123!Secure",
        role=proc_mgr_role,
        department=dept
    )
    proc_mgr_user.organization = org
    proc_mgr_user.save()

    # Fiscal Period & Budget
    now = timezone.now().date()
    fiscal_period = FiscalPeriod.objects.create(
        organization=org,
        year=now.year,
        period_number=1,
        name="FY2026-Q4",
        start_date=now - timezone.timedelta(days=30),
        end_date=now + timezone.timedelta(days=60),
        is_closed=False
    )

    # Budget: allocated=100000, reserved=10000, committed=20000, actual=15000 -> available=55000
    budget = Budget.objects.create(
        cost_center=cc,
        fiscal_period=fiscal_period,
        allocated_amount=Decimal("100000.00"),
        reserved_amount=Decimal("10000.00"),
        committed_amount=Decimal("20000.00"),
        actual_amount=Decimal("15000.00")
    )

    # Approval Policy
    policy = ApprovalPolicy.objects.create(
        name="Targeted PR Approval Policy",
        module=ApprovalPolicy.MODULE_PR,
        department=dept,
        currency="INR",
        min_amount=Decimal("0.00"),
        max_amount=Decimal("500000.00"),
        is_active=True
    )
    step = ApprovalStep.objects.create(
        policy=policy,
        step_number=1,
        approver_role=approver_role
    )

    # Vendor Category & Vendor
    vcat = VendorCategory.objects.create(name="Services", code="SERV01")
    vendor = Vendor.objects.create(
        legal_name="Targeted Remediation Vendor Ltd",
        trade_name="Targeted Vendor",
        vendor_number="VND-TRG-001",
        tax_identification_number="TIN-TRG-001",
        category=vcat,
        organization=org,
        status=Vendor.STATUS_ACTIVE
    )

    return {
        "org": org,
        "dept": dept,
        "cc": cc,
        "admin": admin_user,
        "approver": approver_user,
        "requester": requester_user,
        "proc_mgr": proc_mgr_user,
        "budget": budget,
        "policy": policy,
        "step": step,
        "vendor": vendor,
    }


# ==============================================================================
# DEF-001: Approver Dashboard Budget actual_spend AttributeError Fix
# ==============================================================================

@pytest.mark.django_db
def test_def_001_approver_dashboard_no_attribute_error_and_budget_calculation(targeted_test_data):
    """
    DEF-001 Verification:
    GET /api/v1/approver/dashboard/ must return HTTP 200 without raising
    AttributeError: 'Budget' object has no attribute 'actual_spend'.
    Available budget must equal allocated - (reserved + committed + actual) = 55000.00.
    """
    client = APIClient()
    client.force_authenticate(user=targeted_test_data["approver"])

    response = client.get("/api/v1/approver/dashboard/")
    assert response.status_code == status.HTTP_200_OK, f"Expected 200, got {response.status_code}: {response.data}"

    data = response.data
    assert "available_budget" in data, "Dashboard response must contain 'available_budget'"
    # Available budget: 100000 - 10000 - 20000 - 15000 = 55000.00
    assert float(data["available_budget"]) == 55000.00, f"Expected 55000.00, got {data['available_budget']}"
    assert data["department_name"] == targeted_test_data["dept"].name
    assert "pending_approvals" in data
    assert "approvals_executed" in data


# ==============================================================================
# DEF-002: Approver Queue PurchaseRequisition currency AttributeError Fix
# ==============================================================================

@pytest.mark.django_db
def test_def_002_approver_queue_currency_and_urgency_mapping(targeted_test_data):
    """
    DEF-002 Verification:
    GET /api/v1/approver/queue/ must return HTTP 200 without raising
    AttributeError: 'PurchaseRequisition' object has no attribute 'currency'.
    Queue items must map currency and urgency safely from policy/defaults.
    """
    data = targeted_test_data
    pr = PurchaseRequisition.objects.create(
        pr_number="PR-TRG-001",
        title="Server Upgrade PR",
        department=data["dept"],
        cost_center=data["cc"],
        requester=data["requester"],
        status=PurchaseRequisition.STATUS_SUBMITTED,
        total_amount=Decimal("45000.00"),
        requested_delivery_date=timezone.now().date() + timezone.timedelta(days=14)
    )
    PRLine.objects.create(
        requisition=pr,
        item_description="SSD Drives",
        quantity=Decimal("5"),
        unit_of_measure="EA",
        estimated_unit_price=Decimal("9000.00"),
        estimated_total=Decimal("45000.00")
    )

    client = APIClient()
    client.force_authenticate(user=data["approver"])

    response = client.get("/api/v1/approver/queue/")
    assert response.status_code == status.HTTP_200_OK, f"Expected 200, got {response.status_code}: {response.data}"

    results = response.data if isinstance(response.data, list) else response.data.get("results", [])
    assert len(results) >= 1, f"Expected at least 1 pending PR in approver queue, got {len(results)}"

    pr_item = next((item for item in results if item.get("pr_number") == "PR-TRG-001"), None)
    assert pr_item is not None, "PR-TRG-001 must be present in queue results"
    # Mapped safely from policy currency "INR"
    assert pr_item["currency"] == "INR"
    # 45000 <= 50000 -> "NORMAL"
    assert pr_item["urgency"] == "NORMAL"
    assert float(pr_item["total_amount"]) == 45000.00


# ==============================================================================
# DEF-003: Approval Actions target_object_id Filter Ignored Fix
# ==============================================================================

@pytest.mark.django_db
def test_def_003_approvals_actions_target_object_id_filtering(targeted_test_data):
    """
    DEF-003 Verification:
    GET /api/v1/approvals/actions/?target_object_id=<id> must filter accurately at the
    database queryset level.
    Only matching records must be returned when the parameter is supplied.
    """
    data = targeted_test_data
    target_id_1 = uuid.uuid4()
    target_id_2 = uuid.uuid4()

    # Create actions for target 1
    act_1a = ApprovalAction.objects.create(
        actor=data["approver"],
        policy_step=data["step"],
        target_model_name="PurchaseRequisition",
        target_object_id=target_id_1,
        action=ApprovalAction.ACTION_APPROVE,
        comments="Approved PR 1"
    )
    act_1b = ApprovalAction.objects.create(
        actor=data["approver"],
        policy_step=data["step"],
        target_model_name="PurchaseRequisition",
        target_object_id=target_id_1,
        action=ApprovalAction.ACTION_SUBMIT,
        comments="Submitted PR 1"
    )

    # Create action for target 2
    act_2 = ApprovalAction.objects.create(
        actor=data["approver"],
        policy_step=data["step"],
        target_model_name="PurchaseRequisition",
        target_object_id=target_id_2,
        action=ApprovalAction.ACTION_APPROVE,
        comments="Approved PR 2"
    )

    client = APIClient()
    client.force_authenticate(user=data["approver"])

    # 1. Filter by target_id_1: should return exactly 2 records
    resp1 = client.get(f"/api/v1/approvals/actions/?target_object_id={target_id_1}")
    assert resp1.status_code == status.HTTP_200_OK
    results1 = resp1.data.get("results", resp1.data)
    assert len(results1) == 2, f"Expected 2 actions for target 1, got {len(results1)}"
    for r in results1:
        assert str(r["target_object_id"]) == str(target_id_1)

    # 2. Filter by target_id_2: should return exactly 1 record
    resp2 = client.get(f"/api/v1/approvals/actions/?target_object_id={target_id_2}")
    assert resp2.status_code == status.HTTP_200_OK
    results2 = resp2.data.get("results", resp2.data)
    assert len(results2) == 1, f"Expected 1 action for target 2, got {len(results2)}"
    assert str(results2[0]["target_object_id"]) == str(target_id_2)

    # 3. Filter by non-existent UUID: should return 0 records
    random_uuid = uuid.uuid4()
    resp_none = client.get(f"/api/v1/approvals/actions/?target_object_id={random_uuid}")
    assert resp_none.status_code == status.HTTP_200_OK
    results_none = resp_none.data.get("results", resp_none.data)
    assert len(results_none) == 0, f"Expected 0 actions for random UUID, got {len(results_none)}"

    # 4. Without filter: should return all actions (at least 3)
    resp_all = client.get("/api/v1/approvals/actions/")
    assert resp_all.status_code == status.HTTP_200_OK
    results_all = resp_all.data.get("results", resp_all.data)
    assert len(results_all) >= 3


# ==============================================================================
# DEF-004: Incorrect Reports Dashboard Spend Calculation Fix
# ==============================================================================

@pytest.mark.django_db
def test_def_004_reports_dashboard_total_spend_excludes_unpaid_and_exception_invoices(targeted_test_data):
    """
    DEF-004 Verification:
    GET /api/v1/reports/dashboard/summary/ must strictly calculate total_spend
    based on realized paid supplier invoices (SupplierInvoice.STATUS_PAID).
    Unpaid (pending) and exception invoices must NOT inflate total_spend.
    """
    data = targeted_test_data
    po = PurchaseOrder.objects.create(
        po_number="PO-TRG-001",
        vendor=data["vendor"],
        cost_center=data["cc"],
        created_by=data["proc_mgr"],
        status=PurchaseOrder.STATUS_APPROVED,
        total_amount=Decimal("110000.00")
    )
    POLine.objects.create(
        po=po,
        item_description="Core Network Router",
        quantity=Decimal("1"),
        unit_of_measure="EA",
        unit_price=Decimal("110000.00"),
        line_total=Decimal("110000.00")
    )

    today = timezone.now().date()
    # 1. Paid Invoice: amount = 55,000.00
    inv_paid = SupplierInvoice.objects.create(
        invoice_number="INV-TRG-PAID-001",
        vendor=data["vendor"],
        po=po,
        invoice_date=today,
        due_date=today + timezone.timedelta(days=30),
        subtotal=Decimal("55000.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal("55000.00"),
        status=SupplierInvoice.STATUS_PAID,
        created_by=data["proc_mgr"]
    )

    # 2. Pending/Approval Invoice: amount = 22,000.00
    inv_pending = SupplierInvoice.objects.create(
        invoice_number="INV-TRG-PENDING-001",
        vendor=data["vendor"],
        po=po,
        invoice_date=today,
        due_date=today + timezone.timedelta(days=30),
        subtotal=Decimal("22000.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal("22000.00"),
        status=SupplierInvoice.STATUS_APPROVAL,
        created_by=data["proc_mgr"]
    )

    # 3. Exception Invoice: amount = 33,000.00
    inv_exception = SupplierInvoice.objects.create(
        invoice_number="INV-TRG-EXCEPTION-001",
        vendor=data["vendor"],
        po=po,
        invoice_date=today,
        due_date=today + timezone.timedelta(days=30),
        subtotal=Decimal("33000.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal("33000.00"),
        status=SupplierInvoice.STATUS_EXCEPTION,
        created_by=data["proc_mgr"]
    )

    # 4. Actual Spend Ledger entry: amount = 55,000.00
    SpendLedger.objects.create(
        budget=data["budget"],
        entry_type=SpendLedger.ENTRY_ACTUAL,
        amount=Decimal("55000.00"),
        reference_number=inv_paid.invoice_number,
        description="Invoice payment actual spend",
        created_by=data["proc_mgr"]
    )

    client = APIClient()
    # Test as Superadmin
    client.force_authenticate(user=data["admin"])
    response = client.get("/api/v1/reports/dashboard-summary/")
    assert response.status_code == status.HTTP_200_OK, f"Expected 200, got {response.status_code}: {response.data}"

    res = response.data
    # Total spend must strictly reflect paid invoices (55,000), NOT sum of all invoices (110,000)
    assert float(res["total_spend"]) == 55000.00, f"Expected total_spend 55000.00, got {res['total_spend']}"
    assert float(res["paid_spend"]) == 55000.00, f"Expected paid_spend 55000.00, got {res['paid_spend']}"
    assert float(res["pending_spend"]) == 22000.00, f"Expected pending_spend 22000.00, got {res['pending_spend']}"
    assert float(res["exception_spend"]) == 33000.00, f"Expected exception_spend 33000.00, got {res['exception_spend']}"
    assert float(res["actual_ledger_spend"]) == 55000.00, f"Expected actual_ledger_spend 55000.00, got {res['actual_ledger_spend']}"

    # Also test as Procurement Manager
    client.force_authenticate(user=data["proc_mgr"])
    response_pm = client.get("/api/v1/reports/dashboard-summary/")
    assert response_pm.status_code == status.HTTP_200_OK
    assert float(response_pm.data["total_spend"]) == 55000.00

    # Also verify alias endpoint /dashboard/summary/
    response_alias = client.get("/api/v1/reports/dashboard/summary/")
    assert response_alias.status_code == status.HTTP_200_OK
    assert float(response_alias.data["total_spend"]) == 55000.00
