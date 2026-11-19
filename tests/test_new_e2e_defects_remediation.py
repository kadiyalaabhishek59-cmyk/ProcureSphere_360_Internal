import time
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.approvals.models import ApprovalPolicy, ApprovalStep
from apps.budgets.models import Budget, SpendLedger
from apps.budgets.services import allocate_budget_service
from apps.organization.models import CostCenter, Department, FiscalPeriod, Organization
from apps.requisitions.models import PRLine, PurchaseRequisition


@pytest.fixture
def rbac_fixture(db):
    """Sets up realistic database entities for RBAC and portal testing."""
    today = timezone.now().date()
    org = Organization.objects.create(name="HPE Test Org", code="HPE-TST")
    dept = Department.objects.create(organization=org, name="Finance Dept", code="FIN-D")
    cc = CostCenter.objects.create(department=dept, code="CC-FIN-01", name="Finance Ops")
    fp = FiscalPeriod.objects.create(
        organization=org,
        year=2026,
        period_number=1,
        name="FY26-P1",
        start_date=today - timezone.timedelta(days=30),
        end_date=today + timezone.timedelta(days=60),
    )
    budget = allocate_budget_service(
        cost_center=cc, fiscal_period=fp, allocated_amount=Decimal("200000.00")
    )

    role_admin, _ = Role.objects.get_or_create(
        code=Role.SUPER_ADMIN, defaults={"name": "Super Admin"}
    )
    role_finance, _ = Role.objects.get_or_create(
        code=Role.FINANCE_AP, defaults={"name": "Finance AP"}
    )
    role_stores, _ = Role.objects.get_or_create(
        code=Role.STORES_RECEIVER, defaults={"name": "Stores Receiver"}
    )
    role_legal, _ = Role.objects.get_or_create(
        code=Role.LEGAL_MGR, defaults={"name": "Legal Manager"}
    )
    role_proc, _ = Role.objects.get_or_create(
        code=Role.PROC_EXEC, defaults={"name": "Procurement Executive"}
    )
    role_approver, _ = Role.objects.get_or_create(
        code=Role.DEPT_APPROVER, defaults={"name": "Dept Approver"}
    )
    role_requester, _ = Role.objects.get_or_create(
        code=Role.REQUESTER, defaults={"name": "Requester"}
    )

    superadmin_user = User.objects.create_superuser(
        email="superadmin_test@hpe.com",
        password="SuperPassword123!",
        role=role_admin,
    )
    finance_user = User.objects.create_user(
        email="finance_user_test@hpe.com",
        password="FinancePassword123!",
        role=role_finance,
        organization=org,
        department=dept,
        cost_center=cc,
    )

    # Seed multiple candidate PRs in the DB to test performance and chain evaluation under load
    for i in range(15):
        pr = PurchaseRequisition.objects.create(
            pr_number=f"PR-TST-{i:04d}",
            title=f"Bulk Requisition Test {i}",
            justification="Bulk load testing for finance view",
            requester=finance_user,
            department=dept,
            cost_center=cc,
            total_amount=Decimal("1500.00"),
            status=PurchaseRequisition.STATUS_MANAGER_REVIEW,
            requested_delivery_date=today + timezone.timedelta(days=14),
        )
        PRLine.objects.create(
            requisition=pr,
            item_description=f"Test Line Item {i}",
            quantity=Decimal("1.00"),
            estimated_unit_price=Decimal("1500.00"),
        )

    return {
        "org": org,
        "dept": dept,
        "cc": cc,
        "fp": fp,
        "budget": budget,
        "superadmin_user": superadmin_user,
        "finance_user": finance_user,
    }


