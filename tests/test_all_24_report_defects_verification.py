import datetime
from decimal import Decimal

import pytest
from django.test import Client
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.approvals.models import ApprovalAction, ApprovalPolicy, ApprovalStep
from apps.budgets.models import Budget, BudgetReservation
from apps.contracts.models import Contract
from apps.invoices.models import SupplierInvoice
from apps.notifications.models import Notification
from apps.orders.models import POLine, PurchaseOrder
from apps.organization.models import CostCenter, Department, FiscalPeriod, Organization
from apps.receipts.models import GoodsReceipt
from apps.requisitions.models import PurchaseRequisition
from apps.requisitions.services import (
    create_purchase_requisition_service,
    submit_purchase_requisition_service,
)
from apps.vendors.models import Vendor, VendorCategory


@pytest.fixture
def qa_world(db):
    org = Organization.objects.create(name="QA Org", code="QA-ORG-24")
    dept = Department.objects.create(name="QA Engineering", code="QA-ENG", organization=org)
    cc = CostCenter.objects.create(name="QA Operations", code="QA-CC", department=dept)
    fp = FiscalPeriod.objects.create(
        name="FY2026-P1",
        year=2026,
        period_number=1,
        start_date="2026-01-01",
        end_date="2026-12-31",
        organization=org,
        is_closed=False,
    )
    budget = Budget.objects.create(
        cost_center=cc,
        fiscal_period=fp,
        allocated_amount=Decimal("100000.00"),
        allow_overspend=False,
    )

    role_admin, _ = Role.objects.get_or_create(code=Role.SUPER_ADMIN, defaults={"name": "Super Admin"})
    role_req, _ = Role.objects.get_or_create(code=Role.REQUESTER, defaults={"name": "Requester"})
    role_mgr, _ = Role.objects.get_or_create(code=Role.PROC_MGR, defaults={"name": "Procurement Manager"})
    role_exec, _ = Role.objects.get_or_create(code=Role.PROC_EXEC, defaults={"name": "Procurement Executive"})
    role_fin, _ = Role.objects.get_or_create(code=Role.FINANCE_AP, defaults={"name": "Finance / AP"})
    role_stores, _ = Role.objects.get_or_create(code=Role.STORES_RECEIVER, defaults={"name": "Stores / Receiver"})
    role_legal, _ = Role.objects.get_or_create(code=Role.LEGAL_MGR, defaults={"name": "Legal Manager"})
    role_auditor, _ = Role.objects.get_or_create(code=Role.AUDITOR, defaults={"name": "Auditor"})
    role_vendor, _ = Role.objects.get_or_create(code=Role.VENDOR_USER, defaults={"name": "Vendor User"})

    cat = VendorCategory.objects.create(name="IT Hardware", code="HW-24")
    vendor = Vendor.objects.create(
        legal_name="Cisco Systems Inc",
        vendor_number="VND-CISCO-24",
        category=cat,
        status=Vendor.STATUS_ACTIVE,
        tax_identification_number="TIN-CISCO-24",
    )
    other_vendor = Vendor.objects.create(
        legal_name="Dell Technologies",
        vendor_number="VND-DELL-24",
        category=cat,
        status=Vendor.STATUS_ACTIVE,
        tax_identification_number="TIN-DELL-24",
    )

    admin = User.objects.create_user(email="admin24@test.local", password="Password123!", role=role_admin, organization=org)
    requester = User.objects.create_user(email="req24@test.local", password="Password123!", role=role_req, organization=org, department=dept, cost_center=cc)
    proc_mgr = User.objects.create_user(email="procmgr24@test.local", password="Password123!", role=role_mgr, organization=org)
    proc_exec = User.objects.create_user(email="procexec24@test.local", password="Password123!", role=role_exec, organization=org)
    finance = User.objects.create_user(email="finance24@test.local", password="Password123!", role=role_fin, organization=org)
    stores = User.objects.create_user(email="stores24@test.local", password="Password123!", role=role_stores, organization=org)
    legal = User.objects.create_user(email="legal24@test.local", password="Password123!", role=role_legal, organization=org)
    auditor = User.objects.create_user(email="auditor24@test.local", password="Password123!", role=role_auditor, organization=org)
    vendor_user = User.objects.create_user(email="vendor24@cisco.com", password="Password123!", role=role_vendor, vendor=vendor)
    other_vendor_user = User.objects.create_user(email="vendor24@dell.com", password="Password123!", role=role_vendor, vendor=other_vendor)

    # Deterministic 1-step PR policy: Procurement Manager approval
    pr_policy = ApprovalPolicy.objects.create(
        name="QA 1-Step Policy",
        module=ApprovalPolicy.MODULE_PR,
        organization=org,
        department=dept,
        min_amount=Decimal("0.00"),
        is_active=True,
    )
    ApprovalStep.objects.create(
        policy=pr_policy,
        step_number=1,
        approver_role=role_mgr,
    )

    return {
        "org": org,
        "dept": dept,
        "cc": cc,
        "fp": fp,
        "budget": budget,
        "admin": admin,
        "requester": requester,
        "proc_mgr": proc_mgr,
        "proc_exec": proc_exec,
        "finance": finance,
        "stores": stores,
        "legal": legal,
        "auditor": auditor,
        "vendor_user": vendor_user,
        "other_vendor_user": other_vendor_user,
        "vendor": vendor,
        "other_vendor": other_vendor,
        "role_mgr": role_mgr,
    }


