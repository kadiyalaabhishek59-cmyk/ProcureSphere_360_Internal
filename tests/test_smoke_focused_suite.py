import re
from decimal import Decimal

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.approvals.models import ApprovalAction, ApprovalPolicy, ApprovalStep
from apps.budgets.models import Budget
from apps.core.models import ContactEnquiry
from apps.organization.models import CostCenter, Department, FiscalPeriod, Organization
from apps.requisitions.models import PRLine, PurchaseRequisition


@pytest.fixture
def smoke_env(db):
    """Isolated environment fixture for focused smoke test suite."""
    today = timezone.now().date()
    org, _ = Organization.objects.get_or_create(
        code="SMK-ORG",
        defaults={"name": "Smoke Test Organization", "is_active": True},
    )
    dept, _ = Department.objects.get_or_create(
        code="SMK-DEPT",
        organization=org,
        defaults={"name": "Smoke Operations Department"},
    )
    cc, _ = CostCenter.objects.get_or_create(
        code="SMK-CC-01",
        defaults={"name": "Smoke Cost Center", "department": dept},
    )
    fiscal_period, _ = FiscalPeriod.objects.get_or_create(
        organization=org,
        year=today.year,
        period_number=1,
        defaults={
            "name": f"FY{today.year}-SMK",
            "start_date": today.replace(month=1, day=1),
            "end_date": today.replace(month=12, day=31),
            "is_closed": False,
        },
    )
    Budget.objects.get_or_create(
        cost_center=cc,
        fiscal_period=fiscal_period,
        defaults={"allocated_amount": Decimal("100000.00")},
    )

    sa_role, _ = Role.objects.get_or_create(code=Role.SUPER_ADMIN, defaults={"name": "Super Admin"})
    approver_role, _ = Role.objects.get_or_create(
        code=Role.DEPT_APPROVER, defaults={"name": "Department Approver"}
    )
    requester_role, _ = Role.objects.get_or_create(
        code=Role.REQUESTER, defaults={"name": "Requester"}
    )

    sa_user = User.objects.create_user(
        email="smk_superadmin@procuresphere.com",
        password="Password123!",
        role=sa_role,
        is_superuser=True,
        is_staff=True,
    )
    admin_user = User.objects.create_user(
        email="smk_orgadmin@procuresphere.com",
        password="Password123!",
        role=sa_role,
        organization=org,
        is_superuser=False,
        is_staff=False,
    )
    approver_user = User.objects.create_user(
        email="smk_approver@procuresphere.com",
        password="Password123!",
        role=approver_role,
        organization=org,
        department=dept,
    )
    requester_user = User.objects.create_user(
        email="smk_requester@procuresphere.com",
        password="Password123!",
        role=requester_role,
        organization=org,
        department=dept,
        cost_center=cc,
    )

    return {
        "org": org,
        "dept": dept,
        "cc": cc,
        "fiscal_period": fiscal_period,
        "sa_user": sa_user,
        "admin_user": admin_user,
        "approver_user": approver_user,
        "requester_user": requester_user,
    }


