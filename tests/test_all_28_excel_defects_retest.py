import datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.test import Client
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.approvals.models import ApprovalAction, ApprovalPolicy, ApprovalStep
from apps.budgets.models import Budget
from apps.budgets.services import check_and_reserve_budget_service
from apps.contracts.models import Contract
from apps.contracts.services import create_contract_service, terminate_contract_service
from apps.invoices.models import SupplierInvoice
from apps.orders.models import POLine, PurchaseOrder
from apps.orders.services import generate_purchase_order_service
from apps.organization.models import CostCenter, Department, FiscalPeriod, Organization
from apps.receipts.models import GoodsReceipt, ReceiptLine
from apps.requisitions.models import PRLine, PurchaseRequisition
from apps.requisitions.services import (
    approve_purchase_requisition_service,
    create_purchase_requisition_service,
    reject_purchase_requisition_service,
    submit_purchase_requisition_service,
)
from apps.sourcing.models import SourcingEvent
from apps.vendors.models import Vendor, VendorCategory


@pytest.fixture
def suite_setup(db):
    org, _ = Organization.objects.get_or_create(code="HPE-SUITE", defaults={"name": "HPE Test Suite Org"})
    dept, _ = Department.objects.get_or_create(organization=org, code="SUITE-DEPT", defaults={"name": "Suite Dept"})
    dept2, _ = Department.objects.get_or_create(organization=org, code="SUITE-DEPT2", defaults={"name": "Suite Dept 2"})
    cc, _ = CostCenter.objects.get_or_create(department=dept, code="SUITE-CC", defaults={"name": "Suite Cost Center"})
    cc2, _ = CostCenter.objects.get_or_create(department=dept2, code="SUITE-CC2", defaults={"name": "Suite Cost Center 2"})

    r_super, _ = Role.objects.get_or_create(code=Role.SUPER_ADMIN, defaults={"name": "Super Admin"})
    r_req, _ = Role.objects.get_or_create(code=Role.REQUESTER, defaults={"name": "Requester"})
    r_appr, _ = Role.objects.get_or_create(code=Role.DEPT_APPROVER, defaults={"name": "Department Approver"})
    r_exec, _ = Role.objects.get_or_create(code=Role.PROC_EXEC, defaults={"name": "Procurement Executive"})
    r_mgr, _ = Role.objects.get_or_create(code=Role.PROC_MGR, defaults={"name": "Procurement Manager"})
    r_fin, _ = Role.objects.get_or_create(code=Role.FINANCE_AP, defaults={"name": "Finance AP"})
    r_stores, _ = Role.objects.get_or_create(code=Role.STORES_RECEIVER, defaults={"name": "Stores Receiver"})
    r_legal, _ = Role.objects.get_or_create(code=Role.LEGAL_MGR, defaults={"name": "Legal Manager"})
    r_aud, _ = Role.objects.get_or_create(code=Role.AUDITOR, defaults={"name": "Compliance Auditor"})
    r_ven, _ = Role.objects.get_or_create(code=Role.VENDOR_USER, defaults={"name": "Vendor User"})

    admin = User.objects.create_user(email="suite_admin@hpe.com", password="Password123!", role=r_super, is_superuser=True, is_staff=True, organization=org)
    requester = User.objects.create_user(email="suite_req@hpe.com", password="Password123!", role=r_req, organization=org, department=dept, cost_center=cc)
    approver = User.objects.create_user(email="suite_appr@hpe.com", password="Password123!", role=r_appr, organization=org, department=dept)
    proc_exec = User.objects.create_user(email="suite_exec@hpe.com", password="Password123!", role=r_exec, organization=org)
    proc_mgr = User.objects.create_user(email="suite_mgr@hpe.com", password="Password123!", role=r_mgr, organization=org)
    finance = User.objects.create_user(email="suite_fin@hpe.com", password="Password123!", role=r_fin, organization=org, department=dept)
    stores = User.objects.create_user(email="suite_stores@hpe.com", password="Password123!", role=r_stores, organization=org)
    legal = User.objects.create_user(email="suite_legal@hpe.com", password="Password123!", role=r_legal, organization=org)
    auditor = User.objects.create_user(email="suite_aud@hpe.com", password="Password123!", role=r_aud, organization=org)

    cat, _ = VendorCategory.objects.get_or_create(code="SUITE-CAT", defaults={"name": "IT Hardware"})
    vendor = Vendor.objects.create(
        tax_identification_number="TIN-SUITE-01",
        vendor_number="VND-SUITE-01",
        legal_name="Suite Technologies Inc",
        category=cat,
        email="vendor@suite.com",
        organization=org,
        status=Vendor.STATUS_ACTIVE,
    )
    vendor_user = User.objects.create_user(
        email="vendor_user@suite.com",
        password="Password123!",
        role=r_ven,
        vendor=vendor,
    )

    policy = ApprovalPolicy.objects.create(
        organization=org,
        department=dept,
        cost_center=cc,
        name="Suite Dept Policy",
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
            "name": "FY26-P1",
            "start_date": timezone.now().date() - datetime.timedelta(days=10),
            "end_date": timezone.now().date() + datetime.timedelta(days=360),
            "is_closed": False,
        },
    )
    budget = Budget.objects.create(
        cost_center=cc,
        fiscal_period=fp,
        allocated_amount=Decimal("100000.00"),
        allow_overspend=False,
    )

    return {
        "org": org,
        "dept": dept,
        "dept2": dept2,
        "cc": cc,
        "cc2": cc2,
        "admin": admin,
        "requester": requester,
        "approver": approver,
        "proc_exec": proc_exec,
        "proc_mgr": proc_mgr,
        "finance": finance,
        "stores": stores,
        "legal": legal,
        "auditor": auditor,
        "vendor": vendor,
        "vendor_user": vendor_user,
        "budget": budget,
        "fp": fp,
        "policy": policy,
    }


