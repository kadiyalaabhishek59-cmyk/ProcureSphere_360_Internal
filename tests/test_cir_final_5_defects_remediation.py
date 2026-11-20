"""
Regression test suite verifying remediation of all 5 defects reported in
the CIR Backend API Testing Final Report (ProcureSphere360_C_I_R_Backend_API_Testing_Final_Report.xlsx):

- DEF-001 (TC PO-174): IDOR - VENDOR_USER reading another vendor's PO or unissued draft PO returns 403/404, never 200.
- DEF-002 (TC APR-110): Duplicate step number within the same policy returns 400, never 201.
- DEF-003 (TC CON-013, ORG-087): JSON array body posted to /api/v1/contracts/ or /api/v1/organization/entities/ returns 400, never 500.
- DEF-004 (TC PO-173): VENDOR_USER acknowledging a non-issued or foreign PO returns 403, never 400.
- DEF-005 (TC APR-111): Policy search filter (?search=...) returns the policy even after name mutation / soft-archiving.
"""
import uuid
from decimal import Decimal

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.approvals.models import ApprovalPolicy, ApprovalStep
from apps.contracts.models import Contract
from apps.orders.models import POLine, PurchaseOrder
from apps.organization.models import CostCenter, Department, Organization
from apps.vendors.models import Vendor, VendorCategory


@pytest.fixture
def cir_test_env(db):
    admin_role, _ = Role.objects.get_or_create(code=Role.SUPER_ADMIN, defaults={"name": "Super Admin"})
    vendor_role, _ = Role.objects.get_or_create(code=Role.VENDOR_USER, defaults={"name": "Vendor Portal User"})
    proc_mgr_role, _ = Role.objects.get_or_create(code=Role.PROC_MGR, defaults={"name": "Procurement Manager"})

    admin_user = User.objects.create_superuser(
        email="cir_admin@procuresphere.com",
        password="AdminPassword123!",
        role=admin_role,
    )

    org = Organization.objects.create(name="CIR Test Org", code="CIR-ORG-01")
    dept = Department.objects.create(name="CIR Procurement", code="CIR-DEPT-01", organization=org)
    cost_center = CostCenter.objects.create(name="CIR Core CC", code="CIR-CC-01", department=dept)
    category = VendorCategory.objects.create(name="CIR Hardware", code="CIR-CAT-01")

    # Vendor 1 (Cisco) and its user
    vendor1 = Vendor.objects.create(
        legal_name="Cisco Systems CIR",
        vendor_number="VND-CIR-001",
        tax_identification_number="TAX-CIR-001",
        category=category,
        status=Vendor.STATUS_ACTIVE,
    )
    vendor1_user = User.objects.create_user(
        email="vendor_cisco@cir-test.com",
        password="VendorPassword123!",
        role=vendor_role,
        vendor=vendor1,
    )

    # Vendor 2 (Dell) and its user
    vendor2 = Vendor.objects.create(
        legal_name="Dell Technologies CIR",
        vendor_number="VND-CIR-002",
        tax_identification_number="TAX-CIR-002",
        category=category,
        status=Vendor.STATUS_ACTIVE,
    )
    vendor2_user = User.objects.create_user(
        email="vendor_dell@cir-test.com",
        password="VendorPassword123!",
        role=vendor_role,
        vendor=vendor2,
    )

    # Draft PO for Cisco
    draft_po_cisco = PurchaseOrder.objects.create(
        po_number="PO-CIR-CISCO-DRAFT",
        vendor=vendor1,
        cost_center=cost_center,
        status=PurchaseOrder.STATUS_DRAFT,
        created_by=admin_user,
    )
    POLine.objects.create(
        po=draft_po_cisco,
        item_description="Cisco Switch",
        quantity=Decimal("5.00"),
        unit_price=Decimal("1000.00"),
        line_total=Decimal("5000.00"),
    )

    # Issued PO for Cisco
    issued_po_cisco = PurchaseOrder.objects.create(
        po_number="PO-CIR-CISCO-ISSUED",
        vendor=vendor1,
        cost_center=cost_center,
        status=PurchaseOrder.STATUS_ISSUED,
        created_by=admin_user,
    )
    POLine.objects.create(
        po=issued_po_cisco,
        item_description="Cisco Router",
        quantity=Decimal("2.00"),
        unit_price=Decimal("2500.00"),
        line_total=Decimal("5000.00"),
    )

    # Issued PO for Dell
    issued_po_dell = PurchaseOrder.objects.create(
        po_number="PO-CIR-DELL-ISSUED",
        vendor=vendor2,
        cost_center=cost_center,
        status=PurchaseOrder.STATUS_ISSUED,
        created_by=admin_user,
    )
    POLine.objects.create(
        po=issued_po_dell,
        item_description="Dell Server",
        quantity=Decimal("1.00"),
        unit_price=Decimal("8000.00"),
        line_total=Decimal("8000.00"),
    )

    return {
        "admin_user": admin_user,
        "vendor1_user": vendor1_user,
        "vendor2_user": vendor2_user,
        "vendor1": vendor1,
        "vendor2": vendor2,
        "draft_po_cisco": draft_po_cisco,
        "issued_po_cisco": issued_po_cisco,
        "issued_po_dell": issued_po_dell,
        "proc_mgr_role": proc_mgr_role,
        "org": org,
        "cost_center": cost_center,
    }


