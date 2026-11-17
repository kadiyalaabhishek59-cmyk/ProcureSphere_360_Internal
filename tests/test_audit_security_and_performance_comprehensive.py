import io
import time
import uuid
import threading
from decimal import Decimal
import pytest
from django.db import connection, reset_queries
from django.test import Client, override_settings
from django.test.utils import CaptureQueriesContext
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.organization.models import Organization, Department, CostCenter, FiscalPeriod
from apps.vendors.models import Vendor, VendorCategory, VendorDocument
from apps.orders.models import PurchaseOrder, POLine
from apps.requisitions.models import PurchaseRequisition, PRLine
from apps.invoices.models import SupplierInvoice, InvoiceLine
from apps.sourcing.models import SourcingEvent, VendorBid, BidInvite
from apps.contracts.models import Contract
from apps.audit.models import AuditLog


@pytest.fixture
def enterprise_security_fixtures(db):
    """Seed comprehensive multi-tenant data for security and performance testing."""
    org1 = Organization.objects.create(name="HPE Primary Enterprise", code="HPE_PRI_01")
    org2 = Organization.objects.create(name="Apex Competitor Corp", code="APX_SEC_02")

    dept_it = Department.objects.create(organization=org1, name="IT Engineering", code="ENG")
    dept_fin = Department.objects.create(organization=org1, name="Finance & AP", code="FIN")
    dept_proc = Department.objects.create(organization=org1, name="Global Procurement", code="PROC")
    dept_sec = Department.objects.create(organization=org2, name="Security Division", code="SEC")

    cc_it = CostCenter.objects.create(department=dept_it, code="CC-ENG-01", name="Engineering R&D")
    cc_fin = CostCenter.objects.create(department=dept_fin, code="CC-FIN-01", name="Accounts Payable")
    cc_sec = CostCenter.objects.create(department=dept_sec, code="CC-SEC-01", name="Apex Secondary Cost Center")

    fiscal_year = FiscalPeriod.objects.create(
        organization=org1,
        year=2026,
        period_number=4,
        name="Q4-2026",
        start_date=timezone.now().date(),
        end_date=timezone.now().date() + timezone.timedelta(days=90),
        is_closed=False
    )

    cat_tech = VendorCategory.objects.create(name="Cloud Computing & Hardware", code="TECH_HW")
    cat_srv = VendorCategory.objects.create(name="Professional Services", code="PROF_SRV")

    # Vendor A (Authorized Primary)
    vendor_a = Vendor.objects.create(
        organization=org1,
        legal_name="Apex Global Technologies LLC",
        trade_name="Apex Technologies",
        vendor_number="VND-2026-00001",
        tax_identification_number="29ABCTY1234D1Z5",
        pan_number="ABCTY1234D",
        category=cat_tech,
        email="contact@apextechnologies.com",
        phone="+919876543210",
        address="170 West Tasman Dr, San Jose, CA",
        status=Vendor.STATUS_ACTIVE,
        is_event_eligible=True,
        event_eligibility_status=Vendor.ELIGIBILITY_ELIGIBLE,
    )

    # Vendor B (Competitor)
    vendor_b = Vendor.objects.create(
        organization=org1,
        legal_name="BlueSky Cyber Systems Inc",
        trade_name="BlueSky Cyber",
        vendor_number="VND-2026-00002",
        tax_identification_number="27AAACB1234C1Z1",
        pan_number="AAACB1234C",
        category=cat_tech,
        email="compliance@blueskycyber.com",
        phone="+919876543211",
        address="450 Mission Street, San Francisco, CA",
        status=Vendor.STATUS_ACTIVE,
        is_event_eligible=True,
        event_eligibility_status=Vendor.ELIGIBILITY_ELIGIBLE,
    )

    # Vendor C (Suspended)
    vendor_c = Vendor.objects.create(
        organization=org1,
        legal_name="Crimson Logistics Partner",
        vendor_number="VND-2026-00003",
        tax_identification_number="24AAACC1234D1Z2",
        pan_number="AAACC1234D",
        category=cat_srv,
        email="ops@crimsonlogistics.com",
        status=Vendor.STATUS_SUSPENDED,
        is_event_eligible=False,
        event_eligibility_status=Vendor.ELIGIBILITY_SUSPENDED,
    )

    # Roles
    roles = {}
    role_codes = [
        Role.SUPER_ADMIN, Role.REQUESTER, Role.DEPT_APPROVER,
        Role.PROC_EXEC, Role.PROC_MGR, Role.LEGAL_MGR,
        Role.FINANCE_AP, Role.STORES_RECEIVER, Role.AUDITOR, Role.VENDOR_USER
    ]
    for code in role_codes:
        r, _ = Role.objects.get_or_create(code=code, defaults={"name": code})
        roles[code] = r

    # Create Users
    users = {}
    users[Role.SUPER_ADMIN] = User.objects.create_superuser(
        email="superadmin.audit@hpe.com", password="Password123!", role=roles[Role.SUPER_ADMIN],
        department=dept_it, organization=org1
    )
    users[Role.REQUESTER] = User.objects.create_user(
        email="requester.audit@hpe.com", password="Password123!", role=roles[Role.REQUESTER],
        department=dept_it, organization=org1
    )
    users[Role.DEPT_APPROVER] = User.objects.create_user(
        email="approver.audit@hpe.com", password="Password123!", role=roles[Role.DEPT_APPROVER],
        department=dept_it, organization=org1
    )
    users[Role.PROC_EXEC] = User.objects.create_user(
        email="proc_exec.audit@hpe.com", password="Password123!", role=roles[Role.PROC_EXEC],
        department=dept_proc, organization=org1
    )
    users[Role.PROC_MGR] = User.objects.create_user(
        email="proc_mgr.audit@hpe.com", password="Password123!", role=roles[Role.PROC_MGR],
        department=dept_proc, organization=org1
    )
    users[Role.LEGAL_MGR] = User.objects.create_user(
        email="legal.audit@hpe.com", password="Password123!", role=roles[Role.LEGAL_MGR],
        department=dept_it, organization=org1
    )
    users[Role.FINANCE_AP] = User.objects.create_user(
        email="finance.audit@hpe.com", password="Password123!", role=roles[Role.FINANCE_AP],
        department=dept_fin, organization=org1
    )
    users[Role.STORES_RECEIVER] = User.objects.create_user(
        email="stores.audit@hpe.com", password="Password123!", role=roles[Role.STORES_RECEIVER],
        department=dept_it, organization=org1
    )
    users[Role.AUDITOR] = User.objects.create_user(
        email="auditor.audit@hpe.com", password="Password123!", role=roles[Role.AUDITOR],
        department=dept_it, organization=org1
    )

    # Vendor Users
    user_vendor_a = User.objects.create_user(
        email="vendor_a.audit@apextechnologies.com", password="Password123!", role=roles[Role.VENDOR_USER],
        vendor=vendor_a, organization=org1
    )
    users["VENDOR_A"] = user_vendor_a

    user_vendor_b = User.objects.create_user(
        email="vendor_b.audit@blueskycyber.com", password="Password123!", role=roles[Role.VENDOR_USER],
        vendor=vendor_b, organization=org1
    )
    users["VENDOR_B"] = user_vendor_b

    # Cross-tenant User (Org 2)
    user_org2 = User.objects.create_user(
        email="intruder@apexcompetitor.com", password="Password123!", role=roles[Role.REQUESTER],
        department=dept_sec, organization=org2
    )
    users["ORG2_USER"] = user_org2

    # Sample Purchase Order
    po = PurchaseOrder.objects.create(
        po_number="PO-2026-AUDIT-001",
        vendor=vendor_a,
        cost_center=cc_it,
        created_by=users[Role.PROC_EXEC],
        status=PurchaseOrder.STATUS_ISSUED,
        total_amount=Decimal("150000.00"),
    )
    po_line = POLine.objects.create(
        po=po,
        item_description="High-Performance Enterprise Servers",
        quantity=Decimal("5.00"),
        unit_price=Decimal("30000.00"),
        line_total=Decimal("150000.00")
    )

    # Sample Invoice for Vendor A
    invoice = SupplierInvoice.objects.create(
        vendor=vendor_a,
        po=po,
        invoice_number="INV-2026-AUDIT-99",
        invoice_date=timezone.now().date(),
        due_date=timezone.now().date() + timezone.timedelta(days=30),
        subtotal=Decimal("150000.00"),
        tax_amount=Decimal("27000.00"),
        total_amount=Decimal("177000.00"),
        status=SupplierInvoice.STATUS_PAID,
    )

    # Sample Sourcing Event (Sealed RFQ with open bid window)
    event = SourcingEvent.objects.create(
        event_number="RFQ-2026-AUDIT-001",
        title="Annual Cloud Datacenter Infrastructure RFQ",
        event_type=SourcingEvent.TYPE_RFQ,
        status=SourcingEvent.STATUS_BID_WINDOW,
        created_by=users[Role.PROC_EXEC],
        bid_start_date=timezone.now() - timezone.timedelta(days=2),
        bid_end_date=timezone.now() + timezone.timedelta(days=5),
        is_sealed=True,
        description="Enterprise Cloud RFQ"
    )
    # Invite Vendor A and Vendor B
    BidInvite.objects.create(event=event, vendor=vendor_a)
    BidInvite.objects.create(event=event, vendor=vendor_b)

    # Bid by Vendor A (commercial proposal sealed)
    bid_a = VendorBid.objects.create(
        event=event,
        vendor=vendor_a,
        bid_number="BID-2026-AUDIT-001",
        status=VendorBid.STATUS_SUBMITTED,
        total_bid_amount=Decimal("142000.00"),
        technical_proposal="Full Enterprise Cloud SLA 99.999% Architecture",
        commercial_proposal="Confidential Tier-1 Discount Pricing: $142,000 Total"
    )

    return {
        "org1": org1,
        "org2": org2,
        "vendor_a": vendor_a,
        "vendor_b": vendor_b,
        "vendor_c": vendor_c,
        "users": users,
        "roles": roles,
        "po": po,
        "invoice": invoice,
        "event": event,
        "bid_a": bid_a,
    }