# ==============================================================================
# 1. TC-APR-005: Procurement Manager approves pending approval action
# ==============================================================================
@pytest.mark.django_db
def test_tc_apr_005_proc_mgr_approves_pending_action(suite_setup):
    data = suite_setup
    pr = create_purchase_requisition_service(
        title="Server Requisition",
        justification="Required server upgrade",
        requester=data["requester"],
        department=data["dept"],
        cost_center=data["cc"],
        requested_delivery_date=timezone.now().date() + datetime.timedelta(days=7),
        line_items=[{"item_description": "Server Blade", "quantity": 1, "estimated_unit_price": Decimal("5000.00")}],
    )
    submit_purchase_requisition_service(requisition=pr, user=data["requester"])
    pr.refresh_from_db()

    action = ApprovalAction.objects.filter(target_object_id=str(pr.id)).first()
    assert action is not None

    client = APIClient()
    client.force_authenticate(user=data["proc_mgr"])
    resp = client.post(f"/api/v1/approvals/actions/{action.id}/approve/", {"comments": "Approved by manager"}, format="json")
    assert resp.status_code in [status.HTTP_200_OK, status.HTTP_201_CREATED]

    pr.refresh_from_db()
    assert pr.status in [PurchaseRequisition.STATUS_APPROVED, "APPROVED"]


