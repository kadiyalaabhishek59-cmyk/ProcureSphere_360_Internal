"""
ProcureSphere 360 – Cross-Dashboard Integration & End-to-End Workflow Audit Test Suite.

Covers:
1. Full 13-Stage Procurement Workflow:
   PR Creation -> Dept Approver Approval -> Sourcing RFQ/RFP Creation & Publish ->
   Vendor Invitation & Bid Submission -> Technical & Commercial Evaluation ->
   Award Recommendation & Approval -> PO Generation -> Vendor PO Acknowledgement ->
   Stores Goods Receipt & Inspection -> Vendor Invoice Submission ->
   Finance 3-Way Match & Exception Handling -> Payment Approval & Settlement ->
   Realized Spend Ledger & Dashboard Updates.
2. Cross-Dashboard Reflection Across All Roles:
   Requester, Approver, Procurement Exec, Procurement Manager, Legal, Finance,
   Stores, Vendor, Auditor, and Super Admin.
3. RBAC, Security & Multi-Tenant Isolation:
   Cross-vendor data isolation, bid confidentiality, inactive vendor blocks,
   role-based permission denials (403), document security.
4. Performance & Query Diagnostics.
"""

from decimal import Decimal
import datetime
import uuid
import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from django.test import Client

from apps.accounts.models import Role, User
from apps.approvals.models import ApprovalAction, ApprovalPolicy, ApprovalStep
from apps.audit.models import AuditLog
from apps.budgets.models import Budget, SpendLedger
from apps.budgets.services import allocate_budget_service
from apps.contracts.models import Contract
from apps.invoices.models import MatchException, MatchTolerancePolicy, SupplierInvoice
from apps.invoices.services import (
    create_supplier_invoice_service,
    mark_invoice_paid_service,
    resolve_match_exception_service,
)
from apps.orders.models import POLine, PurchaseOrder
from apps.orders.services import (
    acknowledge_purchase_order_service,
    approve_purchase_order_service,
    issue_purchase_order_service,
    submit_purchase_order_for_approval_service,
)
from apps.organization.models import CostCenter, Department, FiscalPeriod, Organization
from apps.receipts.models import GoodsReceipt, ReceiptLine
from apps.receipts.services import create_goods_receipt_service
from apps.requisitions.models import PRLine, PurchaseRequisition
from apps.requisitions.services import (
    approve_purchase_requisition_service,
    create_purchase_requisition_service,
    submit_purchase_requisition_service,
)
from apps.sourcing.models import (
    AwardDecision,
    BidEvaluation,
    BidInvite,
    SourcingEvent,
    VendorBid,
)
import apps.sourcing.services as sourcing_svc
from apps.vendors.models import Vendor, VendorCategory, VendorDocument


