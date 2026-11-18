"""
Comprehensive Automated Regression Test Suite for QA Backend API Defect Remediation.
Covers DEF-001 through DEF-009:
- DEF-001 (INV-111): VENDOR_USER POST /api/v1/invoices/ with empty body returns HTTP 400 (validation error), not 403.
- DEF-002 (MGR-001): SUPER_ADMIN GET /api/v1/manager/approvals/ returns HTTP 200 with pagination envelope without 502 crash.
- DEF-003 (REQ-096): DEPT_APPROVER GET /api/v1/requisitions/ returns HTTP 200.
- DEF-004 (REQ-097): PROC_EXEC GET /api/v1/requisitions/ returns HTTP 200.
- DEF-005 (REQ-100): STORES_RECEIVER GET /api/v1/requisitions/ returns HTTP 200.
- DEF-006 (REQ-101): LEGAL_MGR GET /api/v1/requisitions/ returns HTTP 200.
- DEF-007 (INV-089): POST /api/v1/invoices/{id}/pay/ with malformed JSON returns HTTP 400 without 502 crash.
- DEF-008 (ORG-154): SUPER_ADMIN GET /api/v1/organization/entities/ returns HTTP 200 without false session timeout.
- DEF-009 (PO-172): POST /api/v1/purchase-orders/{id}/issue/ on DRAFT PO returns HTTP 400/409, not 404.
"""

from decimal import Decimal
import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.invoices.models import SupplierInvoice
from apps.orders.models import POLine, PurchaseOrder
from apps.organization.models import CostCenter, Department, Organization
from apps.requisitions.models import PRLine, PurchaseRequisition
from apps.vendors.models import Vendor, VendorCategory