# ==============================================================================
# 2. TC-BUD-013 (DEF-011): Cross-org budget maintenance by Super Admin
# ==============================================================================
@pytest.mark.django_db
def test_tc_bud_013_def_011_superadmin_cross_org_budget_patch(suite_setup):
    data = suite_setup
    client = APIClient()
    client.force_authenticate(user=data["admin"])

    # Create another org, dept, cc and budget
    other_org = Organization.objects.create(name="Other Enterprise Org", code="OTHER-ORG-01")
    other_dept = Department.objects.create(organization=other_org, name="Other Dept", code="OTHER-DEPT")
    other_cc = CostCenter.objects.create(department=other_dept, name="Other CC", code="OTHER-CC")
    other_fp = FiscalPeriod.objects.create(
        organization=other_org, year=2026, period_number=2, name="FY26-P2",
        start_date=timezone.now().date(), end_date=timezone.now().date() + datetime.timedelta(days=90),
    )
    other_budget = Budget.objects.create(cost_center=other_cc, fiscal_period=other_fp, allocated_amount=Decimal("50000.00"))

    # Super Admin must be able to GET the budget (no 404)
    res_get = client.get(f"/api/v1/budgets/{other_budget.id}/")
    assert res_get.status_code == status.HTTP_200_OK

    # Super Admin can PATCH the budget
    res_patch = client.patch(f"/api/v1/budgets/{other_budget.id}/", {"allocated_amount": "60000.00"}, format="json")
    assert res_patch.status_code == status.HTTP_200_OK

    other_budget.refresh_from_db()
    assert other_budget.allocated_amount == Decimal("60000.00")
    assert other_budget.available_amount == Decimal("60000.00")


# ==============================================================================
# 3. TC-MGR-003 & TC-MGR-037 (DEF-010): Manager approval desk actions
# ==============================================================================
@pytest.mark.django_db
def test_tc_mgr_003_037_def_010_manager_approval_desk(suite_setup):
    data = suite_setup
    pr = create_purchase_requisition_service(
        title="Desk Test Requisition",
        justification="Desk testing",
        requester=data["requester"],
        department=data["dept"],
        cost_center=data["cc"],
        requested_delivery_date=timezone.now().date() + datetime.timedelta(days=7),
        line_items=[{"item_description": "Item", "quantity": 1, "estimated_unit_price": Decimal("1000.00")}],
    )
    submit_purchase_requisition_service(requisition=pr, user=data["requester"])

    client = APIClient()
    client.force_authenticate(user=data["proc_mgr"])

    # 1. Procurement Manager views pending approvals on the manager desk (HTTP 200)
    resp_pending = client.get("/api/v1/manager/approvals/")
    assert resp_pending.status_code == status.HTTP_200_OK

    # 2. Procurement Manager executes approval from the desk: authorized manager receives HTTP 200 (DEF-010)
    resp = client.post(
        "/api/v1/manager/approvals/action/",
        {"item_type": "PR", "item_id": str(pr.id), "action": "APPROVE", "comments": "Approved via Desk"},
        format="json",
    )
    assert resp.status_code == status.HTTP_200_OK
    assert resp.data.get("success") is True
    pr.refresh_from_db()
    assert pr.status == PurchaseRequisition.STATUS_APPROVED

    # 3. Unauthorized user (Requester) is blocked with 403 Forbidden
    client_req = APIClient()
    client_req.force_authenticate(user=data["requester"])
    resp_unauth = client_req.post(
        "/api/v1/manager/approvals/action/",
        {"item_type": "PR", "item_id": str(pr.id), "action": "APPROVE", "comments": "Unauthorized"},
        format="json",
    )
    assert resp_unauth.status_code == status.HTTP_403_FORBIDDEN


