"""
Master Engineering Remediation Regression Test Suite
====================================================
Validates all six confirmed functional defects:
- DEF-002 / DEF-022: Budget limit fail-closed enforcement on normal PR submission (HTTP 400, DRAFT status, zero reservation)
- DEF-010: Manager Approval Desk fully usable by authorized Procurement Managers (HTTP 200 on view and action, 403 for unauthorized)
- DEF-011: Cross-organization budget maintenance by Super Admin (HTTP 200 for Super Admin, 404 tenant isolation for non-admins)
- DEF-019: Goods Receipt PUT full update succeeds without false PO status error or duplicate GRN collision
- DEF-023: RBAC read-permission compliance per docs/rbac_matrix.md
"""

import datetime
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.approvals.models import ApprovalAction, ApprovalPolicy, ApprovalStep
from apps.budgets.models import Budget, BudgetReservation
from apps.contracts.models import Contract
from apps.orders.models import POLine, PurchaseOrder
from apps.organization.models import CostCenter, Department, FiscalPeriod, Organization
from apps.receipts.models import GoodsReceipt, ReceiptLine
from apps.requisitions.models import PurchaseRequisition
from apps.requisitions.services import (
    create_purchase_requisition_service,
    submit_purchase_requisition_service,
)
from apps.vendors.models import Vendor, VendorCategory


@pytest.fixture
def remediation_setup(db):
    org, _ = Organization.objects.get_or_create(code="HPE-REMED", defaults={"name": "HPE Remediation Org"})
    dept, _ = Department.objects.get_or_create(organization=org, code="REM-DEPT", defaults={"name": "Remediation Dept"})
    cc, _ = CostCenter.objects.get_or_create(department=dept, code="REM-CC", defaults={"name": "Remediation Cost Center"})

    r_super, _ = Role.objects.get_or_create(code=Role.SUPER_ADMIN, defaults={"name": "Super Admin"})
    r_req, _ = Role.objects.get_or_create(code=Role.REQUESTER, defaults={"name": "Requester"})
    r_mgr, _ = Role.objects.get_or_create(code=Role.PROC_MGR, defaults={"name": "Procurement Manager"})
    r_exec, _ = Role.objects.get_or_create(code=Role.PROC_EXEC, defaults={"name": "Procurement Executive"})
    r_fin, _ = Role.objects.get_or_create(code=Role.FINANCE_AP, defaults={"name": "Finance AP"})
    r_stores, _ = Role.objects.get_or_create(code=Role.STORES_RECEIVER, defaults={"name": "Stores Receiver"})
    r_legal, _ = Role.objects.get_or_create(code=Role.LEGAL_MGR, defaults={"name": "Legal Manager"})
    r_ven, _ = Role.objects.get_or_create(code=Role.VENDOR_USER, defaults={"name": "Vendor User"})

    admin = User.objects.create_user(
        email="remed_admin@hpe.com", password="Password123!", role=r_super, is_superuser=True, is_staff=True, organization=org
    )
    requester = User.objects.create_user(
        email="remed_req@hpe.com", password="Password123!", role=r_req, organization=org, department=dept, cost_center=cc
    )
    proc_mgr = User.objects.create_user(
        email="remed_mgr@hpe.com", password="Password123!", role=r_mgr, organization=org
    )
    proc_exec = User.objects.create_user(
        email="remed_exec@hpe.com", password="Password123!", role=r_exec, organization=org
    )
    finance = User.objects.create_user(
        email="remed_fin@hpe.com", password="Password123!", role=r_fin, organization=org, department=dept
    )
    stores = User.objects.create_user(
        email="remed_stores@hpe.com", password="Password123!", role=r_stores, organization=org
    )
    legal = User.objects.create_user(
        email="remed_legal@hpe.com", password="Password123!", role=r_legal, organization=org
    )

    cat, _ = VendorCategory.objects.get_or_create(code="REM-CAT", defaults={"name": "Hardware"})
    vendor = Vendor.objects.create(
        tax_identification_number="TIN-REM-01",
        vendor_number="VND-REM-01",
        legal_name="Remediation Technologies Inc",
        category=cat,
        email="vendor@remed.com",
        organization=org,
        status=Vendor.STATUS_ACTIVE,
    )
    vendor_user = User.objects.create_user(
        email="vendor_user@remed.com",
        password="Password123!",
        role=r_ven,
        vendor=vendor,
    )

    policy = ApprovalPolicy.objects.create(
        organization=org,
        department=dept,
        cost_center=cc,
        name="Remediation PR Policy",
        module=ApprovalPolicy.MODULE_PR,
        min_amount=Decimal("0.00"),
        max_amount=Decimal("500000.00"),
        is_active=True,
    )
    ApprovalStep.objects.create(policy=policy, step_number=1, approver_role=r_mgr, specific_approver=proc_mgr)

    fp, _ = FiscalPeriod.objects.get_or_create(
        organization=org,
        year=2026,
        period_number=1,
        defaults={
            "name": "FY26-REM-P1",
            "start_date": timezone.now().date() - datetime.timedelta(days=10),
            "end_date": timezone.now().date() + datetime.timedelta(days=360),
            "is_closed": False,
        },
    )
    budget = Budget.objects.create(
        cost_center=cc,
        fiscal_period=fp,
        allocated_amount=Decimal("10000.00"),
        allow_overspend=False,
    )

    return {
        "org": org,
        "dept": dept,
        "cc": cc,
        "admin": admin,
        "requester": requester,
        "proc_mgr": proc_mgr,
        "proc_exec": proc_exec,
        "finance": finance,
        "stores": stores,
        "legal": legal,
        "vendor": vendor,
        "vendor_user": vendor_user,
        "budget": budget,
        "fp": fp,
        "policy": policy,
    }