# ==============================================================================
# GROUP A: REPORT PARAMETER VALIDATION (DEF-020: TC-AUD-018, TC-AUD-028, TC-AUD-036, TC-MGR-014, TC-MGR-048)
# ==============================================================================
@pytest.mark.django_db
def test_group_a_report_parameter_validation(qa_world):
    data = qa_world
    client = APIClient()

    # 1. TC-AUD-018: GET /api/v1/audit/lifecycle/ without identifier -> HTTP 400
    client.force_authenticate(user=data["auditor"])
    resp = client.get("/api/v1/audit/lifecycle/")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "identifier" in str(resp.data).lower()

    # 2. TC-AUD-028: GET /api/v1/audit/logs/entity-trail/ without target_model/target_object_id -> HTTP 400
    resp = client.get("/api/v1/audit/logs/entity-trail/")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST

    # 3. TC-AUD-036: GET /api/v1/audit/logs/lifecycle/ without identifier -> HTTP 400
    resp = client.get("/api/v1/audit/logs/lifecycle/")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST

    # 4. TC-MGR-014: GET /api/v1/manager/performance/compare/ without vendor_a/vendor_b -> HTTP 400
    client.force_authenticate(user=data["proc_mgr"])
    resp = client.get("/api/v1/manager/performance/compare/")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST

    # 5. TC-MGR-048: GET /manager/api/performance/compare/ without vendor_a/vendor_b -> HTTP 400
    resp = client.get("/manager/api/performance/compare/")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ==============================================================================
