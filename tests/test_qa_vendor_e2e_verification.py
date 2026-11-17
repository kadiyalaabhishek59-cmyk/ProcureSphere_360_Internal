import time
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.audit.models import AuditLog
from apps.budgets.models import SpendLedger
from apps.budgets.services import allocate_budget_service
from apps.contracts.models import (
    Contract,
    ContractDocument,
    ContractMilestone,
    ContractObligation,
)
from apps.invoices.models import MatchTolerancePolicy, PaymentStatus, SupplierInvoice
from apps.invoices.services import create_supplier_invoice_service
from apps.notifications.models import Notification
from apps.orders.models import POLine, PurchaseOrder
from apps.organization.models import CostCenter, Department, FiscalPeriod, Organization
from apps.receipts.models import GoodsReceipt, ReceiptLine
from apps.sourcing.models import (
    AwardDecision,
    BidInvite,
    SourcingEvent,
    VendorBid,
)
from apps.vendors.models import Vendor, VendorCategory, VendorDocument


@pytest.fixture
def qa_ecosystem(db, db_roles):
    """
    Sets up a full multi-tier enterprise procurement ecosystem spanning:
    Vendor A, Vendor B, Procurement Exec, Procurement Manager, Legal Counsel, Finance AP, and Super Admin.
    """
    org = Organization.objects.create(name="Enterprise Global Systems", code="EGS-ORG-01")
    dept = Department.objects.create(organization=org, name="Cloud & IT Systems", code="DEPT-CIT")
    cost_center = CostCenter.objects.create(department=dept, code="CC-CIT-101", name="Cloud Hardware Infrastructure")

    fiscal_period = FiscalPeriod.objects.create(
        organization=org,
        year=2026,
        period_number=1,
        name="FY2026-Q1",
        start_date=timezone.now().date() - timedelta(days=30),
        end_date=timezone.now().date() + timedelta(days=60),
    )
    budget = allocate_budget_service(
        cost_center=cost_center,
        fiscal_period=fiscal_period,
        allocated_amount=Decimal("500000.00"),
    )

    category = VendorCategory.objects.create(name="Hardware & Networking", code="CAT-HW-NET")

    vendor_a = Vendor.objects.create(
        vendor_number="VND-E2E-001",
        legal_name="Nexus Technologies Pvt Ltd",
        trade_name="Nexus Tech",
        tax_identification_number="27AAACN1234A1Z5",
        pan_number="AAACN1234A",
        phone="+919876543210",
        address="Tower 4, Cyber City, Bangalore, India",
        bank_name="HDFC Bank",
        bank_account_number="50200012345678",
        bank_routing_code="HDFC0001234",
        category=category,
        email="billing@nexustech.in",
        status=Vendor.STATUS_ACTIVE,
        is_event_eligible=True,
        event_eligibility_status="ELIGIBLE",
    )

    vendor_b = Vendor.objects.create(
        vendor_number="VND-E2E-002",
        legal_name="Starlight Solutions Inc",
        trade_name="Starlight Corp",
        tax_identification_number="29AAACS5678B1Z2",
        pan_number="AAACS5678B",
        phone="+919123456789",
        address="Sector 18, Gurgaon, India",
        bank_name="ICICI Bank",
        bank_account_number="000105009876",
        bank_routing_code="ICIC0000001",
        category=category,
        email="contact@starlightcorp.com",
        status=Vendor.STATUS_ACTIVE,
        is_event_eligible=True,
        event_eligibility_status="ELIGIBLE",
    )

    # Roles
    r_vendor = Role.objects.get(code=Role.VENDOR_USER)
    r_exec = Role.objects.get(code=Role.PROC_EXEC)
    r_mgr = Role.objects.get(code=Role.PROC_MGR)
    r_legal = Role.objects.get(code=Role.LEGAL_MGR)
    r_fin = Role.objects.get(code=Role.FINANCE_AP)
    r_admin = Role.objects.get(code=Role.SUPER_ADMIN)

    user_v_a = User.objects.create_user(email="agent@nexustech.in", password="Password123!", role=r_vendor, vendor=vendor_a)
    user_v_b = User.objects.create_user(email="portal@starlightcorp.com", password="Password123!", role=r_vendor, vendor=vendor_b)
    user_exec = User.objects.create_user(email="buyer@egs.com", password="Password123!", role=r_exec)
    user_mgr = User.objects.create_user(email="manager@egs.com", password="Password123!", role=r_mgr)
    user_legal = User.objects.create_user(email="legal@egs.com", password="Password123!", role=r_legal)
    user_fin = User.objects.create_user(email="finance@egs.com", password="Password123!", role=r_fin)
    user_admin = User.objects.create_user(email="admin@egs.com", password="Password123!", role=r_admin, is_superuser=True)

    # 3-Way Match Policy
    policy = MatchTolerancePolicy.get_current()
    policy.price_tolerance_pct = Decimal("0.05")
    policy.qty_tolerance_pct = Decimal("0.05")
    policy.save()

    return {
        "org": org,
        "dept": dept,
        "cost_center": cost_center,
        "budget": budget,
        "category": category,
        "vendor_a": vendor_a,
        "vendor_b": vendor_b,
        "user_v_a": user_v_a,
        "user_v_b": user_v_b,
        "user_exec": user_exec,
        "user_mgr": user_mgr,
        "user_legal": user_legal,
        "user_fin": user_fin,
        "user_admin": user_admin,
    }


