import datetime
from decimal import Decimal
import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.approvals.models import ApprovalPolicy, ApprovalStep
from apps.contracts.models import Contract
from apps.invoices.models import SupplierInvoice
from apps.orders.models import POLine, PurchaseOrder
from apps.organization.models import CostCenter, Department, Organization
from apps.requisitions.models import PRLine, PurchaseRequisition
from apps.vendors.models import Vendor, VendorCategory


@pytest.fixture
def qa_test_env(db):
    org = Organization.objects.create(name="QA HPE Enterprise", code="HPE-QA-01")
    dept = Department.objects.create(name="IT Operations", code="IT-QA", organization=org)
    cc = CostCenter.objects.create(name="Cloud Ops", code="CC-QA", department=dept)

    # Roles
    role_admin, _ = Role.objects.get_or_create(code=Role.SUPER_ADMIN, defaults={"name": "Super Admin"})
    role_requester, _ = Role.objects.get_or_create(code=Role.REQUESTER, defaults={"name": "Requester"})
    role_dept_appr, _ = Role.objects.get_or_create(code=Role.DEPT_APPROVER, defaults={"name": "Department Approver"})
    role_procexec, _ = Role.objects.get_or_create(code=Role.PROC_EXEC, defaults={"name": "Procurement Executive"})
    role_procmgr, _ = Role.objects.get_or_create(code=Role.PROC_MGR, defaults={"name": "Procurement Manager"})
    role_finance, _ = Role.objects.get_or_create(code=Role.FINANCE_AP, defaults={"name": "Finance AP"})
    role_receiver, _ = Role.objects.get_or_create(code=Role.STORES_RECEIVER, defaults={"name": "Stores Receiver"})
    role_legal, _ = Role.objects.get_or_create(code=Role.LEGAL_MGR, defaults={"name": "Legal Manager"})
    role_auditor, _ = Role.objects.get_or_create(code=Role.AUDITOR, defaults={"name": "Auditor"})
    role_vendor, _ = Role.objects.get_or_create(code=Role.VENDOR_USER, defaults={"name": "Vendor User"})

    # Users
    admin = User.objects.create_superuser(
        email="qa.admin@hpe.test",
        password="Password123!",
        role=role_admin,
    )
    requester1 = User.objects.create_user(
        email="qa.requester1@hpe.test",
        password="Password123!",
        role=role_requester,
        department=dept,
        cost_center=cc,
    )
    requester2 = User.objects.create_user(
        email="qa.requester2@hpe.test",
        password="Password123!",
        role=role_requester,
        department=dept,
        cost_center=cc,
    )
    dept_appr = User.objects.create_user(
        email="qa.deptappr@hpe.test",
        password="Password123!",
        role=role_dept_appr,
        department=dept,
    )
    procexec = User.objects.create_user(
        email="qa.procexec@hpe.test",
        password="Password123!",
        role=role_procexec,
        department=dept,
    )
    procmgr = User.objects.create_user(
        email="qa.procmgr@hpe.test",
        password="Password123!",
        role=role_procmgr,
        department=dept,
    )
    finance = User.objects.create_user(
        email="qa.finance@hpe.test",
        password="Password123!",
        role=role_finance,
        department=dept,
    )
    legal = User.objects.create_user(
        email="qa.legal@hpe.test",
        password="Password123!",
        role=role_legal,
        department=dept,
    )
    auditor = User.objects.create_user(
        email="qa.auditor@hpe.test",
        password="Password123!",
        role=role_auditor,
        department=dept,
    )

    # Vendors
    cat = VendorCategory.objects.create(name="IT Services", code="IT-SRV")
    vendor1 = Vendor.objects.create(
        vendor_number="VEN-QA-001",
        legal_name="Alpha Tech Solutions Pvt Ltd",
        trade_name="AlphaTech",
        category=cat,
        tax_identification_number="AAACA1234A",
        status=Vendor.STATUS_ACTIVE,
    )
    vendor2 = Vendor.objects.create(
        vendor_number="VEN-QA-002",
        legal_name="Beta Logistics International",
        trade_name="BetaLogistics",
        category=cat,
        tax_identification_number="BBBCB5678B",
        status=Vendor.STATUS_ACTIVE,
    )

    vendor_user1 = User.objects.create_user(
        email="vendor1.user@alphatech.test",
        password="Password123!",
        role=role_vendor,
        vendor=vendor1,
    )
    vendor_user2 = User.objects.create_user(
        email="vendor2.user@betalogistics.test",
        password="Password123!",
        role=role_vendor,
        vendor=vendor2,
    )

    return {
        "org": org,
        "dept": dept,
        "cc": cc,
        "admin": admin,
        "requester1": requester1,
        "requester2": requester2,
        "dept_appr": dept_appr,
        "procexec": procexec,
        "procmgr": procmgr,
        "finance": finance,
        "legal": legal,
        "auditor": auditor,
        "vendor1": vendor1,
        "vendor2": vendor2,
        "vendor_user1": vendor_user1,
        "vendor_user2": vendor_user2,
        "role_procmgr": role_procmgr,
    }


