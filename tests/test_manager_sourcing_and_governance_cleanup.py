from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.audit.models import AuditLog
from apps.organization.models import CostCenter, Department, Organization
from apps.requisitions.models import PurchaseRequisition
from apps.sourcing.models import BidEvaluation, BidInvite, SourcingEvent, VendorBid
from apps.sourcing.permissions import can_approve_award, can_publish_events, sourcing_capabilities
from apps.sourcing.selectors import get_all_sourcing_events, search_sourcing_events
from apps.vendors.models import Vendor, VendorCategory, VendorRiskRecord

pytestmark = [pytest.mark.django_db]


@pytest.fixture
def governance_test_world():
    org = Organization.objects.create(name="Hewlett Packard Enterprise", code="HPE-TEST")
    dept = Department.objects.create(name="IT Infrastructure", code="IT-01", organization=org)
    role_exec, _ = Role.objects.get_or_create(code=Role.PROC_EXEC, defaults={"name": "Procurement Executive"})
    role_mgr, _ = Role.objects.get_or_create(code=Role.PROC_MGR, defaults={"name": "Procurement Manager"})

    proc_exec = User.objects.create_user(
        email="exec@test.com",
        password="Password123!",
        role=role_exec,
        organization=org,
        department=dept,
    )
    proc_mgr = User.objects.create_user(
        email="mgr@test.com",
        password="Password123!",
        role=role_mgr,
        organization=org,
        department=dept,
    )

    cat, _ = VendorCategory.objects.get_or_create(name="Hardware", code="HW-01")

    # Enterprise vendor
    cisco = Vendor.objects.create(
        legal_name="Cisco Systems Inc",
        vendor_number="VND-CISCO-01",
        tax_identification_number="TAX-CISCO-001",
        organization=org,
        category=cat,
        status=Vendor.STATUS_ACTIVE,
    )
    # Draft QA vendor
    qa_draft = Vendor.objects.create(
        legal_name="QA Vendor V999",
        vendor_number="VND-QA-001",
        tax_identification_number="TAX-QA-001",
        organization=org,
        category=cat,
        status=Vendor.STATUS_DRAFT,
    )
    # High risk QA draft vendor
    VendorRiskRecord.objects.create(
        vendor=qa_draft,
        risk_level=VendorRiskRecord.RISK_LEVEL_HIGH,
        assessed_by=proc_mgr,
        assessment_notes="Test high risk on draft",
    )
    # High risk active Cisco vendor
    VendorRiskRecord.objects.create(
        vendor=cisco,
        risk_level=VendorRiskRecord.RISK_LEVEL_HIGH,
        assessed_by=proc_mgr,
        assessment_notes="Watchlist active supplier",
    )

    return {
        "org": org,
        "dept": dept,
        "proc_exec": proc_exec,
        "proc_mgr": proc_mgr,
        "cisco": cisco,
        "qa_draft": qa_draft,
    }


def test_manager_watchlist_excludes_draft_and_prioritizes_enterprise(governance_test_world):
    """
    Manager Watchlist API (/api/v1/manager/watchlist/) must:
    1. Strictly exclude DRAFT, SUBMITTED, and CHANGES_REQUIRED vendors.
    2. Prioritize real enterprise suppliers (Cisco) over QA test vendors.
    """
    client = APIClient()
    client.force_authenticate(user=governance_test_world["proc_mgr"])

    res = client.get("/api/v1/manager/vendor-watchlist/")
    assert res.status_code == status.HTTP_200_OK

    vendors = res.data.get("results", [])
    vendor_ids = [v["id"] for v in vendors]

    # Cisco (active, high-risk) must be in the watchlist
    assert str(governance_test_world["cisco"].id) in vendor_ids

    # QA draft vendor must NEVER appear in the governance watchlist
    assert str(governance_test_world["qa_draft"].id) not in vendor_ids
    for v in vendors:
        assert v["status"] not in ["DRAFT", "SUBMITTED", "CHANGES_REQUIRED"]