# ==============================================================================
# DEF-002 & DEF-022: Budget Limit Fail-Closed Enforcement on Submission
# ==============================================================================
@pytest.mark.django_db
def test_def_002_022_budget_limit_fail_closed_submission(remediation_setup):
    data = remediation_setup
    budget = data["budget"]
    budget.allocated_amount = Decimal("2000.00")
    budget.allow_overspend = False
    budget.save()

    # Requisition exceeding available budget
    pr = create_purchase_requisition_service(
        title="Excess Requisition",
        justification="Critical servers",
        requester=data["requester"],
        department=data["dept"],
        cost_center=data["cc"],
        requested_delivery_date=timezone.now().date() + datetime.timedelta(days=7),
        line_items=[{"item_description": "Blade Server", "quantity": 1, "estimated_unit_price": Decimal("5000.00")}],
    )

    client = APIClient()
    client.force_authenticate(user=data["requester"])

    # 1. Normal submission must return HTTP 400 Bad Request
    resp = client.post(f"/api/v1/requisitions/{pr.id}/submit/", format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "budget" in str(resp.data).lower()

    # 2. Requisition must remain in DRAFT
    pr.refresh_from_db()
    assert pr.status == PurchaseRequisition.STATUS_DRAFT

    # 3. No unauthorized reservation or deduction must occur
    assert not BudgetReservation.objects.filter(requisition=pr).exists()
    budget.refresh_from_db()
    assert budget.reserved_amount == Decimal("0.00")
    assert budget.available_amount == Decimal("2000.00")

    # 4. No approval workflow initiated
    assert not ApprovalAction.objects.filter(target_object_id=str(pr.id)).exists()

    # 5. Even if allow_overspend is True, normal submission must still fail-closed
    budget.allow_overspend = True
    budget.save()
    resp2 = client.post(f"/api/v1/requisitions/{pr.id}/submit/", format="json")
    assert resp2.status_code == status.HTTP_400_BAD_REQUEST
    pr.refresh_from_db()
    assert pr.status == PurchaseRequisition.STATUS_DRAFT
    assert not BudgetReservation.objects.filter(requisition=pr).exists()

    # 6. Valid requisition within available budget succeeds normally
    valid_pr = create_purchase_requisition_service(
        title="Valid Small PR",
        justification="Keyboards",
        requester=data["requester"],
        department=data["dept"],
        cost_center=data["cc"],
        requested_delivery_date=timezone.now().date() + datetime.timedelta(days=7),
        line_items=[{"item_description": "Keyboard", "quantity": 1, "estimated_unit_price": Decimal("500.00")}],
    )
    resp_valid = client.post(f"/api/v1/requisitions/{valid_pr.id}/submit/", format="json")
    assert resp_valid.status_code == status.HTTP_200_OK
    valid_pr.refresh_from_db()
    assert valid_pr.status == PurchaseRequisition.STATUS_MANAGER_REVIEW
    assert BudgetReservation.objects.filter(requisition=valid_pr).exists()


# ==============================================================================
# DEF-010: Manager Approval Desk Usable by Procurement Manager
# ==============================================================================
@pytest.mark.django_db
def test_def_010_manager_approval_desk_usable(remediation_setup):
    data = remediation_setup
    pr = create_purchase_requisition_service(
        title="Approval Desk Test PR",
        justification="Testing desk approval",
        requester=data["requester"],
        department=data["dept"],
        cost_center=data["cc"],
        requested_delivery_date=timezone.now().date() + datetime.timedelta(days=7),
        line_items=[{"item_description": "Network Switch", "quantity": 1, "estimated_unit_price": Decimal("1500.00")}],
    )
    submit_purchase_requisition_service(requisition=pr, user=data["requester"])

    client = APIClient()
    client.force_authenticate(user=data["proc_mgr"])

    # 1. Procurement Manager views pending approvals on the manager desk (HTTP 200)
    resp_pending = client.get("/api/v1/manager/approvals/")
    assert resp_pending.status_code == status.HTTP_200_OK
    assert "results" in resp_pending.data
    results = resp_pending.data["results"]
    assert any(item["reference_number"] == pr.pr_number for item in results)

    # 2. Procurement Manager approves the requisition from the desk (HTTP 200, success=True)
    resp_approve = client.post(
        "/api/v1/manager/approvals/action/",
        {"item_type": "PR", "item_id": str(pr.id), "action": "APPROVE", "comments": "Approved via Desk"},
        format="json",
    )
    assert resp_approve.status_code == status.HTTP_200_OK
    assert resp_approve.data.get("success") is True
    pr.refresh_from_db()
    assert pr.status == PurchaseRequisition.STATUS_APPROVED

    # 3. Unauthorized user (Requester) receives HTTP 403 Forbidden
    client_unauth = APIClient()
    client_unauth.force_authenticate(user=data["requester"])
    resp_unauth = client_unauth.post(
        "/api/v1/manager/approvals/action/",
        {"item_type": "PR", "item_id": str(pr.id), "action": "APPROVE", "comments": "Unauthorized"},
        format="json",
    )
    assert resp_unauth.status_code == status.HTTP_403_FORBIDDEN


# ==============================================================================
# DEF-011: Cross-Organization Budget Maintenance by Super Admin
# ==============================================================================
@pytest.mark.django_db
def test_def_011_cross_org_budget_update_superadmin(remediation_setup):
    data = remediation_setup

    # Create distinct secondary organization, department, and budget
    other_org = Organization.objects.create(name="Secondary Enterprise Org", code="SEC-ORG-01")
    other_dept = Department.objects.create(organization=other_org, name="Secondary Dept", code="SEC-DEPT")
    other_cc = CostCenter.objects.create(department=other_dept, name="Secondary CC", code="SEC-CC")
    other_fp = FiscalPeriod.objects.create(
        organization=other_org,
        year=2026,
        period_number=1,
        name="FY26-SEC-P1",
        start_date=timezone.now().date(),
        end_date=timezone.now().date() + datetime.timedelta(days=90),
    )
    other_budget = Budget.objects.create(
        cost_center=other_cc, fiscal_period=other_fp, allocated_amount=Decimal("40000.00")
    )

    client_admin = APIClient()
    client_admin.force_authenticate(user=data["admin"])

    # 1. Super Admin can read cross-org budget (HTTP 200)
    res_get = client_admin.get(f"/api/v1/budgets/{other_budget.id}/")
    assert res_get.status_code == status.HTTP_200_OK

    # 2. Super Admin can PATCH cross-org budget (HTTP 200)
    res_patch = client_admin.patch(
        f"/api/v1/budgets/{other_budget.id}/", {"allocated_amount": "55000.00"}, format="json"
    )
    assert res_patch.status_code == status.HTTP_200_OK
    other_budget.refresh_from_db()
    assert other_budget.allocated_amount == Decimal("55000.00")
    assert other_budget.available_amount == Decimal("55000.00")

    # 3. Super Admin can PUT cross-org budget (HTTP 200)
    res_put = client_admin.put(
        f"/api/v1/budgets/{other_budget.id}/",
        {
            "cost_center": other_cc.id,
            "fiscal_period": other_fp.id,
            "allocated_amount": "70000.00",
            "allow_overspend": True,
        },
        format="json",
    )
    assert res_put.status_code == status.HTTP_200_OK
    other_budget.refresh_from_db()
    assert other_budget.allocated_amount == Decimal("70000.00")
    assert other_budget.allow_overspend is True

    # 4. Tenant isolation: Non-admin users cannot see or update cross-org budget (HTTP 404)
    client_finance = APIClient()
    client_finance.force_authenticate(user=data["finance"])
    res_fin_get = client_finance.get(f"/api/v1/budgets/{other_budget.id}/")
    assert res_fin_get.status_code == status.HTTP_404_NOT_FOUND
    res_fin_patch = client_finance.patch(
        f"/api/v1/budgets/{other_budget.id}/", {"allocated_amount": "99999.00"}, format="json"
    )
    assert res_fin_patch.status_code == status.HTTP_404_NOT_FOUND


# ==============================================================================
# DEF-019: Goods Receipt PUT Full Update
# ==============================================================================
@pytest.mark.django_db
def test_def_019_goods_receipt_put_update(remediation_setup):
    data = remediation_setup
    po = PurchaseOrder.objects.create(
        po_number="PO-REM-019",
        vendor=data["vendor"],
        cost_center=data["cc"],
        status=PurchaseOrder.STATUS_ISSUED,
        total_amount=Decimal("3000.00"),
        created_by=data["proc_exec"],
    )
    po_line = POLine.objects.create(
        po=po,
        item_description="Storage Array Module",
        quantity=Decimal("3.00"),
        unit_price=Decimal("1000.00"),
        line_total=Decimal("3000.00"),
    )
    grn = GoodsReceipt.objects.create(
        grn_number="GRN-2026-00019",
        po=po,
        received_by=data["stores"],
        received_date=timezone.now().date(),
        delivery_note_number="DN-REM-019",
        remarks="Initial inspection complete",
    )
    r_line = ReceiptLine.objects.create(
        receipt=grn,
        po_line=po_line,
        quantity_received=Decimal("3.00"),
        quantity_accepted=Decimal("3.00"),
        quantity_rejected=Decimal("0.00"),
    )

    # Move PO to COMPLETED or PARTIAL_RECEIPT (receipt has already been issued)
    po.status = PurchaseOrder.STATUS_COMPLETED
    po.save()

    client = APIClient()
    client.force_authenticate(user=data["stores"])

    # Full update (PUT) must succeed without false PO status errors or duplicate collisions
    resp = client.put(
        f"/api/v1/receipts/{grn.id}/",
        {
            "po": str(po.id),
            "received_date": str(timezone.now().date()),
            "delivery_note_number": "DN-REM-019-AMENDED",
            "remarks": "Updated delivery remarks via PUT",
            "lines": [
                {
                    "id": str(r_line.id),
                    "po_line": str(po_line.id),
                    "item_description": "Storage Array Module",
                    "quantity_received": "3.00",
                    "quantity_accepted": "3.00",
                    "quantity_rejected": "0.00",
                }
            ],
        },
        format="json",
    )
    assert resp.status_code == status.HTTP_200_OK
    grn.refresh_from_db()
    assert grn.remarks == "Updated delivery remarks via PUT"
    assert grn.delivery_note_number == "DN-REM-019-AMENDED"


# ==============================================================================
# DEF-023: Role-Based Access Control Read Permission Mismatches
# ==============================================================================
@pytest.mark.django_db
def test_def_023_rbac_matrix_compliance(remediation_setup):
    data = remediation_setup
    client = APIClient()

    # 1. STORES_RECEIVER: 403 on requisitions, 200 on purchase orders
    client.force_authenticate(user=data["stores"])
    res_stores_pr = client.get("/api/v1/requisitions/")
    assert res_stores_pr.status_code == status.HTTP_403_FORBIDDEN

    res_stores_po = client.get("/api/v1/orders/")
    assert res_stores_po.status_code == status.HTTP_200_OK

    # 2. LEGAL_MGR: 403 on requisitions, 200 on contracts
    client.force_authenticate(user=data["legal"])
    res_legal_pr = client.get("/api/v1/requisitions/")
    assert res_legal_pr.status_code == status.HTTP_403_FORBIDDEN

    res_legal_con = client.get("/api/v1/contracts/")
    assert res_legal_con.status_code == status.HTTP_200_OK

    # 3. VENDOR_USER: 200 on own contracts
    Contract.objects.create(
        contract_number="CON-REM-001",
        title="Remediation Hardware Contract",
        vendor=data["vendor"],
        contract_value=Decimal("50000.00"),
        start_date=timezone.now().date(),
        end_date=timezone.now().date() + datetime.timedelta(days=365),
        contract_owner=data["proc_mgr"],
        created_by=data["proc_mgr"],
    )
    client.force_authenticate(user=data["vendor_user"])
    res_vendor_con = client.get("/api/v1/contracts/")
    assert res_vendor_con.status_code == status.HTTP_200_OK
    assert len(res_vendor_con.data["results"]) == 1

    # 4. SUPER_ADMIN: 403 on manager-only KPIs
    client.force_authenticate(user=data["admin"])
    res_admin_kpi = client.get("/api/v1/manager/kpis/")
    assert res_admin_kpi.status_code == status.HTTP_403_FORBIDDEN