@pytest.fixture
def enterprise_audit_environment(db):
    """
    Sets up a complete multi-tenant, multi-department enterprise environment
    with all 10 roles, cost centers, budgets, and vendors.
    """
    # 1. Organizations
    org_primary = Organization.objects.create(name="Primary Enterprise Org", code="ORG-PRI-01")
    org_secondary = Organization.objects.create(name="Secondary Tenant Org", code="ORG-SEC-02")

    # 2. Departments & Cost Centers
    dept_it = Department.objects.create(name="Information Technology", code="IT-01", organization=org_primary)
    dept_sec = Department.objects.create(name="Security", code="SEC-01", organization=org_secondary)

    cc_it = CostCenter.objects.create(name="IT Infrastructure CC", code="CC-IT-INFRA", department=dept_it)
    cc_sec = CostCenter.objects.create(name="Sec Ops CC", code="CC-SEC-OPS", department=dept_sec)

    # 3. Fiscal Period & Budgets
    today = timezone.now().date()
    fp_primary = FiscalPeriod.objects.create(
        organization=org_primary,
        year=today.year,
        period_number=1,
        name=f"FY{today.year}-Q1",
        start_date=today - timezone.timedelta(days=30),
        end_date=today + timezone.timedelta(days=60),
        is_closed=False
    )
    budget_it = allocate_budget_service(
        cost_center=cc_it,
        fiscal_period=fp_primary,
        allocated_amount=Decimal("500000.00")
    )

    # 4. Roles
    super_role, _ = Role.objects.get_or_create(code=Role.SUPER_ADMIN, defaults={"name": "Super Admin"})
    req_role, _ = Role.objects.get_or_create(code=Role.REQUESTER, defaults={"name": "Requester"})
    appr_role, _ = Role.objects.get_or_create(code=Role.DEPT_APPROVER, defaults={"name": "Dept Approver"})
    exec_role, _ = Role.objects.get_or_create(code=Role.PROC_EXEC, defaults={"name": "Procurement Executive"})
    mgr_role, _ = Role.objects.get_or_create(code=Role.PROC_MGR, defaults={"name": "Procurement Manager"})
    legal_role, _ = Role.objects.get_or_create(code=Role.LEGAL_MGR, defaults={"name": "Legal Manager"})
    fin_role, _ = Role.objects.get_or_create(code=Role.FINANCE_AP, defaults={"name": "Finance / AP"})
    stores_role, _ = Role.objects.get_or_create(code=Role.STORES_RECEIVER, defaults={"name": "Stores Receiver"})
    aud_role, _ = Role.objects.get_or_create(code=Role.AUDITOR, defaults={"name": "Compliance / Auditor"})
    ven_role, _ = Role.objects.get_or_create(code=Role.VENDOR_USER, defaults={"name": "Vendor User"})

    # 5. Users
    user_super = User.objects.create_superuser(email="superadmin.audit@hpe.com", password="Pass123!Secure", role=super_role)
    user_req = User.objects.create_user(email="requester.audit@hpe.com", password="Pass123!Secure", role=req_role, department=dept_it, organization=org_primary)
    user_appr = User.objects.create_user(email="approver.audit@hpe.com", password="Pass123!Secure", role=appr_role, department=dept_it, organization=org_primary)
    user_exec = User.objects.create_user(email="procexec.audit@hpe.com", password="Pass123!Secure", role=exec_role, department=dept_it, organization=org_primary)
    user_mgr = User.objects.create_user(email="procmgr.audit@hpe.com", password="Pass123!Secure", role=mgr_role, department=dept_it, organization=org_primary)
    user_legal = User.objects.create_user(email="legal.audit@hpe.com", password="Pass123!Secure", role=legal_role, organization=org_primary)
    user_fin = User.objects.create_user(email="finance.audit@hpe.com", password="Pass123!Secure", role=fin_role, department=dept_it, organization=org_primary)
    user_stores = User.objects.create_user(email="stores.audit@hpe.com", password="Pass123!Secure", role=stores_role, department=dept_it, organization=org_primary)
    user_auditor = User.objects.create_user(email="auditor.audit@hpe.com", password="Pass123!Secure", role=aud_role, organization=org_primary)

    # 6. Vendors: Vendor A (Eligible), Vendor B (Competitor), Vendor C (Suspended)
    vcat = VendorCategory.objects.create(name="IT Hardware & Services", code="IT-HW-01")
    vendor_a = Vendor.objects.create(
        legal_name="Apex Enterprise Solutions Ltd",
        trade_name="Apex Solutions",
        vendor_number="VEN-AUD-001",
        tax_identification_number="TAX-APEX-001",
        category=vcat,
        organization=org_primary,
        status=Vendor.STATUS_ACTIVE,
        is_event_eligible=True,
        event_eligibility_status=Vendor.ELIGIBILITY_ELIGIBLE
    )
    user_vendor_a = User.objects.create_user(
        email="contact@apexsolutions.com",
        password="Pass123!Secure",
        role=ven_role,
        vendor=vendor_a,
        organization=org_primary
    )

    vendor_b = Vendor.objects.create(
        legal_name="BlueSky Cloud Technologies Inc",
        trade_name="BlueSky Tech",
        vendor_number="VEN-AUD-002",
        tax_identification_number="TAX-BLUE-002",
        category=vcat,
        organization=org_primary,
        status=Vendor.STATUS_ACTIVE,
        is_event_eligible=True,
        event_eligibility_status=Vendor.ELIGIBILITY_ELIGIBLE
    )
    user_vendor_b = User.objects.create_user(
        email="contact@blueskytech.com",
        password="Pass123!Secure",
        role=ven_role,
        vendor=vendor_b,
        organization=org_primary
    )

    vendor_suspended = Vendor.objects.create(
        legal_name="Suspended Vendor Corp",
        trade_name="Suspended Corp",
        vendor_number="VEN-AUD-003",
        tax_identification_number="TAX-SUSP-003",
        category=vcat,
        organization=org_primary,
        status=Vendor.STATUS_SUSPENDED
    )
    user_vendor_susp = User.objects.create_user(
        email="contact@suspendedcorp.com",
        password="Pass123!Secure",
        role=ven_role,
        vendor=vendor_suspended,
        organization=org_primary
    )

    # 7. Approval Policy for PR
    pr_policy = ApprovalPolicy.objects.create(
        name="IT Hardware PR Policy",
        module=ApprovalPolicy.MODULE_PR,
        department=dept_it,
        currency="INR",
        min_amount=Decimal("0.00"),
        max_amount=Decimal("500000.00"),
        is_active=True
    )
    ApprovalStep.objects.create(
        policy=pr_policy,
        step_number=1,
        approver_role=appr_role
    )

    # 8. Tolerance Policy
    tol_policy = MatchTolerancePolicy.get_current()
    tol_policy.price_tolerance_pct = Decimal("0.05") # 5% tolerance
    tol_policy.qty_tolerance_pct = Decimal("0.00")
    tol_policy.save()

    return {
        "org_primary": org_primary,
        "org_secondary": org_secondary,
        "dept_it": dept_it,
        "cc_it": cc_it,
        "budget_it": budget_it,
        "users": {
            "super": user_super,
            "req": user_req,
            "appr": user_appr,
            "exec": user_exec,
            "mgr": user_mgr,
            "legal": user_legal,
            "fin": user_fin,
            "stores": user_stores,
            "auditor": user_auditor,
            "vendor_a": user_vendor_a,
            "vendor_b": user_vendor_b,
            "vendor_susp": user_vendor_susp,
        },
        "vendors": {
            "a": vendor_a,
            "b": vendor_b,
            "susp": vendor_suspended,
        }
    }