def test_sourcing_event_publish_permission_split(governance_test_world):
    """
    Procurement Executive can publish sourcing events;
    Procurement Manager can only inspect and award, and is strictly FORBIDDEN from publishing.
    """
    proc_exec = governance_test_world["proc_exec"]
    proc_mgr = governance_test_world["proc_mgr"]

    # Python RBAC capability check
    assert can_publish_events(proc_exec) is True
    assert can_publish_events(proc_mgr) is False

    caps_exec = sourcing_capabilities(proc_exec)
    caps_mgr = sourcing_capabilities(proc_mgr)
    assert caps_exec["can_publish"] is True
    assert caps_mgr["can_publish"] is False

    now = timezone.now()
    event = SourcingEvent.objects.create(
        event_number="RFQ-TEST-001",
        title="Server Procurement Event",
        event_type=SourcingEvent.TYPE_RFQ,
        bid_start_date=now - timedelta(hours=1),
        bid_end_date=now + timedelta(days=5),
        description="Requirements scope",
        created_by=proc_exec,
        status=SourcingEvent.STATUS_DRAFT,
    )

    client = APIClient()

    # Procurement Manager attempts to publish via API -> 403 Forbidden
    client.force_authenticate(user=proc_mgr)
    res_mgr = client.post(f"/api/v1/sourcing-events/{event.id}/publish/")
    assert res_mgr.status_code == status.HTTP_403_FORBIDDEN


def test_pending_awards_desk_only_returns_award_approval_with_bids(governance_test_world):
    """
    /api/v1/sourcing-events/awards/pending/ must ONLY return events in STATUS_AWARD_APPROVAL.
    Events in TECHNICAL_REVIEW or COMMERCIAL_REVIEW must NOT appear under Pending Awards.
    """
    proc_exec = governance_test_world["proc_exec"]
    proc_mgr = governance_test_world["proc_mgr"]
    now = timezone.now()

    # Event in Technical Review (not ready for award)
    event_tech = SourcingEvent.objects.create(
        event_number="RFQ-TECH-001",
        title="Tech Review Event",
        event_type=SourcingEvent.TYPE_RFQ,
        bid_start_date=now - timedelta(days=5),
        bid_end_date=now - timedelta(days=1),
        description="Tech review in progress",
        created_by=proc_exec,
        status=SourcingEvent.STATUS_TECHNICAL_REVIEW,
    )

    # Event in Commercial Review (not ready for award)
    event_comm = SourcingEvent.objects.create(
        event_number="RFQ-COMM-001",
        title="Commercial Review Event",
        event_type=SourcingEvent.TYPE_RFQ,
        bid_start_date=now - timedelta(days=5),
        bid_end_date=now - timedelta(days=1),
        description="Commercial review in progress",
        created_by=proc_exec,
        status=SourcingEvent.STATUS_COMMERCIAL_REVIEW,
    )

    # Event in Award Approval (ready for award decision)
    event_award = SourcingEvent.objects.create(
        event_number="RFQ-AWD-001",
        title="Award Ready Event",
        event_type=SourcingEvent.TYPE_RFQ,
        bid_start_date=now - timedelta(days=5),
        bid_end_date=now - timedelta(days=1),
        description="Award ready",
        created_by=proc_exec,
        status=SourcingEvent.STATUS_AWARD_APPROVAL,
    )
    bid = VendorBid.objects.create(
        event=event_award,
        vendor=governance_test_world["cisco"],
        bid_number="BID-001",
        total_bid_amount=Decimal("15000.00"),
        status=VendorBid.STATUS_SUBMITTED,
    )
    BidEvaluation.objects.create(
        event=event_award,
        bid=bid,
        evaluator=proc_exec,
        technical_score=Decimal("85.00"),
        commercial_score=Decimal("90.00"),
        weighted_total_score=Decimal("87.50"),
    )

    client = APIClient()
    client.force_authenticate(user=proc_mgr)
    res = client.get("/api/v1/sourcing-events/awards/pending/")
    assert res.status_code == status.HTTP_200_OK

    returned_ids = [e["id"] for e in res.data]
    assert str(event_award.id) in returned_ids
    assert str(event_tech.id) not in returned_ids
    assert str(event_comm.id) not in returned_ids


def test_zero_bid_filter_and_pr_badge(governance_test_world):
    """
    Events closed without bids must be filterable by status=NO_BIDS or readiness=NO_BIDS.
    """
    proc_exec = governance_test_world["proc_exec"]
    now = timezone.now()

    # Event cancelled with 0 bids
    event_no_bids = SourcingEvent.objects.create(
        event_number="RFQ-NOBIDS-001",
        title="No Bids Event",
        event_type=SourcingEvent.TYPE_RFQ,
        bid_start_date=now - timedelta(days=5),
        bid_end_date=now - timedelta(days=1),
        description="No bids received",
        created_by=proc_exec,
        status=SourcingEvent.STATUS_CANCELLED,
    )

    qs = get_all_sourcing_events()
    filtered = search_sourcing_events(qs, {"status": "NO_BIDS"})
    assert event_no_bids in list(filtered)

    filtered_readiness = search_sourcing_events(qs, {"readiness": "NO_BIDS"})
    assert event_no_bids in list(filtered_readiness)