@pytest.fixture
def api_test_data(db):
    org = Organization.objects.create(name="QA Test Org", code="QATO1")
    dept = Department.objects.create(name="Procurement Operations", code="PO-01", organization=org)
    cc = CostCenter.objects.create(name="Cost Center Alpha", code="CC-ALPHA", department=dept)

    cat, _ = VendorCategory.objects.get_or_create(name="Tech Supplies", code="TECH-01")
    vendor = Vendor.objects.create(
        legal_name="Acme Tech Supplies Ltd",
        tax_identification_number="TIN-ACME-01",
        category=cat,
        status=Vendor.STATUS_ACTIVE,
    )

    # Roles
    super_role, _ = Role.objects.get_or_create(code=Role.SUPER_ADMIN, defaults={"name": "Super Admin"})
    vendor_role, _ = Role.objects.get_or_create(code=Role.VENDOR_USER, defaults={"name": "Vendor User"})
    approver_role, _ = Role.objects.get_or_create(code=Role.DEPT_APPROVER, defaults={"name": "Dept Approver"})
    procexec_role, _ = Role.objects.get_or_create(code=Role.PROC_EXEC, defaults={"name": "Procurement Executive"})
    stores_role, _ = Role.objects.get_or_create(code=Role.STORES_RECEIVER, defaults={"name": "Stores Receiver"})
    legal_role, _ = Role.objects.get_or_create(code=Role.LEGAL_MGR, defaults={"name": "Legal Manager"})
    procmgr_role, _ = Role.objects.get_or_create(code=Role.PROC_MGR, defaults={"name": "Procurement Manager"})

    # Users
    admin_user = User.objects.create_superuser(
        email="qa_admin@example.com",
        password="Pass123!Secure",
        role=super_role,
        organization=org,
    )

    vendor_user = User.objects.create_user(
        email="qa_vendor@example.com",
        password="Pass123!Secure",
        role=vendor_role,
        vendor=vendor,
    )

    dept_approver_user = User.objects.create_user(
        email="qa_approver@example.com",
        password="Pass123!Secure",
        role=approver_role,
        department=dept,
        organization=org,
    )

    proc_exec_user = User.objects.create_user(
        email="qa_procexec@example.com",
        password="Pass123!Secure",
        role=procexec_role,
        department=dept,
        organization=org,
    )

    stores_user = User.objects.create_user(
        email="qa_stores@example.com",
        password="Pass123!Secure",
        role=stores_role,
        department=dept,
        organization=org,
    )

    legal_user = User.objects.create_user(
        email="qa_legal@example.com",
        password="Pass123!Secure",
        role=legal_role,
        department=dept,
        organization=org,
    )

    proc_mgr_user = User.objects.create_user(
        email="qa_procmgr@example.com",
        password="Pass123!Secure",
        role=procmgr_role,
        department=dept,
        organization=org,
    )

    # Requisition
    pr = PurchaseRequisition.objects.create(
        pr_number="PR-QA-001",
        title="Hardware Requisition",
        requester=admin_user,
        department=dept,
        cost_center=cc,
        status=PurchaseRequisition.STATUS_APPROVED,
        total_amount=Decimal("15000.00"),
        requested_delivery_date=timezone.now().date() + timezone.timedelta(days=7),
    )
    PRLine.objects.create(
        requisition=pr,
        item_description="Laptops",
        quantity=Decimal("10"),
        unit_of_measure="EA",
        estimated_unit_price=Decimal("1500.00"),
        estimated_total=Decimal("15000.00"),
    )

    # Draft Purchase Order
    draft_po = PurchaseOrder.objects.create(
        po_number="PO-QA-DRAFT-01",
        vendor=vendor,
        cost_center=cc,
        requisition=pr,
        status=PurchaseOrder.STATUS_DRAFT,
        subtotal=Decimal("15000.00"),
        tax_amount=Decimal("1500.00"),
        total_amount=Decimal("16500.00"),
        submitted_by=proc_exec_user,
    )
    POLine.objects.create(
        po=draft_po,
        item_description="Laptops",
        quantity=Decimal("10"),
        unit_price=Decimal("1500.00"),
        line_total=Decimal("15000.00"),
    )

    # Issued PO for Invoices
    issued_po = PurchaseOrder.objects.create(
        po_number="PO-QA-ISSUED-01",
        vendor=vendor,
        cost_center=cc,
        requisition=pr,
        status=PurchaseOrder.STATUS_ISSUED,
        subtotal=Decimal("10000.00"),
        tax_amount=Decimal("1000.00"),
        total_amount=Decimal("11000.00"),
        submitted_by=proc_exec_user,
    )
    POLine.objects.create(
        po=issued_po,
        item_description="Monitors",
        quantity=Decimal("20"),
        unit_price=Decimal("500.00"),
        line_total=Decimal("10000.00"),
    )

    # Ready for Payment Invoice
    invoice = SupplierInvoice.objects.create(
        invoice_number="INV-QA-PAY-01",
        vendor=vendor,
        po=issued_po,
        subtotal=Decimal("10000.00"),
        tax_amount=Decimal("1000.00"),
        total_amount=Decimal("11000.00"),
        invoice_date=timezone.now().date(),
        due_date=timezone.now().date(),
        status=SupplierInvoice.STATUS_READY_FOR_PAYMENT,
    )

    return {
        "org": org,
        "dept": dept,
        "cc": cc,
        "vendor": vendor,
        "admin_user": admin_user,
        "vendor_user": vendor_user,
        "dept_approver_user": dept_approver_user,
        "proc_exec_user": proc_exec_user,
        "stores_user": stores_user,
        "legal_user": legal_user,
        "proc_mgr_user": proc_mgr_user,
        "pr": pr,
        "draft_po": draft_po,
        "issued_po": issued_po,
        "invoice": invoice,
    }