# ==============================================================================
# DEF-001 (REQ-079): Requisition IDOR Protection
# ==============================================================================
@pytest.mark.django_db
def test_def_001_requisition_idor_requester_isolation(qa_test_env):
    """
    DEF-001 / REQ-079:
    Ensure that a REQUESTER cannot read requisitions owned by another requester,
    even if both requesters belong to the same department and cost center.
    Must return HTTP 404 (or 403), NOT HTTP 200.
    """
    req1 = qa_test_env["requester1"]
    req2 = qa_test_env["requester2"]
    dept = qa_test_env["dept"]
    cc = qa_test_env["cc"]

    pr1 = PurchaseRequisition.objects.create(
        pr_number="PR-QA-001",
        title="Engineering Laptops Req1",
        requester=req1,
        department=dept,
        cost_center=cc,
        status=PurchaseRequisition.STATUS_SUBMITTED,
        total_amount=Decimal("50000.00"),
        justification="Required hardware for engineering team",
        requested_delivery_date=timezone.now().date() + datetime.timedelta(days=10),
    )
    PRLine.objects.create(
        requisition=pr1,
        item_description="Laptop Dell Precision",
        quantity=Decimal("2"),
        unit_of_measure="EA",
        estimated_unit_price=Decimal("25000.00"),
    )

    client = APIClient()

    # 1. Requester 1 reads their own PR -> HTTP 200 OK
    client.force_authenticate(user=req1)
    resp_own = client.get(f"/api/v1/requisitions/{pr1.id}/")
    assert resp_own.status_code == status.HTTP_200_OK
    assert resp_own.data["id"] == str(pr1.id)

    # 2. Requester 2 (same department) attempts to read Requester 1's PR -> HTTP 404 (Protected against IDOR)
    client.force_authenticate(user=req2)
    resp_idor = client.get(f"/api/v1/requisitions/{pr1.id}/")
    assert resp_idor.status_code in [status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN]

    # 3. Requester 2 list endpoint should not include Requester 1's PR
    resp_list = client.get("/api/v1/requisitions/")
    assert resp_list.status_code == status.HTTP_200_OK
    pr_ids_in_list = [item["id"] for item in resp_list.data.get("results", resp_list.data)]
    assert str(pr1.id) not in pr_ids_in_list

    # 4. Super Admin and Procurement Manager can access for governance
    client.force_authenticate(user=qa_test_env["admin"])
    resp_admin = client.get(f"/api/v1/requisitions/{pr1.id}/")
    assert resp_admin.status_code == status.HTTP_200_OK

    client.force_authenticate(user=qa_test_env["procmgr"])
    resp_mgr = client.get(f"/api/v1/requisitions/{pr1.id}/")
    assert resp_mgr.status_code == status.HTTP_200_OK