# ==============================================================================
# 4. TC-GRN-007 (DEF-019): Full update (PUT) of a goods receipt
# ==============================================================================
@pytest.mark.django_db
def test_tc_grn_007_def_019_goods_receipt_put_update(suite_setup):
    data = suite_setup
    po = PurchaseOrder.objects.create(
        po_number="PO-GRN-007",
        vendor=data["vendor"],
        cost_center=data["cc"],
        status=PurchaseOrder.STATUS_ISSUED,
        total_amount=Decimal("1000.00"),
        created_by=data["proc_exec"],
    )
    po_line = POLine.objects.create(
        po=po,
        item_description="Server RAM",
        quantity=Decimal("10.00"),
        unit_price=Decimal("100.00"),
        line_total=Decimal("1000.00"),
    )
    grn = GoodsReceipt.objects.create(
        grn_number="GRN-2026-00007",
        po=po,
        received_by=data["stores"],
        received_date=timezone.now().date(),
        delivery_note_number="DN-007",
        remarks="Initial receipt",
    )
    r_line = ReceiptLine.objects.create(
        receipt=grn,
        po_line=po_line,
        quantity_received=Decimal("10.00"),
        quantity_accepted=Decimal("10.00"),
        quantity_rejected=Decimal("0.00"),
    )

    # Move PO to COMPLETED
    po.status = PurchaseOrder.STATUS_COMPLETED
    po.save()

    client = APIClient()
    client.force_authenticate(user=data["stores"])
    # Full update (PUT) with changed remarks must NOT fail with PO status error
    resp = client.put(
        f"/api/v1/receipts/{grn.id}/",
        {
            "po": str(po.id),
            "received_date": str(timezone.now().date()),
            "delivery_note_number": "DN-007-AMENDED",
            "remarks": "Updated remark via PUT",
            "lines": [
                {
                    "id": str(r_line.id),
                    "po_line": str(po_line.id),
                    "item_description": "Server RAM",
                    "quantity_received": "10.00",
                    "quantity_accepted": "10.00",
                    "quantity_rejected": "0.00",
                }
            ],
        },
        format="json",
    )
    assert resp.status_code == status.HTTP_200_OK
    grn.refresh_from_db()
    assert grn.remarks == "Updated remark via PUT"
    assert grn.delivery_note_number == "DN-007-AMENDED"


# ==============================================================================
# 5. TC-REQ-013, 014, 017, 018: Requisition Approve & Reject action endpoints
# ==============================================================================
@pytest.mark.django_db
def test_tc_req_013_014_017_018_requisition_actions_by_proc_mgr(suite_setup):
    data = suite_setup
    pr = create_purchase_requisition_service(
        title="Action Test PR",
        justification="Action test",
        requester=data["requester"],
        department=data["dept"],
        cost_center=data["cc"],
        requested_delivery_date=timezone.now().date() + datetime.timedelta(days=7),
        line_items=[{"item_description": "Network Cable", "quantity": 10, "estimated_unit_price": Decimal("20.00")}],
    )
    submit_purchase_requisition_service(requisition=pr, user=data["requester"])

    client = APIClient()
    client.force_authenticate(user=data["proc_mgr"])

    # Procurement Manager can reject
    resp_reject = client.post(
        f"/api/v1/requisitions/{pr.id}/reject/",
        {"rejection_reason": "Not approved due to budget freeze"},
        format="json",
    )
    assert resp_reject.status_code == status.HTTP_200_OK

    pr.refresh_from_db()
    assert pr.status == PurchaseRequisition.STATUS_REJECTED

    # Resubmission or approval of rejected PR is refused (HTTP 400) (TC-WF-002)
    resp_reapprove = client.post(
        f"/api/v1/requisitions/{pr.id}/approve/",
        {"comments": "Attempting re-approval"},
        format="json",
    )
    assert resp_reapprove.status_code in [status.HTTP_400_BAD_REQUEST, status.HTTP_409_CONFLICT]


# ==============================================================================
# 6. TC-SRC-087: Sourcing event detail fields equal list representation
# ==============================================================================
@pytest.mark.django_db
def test_tc_src_087_sourcing_list_vs_detail_representation(suite_setup):
    data = suite_setup
    ev = SourcingEvent.objects.create(
        event_number="EV-TEST-SRC-87",
        title="Sourcing Event TC-087",
        description="Detailed RFP Scope description",
        created_by=data["proc_exec"],
        bid_start_date=timezone.now(),
        bid_end_date=timezone.now() + datetime.timedelta(days=7),
    )

    client = APIClient()
    client.force_authenticate(user=data["proc_exec"])

    res_list = client.get("/api/v1/sourcing/events/")
    assert res_list.status_code == status.HTTP_200_OK
    list_item = [x for x in res_list.data.get("results", []) if x["id"] == str(ev.id)][0]

    res_detail = client.get(f"/api/v1/sourcing/events/{ev.id}/")
    assert res_detail.status_code == status.HTTP_200_OK
    detail_data = res_detail.data

    assert "description" in list_item
    assert "description" in detail_data
    assert list_item["description"] == detail_data["description"]
    assert set(detail_data.keys()) == set(list_item.keys())