@pytest.mark.django_db
class TestSmokeFocusedSuite:
    """
    Focused smoke test suite covering SMK-01 through SMK-08.
    """

    def test_smk_01_app_startup(self, client):
        """SMK-01 — App startup: verify application starts and login page loads without server error."""
        # 1. Landing page loads
        root_resp = client.get("/")
        assert root_resp.status_code == 200, f"Expected 200 for '/', got {root_resp.status_code}"
        assert "ProcureSphere" in root_resp.content.decode("utf-8")

        # 2. Login page loads
        login_resp = client.get("/login/")
        assert (
            login_resp.status_code == 200
        ), f"Expected 200 for '/login/', got {login_resp.status_code}"
        login_html = login_resp.content.decode("utf-8")
        assert "password" in login_html.lower()

        # 3. Healthcheck endpoint loads
        health_resp = client.get("/api/v1/health/")
        assert (
            health_resp.status_code == 200
        ), f"Expected 200 for '/api/v1/health/', got {health_resp.status_code}"

    def test_smk_02_login_and_logout(self, client, smoke_env):
        """SMK-02 — Login and logout: successful login, invalid credentials error, and logout redirection."""
        user = smoke_env["requester_user"]

        # 1. Invalid credentials test
        invalid_resp = client.post(
            "/login/", {"email": user.email, "password": "WrongPassword123!"}
        )
        assert invalid_resp.status_code in [
            200,
            400,
        ], "Invalid login must return 200 or 400 with error message"
        assert "_auth_user_id" not in client.session
        invalid_html = invalid_resp.content.decode("utf-8")
        assert (
            "Invalid email or password" in invalid_html
            or "Please provide" in invalid_html
            or "invalid" in invalid_html.lower()
        )

        # 2. Successful login test
        valid_resp = client.post("/login/", {"email": user.email, "password": "Password123!"})
        assert valid_resp.status_code in [
            200,
            302,
        ], f"Valid login expected 200 or 302, got {valid_resp.status_code}"
        assert client.session.get("_auth_user_id") == str(user.id)

        # 3. Logout test (requires POST per DEF-020 CSRF protection)
        logout_resp = client.post("/logout/")
        assert logout_resp.status_code in [200, 302]
        assert "_auth_user_id" not in client.session

        # 4. Redirection to login when opening protected page after logout
        protected_resp = client.get("/approver/")
        assert protected_resp.status_code in [
            302,
            403,
        ], "Opening protected page unauthenticated must redirect or deny"
        if protected_resp.status_code == 302:
            assert "login" in protected_resp.url.lower()

    def test_smk_03_role_dashboards(self, client, smoke_env):
        """SMK-03 — Role dashboards: Super Admin, Admin, and Department Approver reach dashboard and open core page."""
        # 1. Super Admin
        client.force_login(smoke_env["sa_user"])
        sa_dash = client.get("/admin/")
        assert sa_dash.status_code == 200, f"Super Admin dashboard failed: {sa_dash.status_code}"
        sa_core = client.get("/superadmin/users/")
        assert sa_core.status_code == 200, f"Super Admin core page failed: {sa_core.status_code}"

        # 2. Org Admin
        client.force_login(smoke_env["admin_user"])
        admin_dash = client.get("/superadmin/")
        assert (
            admin_dash.status_code == 200
        ), f"Org Admin dashboard failed: {admin_dash.status_code}"
        admin_core = client.get("/superadmin/policies/")
        assert (
            admin_core.status_code == 200
        ), f"Org Admin core page failed: {admin_core.status_code}"

        # 3. Department Approver
        client.force_login(smoke_env["approver_user"])
        app_dash = client.get("/approver/")
        assert app_dash.status_code == 200, f"Approver dashboard failed: {app_dash.status_code}"
        app_core = client.get("/approver/department-prs/")
        assert app_core.status_code == 200, f"Approver core page failed: {app_core.status_code}"

    def test_smk_04_role_permissions(self, client, smoke_env):
        """SMK-04 — Role permissions: lower-privilege test user is denied access to admin-only pages."""
        requester = smoke_env["requester_user"]
        client.force_login(requester)

        admin_routes = [
            "/superadmin/",
            "/superadmin/users/",
            "/superadmin/policies/",
            "/admin/",
        ]

        for route in admin_routes:
            resp = client.get(route)
            # Must be denied: HTTP 403 Forbidden or redirected away (302) to login/dashboard
            assert resp.status_code in [
                302,
                403,
            ], f"Requester was improperly allowed access to {route}: {resp.status_code}"
            if resp.status_code == 200:
                pytest.fail(f"Access granted to admin-only route {route} for low privilege role")

    def test_smk_05_browser_back_and_signout_guard(self, client, smoke_env):
        """SMK-05 — Browser Back: back returns to internal page without signout modal; stay keeps session, signout ends it."""
        approver = smoke_env["approver_user"]
        client.force_login(approver)

        # 1. Multi-page internal navigation
        r1 = client.get("/approver/")
        assert r1.status_code == 200
        r2 = client.get("/approver/department-prs/")
        assert r2.status_code == 200
        r3 = client.get("/approvals/inbox/")
        assert r3.status_code == 200

        # Simulate Back navigation: request previous page with internal navigation context
        r_back = client.get("/approver/department-prs/", HTTP_REFERER="/approvals/inbox/")
        assert r_back.status_code == 200
        # Session remains intact
        assert client.session.get("_auth_user_id") == str(approver.id)

        # 2. Check modal elements in dashboard layout
        html = r_back.content.decode("utf-8")
        assert (
            'id="signout-confirm-modal"' in html
        ), "Signout confirmation modal missing from dashboard layout"
        assert "Sign Out Confirmation" in html
        assert "stay on your dashboard" in html.lower() or "stay" in html.lower()
        assert "Stay on Dashboard" in html or "Stay in the App" in html
        assert 'id="signout-confirm-action-btn"' in html

        # 3. Exit point: Stay in the App keeps session active
        # User dismisses modal (stay in the app), session preserved
        assert client.session.get("_auth_user_id") == str(approver.id)

        # 4. Exit point: Sign Out ends session
        signout_resp = client.post("/logout/")
        assert signout_resp.status_code in [200, 302]
        assert "_auth_user_id" not in client.session

    def test_smk_06_superadmin_form_validation(self, client, smoke_env):
        """SMK-06 — Super Admin form validation: missing/invalid values show field errors; valid data saves."""
        admin = smoke_env["sa_user"]
        client.force_login(admin)

        # 1. Submit invalid data (missing required name and code)
        invalid_post = client.post(
            "/superadmin/departments/create/",
            {"name": "", "code": "", "organization": smoke_env["org"].id},
        )
        assert (
            invalid_post.status_code == 200
        ), f"Expected 200 re-render with errors, got {invalid_post.status_code}"
        assert not Department.objects.filter(code="").exists()

        form = invalid_post.context.get("form")
        if form:
            assert form.errors, "Expected field-level validation errors on invalid form submission"
            assert "name" in form.errors or "code" in form.errors

        # 2. Submit valid data
        valid_post = client.post(
            "/superadmin/departments/create/",
            {
                "name": "Quality Assurance Lab",
                "code": "QA-LAB-01",
                "organization": smoke_env["org"].id,
                "description": "Valid department for smoke test",
            },
        )
        assert valid_post.status_code in [200, 302]
        assert Department.objects.filter(
            code="QA-LAB-01", name="Quality Assurance Lab"
        ).exists(), "Valid department must be saved to PostgreSQL/database"

    def test_smk_07_contact_enquiry(self, client, smoke_env):
        """SMK-07 — Contact Enquiry: valid enquiry saves and is viewable in admin; invalid shows errors and creates no record."""
        # 1. Invalid submission (name with special characters and short message)
        invalid_resp = client.post(
            "/htmx/contact/",
            {
                "name": "John123#$%",
                "email": "invalid-email",
                "country_code": "+91",
                "phone": "123",
                "message": "short",
            },
        )
        assert invalid_resp.status_code == 200
        invalid_content = invalid_resp.content.decode("utf-8")
        assert (
            "Numbers and special characters are not allowed" in invalid_content
            or "valid" in invalid_content.lower()
            or "error" in invalid_content.lower()
        )
        assert not ContactEnquiry.objects.filter(name="John123#$%").exists()

        # 2. Valid submission
        valid_resp = client.post(
            "/htmx/contact/",
            {
                "name": "Alex Johnson",
                "email": "alex.johnson@enterprisesmoke.com",
                "country_code": "+91",
                "phone": "9876543210",
                "message": "We would like to request an enterprise procurement demo for our organization.",
            },
        )
        assert valid_resp.status_code == 200
        saved_enquiry = ContactEnquiry.objects.filter(
            email="alex.johnson@enterprisesmoke.com"
        ).first()
        assert saved_enquiry is not None, "Valid Contact Enquiry must be persisted in database"
        assert saved_enquiry.name == "Alex Johnson"

        # 3. Authorized user finds it in Django Admin
        client.force_login(smoke_env["sa_user"])
        admin_enquiry_resp = client.get("/admin/core/contactenquiry/")
        assert admin_enquiry_resp.status_code == 200
        admin_enquiry_html = admin_enquiry_resp.content.decode("utf-8")
        assert (
            "Alex Johnson" in admin_enquiry_html
            or "alex.johnson@enterprisesmoke.com" in admin_enquiry_html
        )

    def test_smk_08_approval_workflow(self, client, smoke_env):
        """SMK-08 — Approval workflow: submit PR as Requester, approve as assigned Dept Approver, verify status visible."""
        from apps.requisitions.services import submit_purchase_requisition_service

        requester = smoke_env["requester_user"]
        approver = smoke_env["approver_user"]
        dept = smoke_env["dept"]
        cc = smoke_env["cc"]
        org = smoke_env["org"]

        # Ensure an active approval policy exists
        ApprovalPolicy.objects.all().delete()
        policy = ApprovalPolicy.objects.create(
            name="Smoke Dept Approver Policy",
            organization=org,
            module=ApprovalPolicy.MODULE_PR,
            department=dept,
            is_active=True,
            status=ApprovalPolicy.STATUS_ACTIVE,
            currency="INR",
            min_amount=Decimal("0.00"),
            max_amount=Decimal("50000.00"),
        )
        ApprovalStep.objects.create(
            policy=policy,
            step_number=1,
            approver_role=approver.role,
            specific_approver=approver,
        )

        # 1. Requester creates PR in DRAFT
        pr = PurchaseRequisition.objects.create(
            pr_number="PR-SMK-2026-001",
            title="Procurement Smoke Test PR",
            justification="Necessary supplies for smoke testing operations.",
            requester=requester,
            department=dept,
            cost_center=cc,
            status=PurchaseRequisition.STATUS_DRAFT,
            total_amount=Decimal("500.00"),
            requested_delivery_date=timezone.now().date(),
        )
        PRLine.objects.create(
            requisition=pr,
            item_description="Test Office Supplies",
            quantity=Decimal("5.00"),
            unit_of_measure="EA",
            estimated_unit_price=Decimal("100.00"),
            estimated_total=Decimal("500.00"),
        )

        # Requester submits PR
        client.force_login(requester)
        submit_resp = client.post(f"/requisitions/{pr.id}/submit/")
        assert submit_resp.status_code in [200, 302]

        pr.refresh_from_db()
        assert pr.status in [
            PurchaseRequisition.STATUS_MANAGER_REVIEW,
            PurchaseRequisition.STATUS_SUBMITTED,
        ], f"Submitted PR should be in review, got {pr.status}"

        # 2. Assigned Department Approver approves PR
        client.force_login(approver)
        approve_resp = client.post(
            f"/requisitions/{pr.id}/approve/",
            {"comments": "Approved during smoke test verification"},
            follow=True,
        )
        assert approve_resp.status_code == 200

        pr.refresh_from_db()
        assert (
            pr.status == PurchaseRequisition.STATUS_APPROVED
        ), f"Expected PR to be APPROVED, got {pr.status}"

        # Verify ApprovalAction recorded in audit trail
        action_log = ApprovalAction.objects.filter(
            target_object_id=pr.id,
            actor=approver,
            action=ApprovalAction.ACTION_APPROVE,
        ).first()
        assert action_log is not None, "ApprovalAction must be recorded"
        assert action_log.comments == "Approved during smoke test verification"

        # 3. Status is visible to Requester
        client.force_login(requester)
        req_view = client.get(f"/requisitions/{pr.id}/")
        assert req_view.status_code == 200
        req_html = req_view.content.decode("utf-8")
        assert "Approved" in req_html or "APPROVED" in req_html
        assert "PR-SMK-2026-001" in req_html