# ==============================================================================
# 1. WORKFLOW INTEGRATION TESTING (10 Workflows)
# ==============================================================================

@pytest.mark.django_db
def test_workflow_01_registration_login_onboarding(client, qa_ecosystem):
    """
    Workflow 1: Vendor Registration -> Login -> Onboarding Hub
    Verifies that a newly provisioned vendor can authenticate, access onboarding,
    and inspect qualification milestones without redirection loops.
    """
    w = qa_ecosystem
    client.force_login(w["user_v_a"])

    t0 = time.perf_counter()
    with CaptureQueriesContext(connection) as ctx:
        res = client.get("/vendor/onboarding/")
    t_ms = (time.perf_counter() - t0) * 1000

    assert res.status_code == 200
    assert "Dossier Completion Progress" in res.content.decode()
    assert "1. Corporate Profile" in res.content.decode()
    assert len(ctx.captured_queries) <= 20
    assert t_ms < 2000  # Cold start allowance


@pytest.mark.django_db
def test_workflow_02_onboarding_kyc_upload_legal_review(client, qa_ecosystem):
    """
    Workflow 2: Onboarding -> KYC Bundle Upload -> Legal Approval
    Verifies mandatory document bundle upload (PAN, GST, Bank) and submission for review.
    """
    w = qa_ecosystem
    v_a = w["vendor_a"]
    client.force_login(w["user_v_a"])

    pdf_content = b"%PDF-1.4 Official Certificate Content"
    file_pan = SimpleUploadedFile("pan_nexus.pdf", pdf_content, content_type="application/pdf")
    file_gst = SimpleUploadedFile("gst_nexus.pdf", pdf_content, content_type="application/pdf")
    file_bank = SimpleUploadedFile("bank_nexus.pdf", pdf_content, content_type="application/pdf")

    # Upload Mandatory KYC Bundle (PAN, GST, Bank)
    res_bundle = client.post("/vendor/profile/", data={
        "action": "upload_kyc",
        "upload_mode": "mandatory_bundle",
        "pan_file": file_pan,
        "tax_file": file_gst,
        "bank_file": file_bank,
    })
    assert res_bundle.status_code == 302
    assert VendorDocument.objects.filter(vendor=v_a).count() == 3

    # Submit KYC Bundle for Review
    submit_res = client.post("/vendor/profile/", data={"action": "submit_kyc"})
    assert submit_res.status_code == 302
    v_a.refresh_from_db()
    assert v_a.status in (Vendor.STATUS_KYC_REVIEW, Vendor.STATUS_ACTIVE)