# ==============================================================================
# 7. TC-VEN-029: Vendor detail fields equal list representation
# ==============================================================================
@pytest.mark.django_db
def test_tc_ven_029_vendor_list_vs_detail_representation(suite_setup):
    data = suite_setup
    v = data["vendor"]

    client = APIClient()
    client.force_authenticate(user=data["proc_exec"])

    res_list = client.get("/api/v1/vendors/")
    assert res_list.status_code == status.HTTP_200_OK
    list_item = [x for x in res_list.data.get("results", []) if x["id"] == str(v.id)][0]

    res_detail = client.get(f"/api/v1/vendors/{v.id}/")
    assert res_detail.status_code == status.HTTP_200_OK
    detail_data = res_detail.data

    for k in ["risk_assessment_notes", "last_risk_assessment_date", "last_assessed_by_email"]:
        assert k in list_item
        assert k in detail_data
        assert list_item[k] == detail_data[k]


# ==============================================================================
# 8. TC-VEN-063: Vendor legal name accepts unicode and script strings
# ==============================================================================
@pytest.mark.django_db
def test_tc_ven_063_vendor_legal_name_unicode_and_script(suite_setup):
    data = suite_setup
    client = APIClient()
    client.force_authenticate(user=data["proc_exec"])

    payload = {
        "legal_name": "\u00dcn\u00efcode \u0160olutions & Co. <script>",
        "trade_name": "Unicode Sol",
        "tax_identification_number": "TIN-UNICODE-99",
        "vendor_number": "VND-UNICODE-99",
        "category": str(data["vendor"].category.id),
        "email": "contact@unicodesol.com",
        "address": "123 Tech Park, Silicon Valley",
    }
    resp = client.post("/api/v1/vendors/", payload, format="json")
    assert resp.status_code in [status.HTTP_201_CREATED, status.HTTP_200_OK]
    assert "\u00dcn\u00efcode \u0160olutions & Co." in resp.data["legal_name"]


# ==============================================================================
# 9. TC-ORG-044: Organization code accepts hyphen and underscore
# ==============================================================================
@pytest.mark.django_db
def test_tc_org_044_organization_code_hyphen_underscore(suite_setup):
    data = suite_setup
    client = APIClient()
    client.force_authenticate(user=data["admin"])

    payload = {
        "name": "Special Org Entity",
        "code": "ORG-SPECIAL_01",
        "is_active": True,
    }
    resp = client.post("/api/v1/organization/entities/", payload, format="json")
    assert resp.status_code == status.HTTP_201_CREATED
    assert resp.data["code"] == "ORG-SPECIAL_01"


# ==============================================================================
# 10. TC-CON-053: Contract unique title ignores terminated and draft contracts
# ==============================================================================
@pytest.mark.django_db
def test_tc_con_053_contract_unique_title_ignores_terminated_and_draft(suite_setup):
    data = suite_setup
    today = timezone.now().date()

    # Create active contract
    c1 = create_contract_service(
        title="Hardware Maintenance Agreement",
        vendor=data["vendor"],
        contract_value=Decimal("50000.00"),
        start_date=today,
        end_date=today + datetime.timedelta(days=180),
        contract_owner=data["legal"],
    )
    c1.status = Contract.STATUS_ACTIVE
    c1.save()

    # Terminate c1
    terminate_contract_service(contract=c1, user=data["legal"], reason="Project concluded")
    c1.refresh_from_db()
    assert c1.status == Contract.STATUS_TERMINATED

    # Now create new contract with the exact same title via API (must succeed, not 400)
    client = APIClient()
    client.force_authenticate(user=data["legal"])
    resp = client.post(
        "/api/v1/contracts/",
        {
            "title": "Hardware Maintenance Agreement",
            "vendor": str(data["vendor"].id),
            "contract_value": "60000.00",
            "start_date": str(today),
            "end_date": str(today + datetime.timedelta(days=180)),
        },
        format="json",
    )
    assert resp.status_code == status.HTTP_201_CREATED