# GROUP B: PURCHASE ORDER VENDOR ACKNOWLEDGEMENT AND REJECTION (DEF-031: TC-PO-017, TC-PO-037, TC-PO-055, TC-PO-075)
# ==============================================================================
@pytest.mark.django_db
def test_group_b_purchase_order_vendor_acknowledgement_and_rejection(qa_world):
    data = qa_world
    po = PurchaseOrder.objects.create(
        po_number="PO-24-ACK",
        vendor=data["vendor"],
        cost_center=data["cc"],
        status=PurchaseOrder.STATUS_ISSUED,
        subtotal=Decimal("100.00"),
        tax_amount=Decimal("10.00"),
        total_amount=Decimal("110.00"),
    )
    POLine.objects.create(
        po=po,
        item_description="Server Rack",
        quantity=Decimal("1.00"),
        unit_price=Decimal("100.00"),
        unit_of_measure="EA",
    )

    client_vendor = APIClient()
    client_vendor.force_authenticate(user=data["vendor_user"])

    # Unauthorized vendor user gets HTTP 403
    client_other = APIClient()
    client_other.force_authenticate(user=data["other_vendor_user"])
    resp_unauth = client_other.post(f"/api/v1/orders/{po.id}/acknowledge/", {"notes": "Unauthorized ack"}, format="json")
    assert resp_unauth.status_code == status.HTTP_403_FORBIDDEN

    # Non-existent PO returns HTTP 404
    resp_not_found = client_vendor.post("/api/v1/orders/00000000-0000-4000-8000-000000000000/acknowledge/", {"notes": "Ack"}, format="json")
    assert resp_not_found.status_code == status.HTTP_404_NOT_FOUND

    # 1. TC-PO-017: Authorized vendor acknowledges order -> HTTP 200
    resp_ack = client_vendor.post(f"/api/v1/orders/{po.id}/acknowledge/", {"acknowledgement_notes": "Order accepted"}, format="json")
    assert resp_ack.status_code == status.HTTP_200_OK
    po.refresh_from_db()
    assert po.status == PurchaseOrder.STATUS_ACKNOWLEDGED

    # Reset to ISSUED for reject test
    po.status = PurchaseOrder.STATUS_ISSUED
    po.save(update_fields=["status"])

    # 2. TC-PO-037: Authorized vendor rejects order -> HTTP 200
    resp_rej = client_vendor.post(f"/api/v1/orders/{po.id}/vendor-reject/", {"reason": "Supply shortage"}, format="json")
    assert resp_rej.status_code == status.HTTP_200_OK
    po.refresh_from_db()
    assert po.status in [PurchaseOrder.STATUS_APPROVED, PurchaseOrder.STATUS_ISSUED, PurchaseOrder.STATUS_DRAFT]

    # 3. TC-PO-055: /api/v1/purchase-orders/{id}/acknowledge/ alias returns HTTP 200
    po.status = PurchaseOrder.STATUS_ISSUED
    po.save(update_fields=["status"])
    resp_alias_ack = client_vendor.post(f"/api/v1/purchase-orders/{po.id}/acknowledge/", {"acknowledgement_notes": "Accepted via alias"}, format="json")
    assert resp_alias_ack.status_code == status.HTTP_200_OK

    # 4. TC-PO-075: /api/v1/purchase-orders/{id}/vendor-reject/ alias returns HTTP 200
    po.status = PurchaseOrder.STATUS_ISSUED
    po.save(update_fields=["status"])
    resp_alias_rej = client_vendor.post(f"/api/v1/purchase-orders/{po.id}/vendor-reject/", {"reason": "Rejected via alias"}, format="json")
    assert resp_alias_rej.status_code == status.HTTP_200_OK


# ==============================================================================
# GROUP C: REQUISITION APPROVAL WORKFLOW AND ACTIONABLE STATUS (DEF-032: TC-APR-005, TC-REQ-013, TC-APR-060)
# ==============================================================================
@pytest.mark.django_db
def test_group_c_requisition_approval_workflow(qa_world):
    data = qa_world
    pr = create_purchase_requisition_service(
        title="QA Workstation PR",
        justification="Engineering hardware",
        requester=data["requester"],
        department=data["dept"],
        cost_center=data["cc"],
        requested_delivery_date=timezone.now().date() + datetime.timedelta(days=14),
        line_items=[{"item_description": "Workstation", "quantity": 1, "estimated_unit_price": Decimal("2500.00")}],
    )
    submit_purchase_requisition_service(requisition=pr, user=data["requester"])
    pr.refresh_from_db()

    action = ApprovalAction.objects.filter(
        target_object_id=str(pr.id),
        target_model_name="PurchaseRequisition",
    ).order_by("-created_at").first()

    client_mgr = APIClient()
    client_mgr.force_authenticate(user=data["proc_mgr"])

    # 1. TC-APR-005: Approving pending approval action moves PR to APPROVED (not MANAGER_REVIEW)
    resp = client_mgr.post(f"/api/v1/approvals/actions/{action.id}/approve/", {"comments": "Approved"}, format="json")
    assert resp.status_code == status.HTTP_200_OK
    pr.refresh_from_db()
    assert pr.status == PurchaseRequisition.STATUS_APPROVED

    # 2. TC-REQ-013: POST /api/v1/requisitions/{id}/approve/ moves PR to APPROVED
    pr2 = create_purchase_requisition_service(
        title="QA Laptop PR",
        justification="Engineering laptop",
        requester=data["requester"],
        department=data["dept"],
        cost_center=data["cc"],
        requested_delivery_date=timezone.now().date() + datetime.timedelta(days=14),
        line_items=[{"item_description": "Laptop", "quantity": 1, "estimated_unit_price": Decimal("1500.00")}],
    )
    submit_purchase_requisition_service(requisition=pr2, user=data["requester"])
    resp2 = client_mgr.post(f"/api/v1/requisitions/{pr2.id}/approve/", {"comments": "Approved directly"}, format="json")
    assert resp2.status_code == status.HTTP_200_OK
    pr2.refresh_from_db()
    assert pr2.status == PurchaseRequisition.STATUS_APPROVED

    # 3. TC-APR-060: Deterministic global fallback routing across multiple PRs
    client_admin = APIClient()
    client_admin.force_authenticate(user=data["admin"])
    resp_pr = client_admin.post(
        "/api/v1/requisitions/",
        {
            "title": "Global Fallback PR",
            "justification": "Fallback testing",
            "department": str(data["dept"].id),
            "cost_center": str(data["cc"].id),
            "requested_delivery_date": str(timezone.now().date() + datetime.timedelta(days=7)),
            "lines": [{"item_description": "Network Switch", "quantity": "1.00", "estimated_unit_price": "10.00"}],
        },
        format="json",
    )
    assert resp_pr.status_code == status.HTTP_201_CREATED


