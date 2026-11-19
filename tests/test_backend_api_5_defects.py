import pytest
from decimal import Decimal
from rest_framework.test import APIClient
from rest_framework import status
from apps.accounts.models import Role, User
from apps.organization.models import Organization, Department, CostCenter
from apps.requisitions.models import PurchaseRequisition, PRLine
from apps.approvals.models import ApprovalPolicy, ApprovalStep
from apps.orders.models import PurchaseOrder, POLine
from apps.vendors.models import Vendor, VendorCategory

@pytest.fixture
def api_test_env():
    org = Organization.objects.create(name="QA Org", code="QAORG")
    dept = Department.objects.create(name="Engineering", code="ENG", organization=org)
    cc = CostCenter.objects.create(name="CC-101", code="CC101", department=dept)
    vcat = VendorCategory.objects.create(name="IT", code="IT_CAT")
    vendor = Vendor.objects.create(legal_name="Vendor A", tax_identification_number="TIN123", category=vcat, organization=org, status="ACTIVE")

    role_stores, _ = Role.objects.get_or_create(code=Role.STORES_RECEIVER, defaults={"name": "Stores Receiver"})
    role_legal, _ = Role.objects.get_or_create(code=Role.LEGAL_MGR, defaults={"name": "Legal Manager"})
    role_admin, _ = Role.objects.get_or_create(code=Role.SUPER_ADMIN, defaults={"name": "Super Admin"})
    role_requester, _ = Role.objects.get_or_create(code=Role.REQUESTER, defaults={"name": "Requester"})

    stores_user = User.objects.create_user(email="stores@qa.test", password="Password123!", role=role_stores, organization=org, department=dept)
    legal_user = User.objects.create_user(email="legal@qa.test", password="Password123!", role=role_legal, organization=org, department=dept)
    admin_user = User.objects.create_user(email="admin@qa.test", password="Password123!", role=role_admin, organization=org, is_superuser=True)
    req_user = User.objects.create_user(email="req@qa.test", password="Password123!", role=role_requester, organization=org, department=dept)

    from django.utils import timezone
    pr = PurchaseRequisition.objects.create(
        requester=req_user,
        department=dept,
        cost_center=cc,
        title="Test PR",
        justification="Needs parts",
        status=PurchaseRequisition.STATUS_SUBMITTED,
        requested_delivery_date=timezone.now().date(),
    )
    PRLine.objects.create(requisition=pr, item_description="Widget", quantity=2, estimated_unit_price=Decimal("10.00"), estimated_total=Decimal("20.00"))

    po = PurchaseOrder.objects.create(
        po_number="PO-QA-DRAFT-001",
        vendor=vendor,
        cost_center=cc,
        requisition=pr,
        status=PurchaseOrder.STATUS_DRAFT,
        created_by=admin_user,
    )

    policy = ApprovalPolicy.objects.create(
        name="QA Policy P11182218kt002",
        module="PR",
        organization=org,
        department=dept,
        status="ACTIVE",
        is_active=True,
    )

    return {
        "org": org,
        "dept": dept,
        "cc": cc,
        "vendor": vendor,
        "stores_user": stores_user,
        "legal_user": legal_user,
        "admin_user": admin_user,
        "req_user": req_user,
        "pr": pr,
        "po": po,
        "policy": policy,
        "role_admin": role_admin,
    }

@pytest.mark.django_db
def test_def_001_stores_receiver_get_requisitions(api_test_env):
    """DEF-001: STORES_RECEIVER can GET /api/v1/requisitions/ (HTTP 200)."""
    client = APIClient()
    client.force_authenticate(user=api_test_env["stores_user"])
    res = client.get("/api/v1/requisitions/")
    assert res.status_code == status.HTTP_200_OK

@pytest.mark.django_db
def test_def_002_legal_mgr_get_requisitions(api_test_env):
    """DEF-002: LEGAL_MGR can GET /api/v1/requisitions/ (HTTP 200)."""
    client = APIClient()
    client.force_authenticate(user=api_test_env["legal_user"])
    res = client.get("/api/v1/requisitions/")
    assert res.status_code == status.HTTP_200_OK

@pytest.mark.django_db
def test_def_003_duplicate_step_number_returns_400(api_test_env):
    """DEF-003: Duplicate step number within the same policy returns HTTP 400."""
    policy = api_test_env["policy"]
    role = api_test_env["role_admin"]
    ApprovalStep.objects.create(policy=policy, step_number=1, approver_role=role)

    client = APIClient()
    client.force_authenticate(user=api_test_env["admin_user"])
    res = client.post(
        "/api/v1/approvals/steps/",
        {
            "policy": str(policy.id),
            "step_number": 1,
            "approver_role": str(role.id),
        },
        format="json",
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST

@pytest.mark.django_db
def test_def_004_issue_draft_po_returns_400(api_test_env):
    """DEF-004: Issue a DRAFT PO returns HTTP 400 invalid state."""
    po = api_test_env["po"]
    client = APIClient()
    client.force_authenticate(user=api_test_env["admin_user"])
    res = client.post(f"/api/v1/purchase-orders/{po.id}/issue/", {}, format="json")
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "status" in res.data["error"]["message"].lower() or "approved" in res.data["error"]["message"].lower()

@pytest.mark.django_db
def test_def_005_search_returns_policy_even_after_deletion(api_test_env):
    """DEF-005: Policy list filter 'search' returns policy even after soft-delete archive."""
    policy = api_test_env["policy"]
    client = APIClient()
    client.force_authenticate(user=api_test_env["admin_user"])

    # 1. Search before delete
    res1 = client.get(f"/api/v1/approvals/policies/?search={policy.name}")
    assert res1.status_code == status.HTTP_200_OK
    assert res1.data["count"] >= 1

    # 2. DELETE policy (soft archive)
    del_res = client.delete(f"/api/v1/approvals/policies/{policy.id}/")
    assert del_res.status_code == status.HTTP_204_NO_CONTENT

    # 3. Search after delete still finds the archived policy
    res2 = client.get(f"/api/v1/approvals/policies/?search={policy.name}")
    assert res2.status_code == status.HTTP_200_OK
    assert res2.data["count"] >= 1