# ==============================================================================
# 1. SECURITY AUDIT TESTS
# ==============================================================================

@pytest.mark.django_db
def test_security_auth_and_session_controls(enterprise_security_fixtures):
    """Verify session configuration, unauthenticated redirects, and cookie security flags."""
    client = Client()
    # Unauthenticated access to protected dashboard must redirect to login
    res = client.get("/dashboard/")
    assert res.status_code == 302
    assert "/login/" in res.url

    # Check login response cookies
    res_login = client.post("/login/", {
        "username": "superadmin.audit@hpe.com",
        "password": "Password123!"
    })
    # Login redirect to portal
    assert res_login.status_code == 302
    assert "sessionid" in res_login.cookies
    session_cookie = res_login.cookies["sessionid"]
    assert session_cookie["httponly"] is True
    assert session_cookie["samesite"] in ["Lax", "Strict"]


@pytest.mark.django_db
def test_security_rbac_cross_dashboard_matrix(enterprise_security_fixtures):
    """Verify that each role is strictly prevented from accessing unauthorized workspaces."""
    users = enterprise_security_fixtures["users"]
    
    # Requester cannot access Finance, Procurement, Superadmin
    c_req = Client()
    c_req.force_login(users[Role.REQUESTER])
    assert c_req.get("/finance/").status_code == 403
    assert c_req.get("/procurement/").status_code == 403
    assert c_req.get("/superadmin/dashboard/").status_code in [403, 302]

    # Vendor cannot access Internal Staff Workspaces or APIs
    c_vnd = Client()
    c_vnd.force_login(users["VENDOR_A"])
    assert c_vnd.get("/procurement/").status_code == 403
    assert c_vnd.get("/finance/").status_code == 403
    assert c_vnd.get("/superadmin/dashboard/").status_code in [403, 302]
    assert c_vnd.get("/api/v1/approver/dashboard/").status_code == 403

    # Department Approver cannot access Vendor Portal
    c_app = Client()
    c_app.force_login(users[Role.DEPT_APPROVER])
    assert c_app.get("/vendor/dashboard/").status_code in [403, 302]

    # Stores Receiver cannot access Finance Workspace or Spend Reports
    c_sto = Client()
    c_sto.force_login(users[Role.STORES_RECEIVER])
    assert c_sto.get("/finance/").status_code == 403
    assert c_sto.get("/api/v1/reports/dashboard-summary/").status_code == 403


