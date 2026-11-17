from decimal import Decimal
import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.approvals.models import ApprovalPolicy, ApprovalStep
from apps.approvals.services import toggle_policy_status_service
from apps.budgets.models import Budget
from apps.organization.models import CostCenter, Department, FiscalPeriod, Organization
from apps.requisitions.models import PurchaseRequisition


@pytest.fixture
def qa_defects_env(db):
    org = Organization.objects.create(name="HPE Global Org", code="HPE-QA-01")
    dept = Department.objects.create(organization=org, name="Finance & IT", code="FIT-01")
    cc = CostCenter.objects.create(department=dept, name="Cloud Operations", code="CC-FIT-01")

    now = timezone.now()
    fp = FiscalPeriod.objects.create(
        organization=org,
        year=now.year,
        period_number=1,
        name=f"FY{now.year}-P1",
        start_date=now.date().replace(month=1, day=1),
        end_date=now.date().replace(month=12, day=31),
        is_closed=False,
    )

    budget = Budget.objects.create(
        cost_center=cc,
        fiscal_period=fp,
        allocated_amount=Decimal("100000.00"),
        reserved_amount=Decimal("15000.00"),
        committed_amount=Decimal("25000.00"),
        actual_amount=Decimal("10000.00"),
    )

    admin_role, _ = Role.objects.get_or_create(code=Role.SUPER_ADMIN, defaults={"name": "Super Admin"})
    approver_role, _ = Role.objects.get_or_create(code=Role.DEPT_APPROVER, defaults={"name": "Department Approver"})
    requester_role, _ = Role.objects.get_or_create(code=Role.REQUESTER, defaults={"name": "Requester"})

    superadmin = User.objects.create_user(
        email="admin_qa_test@hpe.com",
        password="Password123!",
        role=admin_role,
        organization=org,
        department=dept,
        is_staff=True,
        is_superuser=True,
    )

    approver = User.objects.create_user(
        email="approver_qa_test@hpe.com",
        password="Password123!",
        role=approver_role,
        organization=org,
        department=dept,
    )

    requester = User.objects.create_user(
        email="requester_qa_test@hpe.com",
        password="Password123!",
        role=requester_role,
        organization=org,
        department=dept,
    )

    policy = ApprovalPolicy.objects.create(
        name="Test Policy DEF-001",
        organization=org,
        department=dept,
        module=ApprovalPolicy.MODULE_PR,
        min_amount=Decimal("0.00"),
        max_amount=Decimal("500000.00"),
        is_active=True,
        status=ApprovalPolicy.STATUS_ACTIVE,
    )
    ApprovalStep.objects.create(
        policy=policy,
        step_number=1,
        approver_role=approver_role,
    )

    pr = PurchaseRequisition.objects.create(
        requester=requester,
        department=dept,
        cost_center=cc,
        title="Server Cluster Upgrade",
        justification="Cloud operational expansion",
        status=PurchaseRequisition.STATUS_MANAGER_REVIEW,
        total_amount=Decimal("18500.00"),
        requested_delivery_date=now.date(),
    )

    return {
        "org": org,
        "dept": dept,
        "cc": cc,
        "fp": fp,
        "budget": budget,
        "superadmin": superadmin,
        "approver": approver,
        "requester": requester,
        "policy": policy,
        "pr": pr,
    }


@pytest.mark.django_db
def test_def_001_toggle_active_policy_to_draft_deactivates(qa_defects_env):
    """
    DEF-001 (UT_APR_073):
    Toggling an ACTIVE policy must transition it to ('DRAFT', False),
    not erroneously stomping it into ('ARCHIVED', False).
    """
    env = qa_defects_env
    policy = env["policy"]
    assert policy.status == ApprovalPolicy.STATUS_ACTIVE
    assert policy.is_active is True

    toggled = toggle_policy_status_service(policy=policy, actor=env["superadmin"])
    policy.refresh_from_db()

    assert toggled.status == ApprovalPolicy.STATUS_DRAFT
    assert toggled.is_active is False
    assert policy.status == ApprovalPolicy.STATUS_DRAFT
    assert policy.is_active is False

    # Toggle back to ACTIVE
    reactivated = toggle_policy_status_service(policy=policy, actor=env["superadmin"])
    policy.refresh_from_db()
    assert reactivated.status == ApprovalPolicy.STATUS_ACTIVE
    assert reactivated.is_active is True
    assert policy.status == ApprovalPolicy.STATUS_ACTIVE
    assert policy.is_active is True


@pytest.mark.django_db
def test_def_002_approver_dashboard_api_budget_headroom(qa_defects_env):
    """
    DEF-002 (LT_APR_008):
    GET /api/v1/approver/dashboard/ must return 200 OK with correct available_budget calculation
    instead of throwing AttributeError for b.actual_spend or b.committed_spend.
    """
    env = qa_defects_env
    client = APIClient()
    client.force_authenticate(user=env["superadmin"])

    response = client.get("/api/v1/approver/dashboard/")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.data}"

    data = response.data
    # Headroom = allocated (100,000) - reserved (15,000) - committed (25,000) - actual (10,000) = 50,000.00
    expected_available = env["budget"].available_amount
    assert Decimal(str(data["available_budget"])) == expected_available
    assert data["pending_approvals"] >= 1


@pytest.mark.django_db
def test_def_003_approver_queue_api_safe_field_access(qa_defects_env):
    """
    DEF-003 (LT_APR_010):
    GET /api/v1/approver/queue/ must return 200 OK without crashing on missing currency or urgency attributes.
    """
    env = qa_defects_env
    client = APIClient()
    client.force_authenticate(user=env["superadmin"])

    response = client.get("/api/v1/approver/queue/")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.data}"

    results = response.data
    assert len(results) >= 1
    item = next(x for x in results if x["title"] == "Server Cluster Upgrade")
    assert item["currency"] == "USD"
    assert item["urgency"] == "MEDIUM"
    assert Decimal(str(item["total_amount"])) == Decimal("18500.00")
