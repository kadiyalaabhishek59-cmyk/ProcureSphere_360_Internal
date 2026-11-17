from decimal import Decimal
import pytest
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.budgets.models import Budget
from apps.organization.models import CostCenter, Department, FiscalPeriod, Organization
from apps.requisitions.models import PurchaseRequisition


@pytest.fixture
def budget_guard_env(db, db_roles):
    org = Organization.objects.create(name="HPE Overspend Test Org", code="HPE-OST-01")
    dept = Department.objects.create(organization=org, name="IT Operations", code="IT-OPS-01")
    cc = CostCenter.objects.create(department=dept, name="Cloud Compute", code="CC-IT-101")

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
        allocated_amount=Decimal("10000.00"),
        reserved_amount=Decimal("0.00"),
        committed_amount=Decimal("0.00"),
        actual_amount=Decimal("0.00"),
        allow_overspend=False,
    )

    finance_user = User.objects.create_user(
        email="finance_overspend@hpe.com",
        password="Password123!",
        role=db_roles[Role.FINANCE_AP],
        organization=org,
    )
    requester = User.objects.create_user(
        email="req_overspend@hpe.com",
        password="Password123!",
        role=db_roles[Role.REQUESTER],
        organization=org,
        department=dept,
    )

    pr = PurchaseRequisition.objects.create(
        requester=requester,
        department=dept,
        cost_center=cc,
        title="Excess Cloud Capacity",
        justification="High load testing",
        status=PurchaseRequisition.STATUS_BUDGET_REVIEW,
        total_amount=Decimal("15000.00"),  # Exceeds 10,000 budget
        requested_delivery_date=now.date(),
    )

    return {
        "org": org,
        "dept": dept,
        "cc": cc,
        "budget": budget,
        "finance_user": finance_user,
        "requester": requester,
        "pr": pr,
    }


@pytest.mark.django_db
def test_budget_overspend_blocked_disables_approval_button(client, budget_guard_env):
    """
    When allow_overspend is False on Cost Center budget:
    - can_approve must be False
    - budget_overspend_blocked must be True
    - can_reject must remain True
    - Overspend Blocked button is displayed in HTML
    """
    env = budget_guard_env
    client.force_login(env["finance_user"])

    response = client.get(f"/requisitions/{env['pr'].id}/")
    assert response.status_code == 200
    assert response.context["budget_overspend_blocked"] is True
    assert response.context["can_approve"] is False
    assert response.context["can_reject"] is True

    content = response.content.decode()
    assert "Overspend Blocked" in content
    assert "Hard Budget Stop Active" in content
    assert "Reject Exception" in content


@pytest.mark.django_db
def test_budget_overspend_blocked_shows_clean_error_on_post(client, budget_guard_env):
    """
    Attempting to POST approve on a budget-blocked PR returns a clean error message
    without raw python bracket formatting.
    """
    env = budget_guard_env
    client.force_login(env["finance_user"])

    response = client.post(
        f"/requisitions/{env['pr'].id}/approve/",
        {"comments": "Attempting override"},
        follow=True,
    )
    assert response.status_code == 200
    messages = list(response.context["messages"])
    err_msgs = [str(m) for m in messages]
    assert any("Budget overspend is not permitted" in m for m in err_msgs)
    assert not any("['" in m or '["' in m for m in err_msgs)


@pytest.mark.django_db
def test_budget_overspend_reject_succeeds(client, budget_guard_env):
    """
    Clicking Reject Exception on a budget-blocked PR succeeds cleanly.
    """
    env = budget_guard_env
    client.force_login(env["finance_user"])

    response = client.post(
        f"/requisitions/{env['pr'].id}/reject/",
        {"comments": "Hard budget stop enforced. Please reduce amount."},
        follow=True,
    )
    assert response.status_code == 200
    env["pr"].refresh_from_db()
    assert env["pr"].status == PurchaseRequisition.STATUS_REJECTED


@pytest.mark.django_db
def test_budget_overspend_allowed_enables_approval_button(client, budget_guard_env):
    """
    When allow_overspend is True:
    - can_approve must be True
    - budget_overspend_blocked must be False
    - Approve Budget Exception succeeds
    """
    env = budget_guard_env
    env["budget"].allow_overspend = True
    env["budget"].save()

    client.force_login(env["finance_user"])
    response = client.get(f"/requisitions/{env['pr'].id}/")
    assert response.status_code == 200
    assert response.context["budget_overspend_blocked"] is False
    assert response.context["can_approve"] is True

    content = response.content.decode()
    assert "Approve Budget Exception" in content

    # Post approval succeeds
    approve_resp = client.post(
        f"/requisitions/{env['pr'].id}/approve/",
        {"comments": "Overrun justified by Finance."},
        follow=True,
    )
    assert approve_resp.status_code == 200
    env["pr"].refresh_from_db()
    assert env["pr"].status == PurchaseRequisition.STATUS_APPROVED