@pytest.mark.django_db
def test_e2e_rbc_055_super_admin_opens_finance_portal_via_direct_url(client, rbac_fixture):
    """
    E2E-RBC-055: Portal matrix: SUPER_ADMIN opens its own /finance/ portal via direct URL.
    Expected: HTTP 200, fast response time (< 2.0s), session remains active.
    """
    client.force_login(rbac_fixture["superadmin_user"])
    start = time.time()
    response = client.get("/finance/")
    elapsed = time.time() - start

    assert response.status_code == 200
    assert elapsed < 2.0, f"Finance dashboard load time too slow: {elapsed:.2f}s"
    assert "Accounts Payable Workspace" in response.content.decode()
    # Confirm session last activity is updated and valid
    assert "_last_activity_ts" in client.session


@pytest.mark.django_db
def test_e2e_rbc_105_finance_ap_opens_finance_portal_via_direct_url(client, rbac_fixture):
    """
    E2E-RBC-105: Portal matrix: FINANCE_AP opens its own /finance/ portal via direct URL.
    Expected: HTTP 200, fast response time (< 2.0s), session remains active.
    """
    client.force_login(rbac_fixture["finance_user"])
    start = time.time()
    response = client.get("/finance/")
    elapsed = time.time() - start

    assert response.status_code == 200
    assert elapsed < 2.0, f"Finance dashboard load time too slow: {elapsed:.2f}s"
    assert "Accounts Payable Workspace" in response.content.decode()
    assert "_last_activity_ts" in client.session


@pytest.mark.django_db
def test_e2e_rbc_106_finance_ap_denied_stores_portal(client, rbac_fixture):
    """
    E2E-RBC-106: Portal matrix: FINANCE_AP is denied the /stores/ portal via direct URL.
    Expected: HTTP 403 (PermissionDenied).
    """
    client.force_login(rbac_fixture["finance_user"])
    response = client.get("/stores/")
    assert response.status_code == 403


@pytest.mark.django_db
def test_e2e_rbc_107_finance_ap_denied_legal_portal(client, rbac_fixture):
    """
    E2E-RBC-107: Portal matrix: FINANCE_AP is denied the /legal/ portal via direct URL.
    Expected: HTTP 403 (PermissionDenied).
    """
    client.force_login(rbac_fixture["finance_user"])
    response = client.get("/legal/")
    assert response.status_code == 403


@pytest.mark.django_db
def test_e2e_rbc_108_finance_ap_denied_procurement_portal(client, rbac_fixture):
    """
    E2E-RBC-108: Portal matrix: FINANCE_AP is denied the /procurement/ portal via direct URL.
    Expected: HTTP 403 (PermissionDenied).
    """
    client.force_login(rbac_fixture["finance_user"])
    response = client.get("/procurement/")
    assert response.status_code == 403


@pytest.mark.django_db
def test_e2e_rbc_109_finance_ap_denied_approver_portal(client, rbac_fixture):
    """
    E2E-RBC-109: Portal matrix: FINANCE_AP is denied the /approver/ portal via direct URL.
    Expected: HTTP 403 (PermissionDenied).
    """
    client.force_login(rbac_fixture["finance_user"])
    response = client.get("/approver/")
    assert response.status_code == 403


@pytest.mark.django_db
def test_e2e_rbc_110_finance_ap_denied_requester_portal(client, rbac_fixture):
    """
    E2E-RBC-110: Portal matrix: FINANCE_AP is denied the /requester/ portal via direct URL.
    Expected: HTTP 403 (PermissionDenied).
    """
    client.force_login(rbac_fixture["finance_user"])
    response = client.get("/requester/")
    assert response.status_code == 403


@pytest.mark.django_db
def test_finance_dashboard_query_count_under_load(client, rbac_fixture, django_assert_num_queries):
    """
    Ensures finance_dashboard_view does not suffer from N+1 query regression.
    Evaluates that running with 15+ candidate PRs stays bounded and under 25 queries total.
    """
    client.force_login(rbac_fixture["finance_user"])
    with django_assert_num_queries(18):
        resp = client.get("/finance/")
        assert resp.status_code == 200