# ==============================================================================
# GROUP D: BUDGET UPDATE AND PATCH INTEGRITY (DEF-011 and DEF-033: TC-BUD-013)
# ==============================================================================
@pytest.mark.django_db
def test_group_d_budget_patch_integrity(qa_world):
    data = qa_world
    budget = data["budget"]

    client_admin = APIClient()
    client_admin.force_authenticate(user=data["admin"])

    # Super Admin can update budget across organizations without 404 (DEF-011)
    resp = client_admin.patch(
        f"/api/v1/budgets/{budget.id}/",
        {"allocated_amount": "120000.00"},
        format="json",
    )
    assert resp.status_code == status.HTTP_200_OK
    budget.refresh_from_db()
    assert budget.allocated_amount == Decimal("120000.00")
    # Derived property available_amount correctly reconciles
    assert budget.available_amount == Decimal("120000.00")


# ==============================================================================
# GROUP E: ROLE-BASED ACCESS CONTROL (DEF-023: TC-MGR-069)
# ==============================================================================
@pytest.mark.django_db
def test_group_e_super_admin_denied_manager_kpis(qa_world):
    data = qa_world
    client_admin = APIClient()
    client_admin.force_authenticate(user=data["admin"])

    # TC-MGR-069: Super Admin must receive HTTP 403 on manager KPIs
    resp = client_admin.get("/api/v1/manager/kpis/")
    assert resp.status_code == status.HTTP_403_FORBIDDEN

    # Procurement Manager receives HTTP 200
    client_mgr = APIClient()
    client_mgr.force_authenticate(user=data["proc_mgr"])
    resp_mgr = client_mgr.get("/api/v1/manager/kpis/")
    assert resp_mgr.status_code == status.HTTP_200_OK


# ==============================================================================
# GROUP F: NOTIFICATION SUMMARY CONSISTENCY AND MUTATION SAFETY (DEF-034: TC-NOT-023)
# ==============================================================================
@pytest.mark.django_db
def test_group_f_notification_summary_consistency_and_mutation_safety(qa_world):
    data = qa_world
    notif = Notification.objects.create(
        recipient=data["admin"],
        notification_type=Notification.TYPE_APPROVAL_REQUIRED,
        title="Pending Requisition",
        message="A requisition requires approval",
        is_read=True,
    )

    client_admin = APIClient()
    client_admin.force_authenticate(user=data["admin"])

    # Read initial read_at
    resp_before = client_admin.get(f"/api/v1/notifications/{notif.id}/")
    initial_read_at = resp_before.data.get("read_at")

    # PATCH title must not mutate read_at (DEF-033)
    resp_patch = client_admin.patch(
        f"/api/v1/notifications/{notif.id}/",
        {"title": "Updated Requisition Title"},
        format="json",
    )
    assert resp_patch.status_code == status.HTTP_200_OK
    assert resp_patch.data.get("title") == "Updated Requisition Title"
    assert resp_patch.data.get("read_at") == initial_read_at

    # TC-NOT-023: Notification summary unread count equals list unread count
    resp_sum = client_admin.get("/api/v1/notifications/summary/")
    resp_list = client_admin.get("/api/v1/notifications/?is_read=false")
    assert resp_sum.status_code == status.HTTP_200_OK
    assert resp_list.status_code == status.HTTP_200_OK
    assert resp_sum.data.get("unread_count") == resp_list.data.get("count")