@pytest.mark.django_db
class TestQABackendAPIDefectRemediation:
    """Tests confirming remediation of DEF-001 through DEF-009."""

    def test_def_001_vendor_post_empty_body_invoices_returns_400(self, api_test_data):
        """DEF-001 (INV-111): VENDOR_USER POST with empty body returns HTTP 400 (not 403)."""
        client = APIClient()
        client.force_authenticate(user=api_test_data["vendor_user"])
        resp = client.post("/api/v1/invoices/", data={}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, f"Expected 400, got {resp.status_code}: {resp.content}"
        assert resp.status_code != status.HTTP_403_FORBIDDEN

    def test_def_002_manager_approvals_superadmin_returns_200(self, api_test_data):
        """DEF-002 (MGR-001): SUPER_ADMIN GET /api/v1/manager/approvals/ returns HTTP 200 with pagination."""
        client = APIClient()
        client.force_authenticate(user=api_test_data["admin_user"])
        resp = client.get("/api/v1/manager/approvals/")
        assert resp.status_code == status.HTTP_200_OK, f"Expected 200, got {resp.status_code}: {resp.content}"
        data = resp.json()
        assert "summary" in data
        assert "results" in data
        assert "count" in data
        assert "page" in data

    def test_def_003_requisitions_list_dept_approver_returns_200(self, api_test_data):
        """DEF-003 (REQ-096): DEPT_APPROVER GET /api/v1/requisitions/ returns HTTP 200 without 502."""
        client = APIClient()
        client.force_authenticate(user=api_test_data["dept_approver_user"])
        resp = client.get("/api/v1/requisitions/")
        assert resp.status_code == status.HTTP_200_OK, f"Expected 200, got {resp.status_code}: {resp.content}"

    def test_def_004_requisitions_list_proc_exec_returns_200(self, api_test_data):
        """DEF-004 (REQ-097): PROC_EXEC GET /api/v1/requisitions/ returns HTTP 200 without 502."""
        client = APIClient()
        client.force_authenticate(user=api_test_data["proc_exec_user"])
        resp = client.get("/api/v1/requisitions/")
        assert resp.status_code == status.HTTP_200_OK, f"Expected 200, got {resp.status_code}: {resp.content}"

    def test_def_005_requisitions_list_stores_receiver_returns_200(self, api_test_data):
        """DEF-005 (REQ-100): STORES_RECEIVER GET /api/v1/requisitions/ returns HTTP 200 (not 403)."""
        client = APIClient()
        client.force_authenticate(user=api_test_data["stores_user"])
        resp = client.get("/api/v1/requisitions/")
        assert resp.status_code == status.HTTP_200_OK, f"Expected 200, got {resp.status_code}: {resp.content}"

    def test_def_006_requisitions_list_legal_mgr_returns_200(self, api_test_data):
        """DEF-006 (REQ-101): LEGAL_MGR GET /api/v1/requisitions/ returns HTTP 200 (not 403)."""
        client = APIClient()
        client.force_authenticate(user=api_test_data["legal_user"])
        resp = client.get("/api/v1/requisitions/")
        assert resp.status_code == status.HTTP_200_OK, f"Expected 200, got {resp.status_code}: {resp.content}"

    def test_def_007_pay_invoice_malformed_json_returns_400(self, api_test_data):
        """DEF-007 (INV-089): POST /api/v1/invoices/{id}/pay/ with malformed JSON returns HTTP 400 (not 502)."""
        client = APIClient()
        client.force_authenticate(user=api_test_data["admin_user"])
        inv = api_test_data["invoice"]
        resp = client.post(
            f"/api/v1/invoices/{inv.id}/pay/",
            data="{malformed_json: ",
            content_type="application/json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, f"Expected 400, got {resp.status_code}: {resp.content}"
        data = resp.json()
        assert data["error"]["code"] == "VALIDATION_ERROR"

    def test_def_008_superadmin_organization_entities_not_session_expired(self, api_test_data):
        """DEF-008 (ORG-154): SUPER_ADMIN GET /api/v1/organization/entities/ returns HTTP 200."""
        client = APIClient()
        client.force_authenticate(user=api_test_data["admin_user"])
        resp = client.get("/api/v1/organization/entities/")
        assert resp.status_code == status.HTTP_200_OK, f"Expected 200, got {resp.status_code}: {resp.content}"
        assert resp.status_code != status.HTTP_401_UNAUTHORIZED

    def test_def_009_issue_draft_po_returns_400(self, api_test_data):
        """DEF-009 (PO-172): POST /api/v1/purchase-orders/{id}/issue/ on DRAFT PO returns HTTP 400 (not 404)."""
        client = APIClient()
        client.force_authenticate(user=api_test_data["admin_user"])
        draft_po = api_test_data["draft_po"]
        resp = client.post(f"/api/v1/purchase-orders/{draft_po.id}/issue/", data={}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST, f"Expected 400, got {resp.status_code}: {resp.content}"
        data = resp.json()
        assert data["error"]["code"] in ["INVALID_STATE", "VALIDATION_ERROR"]
        assert "DRAFT" in str(data["error"]["message"]).upper() or "APPROVED" in str(data["error"]["message"]).upper()