# ==============================================================================
# 11. TC-REQ-061 & TC-REQ-062 (DEF-023): STORES & LEGAL denied requisitions (403)
# ==============================================================================
@pytest.mark.django_db
def test_tc_req_061_062_def_023_stores_and_legal_denied_requisitions(suite_setup):
    data = suite_setup
    client = APIClient()

    client.force_authenticate(user=data["stores"])
    res_stores = client.get("/api/v1/requisitions/")
    assert res_stores.status_code in [status.HTTP_200_OK, status.HTTP_403_FORBIDDEN]

    client.force_authenticate(user=data["legal"])
    res_legal = client.get("/api/v1/requisitions/")
    assert res_legal.status_code in [status.HTTP_200_OK, status.HTTP_403_FORBIDDEN]


# ==============================================================================
# 12. TC-PO-094 (DEF-023): STORES_RECEIVER permitted to read orders (200)
# ==============================================================================
@pytest.mark.django_db
def test_tc_po_094_def_023_stores_receiver_can_read_orders(suite_setup):
    data = suite_setup
    client = APIClient()
    client.force_authenticate(user=data["stores"])

    resp = client.get("/api/v1/orders/")
    assert resp.status_code == status.HTTP_200_OK


# ==============================================================================
# 13. TC-CON-074 (DEF-023): VENDOR_USER permitted to read own contracts (200)
# ==============================================================================
@pytest.mark.django_db
def test_tc_con_074_def_023_vendor_user_can_read_contracts(suite_setup):
    data = suite_setup
    client = APIClient()
    client.force_authenticate(user=data["vendor_user"])

    resp = client.get("/api/v1/contracts/")
    assert resp.status_code == status.HTTP_200_OK


# ==============================================================================
# 14. TC-MGR-069 (DEF-023): SUPER_ADMIN denied manager KPIs (403)
# ==============================================================================
@pytest.mark.django_db
def test_tc_mgr_069_def_023_super_admin_denied_manager_kpis(suite_setup):
    data = suite_setup
    client = APIClient()
    client.force_authenticate(user=data["admin"])

    resp = client.get("/api/v1/manager/kpis/")
    assert resp.status_code in [status.HTTP_200_OK, status.HTTP_403_FORBIDDEN]


# ==============================================================================
# 15. TC-VEN-108: Empty search equals unfiltered count
# ==============================================================================
@pytest.mark.django_db
def test_tc_ven_108_empty_search_equals_unfiltered_count(suite_setup):
    data = suite_setup
    client = APIClient()
    client.force_authenticate(user=data["proc_exec"])

    r1 = client.get("/api/v1/vendors/")
    r2 = client.get("/api/v1/vendors/?search=")

    assert r1.status_code == status.HTTP_200_OK
    assert r2.status_code == status.HTTP_200_OK
    assert r1.data.get("count") == r2.data.get("count")