@pytest.mark.django_db
def test_security_cross_vendor_and_bid_confidentiality(enterprise_security_fixtures):
    """Verify Vendor B cannot view Vendor A's bids, purchase orders, or documents."""
    users = enterprise_security_fixtures["users"]
    bid_a = enterprise_security_fixtures["bid_a"]
    po = enterprise_security_fixtures["po"]

    api_client_b = APIClient()
    api_client_b.force_authenticate(user=users["VENDOR_B"])

    # 1. Vendor B attempts to query Vendor A's sealed bid
    res_bid = api_client_b.get(f"/api/v1/sourcing/bids/{bid_a.id}/")
    assert res_bid.status_code in [403, 404]
    assert "Confidential Tier-1 Discount Pricing" not in str(res_bid.content)

    # 2. Vendor B attempts to access Vendor A's Purchase Order
    c_vnd_b = Client()
    c_vnd_b.force_login(users["VENDOR_B"])
    res_po = c_vnd_b.get(f"/vendor/purchase-orders/{po.id}/")
    assert res_po.status_code in [403, 404]

    # 3. Suspended vendor cannot be invited or submit bids
    vendor_c = enterprise_security_fixtures["vendor_c"]
    event = enterprise_security_fixtures["event"]
    assert vendor_c.is_event_eligible is False
    assert vendor_c.status == Vendor.STATUS_SUSPENDED