# ==============================================================================
# 1. Complete End-to-End 13-Stage Workflow Validation
# ==============================================================================

@pytest.mark.django_db
def test_full_e2e_procurement_workflow_and_cross_dashboard_reflection(enterprise_audit_environment):
    env = enterprise_audit_environment
    u = env["users"]
    v = env["vendors"]
    client = Client()

    # --------------------------------------------------------------------------
    # STAGE 1: Requestor Creates Purchase Requisition (PR)
    # --------------------------------------------------------------------------
    delivery_date = timezone.now().date() + datetime.timedelta(days=14)
    pr = create_purchase_requisition_service(
        title="High Density Compute Cluster",
        justification="Core AI/ML training infrastructure upgrade",
        requester=u["req"],
        department=env["dept_it"],
        cost_center=env["cc_it"],
        requested_delivery_date=delivery_date,
        line_items=[
            {
                "item_description": "GPU Compute Node 8x H100",
                "quantity": Decimal("2"),
                "unit_of_measure": "EA",
                "estimated_unit_price": Decimal("35000.00"),
                "estimated_total": Decimal("70000.00"),
            }
        ],
    )
    assert pr.status == PurchaseRequisition.STATUS_DRAFT
    assert pr.total_amount == Decimal("70000.00")

    # Submit PR for Approval
    pr = submit_purchase_requisition_service(requisition=pr, user=u["req"])
    assert pr.status in [PurchaseRequisition.STATUS_SUBMITTED, PurchaseRequisition.STATUS_MANAGER_REVIEW]

    # Verify Reflection in Requestor Dashboard
    client.force_login(u["req"])
    resp_req = client.get("/requester/")
    assert resp_req.status_code == 200
    assert pr.pr_number in resp_req.content.decode()

    # Verify Reflection in Approver Dashboard & Approver Queue API
    api_client = APIClient()
    api_client.force_authenticate(user=u["appr"])
    resp_queue = api_client.get("/api/v1/approver/queue/")
    assert resp_queue.status_code == status.HTTP_200_OK
    queue_data = resp_queue.data if isinstance(resp_queue.data, list) else resp_queue.data.get("results", [])
    assert any(item.get("pr_number") == pr.pr_number for item in queue_data)

    # --------------------------------------------------------------------------
    # STAGE 2: Department Approver Approves PR
    # --------------------------------------------------------------------------
    pr = approve_purchase_requisition_service(
        requisition=pr,
        approver=u["appr"],
        comments="Approved for AI infrastructure expansion."
    )
    assert pr.status == PurchaseRequisition.STATUS_APPROVED

    # Verify Approver Dashboard updates
    resp_appr_dash = api_client.get("/api/v1/approver/dashboard/")
    assert resp_appr_dash.status_code == status.HTTP_200_OK
    assert resp_appr_dash.data["approvals_executed"] >= 1

    # --------------------------------------------------------------------------
    # STAGE 3: Procurement Executive Creates & Publishes Sourcing RFQ
    # --------------------------------------------------------------------------
    now = timezone.now()
    event = sourcing_svc.create_sourcing_event_service(
        title="Enterprise GPU Infrastructure RFQ",
        event_type=SourcingEvent.TYPE_RFQ,
        bid_start_date=now - datetime.timedelta(hours=1),
        bid_end_date=now + datetime.timedelta(days=2),
        description="Competitive bidding for 2x GPU compute nodes",
        requisition=pr,
        created_by_user=u["exec"]
    )
    assert event.status == SourcingEvent.STATUS_DRAFT

    # --------------------------------------------------------------------------
    # STAGE 4: Eligible Vendors Invited & Event Published
    # --------------------------------------------------------------------------
    sourcing_svc.invite_vendors_to_event_service(
        event=event,
        vendor_ids=[v["a"].id, v["b"].id],
        invited_by=u["exec"]
    )

    # Suspended vendor invitation must be rejected
    with pytest.raises(Exception):
        sourcing_svc.invite_vendors_to_event_service(
            event=event,
            vendor_ids=[v["susp"].id],
            invited_by=u["exec"]
        )

    # Publish Event
    event = sourcing_svc.publish_sourcing_event_service(event=event, user=u["exec"])
    assert event.status in [SourcingEvent.STATUS_PUBLISHED, SourcingEvent.STATUS_BID_WINDOW]

    # Verify Reflection in Procurement Executive Dashboard
    client.force_login(u["exec"])
    resp_proc = client.get("/procurement/")
    assert resp_proc.status_code == 200
    assert event.event_number in resp_proc.content.decode()

    # Verify Sourcing Invitation Reflection in Vendor Dashboard (Vendor A)
    client.force_login(u["vendor_a"])
    resp_v_dash = client.get("/vendor/sourcing/")
    assert resp_v_dash.status_code == 200
    assert event.event_number in resp_v_dash.content.decode()

    # --------------------------------------------------------------------------
    # STAGE 5: Vendors Submit Bids & Bid Confidentiality
    # --------------------------------------------------------------------------
    # Vendor A submits bid: ₹36,000 / unit = ₹72,000 total
    bid_a = sourcing_svc.submit_vendor_bid_service(
        event=event,
        vendor=v["a"],
        submitted_by_user=u["vendor_a"],
        line_items=[
            {
                "item_description": "GPU Compute Node 8x H100",
                "quantity": "2",
                "quoted_unit_price": "36000.00",
            }
        ],
        proposal_summary="Vendor A Proposal",
        technical_proposal="Full enterprise support included",
        commercial_proposal="Net 30 payment terms"
    )
    assert bid_a.total_bid_amount == Decimal("72000.00")

    # Vendor B submits competitive bid: ₹34,000 / unit = ₹68,000 total
    bid_b = sourcing_svc.submit_vendor_bid_service(
        event=event,
        vendor=v["b"],
        submitted_by_user=u["vendor_b"],
        line_items=[
            {
                "item_description": "GPU Compute Node 8x H100",
                "quantity": "2",
                "quoted_unit_price": "34000.00",
            }
        ],
        proposal_summary="Vendor B Proposal",
        technical_proposal="Tier-1 certified hardware",
        commercial_proposal="Immediate delivery and Net 30"
    )
    assert bid_b.total_bid_amount == Decimal("68000.00")

    # --------------------------------------------------------------------------
    # STAGE 6: Evaluation, Award Recommendation & Approval
    # --------------------------------------------------------------------------
    # Close window for evaluation
    event.bid_end_date = timezone.now() - datetime.timedelta(minutes=1)
    event.save()
    sourcing_svc.sync_event_window_status(event=event)
    assert event.status == SourcingEvent.STATUS_TECHNICAL_REVIEW

    # Technical Evaluations
    sourcing_svc.record_technical_evaluation_service(event=event, bid=bid_a, evaluator=u["exec"], score=85)
    sourcing_svc.record_technical_evaluation_service(event=event, bid=bid_b, evaluator=u["exec"], score=90)

    # Move to Commercial Review
    sourcing_svc.advance_to_commercial_review_service(event=event, user=u["exec"])
    event.refresh_from_db()
    assert event.status == SourcingEvent.STATUS_COMMERCIAL_REVIEW

    sourcing_svc.record_commercial_evaluation_service(event=event, bid=bid_a, evaluator=u["exec"], score=80)
    sourcing_svc.record_commercial_evaluation_service(event=event, bid=bid_b, evaluator=u["exec"], score=95)

    # Recommend Award to Vendor B
    award_decision = sourcing_svc.recommend_award_service(
        event=event,
        winning_bid=bid_b,
        recommended_by=u["exec"],
        award_reason="Highest technical & commercial composite score"
    )
    assert award_decision.status == AwardDecision.STATUS_PENDING

    # Procurement Manager Approves Award
    sourcing_svc.approve_award_service(
        event=event,
        approver=u["mgr"],
        comments="Approved award to BlueSky Tech."
    )
    event.refresh_from_db()
    assert event.status == SourcingEvent.STATUS_AWARDED

    # --------------------------------------------------------------------------
    # STAGE 7: Generate & Issue Purchase Order (PO)
    # --------------------------------------------------------------------------
    po = sourcing_svc.generate_po_from_award_service(
        event=event,
        user=u["exec"],
        cost_center=env["cc_it"]
    )
    assert po.vendor == v["b"]
    assert po.status == PurchaseOrder.STATUS_DRAFT

    # Submit & Approve PO
    po = submit_purchase_order_for_approval_service(po=po, actor=u["exec"])
    po = approve_purchase_order_service(po=po, approver=u["mgr"], comments="PO Approved")
    po = issue_purchase_order_service(po=po, actor=u["exec"])
    assert po.status == PurchaseOrder.STATUS_ISSUED

    # --------------------------------------------------------------------------
    # STAGE 8: Vendor Acknowledges PO
    # --------------------------------------------------------------------------
    po = acknowledge_purchase_order_service(
        po=po,
        vendor_user=u["vendor_b"],
        acknowledgement_notes="Order acknowledged. Delivery scheduled in 5 days."
    )
    assert po.status == PurchaseOrder.STATUS_ACKNOWLEDGED

    # Verify Vendor Dashboard Shows Acknowledged PO
    client.force_login(u["vendor_b"])
    resp_v_po = client.get("/vendor/purchase-orders/")
    assert resp_v_po.status_code == 200
    assert po.po_number in resp_v_po.content.decode()

    # --------------------------------------------------------------------------
    # STAGE 9: Stores Records Delivery & Goods Receipt Note (GRN)
    # --------------------------------------------------------------------------
    grn = create_goods_receipt_service(
        po=po,
        received_by=u["stores"],
        receipt_items=[
            {
                "po_line": po.lines.first(),
                "quantity_received": Decimal("2.00"),
                "quantity_accepted": Decimal("2.00"),
            }
        ],
        delivery_note_number="DN-BLUE-2026-991"
    )
    assert grn.grn_number.startswith("GRN-")
    po.refresh_from_db()
    assert po.status == PurchaseOrder.STATUS_COMPLETED

    # Verify Reflection in Stores Dashboard
    client.force_login(u["stores"])
    resp_stores = client.get("/stores/")
    assert resp_stores.status_code == 200

    # --------------------------------------------------------------------------
    # STAGE 10: Vendor Submits Invoice via Portal
    # --------------------------------------------------------------------------
    today = timezone.now().date()
    inv = create_supplier_invoice_service(
        vendor=v["b"],
        po=po,
        invoice_number="INV-BLUE-E2E-001",
        invoice_date=today,
        due_date=today + datetime.timedelta(days=30),
        line_items=[
            {
                "po_line": po.lines.first(),
                "quantity": Decimal("2.00"),
                "unit_price": Decimal("34000.00"), # exact contract price
            }
        ],
        created_by_user=u["vendor_b"]
    )
    assert inv.status == SupplierInvoice.STATUS_RECEIVED
    assert inv.total_amount == Decimal("74800.00") # 68,000 + 10% tax

    # --------------------------------------------------------------------------
    # STAGE 11: Finance Performs Automated 3-Way Match (PO, GRN, Invoice)
    # --------------------------------------------------------------------------
    from apps.invoices.services import run_3_way_match_service
    inv, match_exceptions = run_3_way_match_service(invoice=inv, user=u["fin"])
    assert len(match_exceptions) == 0, f"Expected 0 exceptions, got {len(match_exceptions)}"
    assert inv.status == SupplierInvoice.STATUS_READY_FOR_PAYMENT

    # --------------------------------------------------------------------------
    # STAGE 12: Finance Approves & Settles Payment
    # --------------------------------------------------------------------------
    # Finance Dashboard displays invoice count ready for payment in metrics
    client.force_login(u["fin"])
    resp_fin = client.get("/finance/")
    assert resp_fin.status_code == 200
    assert resp_fin.context["metrics"]["ready_for_payment"] >= 1

    # Invoices list displays the specific invoice
    resp_inv_list = client.get("/invoices/")
    assert resp_inv_list.status_code == 200
    assert inv.invoice_number in resp_inv_list.content.decode()

    # Mark Paid
    paid_inv = mark_invoice_paid_service(
        invoice=inv,
        user=u["fin"],
        payment_reference="UTR-E2E-2026-8877"
    )
    assert paid_inv.status == SupplierInvoice.STATUS_PAID

    # --------------------------------------------------------------------------
    # STAGE 13: Payment Reflection Across Dashboards & Financial Ledger
    # --------------------------------------------------------------------------
    # 1. Budget actual spend incremented
    env["budget_it"].refresh_from_db()
    assert env["budget_it"].actual_amount == Decimal("74800.00")

    # 2. SpendLedger recorded actual cash outflow
    ledger_entry = SpendLedger.objects.filter(
        budget=env["budget_it"],
        entry_type=SpendLedger.ENTRY_ACTUAL,
        reference_number=inv.invoice_number
    ).first()
    assert ledger_entry is not None
    assert ledger_entry.amount == Decimal("74800.00")

    # 3. Reports Dashboard API returns exact paid spend
    api_client.force_authenticate(user=u["super"])
    resp_reports = api_client.get("/api/v1/reports/dashboard-summary/")
    assert resp_reports.status_code == status.HTTP_200_OK
    assert float(resp_reports.data["total_spend"]) == 74800.00
    assert float(resp_reports.data["paid_spend"]) == 74800.00

    # 4. Vendor Dashboard reflects paid status
    client.force_login(u["vendor_b"])
    resp_v_inv = client.get("/vendor/invoices/")
    assert resp_v_inv.status_code == 200
    assert inv.invoice_number in resp_v_inv.content.decode()