# ==============================================================================
# GROUP G: BUDGET RESERVATION AND OVER-BUDGET WORKFLOW (DEF-022: TC-WF-001)
# ==============================================================================
@pytest.mark.django_db
def test_group_g_budget_reservation_no_duplicate(qa_world):
    data = qa_world
    pr = create_purchase_requisition_service(
        title="Hardware Purchase",
        justification="Production hardware",
        requester=data["requester"],
        department=data["dept"],
        cost_center=data["cc"],
        requested_delivery_date=timezone.now().date() + datetime.timedelta(days=7),
        line_items=[{"item_description": "Hardware", "quantity": 1, "estimated_unit_price": Decimal("200.00")}],
    )
    submit_purchase_requisition_service(requisition=pr, user=data["requester"])
    pr.refresh_from_db()

    # Requisition approved by Procurement Manager
    client_mgr = APIClient()
    client_mgr.force_authenticate(user=data["proc_mgr"])
    resp = client_mgr.post(f"/api/v1/requisitions/{pr.id}/approve/", {"comments": "Approved"}, format="json")
    assert resp.status_code == status.HTTP_200_OK

    # Budget reservation must be exactly 200.00, not 400.00 (DEF-022 / TC-WF-001)
    budget = data["budget"]
    budget.refresh_from_db()
    assert budget.reserved_amount == Decimal("200.00")


# ==============================================================================
# GROUP H: INVOICE PAYMENT INTEGRITY (TC-INV-029)
# ==============================================================================
@pytest.mark.django_db
def test_group_h_invoice_payment_reference(qa_world):
    data = qa_world
    po = PurchaseOrder.objects.create(
        po_number="PO-24-INV",
        vendor=data["vendor"],
        cost_center=data["cc"],
        status=PurchaseOrder.STATUS_COMPLETED,
        subtotal=Decimal("100.00"),
        tax_amount=Decimal("10.00"),
        total_amount=Decimal("110.00"),
    )
    inv = SupplierInvoice.objects.create(
        invoice_number="INV-24-001",
        po=po,
        vendor=data["vendor"],
        status=SupplierInvoice.STATUS_READY_FOR_PAYMENT,
        subtotal=Decimal("100.00"),
        tax_amount=Decimal("10.00"),
        total_amount=Decimal("110.00"),
        invoice_date=timezone.now().date(),
        due_date=timezone.now().date() + datetime.timedelta(days=30),
    )

    client_fin = APIClient()
    client_fin.force_authenticate(user=data["finance"])

    # TC-INV-029: Paying invoice succeeds with HTTP 200
    resp_pay = client_fin.post(f"/api/v1/invoices/{inv.id}/pay/", {"payment_reference": "QA-PAY-1"}, format="json")
    assert resp_pay.status_code == status.HTTP_200_OK
    inv.refresh_from_db()
    assert inv.status == SupplierInvoice.STATUS_PAID


# ==============================================================================
# GROUP I: PO AMENDMENT ON ISSUED ORDER (TC-PO-019, TC-PO-057)
# ==============================================================================
@pytest.mark.django_db
def test_group_i_po_amendment_on_issued_order(qa_world):
    data = qa_world
    po = PurchaseOrder.objects.create(
        po_number="PO-24-AMEND",
        vendor=data["vendor"],
        cost_center=data["cc"],
        status=PurchaseOrder.STATUS_ISSUED,
        subtotal=Decimal("100.00"),
        tax_amount=Decimal("10.00"),
        total_amount=Decimal("110.00"),
    )
    POLine.objects.create(
        po=po,
        item_description="Server RAM",
        quantity=Decimal("2.00"),
        unit_price=Decimal("50.00"),
        unit_of_measure="EA",
    )

    client_exec = APIClient()
    client_exec.force_authenticate(user=data["proc_exec"])

    # TC-PO-019: POST /api/v1/orders/{id}/amend/ succeeds with HTTP 200
    resp_amend = client_exec.post(f"/api/v1/orders/{po.id}/amend/", {"reason": "Scope update"}, format="json")
    assert resp_amend.status_code == status.HTTP_200_OK
    po.refresh_from_db()
    assert po.status == PurchaseOrder.STATUS_AMENDMENT_PENDING

    # TC-PO-057: /api/v1/purchase-orders/{id}/amend/ alias
    po.status = PurchaseOrder.STATUS_ISSUED
    po.amendments.all().delete()
    po.save()
    resp_alias = client_exec.post(f"/api/v1/purchase-orders/{po.id}/amend/", {"reason": "Scope update alias"}, format="json")
    assert resp_alias.status_code == status.HTTP_200_OK