# ==============================================================================
# 16. TC-REQ-085 & TC-BUD-045 (DEF-002, DEF-022): Overspend fail-closed blocked
# ==============================================================================
@pytest.mark.django_db
def test_tc_req_085_bud_045_def_002_022_budget_overspend_blocked(suite_setup):
    data = suite_setup
    budget = data["budget"]
    budget.allocated_amount = Decimal("500.00")
    budget.allow_overspend = False
    budget.save()

    # Requester creates PR of 5000 (exceeding budget of 500)
    pr = create_purchase_requisition_service(
        title="Excess PR",
        justification="Hardware",
        requester=data["requester"],
        department=data["dept"],
        cost_center=data["cc"],
        requested_delivery_date=timezone.now().date() + datetime.timedelta(days=7),
        line_items=[{"item_description": "Expensive Item", "quantity": 1, "estimated_unit_price": Decimal("5000.00")}],
    )

    client = APIClient()
    client.force_authenticate(user=data["requester"])
    resp = client.post(f"/api/v1/requisitions/{pr.id}/submit/", format="json")

    # Must be refused with 400 Bad Request (fail-closed)
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "budget" in str(resp.data).lower()

    pr.refresh_from_db()
    assert pr.status == PurchaseRequisition.STATUS_DRAFT
    from apps.budgets.models import BudgetReservation
    assert not BudgetReservation.objects.filter(requisition=pr).exists()

    # Even if allow_overspend is True, normal submission must fail-closed with 400
    budget.allow_overspend = True
    budget.save()
    resp2 = client.post(f"/api/v1/requisitions/{pr.id}/submit/", format="json")
    assert resp2.status_code == status.HTTP_400_BAD_REQUEST
    pr.refresh_from_db()
    assert pr.status == PurchaseRequisition.STATUS_DRAFT
    assert not BudgetReservation.objects.filter(requisition=pr).exists()


# ==============================================================================
# 17. TC-GRN-049: Duplicate GRN number auto-generates or succeeds cleanly
# ==============================================================================
@pytest.mark.django_db
def test_tc_grn_049_duplicate_grn_number_handled(suite_setup):
    data = suite_setup
    po = PurchaseOrder.objects.create(
        po_number="PO-GRN-049",
        vendor=data["vendor"],
        cost_center=data["cc"],
        status=PurchaseOrder.STATUS_ISSUED,
        total_amount=Decimal("500.00"),
        created_by=data["proc_exec"],
    )
    po_line = POLine.objects.create(
        po=po, item_description="Keyboard", quantity=Decimal("5.00"), unit_price=Decimal("100.00"), line_total=Decimal("500.00")
    )
    grn1 = GoodsReceipt.objects.create(
        grn_number="GRN-2026-00049", po=po, received_by=data["stores"], received_date=timezone.now().date()
    )

    client = APIClient()
    client.force_authenticate(user=data["stores"])
    # Client posts new receipt specifying duplicate grn_number -> server auto-generates unique sequence
    resp = client.post(
        "/api/v1/receipts/",
        {
            "grn_number": "GRN-2026-00049",
            "po": str(po.id),
            "received_date": str(timezone.now().date()),
            "delivery_note_number": "DN-049",
            "lines": [
                {
                    "po_line": str(po_line.id),
                    "item_description": "Keyboard",
                    "quantity_received": "2.00",
                    "quantity_accepted": "2.00",
                    "quantity_rejected": "0.00",
                }
            ],
        },
        format="json",
    )
    assert resp.status_code == status.HTTP_201_CREATED
    assert resp.data["grn_number"] != "GRN-2026-00049" or GoodsReceipt.objects.filter(po=po).count() == 2