# ==============================================================================
# DEF-002 (CON-172): Contract Creation RBAC for Procurement Manager
# ==============================================================================
@pytest.mark.django_db
def test_def_002_contract_creation_rbac_proc_mgr(qa_test_env):
    """
    DEF-002 / CON-172:
    Procurement Manager (PROC_MGR) must be authorized to create contracts via
    POST /api/v1/contracts/. When submitting empty body, permission must pass
    and return HTTP 400 (validation failure), NOT HTTP 403 (Permission Denied).
    """
    procmgr = qa_test_env["procmgr"]
    client = APIClient()
    client.force_authenticate(user=procmgr)

    # Empty payload to verify permission passes and validation fails with 400
    resp_empty = client.post("/api/v1/contracts/", {}, format="json")
    assert resp_empty.status_code == status.HTTP_400_BAD_REQUEST, (
        f"Expected HTTP 400 validation error for PROC_MGR, got {resp_empty.status_code}: {resp_empty.data}"
    )

    # Valid contract creation by Procurement Manager -> HTTP 201
    contract_payload = {
        "title": "Cloud Hosting Service Agreement 2026",
        "vendor": str(qa_test_env["vendor1"].id),
        "contract_value": "1200000.00",
        "start_date": str(timezone.now().date()),
        "end_date": str(timezone.now().date() + datetime.timedelta(days=365)),
    }
    resp_create = client.post("/api/v1/contracts/", contract_payload, format="json")
    assert resp_create.status_code == status.HTTP_201_CREATED, (
        f"Expected HTTP 201 for valid contract creation, got {resp_create.status_code}: {resp_create.data}"
    )
    assert resp_create.data["title"] == "Cloud Hosting Service Agreement 2026"

    # Non-permitted role (e.g. Requester) should receive 403
    client.force_authenticate(user=qa_test_env["requester1"])
    resp_denied = client.post("/api/v1/contracts/", {}, format="json")
    assert resp_denied.status_code == status.HTTP_403_FORBIDDEN


# ==============================================================================
# DEF-003 (CON-187): Vendor Contract List Access via API
# ==============================================================================
@pytest.mark.django_db
def test_def_003_vendor_contract_list_isolation(qa_test_env):
    """
    DEF-003 / CON-187:
    Vendor user must be allowed to view contracts via GET /api/v1/contracts/
    and see only their own vendor's contracts (HTTP 200), not blocked with 403.
    Vendor mutations (POST/PUT/DELETE) must still be blocked with HTTP 403.
    """
    vendor1 = qa_test_env["vendor1"]
    vendor2 = qa_test_env["vendor2"]
    v_user1 = qa_test_env["vendor_user1"]
    legal = qa_test_env["legal"]

    c1 = Contract.objects.create(
        contract_number="CNT-QA-V1-001",
        title="AlphaTech Maintenance Agreement",
        vendor=vendor1,
        created_by=legal,
        contract_owner=legal,
        contract_value=Decimal("500000.00"),
        start_date=timezone.now().date(),
        end_date=timezone.now().date() + datetime.timedelta(days=180),
        status=Contract.STATUS_ACTIVE,
    )
    c2 = Contract.objects.create(
        contract_number="CNT-QA-V2-002",
        title="BetaLogistics Freight Agreement",
        vendor=vendor2,
        created_by=legal,
        contract_owner=legal,
        contract_value=Decimal("750000.00"),
        start_date=timezone.now().date(),
        end_date=timezone.now().date() + datetime.timedelta(days=180),
        status=Contract.STATUS_ACTIVE,
    )

    client = APIClient()
    client.force_authenticate(user=v_user1)

    # 1. Vendor 1 accesses GET /api/v1/contracts/ -> HTTP 200 OK (VendorPortalIsolationMiddleware permits safe read)
    resp_list = client.get("/api/v1/contracts/")
    assert resp_list.status_code == status.HTTP_200_OK, (
        f"Expected HTTP 200 for vendor contract list, got {resp_list.status_code}: {resp_list.data}"
    )

    results = resp_list.data.get("results", resp_list.data)
    result_ids = [item["id"] for item in results]
    assert str(c1.id) in result_ids, "Vendor 1 must see their own contract"
    assert str(c2.id) not in result_ids, "Vendor 1 must NOT see Vendor 2's contract"

    # 2. Vendor 1 accesses detail of own contract -> HTTP 200
    resp_detail_own = client.get(f"/api/v1/contracts/{c1.id}/")
    assert resp_detail_own.status_code == status.HTTP_200_OK

    # 3. Vendor 1 attempts to access Vendor 2's contract -> HTTP 404/403
    resp_detail_other = client.get(f"/api/v1/contracts/{c2.id}/")
    assert resp_detail_other.status_code in [status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN]

    # 4. Vendor attempting write operation on /api/v1/contracts/ is strictly blocked -> HTTP 403
    resp_write = client.post("/api/v1/contracts/", {}, format="json")
    assert resp_write.status_code == status.HTTP_403_FORBIDDEN