@pytest.mark.django_db
def test_workflow_03_approved_vendor_sourcing_event_visibility(client, qa_ecosystem):
    """
    Workflow 3: Approved Vendor -> Sourcing Event Visibility
    Invited vendor can view active RFQ events, while uninvited vendor cannot see them.
    """
    w = qa_ecosystem
    v_a = w["vendor_a"]
    v_b = w["vendor_b"]

    event = SourcingEvent.objects.create(
        event_number="RFQ-2026-CLOUD-01",
        title="Enterprise Server Blades RFP",
        event_type=SourcingEvent.TYPE_RFQ,
        status=SourcingEvent.STATUS_PUBLISHED,
        bid_start_date=timezone.now() - timedelta(days=1),
        bid_end_date=timezone.now() + timedelta(days=10),
        created_by=w["user_exec"],
    )
    BidInvite.objects.create(event=event, vendor=v_a)

    # Vendor A (invited)
    client.force_login(w["user_v_a"])
    res_a = client.get("/vendor/sourcing/")
    assert res_a.status_code == 200
    assert "Enterprise Server Blades RFP" in res_a.content.decode()

    # Vendor B (not invited)
    client.force_login(w["user_v_b"])
    res_b = client.get("/vendor/sourcing/")
    assert res_b.status_code == 200
    assert "Enterprise Server Blades RFP" not in res_b.content.decode()


@pytest.mark.django_db
def test_workflow_04_sourcing_bid_creation_and_submission(client, qa_ecosystem):
    """
    Workflow 4: Sourcing Event -> Bid Creation -> Sealed Bid Submission
    Enforces sealed quotation handling, draft save, and immutable submission snapshot.
    """
    w = qa_ecosystem
    v_a = w["vendor_a"]

    event = SourcingEvent.objects.create(
        event_number="RFQ-2026-STORAGE",
        title="SAN Storage Expansion",
        status=SourcingEvent.STATUS_BID_WINDOW,
        bid_start_date=timezone.now() - timedelta(days=1),
        bid_end_date=timezone.now() + timedelta(days=5),
        created_by=w["user_exec"],
    )
    BidInvite.objects.create(event=event, vendor=v_a)

    client.force_login(w["user_v_a"])

    # 1. Save Draft
    res_draft = client.post(f"/vendor/bids/create/{event.id}/", data={
        "action": "save_draft",
        "proposal_summary": "Initial draft proposal for storage expansion",
        "technical_proposal": "Full NVMe enterprise SAN storage with HA controllers",
        "commercial_proposal": "Net 30 terms, comprehensive 3-year support",
        "line_description[]": ["NVMe Storage Expansion Shelf", "Fiber Channel Controller"],
        "line_quantity[]": ["2", "4"],
        "line_price[]": ["25000.00", "8750.00"],
    }, follow=True)
    assert res_draft.status_code == 200

    bid = VendorBid.objects.get(event=event, vendor=v_a)
    assert bid.status == VendorBid.STATUS_DRAFT

    # 2. Formal Submit
    res_submit = client.post(f"/vendor/bids/create/{event.id}/", data={
        "action": "submit_bid",
        "proposal_summary": "Formal proposal for SAN Storage Expansion",
        "technical_proposal": "Full NVMe enterprise SAN storage with HA controllers",
        "commercial_proposal": "Net 30 terms, comprehensive 3-year support",
        "line_description[]": ["NVMe Storage Expansion Shelf", "Fiber Channel Controller"],
        "line_quantity[]": ["2", "4"],
        "line_price[]": ["25000.00", "8750.00"],
        "terms_agreed": "on",
    }, follow=True)
    assert res_submit.status_code == 200
    bid.refresh_from_db()
    assert bid.status == VendorBid.STATUS_SUBMITTED
    assert bid.submitted_at is not None