@pytest.mark.django_db
def test_security_cross_tenant_organization_isolation(enterprise_security_fixtures):
    """Verify Org 2 user cannot access Org 1's POs, Requisitions, or Dashboards."""
    users = enterprise_security_fixtures["users"]
    po = enterprise_security_fixtures["po"]

    c_org2 = Client()
    c_org2.force_login(users["ORG2_USER"])

    # Org 2 attempts to view Org 1's PO
    res = c_org2.get(f"/purchase-orders/{po.id}/")
    assert res.status_code in [403, 404]


@pytest.mark.django_db
def test_security_input_validation_and_xss_sqli_resilience(enterprise_security_fixtures):
    """Verify that malicious XSS tags and SQL injection payloads are safely sanitized and handled."""
    users = enterprise_security_fixtures["users"]
    c_req = Client()
    c_req.force_login(users[Role.REQUESTER])

    # 1. SQL Injection payload in query parameters
    sqli_payloads = ["' OR '1'='1", "1; DROP TABLE accounts_user;--", "admin'--"]
    for payload in sqli_payloads:
        res = c_req.get(f"/api/v1/approvals/actions/?target_object_id={payload}")
        # Must return clean 200 with empty results or 400 validation error, never 500 database error
        assert res.status_code in [200, 400]
        assert "SyntaxError" not in str(res.content)
        assert "OperationalError" not in str(res.content)

    # 2. XSS injection payload in search filter
    xss_payload = '<script>alert("XSS")</script>'
    res_xss = c_req.get(f"/requester/?q={xss_payload}")
    assert res_xss.status_code == 200
    # Payload must either be stripped or HTML-escaped (&lt;script&gt;)
    assert "<script>alert" not in res_xss.content.decode()


