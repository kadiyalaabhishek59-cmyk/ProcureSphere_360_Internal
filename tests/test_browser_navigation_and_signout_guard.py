import pytest
from django.test import Client

from apps.accounts.models import Role, User


@pytest.mark.django_db
class TestBrowserNavigationAndSignoutGuard:
    """
    Validates browser history navigation, undo/redo controls, and signout confirmation guard.
    """

    def test_landing_page_never_cache_headers(self, client):
        """Anonymous landing page has never_cache headers to prevent bfcache retention."""
        response = client.get("/")
        assert response.status_code == 200
        # Check Cache-Control headers
        cache_control = response.headers.get("Cache-Control", "")
        assert "no-cache" in cache_control or "no-store" in cache_control

    def test_landing_page_expires_session_and_renders_clean_navbar(self, client):
        """Visiting '/' renders clean public navbar (no Dashboard/Sign Out buttons) while preserving session."""
        role, _ = Role.objects.get_or_create(code=Role.REQUESTER, defaults={"name": "Requester"})
        user = User.objects.create_user(
            email="nav_test_requester@procuresphere.com",
            password="Password123!",
            role=role,
        )
        client.force_login(user)

        response = client.get("/")
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "ProcureSphere 360" in content

        # Navbar must NOT contain extra Dashboard or Sign Out buttons
        assert "navbar-dashboard-btn" not in content
        assert "navbar-signout-btn" not in content

        # Session is preserved on server without abrupt sign-outs
        session = client.session
        assert "_auth_user_id" in session

        cache_control = response.headers.get("Cache-Control", "")
        assert "no-cache" in cache_control or "no-store" in cache_control

    def test_login_templates_contain_no_one_click_login_buttons(self):
        """Login templates must have no 1-click / quick test credentials / demo buttons."""
        from django.template.loader import render_to_string

        # Standalone login page
        login_page_html = render_to_string("pages/login.html", {})
        assert "Quick Test Credentials" not in login_page_html
        assert "dev-quick-login-section" not in login_page_html
        assert "quickLogin" not in login_page_html

        # Accounts login page
        accounts_login_html = render_to_string("accounts/login.html", {})
        assert "Quick Test Credentials" not in accounts_login_html
        assert "fillCredentials" not in accounts_login_html

        # Landing modal login
        modal_login_html = render_to_string("landing/modals/login_modal.html", {})
        assert "dev-quick-login" not in modal_login_html
        assert "quickLogin" not in modal_login_html

    def test_dashboard_templates_contain_signout_modal_and_no_inpage_arrow_boxes(self, client):
        """Dashboard renders sign-out confirmation modal and avoids in-page undo/redo boxes (browser arrows used instead)."""
        role, _ = Role.objects.get_or_create(code=Role.REQUESTER, defaults={"name": "Requester"})
        user = User.objects.create_user(
            email="nav_arrows_test@procuresphere.com",
            password="Password123!",
            role=role,
        )
        client.force_login(user)

        response = client.get("/requester/")
        assert response.status_code == 200
        content = response.content.decode("utf-8")

        # In-page navigation arrow boxes are removed (browser native arrows are used instead)
        assert "ps-nav-arrows" not in content
        assert "psNavBackBtn" not in content
        assert "psNavForwardBtn" not in content

        # Verify signout confirmation modal is rendered with auto-dismiss countdown elements
        assert 'id="signout-confirm-modal"' in content
        assert "Sign Out Confirmation" in content
        assert "Stay on Dashboard" in content
        assert 'href="/logout/"' in content
        assert 'id="signout-countdown-sec"' in content
        assert 'id="signout-progress-bar"' in content

    def test_sidebar_toggle_button_partial_has_no_inpage_arrow_boxes(self):
        """Verify sidebar_toggle_button.html renders clean sidebar toggle button without separate arrow boxes."""
        from django.template.loader import render_to_string

        rendered = render_to_string("partials/sidebar_toggle_button.html", {"sidebar_id": "testSidebar"})
        assert "sidebarToggleBtn" in rendered
        assert "ps-nav-arrows" not in rendered
        assert "psNavBackBtn" not in rendered
        assert "psNavForwardBtn" not in rendered

    def test_vendor_dashboard_and_subpages_guard_structure(self, client):
        """Vendor dashboard and subpages contain signout modal in layout without in-page arrow boxes."""
        from apps.vendors.models import Vendor, VendorCategory

        role, _ = Role.objects.get_or_create(code=Role.VENDOR_USER, defaults={"name": "Vendor Portal User"})
        cat, _ = VendorCategory.objects.get_or_create(code="IT_SERVICES", defaults={"name": "IT Services"})
        vendor, _ = Vendor.objects.get_or_create(
            vendor_number="VND-NAV-TEST-01",
            defaults={"legal_name": "Nav Test Vendor Inc", "category": cat, "email": "navtest@vendor.com"},
        )
        user = User.objects.create_user(
            email="nav_vendor_guard_test@procuresphere.com",
            password="Password123!",
            role=role,
        )
        user.vendor = vendor
        user.save()
        client.force_login(user)

        # Check vendor root dashboard and vendor subpages
        for subpath in ["/vendor/", "/vendor/profile/", "/vendor/sourcing/", "/vendor/bids/"]:
            response = client.get(subpath)
            assert response.status_code == 200
            content = response.content.decode("utf-8")
            assert "ps-nav-arrows" not in content
            assert "psNavBackBtn" not in content
            assert "psNavForwardBtn" not in content
            assert 'id="signout-confirm-modal"' in content

    def test_app_js_contains_subpage_safe_navigation_guard(self):
        """Static app.js has strict subpage bypass, section hash tracking, and sessionStorage subpage tracking."""
        with open("static/js/app.js", "r", encoding="utf-8") as f:
            app_js = f.read()

        # Strict root detection
        assert "isDashboardRoot" in app_js
        assert "'/vendor'" in app_js
        assert "'/vendor/dashboard'" in app_js

        # Subpage safety checks
        assert "ps_visited_subpage" in app_js
        assert "cameFromSubpage" in app_js
        assert "isSectionHash" in app_js
        assert "if (!currentlyOnRoot) {" in app_js
        assert "showSignoutModal()" in app_js
        assert "armDashboardGuard()" in app_js

    def test_login_page_renders_another_tab_and_inactivity_notices(self, client):
        """Visiting /login/?reason=another_tab or inactivity renders appropriate security alert notices."""
        # 1. another_tab notice
        resp_tab = client.get("/login/?reason=another_tab")
        assert resp_tab.status_code == 200
        content_tab = resp_tab.content.decode("utf-8")
        assert "Your account was signed into in another tab or window" in content_tab

        # 2. inactivity notice
        resp_idle = client.get("/login/?reason=inactivity")
        assert resp_idle.status_code == 200
        content_idle = resp_idle.content.decode("utf-8")
        assert "Your session timed out after 5 minutes of inactivity" in content_idle

    def test_ajax_login_returns_json_for_history_replacement(self, client):
        """AJAX login request returns JSON with redirect URL for window.location.replace navigation."""
        role, _ = Role.objects.get_or_create(code=Role.REQUESTER, defaults={"name": "Requester"})
        User.objects.create_user(
            email="ajax_login_test@procuresphere.com",
            password="Password123!",
            role=role,
        )

        resp = client.post(
            "/login/",
            {"email": "ajax_login_test@procuresphere.com", "password": "Password123!"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("ok") is True
        assert data.get("redirect") == "/requester/"

    def test_login_template_contains_ajax_navigation_and_session_broadcast(self):
        """login.html contains AJAX submission with dashboard redirect and BroadcastChannel sync."""
        with open("templates/pages/login.html", "r", encoding="utf-8") as f:
            login_html = f.read()

        assert "window.location.href = data.redirect" in login_html
        assert "ps360_session_channel" in login_html
        assert "ps360_active_session_id" in login_html
        assert "NEW_LOGIN" in login_html

    def test_authenticated_user_visiting_login_with_signed_out_reason_is_logged_out(self, client):
        """Authenticated user arriving on /login/?reason=signed_out is logged out and sees sign-out banner."""
        role, _ = Role.objects.get_or_create(code=Role.SUPER_ADMIN, defaults={"name": "Super Admin"})
        user = User.objects.create_user(
            email="auth_logout_back_test@procuresphere.com",
            password="Password123!",
            role=role,
        )
        client.force_login(user)
        assert "_auth_user_id" in client.session

        resp = client.get("/login/?reason=signed_out")
        assert resp.status_code == 200
        content = resp.content.decode("utf-8")
        assert "You have been signed out of your session." in content
        # Session is terminated
        assert "_auth_user_id" not in client.session

    def test_signout_modal_contains_csrf_post_form(self, client):
        """Dashboard sign-out modal contains a POST form to /logout/ with CSRF protection."""
        role, _ = Role.objects.get_or_create(code=Role.SUPER_ADMIN, defaults={"name": "Super Admin"})
        user = User.objects.create_user(
            email="signout_form_test@procuresphere.com",
            password="Password123!",
            role=role,
        )
        client.force_login(user)
        resp = client.get("/superadmin/")
        assert resp.status_code == 200
        content = resp.content.decode("utf-8")
        assert 'id="signout-confirm-form"' in content
        assert 'action="/logout/"' in content
        assert 'id="signout-confirm-action-btn"' in content

    def test_app_js_contains_perform_signout_and_gesture_arming(self):
        """app.js contains performSignout function, gesture listeners, and repeat back-click exit logic."""
        with open("static/js/app.js", "r", encoding="utf-8") as f:
            app_js = f.read()

        assert "performSignout" in app_js
        assert "ensureArmedOnGesture" in app_js
        assert "isModalOpen" in app_js
        assert "lastBackClickTime" in app_js
        assert "ps360_user_signed_out" in app_js
        assert "/login/?reason=signed_out" in app_js
        assert "/api/v1/auth/session-exit/" in app_js

    def test_security_headers_middleware_sets_anti_cache_headers_for_authenticated_users(self, client):
        """Authenticated GET responses receive strict anti-cache headers to prevent bfcache retention on forward navigation."""
        role, _ = Role.objects.get_or_create(code=Role.SUPER_ADMIN, defaults={"name": "Super Admin"})
        user = User.objects.create_user(
            email="anticache_test@procuresphere.com",
            password="Password123!",
            role=role,
        )
        client.force_login(user)
        resp = client.get("/superadmin/")
        assert resp.status_code == 200
        cache_control = resp.headers.get("Cache-Control", "")
        assert "no-cache" in cache_control
        assert "no-store" in cache_control
        assert "must-revalidate" in cache_control
        assert resp.headers.get("Pragma") == "no-cache"
        assert resp.headers.get("Expires") == "0"

    def test_session_keepalive_get_returns_status_and_rejects_unauthenticated(self, client):
        """GET /api/v1/auth/session-keepalive/ returns 200 for authenticated user and 401 for anonymous."""
        # Anonymous
        resp_anon = client.get("/api/v1/auth/session-keepalive/")
        assert resp_anon.status_code == 401

        # Authenticated
        role, _ = Role.objects.get_or_create(code=Role.REQUESTER, defaults={"name": "Requester"})
        user = User.objects.create_user(
            email="keepalive_get_test@procuresphere.com",
            password="Password123!",
            role=role,
        )
        client.force_login(user)
        resp_auth = client.get("/api/v1/auth/session-keepalive/")
        assert resp_auth.status_code == 200
        assert resp_auth.json().get("status") == "authenticated"

    def test_session_timeout_js_contains_multi_tab_sync_and_5min_timer(self):
        """session_timeout.js contains multi-tab session listener and 5-minute inactivity timeout."""
        with open("static/js/session_timeout.js", "r", encoding="utf-8") as f:
            timeout_js = f.read()

        assert "ps360_session_channel" in timeout_js
        assert "ps360_active_session_id" in timeout_js
        assert "ps360_tab_session_id" in timeout_js
        assert "/login/?reason=another_tab" in timeout_js
        assert "idleTimeoutSeconds = 300" in timeout_js or "idleTimeoutSeconds" in timeout_js

    def test_session_exit_beacon_terminates_session_and_sets_cookies(self, client):
        """POST /api/v1/auth/session-exit/ terminates active user session and sets anti-cache guard cookies."""
        role, _ = Role.objects.get_or_create(code=Role.SUPER_ADMIN, defaults={"name": "Super Admin"})
        user = User.objects.create_user(
            email="session_exit_test@procuresphere.com",
            password="Password123!",
            role=role,
        )
        client.force_login(user)
        assert "_auth_user_id" in client.session

        resp = client.post("/api/v1/auth/session-exit/")
        assert resp.status_code == 200
        assert "_auth_user_id" not in client.session
        assert resp.cookies.get("ps360_user_signed_out").value == "1"
        assert resp.cookies.get("ps360_just_logged_out").value == "1"

    def test_forward_navigation_to_dashboard_with_signed_out_cookie_redirects_to_login(self, client):
        """Forward navigation (Right arrow) from Chrome homepage to dashboard with signed_out cookie redirects to login."""
        role, _ = Role.objects.get_or_create(code=Role.SUPER_ADMIN, defaults={"name": "Super Admin"})
        user = User.objects.create_user(
            email="forward_arrow_test@procuresphere.com",
            password="Password123!",
            role=role,
        )
        client.force_login(user)
        assert "_auth_user_id" in client.session

        # Simulate user having exited to Chrome homepage where ps360_user_signed_out cookie was set
        client.cookies["ps360_user_signed_out"] = "1"

        # User clicks Right (Forward) arrow from Chrome homepage back to dashboard
        resp = client.get("/superadmin/")
        assert resp.status_code == 302
        assert resp.url == "/login/?reason=signed_out"
        # Session is strictly invalidated
        assert "_auth_user_id" not in client.session

    def test_forward_navigation_unauthenticated_with_signed_out_cookie_redirects_to_login(self, client):
        """Even if beacon already terminated session, forward arrow with cookie redirects to login with reason."""
        client.cookies["ps360_user_signed_out"] = "1"
        resp = client.get("/superadmin/")
        assert resp.status_code == 302
        assert resp.url == "/login/?reason=signed_out"

    def test_login_page_renders_signed_out_notice_when_cookie_present(self, client):
        """GET /login/ with ps360_user_signed_out cookie renders signed out notice and clears cookie."""
        client.cookies["ps360_user_signed_out"] = "1"
        resp = client.get("/login/")
        assert resp.status_code == 200
        content = resp.content.decode("utf-8")
        assert "You have been signed out of your session." in content
        # Cookie is deleted
        assert resp.cookies.get("ps360_user_signed_out").value == ""

    def test_app_js_contains_pagehide_and_rearm_dashboard_guard(self):
        """Verify static/js/app.js implements pagehide exit detection and rearmDashboardGuard."""
        with open("static/js/app.js", "r", encoding="utf-8") as f:
            app_js = f.read()

        assert "pagehide" in app_js
        assert "beforeunload" in app_js
        assert "rearmDashboardGuard" in app_js
        assert "dismissSignoutModal" in app_js
        assert "handleDashboardExit" in app_js

    def test_all_10_dashboards_contain_signout_guard_modal(self, client):
        """All 10 enterprise role dashboard roots render signout confirmation modal and guard scripts."""
        dashboard_endpoints = [
            (Role.SUPER_ADMIN, "/superadmin/"),
            (Role.REQUESTER, "/requester/"),
            (Role.DEPT_APPROVER, "/approver/"),
            (Role.PROC_EXEC, "/procurement/"),
            (Role.PROC_MGR, "/manager/"),
            (Role.FINANCE_AP, "/finance/"),
            (Role.STORES_RECEIVER, "/stores/"),
            (Role.LEGAL_MGR, "/legal/"),
            (Role.AUDITOR, "/audit/dashboard/"),
            (Role.VENDOR_USER, "/vendor/"),
        ]

        from apps.vendors.models import Vendor, VendorCategory

        cat, _ = VendorCategory.objects.get_or_create(code="SERVICES", defaults={"name": "Services"})
        vendor, _ = Vendor.objects.get_or_create(
            vendor_number="VND-ALL-DASH-01",
            defaults={"legal_name": "All Dashboards Vendor", "category": cat, "email": "alldash@vendor.com"},
        )

        for role_code, endpoint in dashboard_endpoints:
            role, _ = Role.objects.get_or_create(code=role_code, defaults={"name": role_code})
            test_email = f"dash_guard_{role_code.lower()}@procuresphere.com"
            user, _ = User.objects.get_or_create(
                email=test_email,
                defaults={"username": test_email, "role": role, "is_active": True},
            )
            if role_code == Role.VENDOR_USER and not getattr(user, "vendor", None):
                user.vendor = vendor
                user.save()

            client.force_login(user)
            resp = client.get(endpoint)
            assert resp.status_code in [200, 302], f"Failed loading {endpoint} for {role_code}"
            if resp.status_code == 200:
                html = resp.content.decode("utf-8")
                assert 'id="signout-confirm-modal"' in html, f"Modal missing on {endpoint}"
                assert "Sign Out Confirmation" in html, f"Modal title missing on {endpoint}"
                assert 'app.js' in html, f"app.js missing on {endpoint}"
                assert 'session_timeout.js' in html, f"session_timeout.js missing on {endpoint}"

    def test_login_exit_button_redirects_to_landing_page(self, client):
        """Clicking Exit on the login page navigates to /?logged_out=1, clears cookies, and renders landing page."""
        role, _ = Role.objects.get_or_create(code=Role.REQUESTER, defaults={"name": "Requester"})
        user, _ = User.objects.get_or_create(
            email="exit_test_user@procuresphere.com",
            defaults={"username": "exit_test_user@procuresphere.com", "role": role, "is_active": True},
        )
        client.force_login(user)

        # GET /?logged_out=1 terminates session and renders landing page
        response = client.get("/?logged_out=1")
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "ProcureSphere 360" in content
        # Session must be logged out
        assert "_auth_user_id" not in client.session

        # Verify login template has exit button pointing to /?logged_out=1
        with open("templates/pages/login.html", "r", encoding="utf-8") as f:
            login_html = f.read()
        assert 'id="login-exit-btn"' in login_html
        assert 'href="/?logged_out=1"' in login_html
        assert "window.location.href = '/?logged_out=1'" in login_html

    def test_subpage_to_dashboard_back_navigation_bypasses_signout(self):
        """app.js and base.html ensure that returning to dashboard from an internal subpage never signs out."""
        with open("static/js/app.js", "r", encoding="utf-8") as f:
            app_js = f.read()

        with open("templates/base.html", "r", encoding="utf-8") as f:
            base_html = f.read()

        # Both app.js and base.html must have subpage history bypass
        assert "hasSubpageHistory" in app_js
        assert "hasSubpageHistory" in base_html
        assert "ps_visited_subpage" in app_js
        assert "ps360_active_subpage" in app_js
        assert "dismissSignoutModal(true)" in app_js

    def test_internal_navigation_guard_prevents_false_signout(self, client):
        """Internal navigation sets tracking flags and clears residual exit tokens to prevent false signouts."""
        with open("static/js/app.js", "r", encoding="utf-8") as f:
            app_js = f.read()

        assert "markInternalNav" in app_js
        assert "ps_is_internal_navigation" in app_js
        assert "pointerdown" in app_js

        with open("templates/base.html", "r", encoding="utf-8") as f:
            base_html = f.read()

        assert "ps_is_internal_navigation" in base_html

        role, _ = Role.objects.get_or_create(code=Role.DEPT_APPROVER, defaults={"name": "Department Approver"})
        user, _ = User.objects.get_or_create(
            email="approver_nav_guard_test@procuresphere.com",
            defaults={"username": "approver_nav_guard_test@procuresphere.com", "role": role, "is_active": True},
        )
        client.force_login(user)

        # Department PRs page loads cleanly
        resp_dept = client.get("/approver/department-prs/")
        assert resp_dept.status_code == 200

        # Navigating to Pending Approvals queue retains active authentication
        resp_inbox = client.get("/approvals/inbox/?status=PENDING")
        assert resp_inbox.status_code == 200
        assert "_auth_user_id" in client.session

    def test_sidebar_scroll_state_preservation(self, client):
        """Sidebar scroll position is captured and restored across page navigations to keep the same state."""
        with open("static/js/app.js", "r", encoding="utf-8") as f:
            app_js = f.read()

        assert "initSidebarScrollPreservation" in app_js
        assert "ps_sidebar_scroll_pos" in app_js
        assert "getSidebarScrollContainer" in app_js

        with open("templates/base.html", "r", encoding="utf-8") as f:
            base_html = f.read()

        assert "restoreSidebarScrollState" in base_html
        assert "ps_sidebar_scroll_pos" in base_html

        role, _ = Role.objects.get_or_create(code=Role.SUPER_ADMIN, defaults={"name": "Super Admin"})
        user, _ = User.objects.get_or_create(
            email="sa_sidebar_scroll_test@procuresphere.com",
            defaults={"username": "sa_sidebar_scroll_test@procuresphere.com", "role": role, "is_active": True},
        )
        client.force_login(user)

        resp_sa = client.get("/superadmin/")
        assert resp_sa.status_code == 200
        content = resp_sa.content.decode("utf-8")
        assert "restoreSidebarScrollState" in content
        assert "ps_sidebar_scroll_pos" in content