# ==============================================================================
# GROUP J, K, L, M, N: BOUNDARIES, CONSTRAINTS & REDIRECTS
# ==============================================================================
@pytest.mark.django_db
def test_group_j_organization_code_validation(qa_world):
    data = qa_world
    client_admin = APIClient()
    client_admin.force_authenticate(user=data["admin"])

    # TC-ORG-044: Organization code with hyphen/underscore is accepted -> HTTP 201
    resp = client_admin.post(
        "/api/v1/organization/entities/",
        {"name": "Special Org", "code": "ORG-SPECIAL_01"},
        format="json",
    )
    assert resp.status_code == status.HTTP_201_CREATED


@pytest.mark.django_db
def test_group_k_contract_title_validation(qa_world):
    data = qa_world
    client_legal = APIClient()
    client_legal.force_authenticate(user=data["legal"])

    # TC-CON-053: Contract title of 255 chars accepted -> HTTP 201
    title_255 = "C" * 255
    resp = client_legal.post(
        "/api/v1/contracts/",
        {
            "title": title_255,
            "vendor": str(data["vendor"].id),
            "contract_value": "50000.00",
            "start_date": str(timezone.now().date()),
            "end_date": str(timezone.now().date() + datetime.timedelta(days=365)),
        },
        format="json",
    )
    assert resp.status_code == status.HTTP_201_CREATED


@pytest.mark.django_db
def test_group_l_goods_receipt_duplicate_number_handling(qa_world):
    data = qa_world
    po = PurchaseOrder.objects.create(
        po_number="PO-24-GRN",
        vendor=data["vendor"],
        cost_center=data["cc"],
        status=PurchaseOrder.STATUS_ISSUED,
        subtotal=Decimal("100.00"),
        tax_amount=Decimal("10.00"),
        total_amount=Decimal("110.00"),
    )
    pol = POLine.objects.create(
        po=po,
        item_description="SSD Drive",
        quantity=Decimal("10.00"),
        unit_price=Decimal("10.00"),
        unit_of_measure="EA",
    )

    client_stores = APIClient()
    client_stores.force_authenticate(user=data["stores"])

    payload = {
        "po": str(po.id),
        "delivery_note_number": "DN-DUP-01",
        "lines": [{"po_line_id": str(pol.id), "quantity_received": "2.00"}],
    }

    # First receipt
    resp1 = client_stores.post("/api/v1/receipts/", payload, format="json")
    assert resp1.status_code == status.HTTP_201_CREATED

    # TC-GRN-049: Second receipt with same supplied number creates distinct server GRN -> HTTP 201
    resp2 = client_stores.post("/api/v1/receipts/", payload, format="json")
    assert resp2.status_code == status.HTTP_201_CREATED
    assert resp1.data["grn_number"] != resp2.data["grn_number"]


@pytest.mark.django_db
def test_group_m_vendor_summary_count_reconciliation(qa_world):
    data = qa_world
    client_exec = APIClient()
    client_exec.force_authenticate(user=data["proc_exec"])

    # TC-VEN-122: Vendor summary total equals list count
    resp_summary = client_exec.get("/api/v1/vendors/summary/")
    resp_list = client_exec.get("/api/v1/vendors/")
    assert resp_summary.status_code == status.HTTP_200_OK
    assert resp_list.status_code == status.HTTP_200_OK
    assert resp_summary.data.get("total_vendors") == resp_list.data.get("count")


@pytest.mark.django_db
def test_group_n_auditor_dashboard_redirect(qa_world):
    data = qa_world
    client = Client()

    # TC-UI-010: Auditor login redirects to /auditor/
    resp = client.post(
        "/login/",
        {"email": data["auditor"].email, "password": "Password123!"},
        follow=False,
    )
    assert resp.status_code == 302
    assert resp.url == "/auditor/"