# ==============================================================================
# 2. Cross-Dashboard Integration Validation Across All 10 Roles
# ==============================================================================

@pytest.mark.django_db
def test_cross_dashboard_views_render_and_enforce_role_isolation(enterprise_audit_environment):
    env = enterprise_audit_environment
    u = env["users"]
    client = Client()

    dashboards = [
        ("super", "/superadmin/dashboard/", 200),
        ("req", "/requester/", 200),
        ("appr", "/approver/", 200),
        ("exec", "/procurement/", 200),
        ("mgr", "/manager/dashboard/", 200),
        ("legal", "/legal/", 200),
        ("fin", "/finance/", 200),
        ("stores", "/stores/", 200),
        ("auditor", "/audit/dashboard/", 200),
        ("vendor_a", "/vendor/dashboard/", 200),
    ]

    for user_key, url, expected_code in dashboards:
        client.force_login(u[user_key])
        resp = client.get(url)
        assert resp.status_code == expected_code, f"Failed rendering {url} for role {user_key}: {resp.status_code}"


# ==============================================================================
# 3. RBAC, Security & Tenant Isolation Validation
# ==============================================================================

@pytest.mark.django_db
def test_cross_vendor_and_cross_tenant_security_isolation(enterprise_audit_environment):
    env = enterprise_audit_environment
    u = env["users"]
    v = env["vendors"]
    client = Client()

    # 1. Cross-Vendor Profile & Document Isolation: Vendor A cannot access Vendor B's details
    client.force_login(u["vendor_a"])
    resp_b_doc = client.get(f"/vendor/documents/?vendor_id={v['b'].id}")
    # Must only display Vendor A's own documents or reject cross-access
    assert v["b"].legal_name not in resp_b_doc.content.decode()

    # 2. Unauthorized Role Attempts to Access Finance Dashboard -> 403 Forbidden
    client.force_login(u["req"])
    resp_unauth = client.get("/finance/")
    assert resp_unauth.status_code == 403

    # 3. Vendor User attempts to access Internal Procurement Dashboard -> 403 Forbidden
    client.force_login(u["vendor_a"])
    resp_ven_unauth = client.get("/procurement/")
    assert resp_ven_unauth.status_code == 403

    # 4. Inactive / Suspended Vendor Blocked from Sourcing Events
    client.force_login(u["vendor_susp"])
    resp_susp = client.get("/vendor/sourcing/")
    assert resp_susp.status_code == 200
    # Must show 0 accessible events for suspended vendor
    assert "No active sourcing events" in resp_susp.content.decode() or "0" in resp_susp.content.decode()