# ─────────────────────────────────────────────────────────────────────────────
# DEF-001 (TC PO-174): IDOR - VENDOR_USER reading PO
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_def_001_vendor_cannot_read_draft_po_belonging_to_own_vendor(cir_test_env):
    """
    TC PO-174: Vendor user must NOT be able to read an unissued DRAFT purchase order
    even if it belongs to their own vendor organization (403/404 forbidden).
    """
    client = APIClient()
    client.force_authenticate(user=cir_test_env["vendor1_user"])
    draft_po = cir_test_env["draft_po_cisco"]

    res = client.get(f"/api/v1/purchase-orders/{draft_po.id}/")
    assert res.status_code in [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND]


@pytest.mark.django_db
def test_def_001_vendor_cannot_read_po_belonging_to_another_vendor(cir_test_env):
    """
    TC PO-174: Vendor user must NOT be able to read a purchase order belonging
    to another vendor organization (IDOR protection - 403/404 forbidden).
    """
    client = APIClient()
    client.force_authenticate(user=cir_test_env["vendor1_user"])
    foreign_po = cir_test_env["issued_po_dell"]

    res = client.get(f"/api/v1/purchase-orders/{foreign_po.id}/")
    assert res.status_code in [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND]


@pytest.mark.django_db
def test_def_001_vendor_can_read_own_issued_po(cir_test_env):
    """
    Legitimate read: Vendor user CAN read their own ISSUED purchase order.
    """
    client = APIClient()
    client.force_authenticate(user=cir_test_env["vendor1_user"])
    own_issued_po = cir_test_env["issued_po_cisco"]

    res = client.get(f"/api/v1/purchase-orders/{own_issued_po.id}/")
    assert res.status_code == status.HTTP_200_OK
    assert res.data["id"] == str(own_issued_po.id)