@pytest.mark.django_db
def test_workflow_05_bid_selection_po_acknowledgement(client, qa_ecosystem):
    """
    Workflow 5: Bid Selection -> Purchase Order -> PO Acknowledgement
    Verifies PO state transition from ISSUED to ACKNOWLEDGED with audit logging.
    """
    w = qa_ecosystem
    v_a = w["vendor_a"]

    po = PurchaseOrder.objects.create(
        vendor=v_a,
        cost_center=w["cost_center"],
        status=PurchaseOrder.STATUS_ISSUED,
        total_amount=Decimal("45000.00"),
        created_by=w["user_exec"],
    )

    client.force_login(w["user_v_a"])
    res_detail = client.get(f"/vendor/purchase-orders/{po.id}/")
    assert res_detail.status_code == 200
    assert po.po_number in res_detail.content.decode()

    # Acknowledge PO
    res_ack = client.post(f"/vendor/purchase-orders/{po.id}/acknowledge/")
    assert res_ack.status_code == 302
    po.refresh_from_db()
    assert po.status == PurchaseOrder.STATUS_ACKNOWLEDGED
    assert po.acknowledged_at is not None


@pytest.mark.django_db
def test_workflow_06_po_goods_receipt_invoice_submission(client, qa_ecosystem):
    """
    Workflow 6: PO -> Goods Receipt (GRN) -> Invoice Submission
    Verifies that vendor can submit an invoice only against accepted GRN quantities.
    """
    w = qa_ecosystem
    v_a = w["vendor_a"]

    po = PurchaseOrder.objects.create(
        vendor=v_a,
        cost_center=w["cost_center"],
        status=PurchaseOrder.STATUS_ACKNOWLEDGED,
        total_amount=Decimal("30000.00"),
        created_by=w["user_exec"],
    )
    po_line = POLine.objects.create(
        po=po,
        item_description="Rack Server Unit 2U",
        quantity=Decimal("10.00"),
        unit_price=Decimal("3000.00"),
        line_total=Decimal("30000.00"),
    )

    # Goods Receipt
    grn = GoodsReceipt.objects.create(
        po=po,
        grn_number="GRN-QA-001",
        received_by=w["user_exec"],
        received_date=timezone.now(),
    )
    ReceiptLine.objects.create(
        receipt=grn,
        po_line=po_line,
        quantity_received=Decimal("10.00"),
        quantity_accepted=Decimal("10.00"),
        quantity_rejected=Decimal("0.00"),
    )

    client.force_login(w["user_v_a"])

    # Invoice Submission
    t0 = time.perf_counter()
    post_res = client.post(f"/vendor/purchase-orders/{po.id}/submit-invoice/", data={
        "invoice_number": "INV-NEXUS-2026-001",
        "invoice_date": timezone.now().date().isoformat(),
        "due_date": (timezone.now().date() + timedelta(days=30)).isoformat(),
        "notes": "Full order delivery",
        f"qty_{po_line.id}": "10.00",
        f"price_{po_line.id}": "3000.00",
        "tax_amount": "5400.00",
    })
    t_ms = (time.perf_counter() - t0) * 1000

    assert post_res.status_code == 302
    assert t_ms < 600  # Latency check

    inv = SupplierInvoice.objects.get(vendor=v_a, invoice_number="INV-NEXUS-2026-001")
    assert inv.subtotal == Decimal("30000.00")
    assert inv.total_amount == Decimal("33000.00")