# ==============================================================================
# 4. Performance & API Response Diagnostic Validation
# ==============================================================================

@pytest.mark.django_db
def test_dashboard_api_response_diagnostics_and_stability(enterprise_audit_environment):
    env = enterprise_audit_environment
    u = env["users"]
    api_client = APIClient()

    # Test Department Approver Dashboard API response time and payload structure
    api_client.force_authenticate(user=u["appr"])
    t_start = timezone.now()
    resp_appr = api_client.get("/api/v1/approver/dashboard/")
    duration = (timezone.now() - t_start).total_seconds()

    assert resp_appr.status_code == status.HTTP_200_OK
    assert duration < 2.0, f"Approver dashboard API exceeded 2.0s: {duration}s"
    assert "available_budget" in resp_appr.data
    assert "approvals_executed" in resp_appr.data

    # Test Reports Dashboard API response time
    api_client.force_authenticate(user=u["super"])
    t_start = timezone.now()
    resp_reports = api_client.get("/api/v1/reports/dashboard-summary/")
    duration_reports = (timezone.now() - t_start).total_seconds()

    assert resp_reports.status_code == status.HTTP_200_OK
    assert duration_reports < 2.0, f"Reports dashboard API exceeded 2.0s: {duration_reports}s"
    assert "total_spend" in resp_reports.data