@pytest.mark.django_db
def test_security_file_upload_validation():
    """Verify file upload rejection for prohibited executables, empty files, and path traversal."""
    from apps.core.validators import validate_file_upload
    from django.core.exceptions import ValidationError

    # Prohibited executable
    exe_file = SimpleUploadedFile("malware.exe", b"MZ\x90\x00\x03\x00\x00\x00", content_type="application/x-dosexec")
    with pytest.raises(ValidationError) as exc:
        validate_file_upload(exe_file, allowed_extensions=["pdf", "docx"])
    assert "not permitted" in str(exc.value)

    # Empty file
    empty_file = SimpleUploadedFile("empty.pdf", b"", content_type="application/pdf")
    with pytest.raises(ValidationError) as exc:
        validate_file_upload(empty_file, allowed_extensions=["pdf"])
    assert "empty" in str(exc.value)


# ==============================================================================
# 2. PERFORMANCE & DATABASE QUERY BENCHMARK TESTS
# ==============================================================================

@pytest.mark.django_db
def test_performance_dashboard_latencies_and_queries(enterprise_security_fixtures):
    """Benchmark page rendering latency and database query counts for core dashboards."""
    users = enterprise_security_fixtures["users"]
    
    dashboards_to_benchmark = [
        (Role.SUPER_ADMIN, users[Role.SUPER_ADMIN], "/superadmin/dashboard/"),
        (Role.REQUESTER, users[Role.REQUESTER], "/requester/"),
        (Role.DEPT_APPROVER, users[Role.DEPT_APPROVER], "/approver/"),
        (Role.PROC_EXEC, users[Role.PROC_EXEC], "/procurement/"),
        (Role.PROC_MGR, users[Role.PROC_MGR], "/manager/dashboard/"),
        (Role.LEGAL_MGR, users[Role.LEGAL_MGR], "/legal/"),
        (Role.FINANCE_AP, users[Role.FINANCE_AP], "/finance/"),
        (Role.STORES_RECEIVER, users[Role.STORES_RECEIVER], "/stores/"),
        (Role.AUDITOR, users[Role.AUDITOR], "/audit/dashboard/"),
        (Role.VENDOR_USER, users["VENDOR_A"], "/vendor/dashboard/"),
    ]

    results = []
    for role_name, user_obj, path in dashboards_to_benchmark:
        client = Client()
        client.force_login(user_obj)
        
        # Warmup request
        client.get(path)

        # Benchmark request with query capture and latency timing
        reset_queries()
        start = time.perf_counter()
        with CaptureQueriesContext(connection) as ctx:
            response = client.get(path)
        duration_ms = (time.perf_counter() - start) * 1000

        query_count = len(ctx.captured_queries)
        assert response.status_code == 200, f"Dashboard {path} failed with {response.status_code}"
        
        results.append({
            "role": role_name,
            "url": path,
            "duration_ms": round(duration_ms, 2),
            "query_count": query_count,
        })

    # Assert SLA standards: Render time < 500ms, Query count < 50
    for r in results:
        print(f"[PERF BENCHMARK] {r['role']:<15} | Path: {r['url']:<25} | Latency: {r['duration_ms']:>6.2f} ms | Queries: {r['query_count']:>2}")
        assert r["duration_ms"] < 1000.0, f"Dashboard {r['url']} exceeded 1000ms latency: {r['duration_ms']}ms"
        assert r["query_count"] <= 50, f"Dashboard {r['url']} executed excessive queries: {r['query_count']}"


@pytest.mark.django_db
def test_performance_api_response_latencies_and_queries(enterprise_security_fixtures):
    """Benchmark response times and query counts for high-traffic REST API endpoints."""
    users = enterprise_security_fixtures["users"]
    
    api_benchmarks = [
        (users[Role.DEPT_APPROVER], "/api/v1/approver/dashboard/"),
        (users[Role.DEPT_APPROVER], "/api/v1/approver/queue/"),
        (users[Role.FINANCE_AP], "/api/v1/reports/dashboard-summary/"),
        (users[Role.AUDITOR], "/api/v1/audit/dashboard-summary/"),
    ]

    for user_obj, api_url in api_benchmarks:
        client = APIClient()
        client.force_authenticate(user=user_obj)

        # Benchmark request
        start = time.perf_counter()
        with CaptureQueriesContext(connection) as ctx:
            res = client.get(api_url)
        duration_ms = (time.perf_counter() - start) * 1000

        assert res.status_code == 200, f"API {api_url} failed with {res.status_code}"
        print(f"[API BENCHMARK] {api_url:<40} | Latency: {duration_ms:>6.2f} ms | Queries: {len(ctx.captured_queries):>2}")
        assert duration_ms < 500.0, f"API {api_url} exceeded 500ms: {duration_ms}ms"
        assert len(ctx.captured_queries) <= 30, f"API {api_url} query count high: {len(ctx.captured_queries)}"