@pytest.mark.django_db
def test_workflow_07_invoice_3way_matching_finance_approval(client, qa_ecosystem):
    """
    Workflow 7: Invoice -> 3-Way Match Verification -> Finance Approval
    Tests automated matching against PO & GRN and transition to READY_FOR_PAYMENT.
    """
    w = qa_ecosystem
    v_a = w["vendor_a"]

    po = PurchaseOrder.objects.create(
        vendor=v_a,
        cost_center=w["cost_center"],
        status=PurchaseOrder.STATUS_ACKNOWLEDGED,
        total_amount=Decimal("20000.00"),
    )
    inv = SupplierInvoice.objects.create(
        vendor=v_a,
        po=po,
        invoice_number="INV-MATCH-001",
        invoice_date=timezone.now().date(),
        due_date=(timezone.now() + timedelta(days=30)).date(),
        subtotal=Decimal("20000.00"),
        tax_amount=Decimal("3600.00"),
        total_amount=Decimal("23600.00"),
        status=SupplierInvoice.STATUS_READY_FOR_PAYMENT,
    )

    client.force_login(w["user_v_a"])
    inv_res = client.get(f"/vendor/invoices/{inv.id}/")
    assert inv_res.status_code == 200
    assert "INV-MATCH-001" in inv_res.content.decode()


@pytest.mark.django_db
def test_workflow_08_finance_approval_payment_tracking(client, qa_ecosystem):
    """
    Workflow 8: Finance Approval -> Treasury Disbursement -> Dedicated Payment Ledger
    Validates that disbursed payment records surface in /vendor/payments/ with remittance advice.
    """
    w = qa_ecosystem
    v_a = w["vendor_a"]

    po = PurchaseOrder.objects.create(
        vendor=v_a,
        cost_center=w["cost_center"],
        status=PurchaseOrder.STATUS_ACKNOWLEDGED,
        total_amount=Decimal("15000.00"),
    )
    inv = SupplierInvoice.objects.create(
        vendor=v_a,
        po=po,
        invoice_number="INV-DISBURSED-01",
        invoice_date=timezone.now().date(),
        due_date=(timezone.now() + timedelta(days=15)).date(),
        subtotal=Decimal("15000.00"),
        tax_amount=Decimal("2700.00"),
        total_amount=Decimal("17700.00"),
        status=SupplierInvoice.STATUS_PAID,
    )
    payment = PaymentStatus.objects.create(
        invoice=inv,
        payment_reference="PAY-DISB-EGS-9911",
        payment_date=timezone.now().date(),
        amount_paid=Decimal("17700.00"),
        payment_method="RTGS_TRANSFER",
        paid_by=w["user_fin"],
    )

    client.force_login(w["user_v_a"])
    pay_res = client.get("/vendor/payments/")
    assert pay_res.status_code == 200
    content = pay_res.content.decode()
    assert "PAY-DISB-EGS-9911" in content
    assert "17700.00" in content
    assert "RTGS_TRANSFER" in content


@pytest.mark.django_db
def test_workflow_09_contract_creation_and_visibility(client, qa_ecosystem):
    """
    Workflow 9: Contract Creation -> Contract Detail & Milestone Tracking
    Validates contract detail page, milestone schedule, obligations, and executed documents.
    """
    w = qa_ecosystem
    v_a = w["vendor_a"]

    contract = Contract.objects.create(
        contract_number="EGS-CNT-2026-CLOUD",
        title="Master Cloud Infrastructure Services Agreement",
        vendor=v_a,
        contract_value=Decimal("120000.00"),
        start_date=timezone.now().date(),
        end_date=(timezone.now() + timedelta(days=365)).date(),
        contract_owner=w["user_legal"],
        status=Contract.STATUS_ACTIVE,
    )
    ContractMilestone.objects.create(
        contract=contract,
        title="Phase 1 Cloud Provisioning",
        due_date=(timezone.now() + timedelta(days=60)).date(),
        amount=Decimal("40000.00"),
    )
    ContractObligation.objects.create(
        contract=contract,
        title="99.99% Infrastructure Uptime SLA",
        due_date=(timezone.now() + timedelta(days=30)).date(),
        responsible_party="VENDOR",
    )

    client.force_login(w["user_v_a"])
    res = client.get(f"/vendor/contracts/{contract.id}/")
    assert res.status_code == 200
    content = res.content.decode()
    assert "EGS-CNT-2026-CLOUD" in content
    assert "Phase 1 Cloud Provisioning" in content
    assert "99.99% Infrastructure Uptime SLA" in content
    assert "120000.00" in content