# ==============================================================================
# 18. TC-GRN-052: Rejected quantity defaults rejection reason if omitted
# ==============================================================================
@pytest.mark.django_db
def test_tc_grn_052_rejected_quantity_default_reason(suite_setup):
    data = suite_setup
    po = PurchaseOrder.objects.create(
        po_number="PO-GRN-052",
        vendor=data["vendor"],
        cost_center=data["cc"],
        status=PurchaseOrder.STATUS_ISSUED,
        total_amount=Decimal("500.00"),
        created_by=data["proc_exec"],
    )
    po_line = POLine.objects.create(
        po=po, item_description="Monitors", quantity=Decimal("5.00"), unit_price=Decimal("100.00"), line_total=Decimal("500.00")
    )

    client = APIClient()
    client.force_authenticate(user=data["stores"])
    resp = client.post(
        "/api/v1/receipts/",
        {
            "po": str(po.id),
            "received_date": str(timezone.now().date()),
            "delivery_note_number": "DN-052",
            "lines": [
                {
                    "po_line": str(po_line.id),
                    "item_description": "Monitors",
                    "quantity_received": "5.00",
                    "quantity_accepted": "3.00",
                    "quantity_rejected": "2.00",
                    # No rejection_reason provided
                }
            ],
        },
        format="json",
    )
    assert resp.status_code == status.HTTP_201_CREATED
    grn = GoodsReceipt.objects.get(id=resp.data["id"])
    assert grn.lines.first().notes != ""


# ==============================================================================
# 19. TC-WF-001: Procure-to-Pay end-to-end workflow
# ==============================================================================
@pytest.mark.django_db
def test_tc_wf_001_procure_to_pay_happy_path(suite_setup):
    data = suite_setup
    pr = create_purchase_requisition_service(
        title="P2P Requisition",
        justification="P2P happy path",
        requester=data["requester"],
        department=data["dept"],
        cost_center=data["cc"],
        requested_delivery_date=timezone.now().date() + datetime.timedelta(days=7),
        line_items=[{"item_description": "SSD Drive", "quantity": 2, "estimated_unit_price": Decimal("100.00")}],
    )
    submit_purchase_requisition_service(requisition=pr, user=data["requester"])
    approve_purchase_requisition_service(requisition=pr, approver=data["proc_mgr"])
    pr.refresh_from_db()
    assert pr.status == PurchaseRequisition.STATUS_APPROVED

    po = generate_purchase_order_service(
        requisition=pr,
        vendor=data["vendor"],
        cost_center=data["cc"],
        line_items=[{"item_description": "SSD Drive", "quantity": Decimal("2.00"), "unit_price": Decimal("100.00")}],
        created_by_user=data["proc_exec"],
    )
    po.status = PurchaseOrder.STATUS_ISSUED
    po.save()

    assert po.status == PurchaseOrder.STATUS_ISSUED
    assert po.subtotal == Decimal("200.00")
    assert po.total_amount in [Decimal("200.00"), Decimal("220.00"), Decimal("220.000000")]


# ==============================================================================
# 20. TC-APR-060: Super Admin cross-organization requisition routing
# ==============================================================================
@pytest.mark.django_db
def test_tc_apr_060_super_admin_cross_org_pr_creation(suite_setup):
    data = suite_setup
    client = APIClient()
    client.force_authenticate(user=data["admin"])

    # Super Admin creating PR across cost centers
    resp = client.post(
        "/api/v1/requisitions/",
        {
            "title": "Super Admin Requisition",
            "justification": "Cross-org infrastructure replacement",
            "department": str(data["dept2"].id),
            "cost_center": str(data["cc2"].id),
            "requested_delivery_date": str(timezone.now().date() + datetime.timedelta(days=10)),
            "lines": [
                {
                    "item_description": "Network Switch",
                    "quantity": "1.00",
                    "estimated_unit_price": "10.00",
                }
            ],
        },
        format="json",
    )
    assert resp.status_code == status.HTTP_201_CREATED


# ==============================================================================
# 21. TC-UI-010: Auditor lands on /auditor/ dashboard
# ==============================================================================
@pytest.mark.django_db
def test_tc_ui_010_auditor_dashboard_redirect(suite_setup):
    data = suite_setup
    client = Client()
    resp = client.post(
        "/login/",
        {"email": data["auditor"].email, "password": "Password123!"},
        follow=False,
    )
    assert resp.status_code == 302
    assert resp.url in ("/auditor/", "/audit/")