# ==============================================================================
# DEF-004 (INV-105): Invoice Creation RBAC for Procurement Executive
# ==============================================================================
@pytest.mark.django_db
def test_def_004_invoice_creation_rbac_proc_exec(qa_test_env):
    """
    DEF-004 / INV-105:
    Procurement Executive (PROC_EXEC) is a permitted role for invoice creation.
    POST /api/v1/invoices/ with empty body must pass permission check and return
    HTTP 400 (validation error), NOT HTTP 403 (Permission Denied).
    Dangerous actions (e.g. pay_invoice) must remain blocked with HTTP 403.
    """
    procexec = qa_test_env["procexec"]
    client = APIClient()
    client.force_authenticate(user=procexec)

    resp = client.post("/api/v1/invoices/", {}, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST, (
        f"Expected HTTP 400 validation error for PROC_EXEC invoice creation, got {resp.status_code}: {resp.data}"
    )

    # Verify payment action remains forbidden for PROC_EXEC
    import uuid
    dummy_id = uuid.uuid4()
    resp_pay = client.post(f"/api/v1/invoices/{dummy_id}/pay/", {}, format="json")
    assert resp_pay.status_code == status.HTTP_403_FORBIDDEN


# ==============================================================================
# DEF-005 (INV-106): Invoice Creation RBAC for Procurement Manager
# ==============================================================================
@pytest.mark.django_db
def test_def_005_invoice_creation_rbac_proc_mgr(qa_test_env):
    """
    DEF-005 / INV-106:
    Procurement Manager (PROC_MGR) is a permitted role for invoice creation.
    POST /api/v1/invoices/ with empty body must pass permission check and return
    HTTP 400 (validation error), NOT HTTP 403 (Permission Denied).
    Dangerous actions (e.g. resolve_exception) must remain blocked with HTTP 403.
    """
    procmgr = qa_test_env["procmgr"]
    client = APIClient()
    client.force_authenticate(user=procmgr)

    resp = client.post("/api/v1/invoices/", {}, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST, (
        f"Expected HTTP 400 validation error for PROC_MGR invoice creation, got {resp.status_code}: {resp.data}"
    )

    # Verify match exception resolution remains restricted to Finance/SuperAdmin
    import uuid
    dummy_id = uuid.uuid4()
    resp_resolve = client.post(f"/api/v1/invoices/exceptions/{dummy_id}/resolve/", {}, format="json")
    assert resp_resolve.status_code in [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND]


# ==============================================================================
# DEF-006 (APR-110): Duplicate Approval Step Number Validation
# ==============================================================================
@pytest.mark.django_db
def test_def_006_duplicate_approval_step_number_rejected(qa_test_env):
    """
    DEF-006 / APR-110:
    Duplicate step number within the same approval policy must return HTTP 400
    (validation error enforcing unique(policy, step_number)), NOT HTTP 201.
    """
    admin = qa_test_env["admin"]
    org = qa_test_env["org"]
    role_procmgr = qa_test_env["role_procmgr"]

    policy = ApprovalPolicy.objects.create(
        name="QA Engineering Requisition Policy",
        module=ApprovalPolicy.MODULE_PR,
        organization=org,
        status=ApprovalPolicy.STATUS_ACTIVE,
    )
    # Existing step 1
    ApprovalStep.objects.create(
        policy=policy,
        step_number=1,
        approver_role=role_procmgr,
        description="First Review",
    )

    client = APIClient()
    client.force_authenticate(user=admin)

    # Attempt to create duplicate step 1 for the same policy -> HTTP 400
    duplicate_payload = {
        "policy": str(policy.id),
        "step_number": 1,
        "approver_role": str(role_procmgr.id),
        "description": "Duplicate Step 1",
    }
    resp = client.post("/api/v1/approvals/steps/", duplicate_payload, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST, (
        f"Expected HTTP 400 for duplicate step number, got {resp.status_code}: {resp.data}"
    )

    # Creating step 2 should succeed -> HTTP 201
    step2_payload = {
        "policy": str(policy.id),
        "step_number": 2,
        "approver_role": str(role_procmgr.id),
        "description": "Second Review",
    }
    resp_valid = client.post("/api/v1/approvals/steps/", step2_payload, format="json")
    assert resp_valid.status_code == status.HTTP_201_CREATED
    assert resp_valid.data["step_number"] == 2


# ==============================================================================
# DEF-007 (PO-172): Issue DRAFT Purchase Order Invalid Transition
# ==============================================================================
@pytest.mark.django_db
def test_def_007_issue_draft_purchase_order_invalid_transition(qa_test_env):
    """
    DEF-007 / PO-172:
    Attempting to issue a DRAFT purchase order that has not been approved must
    return HTTP 400 (invalid state transition), NOT HTTP 404.
    """
    admin = qa_test_env["admin"]
    vendor = qa_test_env["vendor1"]
    cc = qa_test_env["cc"]

    po = PurchaseOrder.objects.create(
        po_number="PO-QA-DRAFT-001",
        vendor=vendor,
        cost_center=cc,
        status=PurchaseOrder.STATUS_DRAFT,
        created_by=admin,
        total_amount=Decimal("10000.00"),
    )
    POLine.objects.create(
        po=po,
        item_description="Server Rack Accessories",
        quantity=Decimal("1.00"),
        unit_price=Decimal("10000.00"),
    )

    client = APIClient()
    client.force_authenticate(user=admin)

    resp = client.post(f"/api/v1/purchase-orders/{po.id}/issue/", {}, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST, (
        f"Expected HTTP 400 invalid transition error, got {resp.status_code}: {resp.data}"
    )
    err_text = str(resp.data).lower()
    assert "draft" in err_text or "approved" in err_text or "cannot issue" in err_text


# ==============================================================================
# DEF-008 (APR-111): Approval Policy List Search Filter
# ==============================================================================
@pytest.mark.django_db
def test_def_008_approval_policy_search_filter(qa_test_env):
    """
    DEF-008 / APR-111:
    Policy list filter 'search' returns matching approval policies (HTTP 200, count >= 1).
    """
    admin = qa_test_env["admin"]
    org = qa_test_env["org"]

    target_name = "QA Policy P11161240ft007"
    policy = ApprovalPolicy.objects.create(
        name=target_name,
        module=ApprovalPolicy.MODULE_PR,
        organization=org,
        status=ApprovalPolicy.STATUS_ACTIVE,
        description="Search verification test policy",
    )

    client = APIClient()
    client.force_authenticate(user=admin)

    # Search by full query
    resp = client.get(f"/api/v1/approvals/policies/?search={target_name}")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["count"] >= 1
    found_names = [p["name"] for p in resp.data["results"]]
    assert target_name in found_names

    # Search with partial term
    resp_partial = client.get("/api/v1/approvals/policies/?search=P11161240ft007")
    assert resp_partial.status_code == status.HTTP_200_OK
    assert resp_partial.data["count"] >= 1

    # Search with non-existent term returns 0 results
    resp_empty = client.get("/api/v1/approvals/policies/?search=NonExistentUniqueToken999XYZ")
    assert resp_empty.status_code == status.HTTP_200_OK
    assert resp_empty.data["count"] == 0