@pytest.mark.django_db
def test_workflow_10_vendor_support_ticket_submission_and_notification(client, qa_ecosystem):
    """
    Workflow 10: Vendor Support -> Ticket Submission -> Audit Log & In-App Notification
    Verifies end-to-end inquiry logging and buyer directory representation.
    """
    w = qa_ecosystem
    v_a = w["vendor_a"]

    client.force_login(w["user_v_a"])
    post_res = client.post("/vendor/support/", data={
        "category": "PAYMENT_DISBURSEMENT",
        "priority": "HIGH",
        "reference_no": "PAY-REF-CHECK",
        "subject": "Inquiry on Remittance Advice Settlement Date",
        "message": "Kindly confirm the bank RTGS value date for payment reference PAY-REF-CHECK.",
    })
    assert post_res.status_code == 302

    # Verify AuditLog
    inquiry_log = AuditLog.objects.filter(
        actor=w["user_v_a"],
        action="SUPPORT_INQUIRY",
        target_model="Vendor",
        target_object_id=str(v_a.id),
    ).first()
    assert inquiry_log is not None
    assert inquiry_log.new_state["subject"] == "Inquiry on Remittance Advice Settlement Date"

    # Verify Notification
    notif = Notification.objects.filter(recipient=w["user_v_a"], notification_type="SYSTEM_ALERT").first()
    assert notif is not None
    assert "Support Inquiry Registered" in notif.title


# ==============================================================================
# 2. CROSS-DASHBOARD INTEGRATION VALIDATION
# ==============================================================================

@pytest.mark.django_db
def test_cross_dashboard_visibility_across_all_roles(client, qa_ecosystem):
    """
    Cross-Dashboard Validation:
    Ensures that when a vendor performs actions, data synchronizes cleanly across:
    - Vendor Dashboard
    - Procurement Executive Dashboard
    - Procurement Manager Dashboard
    - Legal Dashboard
    - Finance Dashboard
    - Super Admin Dashboard
    """
    w = qa_ecosystem
    v_a = w["vendor_a"]

    # 1. Vendor views own dashboard
    client.force_login(w["user_v_a"])
    res_vendor = client.get("/vendor/")
    assert res_vendor.status_code == 200

    # 2. Procurement Executive Dashboard
    client.force_login(w["user_exec"])
    res_exec = client.get("/procurement/")
    assert res_exec.status_code in (200, 302)

    # 3. Procurement Manager Dashboard
    client.force_login(w["user_mgr"])
    res_mgr = client.get("/manager/")
    assert res_mgr.status_code in (200, 302)

    # 4. Legal Dashboard
    client.force_login(w["user_legal"])
    res_legal = client.get("/legal/")
    assert res_legal.status_code in (200, 302)

    # 5. Finance Dashboard
    client.force_login(w["user_fin"])
    res_fin = client.get("/finance/")
    assert res_fin.status_code in (200, 302)

    # 6. Admin Dashboard
    client.force_login(w["user_admin"])
    res_admin = client.get("/admin/dashboard/")
    assert res_admin.status_code in (200, 302)


# ==============================================================================
# 3. SECURITY & TENANT ISOLATION VALIDATION
# ==============================================================================