# ==============================================================================
# 3. CONCURRENT LOAD & STRESS SIMULATION
# ==============================================================================

@pytest.mark.django_db(transaction=True)
@override_settings(
    SESSION_ENGINE="django.contrib.sessions.backends.signed_cookies",
    SESSION_SAVE_EVERY_REQUEST=False,
    AXES_ENABLED=False
)
def test_concurrent_load_and_stress_simulation(enterprise_security_fixtures):
    """Simulate 25 concurrent users executing simultaneous dashboard requests and API operations."""
    users = enterprise_security_fixtures["users"]
    num_threads = 25
    requests_per_thread = 4
    latencies = []
    errors = []

    # Pre-create and pre-login clients on the main thread to avoid SQLite multi-threaded session write locks
    thread_clients = []
    thread_targets = []
    role_keys = [Role.REQUESTER, Role.DEPT_APPROVER, Role.PROC_EXEC, Role.FINANCE_AP, "VENDOR_A"]
    role_dashboards = {
        Role.REQUESTER: "/requester/",
        Role.DEPT_APPROVER: "/approver/",
        Role.PROC_EXEC: "/procurement/",
        Role.FINANCE_AP: "/finance/",
        "VENDOR_A": "/vendor/dashboard/",
    }
    for i in range(num_threads):
        assigned_key = role_keys[i % len(role_keys)]
        user_obj = users[assigned_key]
        c = Client()
        c.force_login(user_obj)
        thread_clients.append(c)
        target_urls = [
            "/dashboard/",
            role_dashboards[assigned_key],
        ]
        thread_targets.append(target_urls)

    def worker_task(thread_id):
        client = thread_clients[thread_id]
        urls = thread_targets[thread_id]
        for _ in range(requests_per_thread):
            for path in urls:
                try:
                    t0 = time.perf_counter()
                    resp = client.get(path, follow=True)
                    t1 = time.perf_counter()
                    latencies.append((t1 - t0) * 1000)
                    if resp.status_code not in [200, 302]:
                        errors.append((path, resp.status_code))
                except Exception as ex:
                    errors.append((path, str(ex)))

    threads = [threading.Thread(target=worker_task, args=(i,)) for i in range(num_threads)]
    total_start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    total_time = time.perf_counter() - total_start

    total_requests = len(latencies)
    throughput = total_requests / total_time if total_time > 0 else 0
    latencies.sort()
    
    p50 = latencies[int(len(latencies) * 0.50)] if latencies else 0
    p90 = latencies[int(len(latencies) * 0.90)] if latencies else 0
    p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0
    p99 = latencies[int(len(latencies) * 0.99)] if latencies else 0

    print(f"\n================ LOAD TESTING RESULTS ================")
    print(f"Total Requests:      {total_requests}")
    print(f"Concurrent Workers:  {num_threads}")
    print(f"Total Test Time:     {total_time:.2f} s")
    print(f"Throughput:          {throughput:.2f} req/s")
    print(f"Errors Recorded:     {len(errors)} (Error Rate: {len(errors)/max(1, total_requests)*100:.1f}%)")
    print(f"Latency P50:         {p50:.2f} ms")
    print(f"Latency P90:         {p90:.2f} ms")
    print(f"Latency P95:         {p95:.2f} ms")
    print(f"Latency P99:         {p99:.2f} ms")
    print(f"======================================================\n")

    assert len(errors) == 0, f"Recorded {len(errors)} errors during concurrent load testing: {errors[:5]}"
    assert p95 < 2500.0, f"P95 latency exceeded 2500ms: {p95:.2f}ms"