# ─────────────────────────────────────────────────────────────────────────────
# DEF-002 (TC APR-110): Duplicate step number within the same policy
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_def_002_duplicate_step_number_returns_400(cir_test_env):
    """
    TC APR-110: Attempting to create an approval step with a duplicate step number
    within the same policy returns HTTP 400 Bad Request, never HTTP 201.
    """
    admin = cir_test_env["admin_user"]
    proc_mgr_role = cir_test_env["proc_mgr_role"]

    policy = ApprovalPolicy.objects.create(
        name="CIR Unique Step Policy",
        module=ApprovalPolicy.MODULE_PR,
        created_by=admin,
    )
    ApprovalStep.objects.create(
        policy=policy,
        step_number=1,
        approver_role=proc_mgr_role,
        created_by=admin,
    )

    client = APIClient()
    client.force_authenticate(user=admin)
    res = client.post(
        "/api/v1/approvals/steps/",
        {
            "policy": str(policy.id),
            "step_number": 1,
            "approver_role": str(proc_mgr_role.id),
        },
        format="json",
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "step_number" in str(res.data).lower()


@pytest.mark.django_db
def test_def_002_step_delete_preserves_uniqueness_guard(cir_test_env):
    """
    TC APR-101 & APR-110: Deleting an approval step soft-archives / preserves history
    per Rule 5, returning 204 without permitting duplicate step collision.
    """
    admin = cir_test_env["admin_user"]
    proc_mgr_role = cir_test_env["proc_mgr_role"]

    policy = ApprovalPolicy.objects.create(
        name="CIR Governance Step Policy",
        module=ApprovalPolicy.MODULE_PR,
        created_by=admin,
    )
    step1 = ApprovalStep.objects.create(
        policy=policy,
        step_number=1,
        approver_role=proc_mgr_role,
        created_by=admin,
    )

    client = APIClient()
    client.force_authenticate(user=admin)

    # APR-101 DELETE returns 204
    del_res = client.delete(f"/api/v1/approvals/steps/{step1.id}/")
    assert del_res.status_code == status.HTTP_204_NO_CONTENT

    # APR-110 Duplicate step creation is rejected with 400
    create_res = client.post(
        "/api/v1/approvals/steps/",
        {
            "policy": str(policy.id),
            "step_number": 1,
            "approver_role": str(proc_mgr_role.id),
        },
        format="json",
    )
    assert create_res.status_code == status.HTTP_400_BAD_REQUEST


# ─────────────────────────────────────────────────────────────────────────────
# DEF-003 (TC CON-013, ORG-087): JSON array body instead of dictionary
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_def_003_contracts_create_with_json_array_returns_400_not_500(cir_test_env):
    """
    TC CON-013: Posting a JSON array ["unexpected", "array"] to /api/v1/contracts/
    returns HTTP 400 Bad Request (handled validation error), never HTTP 500.
    """
    client = APIClient()
    client.force_authenticate(user=cir_test_env["admin_user"])

    res = client.post("/api/v1/contracts/", ["unexpected", "array"], format="json")
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert res.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR


@pytest.mark.django_db
def test_def_003_organization_entities_create_with_json_array_returns_400_not_500(cir_test_env):
    """
    TC ORG-087: Posting a JSON array ["unexpected", "array"] to /api/v1/organization/entities/
    returns HTTP 400 Bad Request, never HTTP 500.
    """
    client = APIClient()
    client.force_authenticate(user=cir_test_env["admin_user"])

    res = client.post("/api/v1/organization/entities/", ["unexpected", "array"], format="json")
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert res.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR


# ─────────────────────────────────────────────────────────────────────────────
# DEF-004 (TC PO-173): VENDOR_USER acknowledges non-issued / foreign PO
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_def_004_vendor_cannot_acknowledge_foreign_po(cir_test_env):
    """
    TC PO-173: VENDOR_USER attempting to acknowledge a PO of another vendor
    returns HTTP 403 Forbidden.
    """
    client = APIClient()
    client.force_authenticate(user=cir_test_env["vendor1_user"])
    foreign_po = cir_test_env["issued_po_dell"]

    res = client.post(f"/api/v1/purchase-orders/{foreign_po.id}/acknowledge/", {}, format="json")
    assert res.status_code in [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND]


@pytest.mark.django_db
def test_def_004_vendor_cannot_acknowledge_draft_po(cir_test_env):
    """
    TC PO-173: VENDOR_USER attempting to acknowledge an unissued DRAFT PO
    returns HTTP 403 Forbidden (not 400).
    """
    client = APIClient()
    client.force_authenticate(user=cir_test_env["vendor1_user"])
    draft_po = cir_test_env["draft_po_cisco"]

    res = client.post(f"/api/v1/purchase-orders/{draft_po.id}/acknowledge/", {}, format="json")
    assert res.status_code in [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND]


@pytest.mark.django_db
def test_def_004_vendor_can_acknowledge_own_issued_po(cir_test_env):
    """
    Legitimate workflow: VENDOR_USER acknowledges own ISSUED PO -> 200 OK.
    """
    client = APIClient()
    client.force_authenticate(user=cir_test_env["vendor1_user"])
    own_po = cir_test_env["issued_po_cisco"]

    res = client.post(
        f"/api/v1/purchase-orders/{own_po.id}/acknowledge/",
        {"notes": "Acknowledged delivery timeline."},
        format="json",
    )
    assert res.status_code == status.HTTP_200_OK
    own_po.refresh_from_db()
    assert own_po.status == PurchaseOrder.STATUS_ACKNOWLEDGED


# ─────────────────────────────────────────────────────────────────────────────
# DEF-005 (TC APR-111): Approval policy search returns QA policy
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_def_005_search_returns_policy_after_name_update_and_archive(cir_test_env):
    """
    TC APR-111: When an approval policy is renamed (PUT/PATCH) and soft-archived (DELETE),
    filtering by ?search=<original_qa_name> returns the policy with count >= 1.
    """
    admin = cir_test_env["admin_user"]
    qa_policy_name = "QA Policy P11191536cu007"

    client = APIClient()
    client.force_authenticate(user=admin)

    # 1. Create policy
    create_res = client.post(
        "/api/v1/approvals/policies/",
        {
            "name": qa_policy_name,
            "module": ApprovalPolicy.MODULE_PR,
            "description": "Initial QA policy",
            "currency": "INR",
        },
        format="json",
    )
    assert create_res.status_code == status.HTTP_201_CREATED
    policy_id = create_res.data["id"]

    # 2. Update policy name via PATCH (APR-060 simulation)
    patch_res = client.patch(
        f"/api/v1/approvals/policies/{policy_id}/",
        {"name": "QA Policy Updated"},
        format="json",
    )
    assert patch_res.status_code == status.HTTP_200_OK

    # 3. Soft-archive via DELETE (APR-066 simulation)
    del_res = client.delete(f"/api/v1/approvals/policies/{policy_id}/")
    assert del_res.status_code == status.HTTP_204_NO_CONTENT

    # 4. Search by original name (APR-111)
    search_res = client.get(f"/api/v1/approvals/policies/?search={qa_policy_name}")
    assert search_res.status_code == status.HTTP_200_OK
    assert search_res.data["count"] >= 1
    found_ids = [item["id"] for item in search_res.data["results"]]
    assert policy_id in found_ids