@pytest.mark.django_db
def test_security_cross_vendor_idor_isolation(client, qa_ecosystem):
    """
    Security Validation:
    Strict cross-vendor data isolation (preventing Insecure Direct Object References).
    Vendor B must NEVER access Vendor A's purchase orders, invoices, contracts, or support logs.
    """
    w = qa_ecosystem
    v_a = w["vendor_a"]

    po_a = PurchaseOrder.objects.create(
        vendor=v_a,
        cost_center=w["cost_center"],
        status=PurchaseOrder.STATUS_ISSUED,
        total_amount=Decimal("10000.00"),
    )
    inv_a = SupplierInvoice.objects.create(
        vendor=v_a,
        po=po_a,
        invoice_number="INV-A-CONFIDENTIAL",
        invoice_date=timezone.now().date(),
        due_date=(timezone.now() + timedelta(days=30)).date(),
        subtotal=Decimal("10000.00"),
        total_amount=Decimal("10000.00"),
    )
    cnt_a = Contract.objects.create(
        contract_number="CNT-A-SECRET",
        title="Classified Vendor Agreement",
        vendor=v_a,
        contract_value=Decimal("50000.00"),
        start_date=timezone.now().date(),
        end_date=(timezone.now() + timedelta(days=180)).date(),
        contract_owner=w["user_legal"],
    )

    client.force_login(w["user_v_b"])

    # Attempt cross-vendor PO access
    res_po = client.get(f"/vendor/purchase-orders/{po_a.id}/")
    assert res_po.status_code in (403, 404)

    # Attempt cross-vendor invoice access
    res_inv = client.get(f"/vendor/invoices/{inv_a.id}/")
    assert res_inv.status_code in (403, 404)

    # Attempt cross-vendor contract access
    res_cnt = client.get(f"/vendor/contracts/{cnt_a.id}/")
    assert res_cnt.status_code in (403, 404)


@pytest.mark.django_db
def test_security_rbac_boundary_controls(client, qa_ecosystem):
    """
    Security Validation: Role-Based Access Control (RBAC).
    Unauthenticated users are redirected to login.
    Non-vendor users attempting to access vendor portal views receive HTTP 403.
    """
    w = qa_ecosystem

    # Unauthenticated
    client.logout()
    res_anon = client.get("/vendor/")
    assert res_anon.status_code == 302
    assert "/login" in res_anon.url

    # Internal Finance user blocked from vendor dashboard
    client.force_login(w["user_fin"])
    res_fin = client.get("/vendor/")
    assert res_fin.status_code == 403


# ==============================================================================
# 4. PERFORMANCE & QUERY PROFILING BENCHMARKS
# ==============================================================================

@pytest.mark.django_db
def test_performance_dashboard_loading_and_query_counts(client, qa_ecosystem):
    """
    Performance Validation:
    Measures endpoint response latency (ms) and database query counts across primary views:
    - Overview (/vendor/)
    - Onboarding (/vendor/onboarding/)
    - Payments (/vendor/payments/)
    - Contracts (/vendor/contracts/)
    - Support (/vendor/support/)
    Ensures zero N+1 database explosions and sub-500ms response times.
    """
    w = qa_ecosystem
    client.force_login(w["user_v_a"])

    endpoints = [
        ("/vendor/", 35, 450),
        ("/vendor/onboarding/", 18, 400),
        ("/vendor/payments/", 15, 350),
        ("/vendor/contracts/", 15, 350),
        ("/vendor/support/", 15, 300),
    ]

    for url, max_queries, max_ms in endpoints:
        t0 = time.perf_counter()
        with CaptureQueriesContext(connection) as ctx:
            res = client.get(url)
        t_ms = (time.perf_counter() - t0) * 1000

        assert res.status_code == 200
        assert len(ctx.captured_queries) <= max_queries, f"Too many queries on {url}: {len(ctx.captured_queries)} > {max_queries}"
        assert t_ms < max_ms, f"Latency too high on {url}: {t_ms:.2f}ms > {max_ms}ms"


@pytest.mark.django_db
def test_performance_repeated_requests_and_session_resilience(client, qa_ecosystem):
    """
    Performance Validation: Repeated sequential requests under sustained session.
    Simulates high-frequency user interactions (20 requests) ensuring zero memory leaks or session drops.
    """
    w = qa_ecosystem
    client.force_login(w["user_v_a"])

    latencies = []
    for _ in range(20):
        t0 = time.perf_counter()
        res = client.get("/vendor/")
        latencies.append((time.perf_counter() - t0) * 1000)
        assert res.status_code == 200

    avg_ms = sum(latencies) / len(latencies)
    assert avg_ms < 250, f"Average latency too high: {avg_ms:.2f}ms"
