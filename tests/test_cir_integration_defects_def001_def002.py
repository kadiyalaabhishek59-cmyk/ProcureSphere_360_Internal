"""
Dedicated Regression Test Suite for Integration Defect Remediation:
- DEF-001 (TC-APR-008): GET /api/v1/approvals/actions/?target_object_id=<id> filtering at database queryset level.
- DEF-002 (TC-RPT-005): Dashboard total_spend reconciliation with PAID invoices and ACTUAL spend ledger.

Report reference: ProcureSphere360_C_I_R_Integration_Testing_Report.xlsx
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
def cir_defect_test_data(db):
    """
    Sets up multi-tenant test organizations, roles, users, and masters
    for validating DEF-001 (TC-APR-008) and DEF-002 (TC-RPT-005).
    """
    # 1. Primary Organization
    org = Organization.objects.create(name="HPE Primary Enterprise", code="HPE-ORG-01")
    dept = Department.objects.create(name="Global Procurement", code="GP-01", organization=org)
    cc = CostCenter.objects.create(name="Core IT Ops", code="CC-IT-001", department=dept)

    # 2. Secondary Organization (for boundary & isolation checks)
    other_org = Organization.objects.create(name="External Sister Entity", code="EXT-ORG-02")
    other_dept = Department.objects.create(name="Logistics", code="LOG-02", organization=other_org)
    other_cc = CostCenter.objects.create(name="Logistics CC", code="CC-LOG-002", department=other_dept)

    # 3. Roles
    super_role, _ = Role.objects.get_or_create(code=Role.SUPER_ADMIN, defaults={"name": "Super Admin"})
    proc_mgr_role, _ = Role.objects.get_or_create(code=Role.PROC_MGR, defaults={"name": "Procurement Manager"})
    dept_approver_role, _ = Role.objects.get_or_create(code=Role.DEPT_APPROVER, defaults={"name": "Department Approver"})
    requester_role, _ = Role.objects.get_or_create(code=Role.REQUESTER, defaults={"name": "Requester"})
    finance_role, _ = Role.objects.get_or_create(code=Role.FINANCE_AP, defaults={"name": "Finance AP"})
    auditor_role, _ = Role.objects.get_or_create(code=Role.AUDITOR, defaults={"name": "Auditor"})

    # 4. Users
    super_user = User.objects.create_superuser(
        email="cir_superadmin@hpe.test",
        password="Pass123!Secure",
        role=super_role
    )

    proc_mgr = User.objects.create_user(
        email="cir_procmgr@hpe.test",
        password="Pass123!Secure",
        role=proc_mgr_role,
        department=dept
    )
    proc_mgr.organization = org
    proc_mgr.save()

    dept_approver = User.objects.create_user(
        email="cir_approver@hpe.test",
        password="Pass123!Secure",
        role=dept_approver_role,
        department=dept
    )
    dept_approver.organization = org
    dept_approver.save()

    requester = User.objects.create_user(
        email="cir_requester@hpe.test",
        password="Pass123!Secure",
        role=requester_role,
        department=dept
    )
    requester.organization = org
    requester.save()

    finance_user = User.objects.create_user(
        email="cir_finance@hpe.test",
        password="Pass123!Secure",
        role=finance_role,
        department=dept
    )
    finance_user.organization = org
    finance_user.save()

    auditor_user = User.objects.create_user(
        email="cir_auditor@hpe.test",
        password="Pass123!Secure",
        role=auditor_role,
        department=dept
    )
    auditor_user.organization = org
    auditor_user.save()

    # User in other organization
    other_user = User.objects.create_user(
        email="cir_other@external.test",
        password="Pass123!Secure",
        role=proc_mgr_role,
        department=other_dept
    )
    other_user.organization = other_org
    other_user.save()

    # 5. Fiscal Period & Budget
    now = timezone.now().date()
    fiscal_period = FiscalPeriod.objects.create(
        organization=org,
        year=now.year,
        period_number=1,
        name="FY2026-CIR-Q1",
        start_date=now - timezone.timedelta(days=30),
        end_date=now + timezone.timedelta(days=60),
        is_closed=False
    )

    budget = Budget.objects.create(
        cost_center=cc,
        fiscal_period=fiscal_period,
        allocated_amount=Decimal("500000.00"),
        reserved_amount=Decimal("50000.00"),
        committed_amount=Decimal("100000.00"),
        actual_amount=Decimal("75000.00")
    )

    # 6. Policy & Step
    policy = ApprovalPolicy.objects.create(
        name="CIR Standard PO Policy",
        module=ApprovalPolicy.MODULE_PO,
        min_amount=Decimal("0.00"),
        max_amount=Decimal("1000000.00"),
        department=dept,
        organization=org,
        is_active=True
    )
    step = ApprovalStep.objects.create(
        policy=policy,
        step_number=1,
        description="Manager Signoff",
        approver_role=proc_mgr_role,
        is_mandatory=True
    )

    # 7. Vendors
    cat, _ = VendorCategory.objects.get_or_create(code="ITHW", defaults={"name": "IT Hardware"})
    vendor = Vendor.objects.create(
        legal_name="Cisco Systems Inc",
        trade_name="Cisco Systems",
        vendor_number="VND-CIR-00001",
        tax_identification_number="TAX-CIR-001",
        registration_number="REG-CIR-001",
        category=cat,
        status=Vendor.STATUS_ACTIVE,
        organization=org,
        created_by=proc_mgr
    )
    other_vendor = Vendor.objects.create(
        legal_name="External Global Ltd",
        trade_name="External Global",
        vendor_number="VND-CIR-EXT-002",
        tax_identification_number="TAX-CIR-002",
        registration_number="REG-CIR-002",
        category=cat,
        status=Vendor.STATUS_ACTIVE,
        organization=other_org,
        created_by=other_user
    )

    return {
        "org": org,
        "other_org": other_org,
        "dept": dept,
        "cc": cc,
        "other_dept": other_dept,
        "other_cc": other_cc,
        "super_user": super_user,
        "proc_mgr": proc_mgr,
        "dept_approver": dept_approver,
        "requester": requester,
        "finance_user": finance_user,
        "auditor_user": auditor_user,
        "other_user": other_user,
        "fiscal_period": fiscal_period,
        "budget": budget,
        "policy": policy,
        "step": step,
        "vendor": vendor,
        "other_vendor": other_vendor,
    }


# ==============================================================================
# DEF-001 (TC-APR-008): GET /api/v1/approvals/actions/?target_object_id=<id>
# ==============================================================================

@pytest.mark.django_db
def test_cir_def001_tc_apr_008_approval_actions_target_object_id_filtering(cir_defect_test_data):
    """
    DEF-001 / TC-APR-008 Verification:
    GET /api/v1/approvals/actions/?target_object_id=<id> must filter accurately at the
    database queryset level.

    Expected:
    1. Returns only actions matching target_object_id (e.g. exactly 1 or 2 rows, not all 3,868).
    2. Works across Super Admin, Procurement Manager, Department Approver, and Auditor.
    3. Handles trailing slashes, clean UUID parsing, and returns 0 rows for non-existent UUIDs.
    4. Supports parameter aliases target_id and object_id.
    """
    data = cir_defect_test_data

    # Create Requisition 1 and 2
    pr1 = PurchaseRequisition.objects.create(
        pr_number="PR-CIR-001",
        title="Engineering Laptops Batch 1",
        department=data["dept"],
        cost_center=data["cc"],
        requester=data["requester"],
        created_by=data["requester"],
        status=PurchaseRequisition.STATUS_SUBMITTED,
        total_amount=Decimal("15000.00"),
        requested_delivery_date=timezone.now().date() + timezone.timedelta(days=14)
    )
    pr2 = PurchaseRequisition.objects.create(
        pr_number="PR-CIR-002",
        title="Server Racks Expansion",
        department=data["dept"],
        cost_center=data["cc"],
        requester=data["requester"],
        created_by=data["requester"],
        status=PurchaseRequisition.STATUS_SUBMITTED,
        total_amount=Decimal("45000.00"),
        requested_delivery_date=timezone.now().date() + timezone.timedelta(days=21)
    )

    # Create Approval Actions:
    # Exactly 1 action for PR 1
    act_pr1 = ApprovalAction.objects.create(
        actor=data["requester"],
        policy_step=data["step"],
        target_model_name="PurchaseRequisition",
        target_object_id=pr1.id,
        action=ApprovalAction.ACTION_SUBMIT,
        comments="Submitted for manager review"
    )

    # Exactly 2 actions for PR 2
    act_pr2_submit = ApprovalAction.objects.create(
        actor=data["requester"],
        policy_step=data["step"],
        target_model_name="PurchaseRequisition",
        target_object_id=pr2.id,
        action=ApprovalAction.ACTION_SUBMIT,
        comments="Submitted PR 2"
    )
    act_pr2_approve = ApprovalAction.objects.create(
        actor=data["proc_mgr"],
        policy_step=data["step"],
        target_model_name="PurchaseRequisition",
        target_object_id=pr2.id,
        action=ApprovalAction.ACTION_APPROVE,
        comments="Approved PR 2"
    )

    # 1 Unrelated action for a different dummy UUID
    dummy_uuid = uuid.uuid4()
    ApprovalAction.objects.create(
        actor=data["super_user"],
        policy_step=data["step"],
        target_model_name="PurchaseRequisition",
        target_object_id=dummy_uuid,
        action=ApprovalAction.ACTION_APPROVE,
        comments="Unrelated action"
    )

    client = APIClient()

    # Step 1: Procurement Manager queries target_object_id=<pr1.id> -> must return EXACTLY 1 row
    client.force_authenticate(user=data["proc_mgr"])
    resp = client.get(f"/api/v1/approvals/actions/?target_object_id={pr1.id}")
    assert resp.status_code == status.HTTP_200_OK, f"Expected 200, got {resp.status_code}: {resp.data}"
    results = resp.data.get("results", resp.data)
    assert len(results) == 1, f"Expected exactly 1 action for PR 1, got {len(results)}"
    assert str(results[0]["target_object_id"]) == str(pr1.id)
    assert results[0]["id"] == str(act_pr1.id)

    # Step 2: Department Approver queries target_object_id=<pr2.id> -> must return EXACTLY 2 rows
    client.force_authenticate(user=data["dept_approver"])
    resp2 = client.get(f"/api/v1/approvals/actions/?target_object_id={pr2.id}")
    assert resp2.status_code == status.HTTP_200_OK
    results2 = resp2.data.get("results", resp2.data)
    assert len(results2) == 2, f"Expected exactly 2 actions for PR 2, got {len(results2)}"
    for r in results2:
        assert str(r["target_object_id"]) == str(pr2.id)

    # Step 3: Super Admin queries target_object_id=<pr1.id>
    client.force_authenticate(user=data["super_user"])
    resp_super = client.get(f"/api/v1/approvals/actions/?target_object_id={pr1.id}")
    assert resp_super.status_code == status.HTTP_200_OK
    results_super = resp_super.data.get("results", resp_super.data)
    assert len(results_super) == 1

    # Step 4: Auditor queries target_object_id=<pr2.id>
    client.force_authenticate(user=data["auditor_user"])
    resp_auditor = client.get(f"/api/v1/approvals/actions/?target_object_id={pr2.id}")
    assert resp_auditor.status_code == status.HTTP_200_OK
    results_auditor = resp_auditor.data.get("results", resp_auditor.data)
    assert len(results_auditor) == 2

    # Step 5: Trailing slash handling: ?target_object_id=<pr1.id>/
    client.force_authenticate(user=data["proc_mgr"])
    resp_slash = client.get(f"/api/v1/approvals/actions/?target_object_id={pr1.id}/")
    assert resp_slash.status_code == status.HTTP_200_OK
    results_slash = resp_slash.data.get("results", resp_slash.data)
    assert len(results_slash) == 1

    # Step 6: Parameter aliases: target_id and object_id
    resp_alias1 = client.get(f"/api/v1/approvals/actions/?target_id={pr1.id}")
    assert resp_alias1.status_code == status.HTTP_200_OK
    assert len(resp_alias1.data.get("results", resp_alias1.data)) == 1

    resp_alias2 = client.get(f"/api/v1/approvals/actions/?object_id={pr1.id}")
    assert resp_alias2.status_code == status.HTTP_200_OK
    assert len(resp_alias2.data.get("results", resp_alias2.data)) == 1

    # Step 7: Non-existent UUID returns empty result set (0 items, not all actions)
    non_existent_uuid = uuid.uuid4()
    resp_none = client.get(f"/api/v1/approvals/actions/?target_object_id={non_existent_uuid}")
    assert resp_none.status_code == status.HTTP_200_OK
    results_none = resp_none.data.get("results", resp_none.data)
    assert len(results_none) == 0

    # Step 8: Malformed non-UUID string returns empty result set safely
    resp_malformed = client.get("/api/v1/approvals/actions/?target_object_id=not-a-valid-uuid")
    assert resp_malformed.status_code == status.HTTP_200_OK
    results_malformed = resp_malformed.data.get("results", resp_malformed.data)
    assert len(results_malformed) == 0


# ==============================================================================
# DEF-002 (TC-RPT-005): Dashboard total_spend Reconciliation
# ==============================================================================

@pytest.mark.django_db
def test_cir_def002_tc_rpt_005_dashboard_total_spend_reconciliation(cir_defect_test_data):
    """
    DEF-002 / TC-RPT-005 Verification:
    Dashboard total_spend must reconcile with PAID invoices and ACTUAL spend ledger.
    It must strictly exclude unpaid (received, matching, exception, ready-for-payment) invoices.

    Expected:
    1. total_spend == sum of PAID invoices for the organization.
    2. Unpaid invoices (RECEIVED, 3WAY_MATCH, EXCEPTION, READY_FOR_PAYMENT) do NOT inflate total_spend.
    3. pending_spend and exception_spend capture their respective non-paid buckets accurately.
    4. Multi-tenant isolation: other organizations' paid invoices are not counted.
    """
    data = cir_defect_test_data

    # Create Approved Purchase Order
    po = PurchaseOrder.objects.create(
        po_number="PO-CIR-001",
        vendor=data["vendor"],
        cost_center=data["cc"],
        created_by=data["proc_mgr"],
        status=PurchaseOrder.STATUS_APPROVED,
        total_amount=Decimal("300000.00")
    )
    POLine.objects.create(
        po=po,
        item_description="Enterprise Switching Infrastructure",
        quantity=Decimal("2"),
        unit_of_measure="EA",
        unit_price=Decimal("150000.00"),
        line_total=Decimal("300000.00")
    )

    today = timezone.now().date()

    # Invoice 1: PAID -> 50,000.00 (MUST be in total_spend)
    SupplierInvoice.objects.create(
        invoice_number="INV-CIR-PAID-01",
        vendor=data["vendor"],
        po=po,
        created_by=data["finance_user"],
        approved_by=data["proc_mgr"],
        invoice_date=today - timezone.timedelta(days=10),
        due_date=today + timezone.timedelta(days=20),
        subtotal=Decimal("50000.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal("50000.00"),
        status=SupplierInvoice.STATUS_PAID
    )

    # Invoice 2: PAID -> 25,000.00 (MUST be in total_spend)
    SupplierInvoice.objects.create(
        invoice_number="INV-CIR-PAID-02",
        vendor=data["vendor"],
        po=po,
        created_by=data["finance_user"],
        approved_by=data["proc_mgr"],
        invoice_date=today - timezone.timedelta(days=5),
        due_date=today + timezone.timedelta(days=25),
        subtotal=Decimal("25000.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal("25000.00"),
        status=SupplierInvoice.STATUS_PAID
    )

    # Invoice 3: RECEIVED (unpaid) -> 30,000.00 (MUST NOT be in total_spend)
    SupplierInvoice.objects.create(
        invoice_number="INV-CIR-UNPAID-RCV",
        vendor=data["vendor"],
        po=po,
        created_by=data["finance_user"],
        invoice_date=today - timezone.timedelta(days=4),
        due_date=today + timezone.timedelta(days=26),
        subtotal=Decimal("30000.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal("30000.00"),
        status=SupplierInvoice.STATUS_RECEIVED
    )

    # Invoice 4: 3WAY MATCH IN PROGRESS (unpaid) -> 40,000.00 (MUST NOT be in total_spend)
    SupplierInvoice.objects.create(
        invoice_number="INV-CIR-UNPAID-MATCH",
        vendor=data["vendor"],
        po=po,
        created_by=data["finance_user"],
        invoice_date=today - timezone.timedelta(days=3),
        due_date=today + timezone.timedelta(days=27),
        subtotal=Decimal("40000.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal("40000.00"),
        status=SupplierInvoice.STATUS_MATCHING
    )

    # Invoice 5: EXCEPTION -> 15,000.00 (MUST NOT be in total_spend, must be in exception_spend)
    SupplierInvoice.objects.create(
        invoice_number="INV-CIR-EXCP-01",
        vendor=data["vendor"],
        po=po,
        created_by=data["finance_user"],
        invoice_date=today - timezone.timedelta(days=2),
        due_date=today + timezone.timedelta(days=28),
        subtotal=Decimal("15000.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal("15000.00"),
        status=SupplierInvoice.STATUS_EXCEPTION
    )

    # Invoice 6: READY_FOR_PAYMENT (unpaid) -> 60,000.00 (MUST NOT be in total_spend)
    SupplierInvoice.objects.create(
        invoice_number="INV-CIR-READY-01",
        vendor=data["vendor"],
        po=po,
        created_by=data["finance_user"],
        invoice_date=today - timezone.timedelta(days=1),
        due_date=today + timezone.timedelta(days=29),
        subtotal=Decimal("60000.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal("60000.00"),
        status=SupplierInvoice.STATUS_READY_FOR_PAYMENT
    )

    # Invoice 7: OTHER ORGANIZATION's PAID invoice -> 80,000.00 (MUST be excluded)
    other_po = PurchaseOrder.objects.create(
        po_number="PO-CIR-EXT-002",
        vendor=data["other_vendor"],
        cost_center=data["other_cc"],
        created_by=data["other_user"],
        status=PurchaseOrder.STATUS_APPROVED,
        total_amount=Decimal("100000.00")
    )
    SupplierInvoice.objects.create(
        invoice_number="INV-CIR-EXT-PAID",
        vendor=data["other_vendor"],
        po=other_po,
        created_by=data["other_user"],
        approved_by=data["other_user"],
        invoice_date=today,
        due_date=today + timezone.timedelta(days=30),
        subtotal=Decimal("80000.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal("80000.00"),
        status=SupplierInvoice.STATUS_PAID
    )

    # SpendLedger Actual Spend: 75,000.00
    SpendLedger.objects.create(
        budget=data["budget"],
        entry_type=SpendLedger.ENTRY_ACTUAL,
        amount=Decimal("75000.00"),
        description="Realized spend for Cisco Systems equipment",
        reference_number="INV-CIR-PAID-01",
        created_by=data["finance_user"]
    )

    client = APIClient()

    # Step 1: Query as FINANCE_AP
    client.force_authenticate(user=data["finance_user"])
    resp = client.get("/api/v1/reports/dashboard-summary/")
    assert resp.status_code == status.HTTP_200_OK, f"Expected 200, got {resp.status_code}: {resp.data}"

    data_out = resp.data
    expected_paid_spend = 75000.00  # 50,000 + 25,000
    expected_pending_spend = 130000.00  # 30,000 (rcv) + 40,000 (match) + 60,000 (ready)
    expected_exception_spend = 15000.00

    # Total spend must match realized actual paid spend exactly
    assert data_out["total_spend"] == pytest.approx(expected_paid_spend, rel=1e-2), (
        f"DEF-002 Violation: total_spend {data_out['total_spend']} does not reconcile with "
        f"paid invoices {expected_paid_spend}. Unpaid/exception invoices were incorrectly counted!"
    )
    assert data_out["paid_spend"] == pytest.approx(expected_paid_spend, rel=1e-2)
    assert data_out["pending_spend"] == pytest.approx(expected_pending_spend, rel=1e-2)
    assert data_out["exception_spend"] == pytest.approx(expected_exception_spend, rel=1e-2)
    assert data_out["actual_ledger_spend"] == pytest.approx(75000.00, rel=1e-2)

    # Step 2: Query alias endpoint /api/v1/reports/dashboard/summary/
    resp_alias = client.get("/api/v1/reports/dashboard/summary/")
    assert resp_alias.status_code == status.HTTP_200_OK
    assert resp_alias.data["total_spend"] == pytest.approx(expected_paid_spend, rel=1e-2)
    assert resp_alias.data["paid_spend"] == pytest.approx(expected_paid_spend, rel=1e-2)

    # Step 3: Query as Procurement Manager
    client.force_authenticate(user=data["proc_mgr"])
    resp_pm = client.get("/api/v1/reports/dashboard-summary/")
    assert resp_pm.status_code == status.HTTP_200_OK
    assert resp_pm.data["total_spend"] == pytest.approx(expected_paid_spend, rel=1e-2)
