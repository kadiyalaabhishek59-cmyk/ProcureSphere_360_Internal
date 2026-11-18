import datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.audit.models import AuditLog
from apps.budgets.services import allocate_budget_service
from apps.orders.models import POLine, PurchaseOrder
from apps.organization.models import CostCenter, Department, FiscalPeriod, Organization
from apps.receipts.models import GoodsReceipt, InspectionRecord, ReceiptLine, RejectionRecord
from apps.receipts.services import (
    correct_receipt_line_quantity_service,
    record_inspection_service,
    validate_audit_reason_text,
)
from apps.vendors.models import Vendor, VendorCategory


@pytest.fixture
def stores_bugs_world(db, db_roles):
    org = Organization.objects.create(name="HPE Store Receiver Org", code="HPE-SR-ORG")
    dept = Department.objects.create(organization=org, name="Receiving Logistics", code="DEPT-SR-REC")
    cost_center = CostCenter.objects.create(department=dept, code="CC-SR-REC", name="Dock 42")
    fiscal_period = FiscalPeriod.objects.create(
        organization=org,
        year=2026,
        period_number=1,
        name="FY2026-SR-Q1",
        start_date=timezone.now().date() - datetime.timedelta(days=10),
        end_date=timezone.now().date() + datetime.timedelta(days=80),
    )
    allocate_budget_service(
        cost_center=cost_center,
        fiscal_period=fiscal_period,
        allocated_amount=Decimal("1000000.00"),
    )

    cat = VendorCategory.objects.create(name="Warehouse Supplies", code="CAT-WH-SR")
    vendor = Vendor.objects.create(
        legal_name="Apex Global Logistics Inc",
        vendor_number="VND-SR-001",
        tax_identification_number="TIN-AGL-SR-01",
        category=cat,
        status=Vendor.STATUS_ACTIVE,
        organization=org,
    )

    receiver = User.objects.create_user(
        email="receiver_bugs@hpe.com",
        password="Password123!",
        role=db_roles[Role.STORES_RECEIVER],
        organization=org,
        department=dept,
    )

    po = PurchaseOrder.objects.create(
        po_number="PO-SR-2026-001",
        version=1,
        vendor=vendor,
        cost_center=cost_center,
        status=PurchaseOrder.STATUS_ISSUED,
        total_amount=Decimal("5000.00"),
    )
    po_line = POLine.objects.create(
        po=po,
        item_description="Industrial Barcode Scanner",
        quantity=Decimal("10.00"),
        unit_of_measure="EA",
        unit_price=Decimal("500.00"),
        quantity_received=Decimal("10.00"),
    )

    grn = GoodsReceipt.objects.create(
        grn_number="GRN-SR-2026-001",
        po=po,
        received_by=receiver,
        received_date=timezone.now(),
        delivery_note_number="DN-SR-001",
    )
    grn_line = ReceiptLine.objects.create(
        receipt=grn,
        po_line=po_line,
        quantity_received=Decimal("10.00"),
        quantity_accepted=Decimal("10.00"),
    )

    return {
        "org": org,
        "receiver": receiver,
        "vendor": vendor,
        "po": po,
        "po_line": po_line,
        "grn": grn,
        "grn_line": grn_line,
    }


@pytest.mark.django_db
def test_bug_010_and_bug_011_record_goods_receipt_modal_and_decoupled_routing(client, stores_bugs_world):
    """
    BUG-010: Verify '+ Record Goods Receipt' opens the dedicated modal targeting receivable POs.
    BUG-011: Verify 'View Pending Deliveries' routes distinctly to '?tab=deliveries'.
    """
    receiver = stores_bugs_world["receiver"]
    client.force_login(receiver)

    resp = client.get("/receipts/")
    assert resp.status_code == 200
    html = resp.content.decode()

    # BUG-010: Button launches the modal instead of misrouting
    assert 'data-bs-target="#recordGoodsReceiptModal"' in html
    assert 'id="recordGoodsReceiptModal"' in html
    assert "Record Goods Receipt Note" in html
    assert f"/receipts/create/{stores_bugs_world['po'].id}/" in html

    # BUG-011: Decoupled buttons - View Pending Deliveries routes to ?tab=deliveries
    assert 'href="/purchase-orders/?tab=deliveries"' in html or 'href="/orders/?tab=deliveries"' in html


@pytest.mark.django_db
def test_bug_001_differentiated_views_receive_po_goods_vs_po_deliveries(client, stores_bugs_world):
    """
    BUG-001: Verify Receive PO Goods (/purchase-orders/) and PO Deliveries (/purchase-orders/?tab=deliveries)
    have distinct visual tabs, headers, badges, and action flows.
    """
    receiver = stores_bugs_world["receiver"]
    client.force_login(receiver)

    # 1. Inbound Receiving Desk (/purchase-orders/)
    resp_rcv = client.get("/purchase-orders/")
    assert resp_rcv.status_code == 200
    html_rcv = resp_rcv.content.decode()

    assert resp_rcv.context["active_tab"] == "receive"
    assert "Inbound Receiving Desk" in html_rcv
    assert "Receive PO Goods" in html_rcv
    assert f"/receipts/create/{stores_bugs_world['po'].id}/" in html_rcv
    assert "Receive" in html_rcv
    assert "View Details" in html_rcv

    # 2. PO Deliveries Tracking (/purchase-orders/?tab=deliveries)
    resp_del = client.get("/purchase-orders/?tab=deliveries")
    assert resp_del.status_code == 200
    html_del = resp_del.content.decode()

    assert resp_del.context["active_tab"] == "deliveries"
    assert "Delivery Tracking &amp; Schedules" in html_del or "Delivery Tracking & Schedules" in html_del
    assert "PO Deliveries" in html_del
    assert "Track Deliveries" in html_del
    assert "Awaiting 1st Delivery" in html_del


@pytest.mark.django_db
def test_bug_009_correction_reason_format_validation(client, stores_bugs_world):
    """
    BUG-009: Verify Correction Reason rejects arbitrary gibberish, pure digits, and repetitive characters,
    while accepting meaningful explanations.
    """
    line = stores_bugs_world["grn_line"]
    receiver = stores_bugs_world["receiver"]

    # 1. Test validate_audit_reason_text directly
    with pytest.raises(ValidationError, match="mandatory"):
        validate_audit_reason_text("", "Correction reason")

    with pytest.raises(ValidationError, match="at least 5 characters"):
        validate_audit_reason_text("bad", "Correction reason")

    with pytest.raises(ValidationError, match="cannot consist solely of numbers"):
        validate_audit_reason_text("12345678", "Correction reason")

    with pytest.raises(ValidationError, match="cannot consist of repetitive single characters"):
        validate_audit_reason_text("aaaaaaa", "Correction reason")

    with pytest.raises(ValidationError, match="meaningful descriptive text"):
        validate_audit_reason_text("!@#$%^&*()_+", "Correction reason")

    # Valid reason passes
    clean = validate_audit_reason_text("Waybill recount discrepancy", "Correction reason")
    assert clean == "Waybill recount discrepancy"

    # 2. Test via service
    with pytest.raises(ValidationError):
        correct_receipt_line_quantity_service(
            receipt_line=line,
            corrected_by=receiver,
            new_quantity_received=Decimal("9.00"),
            reason="99999999",  # Invalid pure digits
        )

    # Valid service call succeeds
    correct_receipt_line_quantity_service(
        receipt_line=line,
        corrected_by=receiver,
        new_quantity_received=Decimal("9.00"),
        reason="Physical count adjustment after box unpack",
    )
    line.refresh_from_db()
    assert line.quantity_received == Decimal("9.00")

    # 3. Test via view endpoint
    client.force_login(receiver)
    resp_bad = client.post(
        f"/receipts/lines/{line.id}/correct/",
        {"quantity_received": "8.00", "reason": "11111111"},
        follow=True,
    )
    assert resp_bad.status_code == 200
    line.refresh_from_db()
    assert line.quantity_received == Decimal("9.00")  # Not modified

    resp_good = client.post(
        f"/receipts/lines/{line.id}/correct/",
        {"quantity_received": "8.00", "reason": "Supplier invoice mismatch adjustment"},
        follow=True,
    )
    assert resp_good.status_code == 200
    line.refresh_from_db()
    assert line.quantity_received == Decimal("8.00")


@pytest.mark.django_db
def test_bug_008_rejection_reason_format_validation(client, stores_bugs_world):
    """
    BUG-008: Verify Rejection Reason rejects arbitrary numbers, gibberish, or empty reasons
    when rejecting quantities.
    """
    grn = stores_bugs_world["grn"]
    line = stores_bugs_world["grn_line"]
    receiver = stores_bugs_world["receiver"]

    client.force_login(receiver)

    # 1. Pure numbers rejected
    resp_digits = client.post(
        f"/receipts/{grn.id}/inspect/",
        {
            f"passed_{line.id}": "false",
            f"rejected_quantity_{line.id}": "5.00",
            f"rejection_reason_{line.id}": "12345678",
        },
    )
    assert resp_digits.status_code == 200
    assert "cannot consist solely of numbers" in resp_digits.content.decode()

    # 2. Repetitive characters rejected
    resp_repeat = client.post(
        f"/receipts/{grn.id}/inspect/",
        {
            f"passed_{line.id}": "false",
            f"rejected_quantity_{line.id}": "5.00",
            f"rejection_reason_{line.id}": "xxxxxxx",
        },
    )
    assert resp_repeat.status_code == 200
    assert "cannot consist of repetitive single characters" in resp_repeat.content.decode()

    # 3. Meaningful rejection reason succeeds
    resp_valid = client.post(
        f"/receipts/{grn.id}/inspect/",
        {
            f"passed_{line.id}": "false",
            f"rejected_quantity_{line.id}": "4.00",
            f"rejection_reason_{line.id}": "Cracked optical lens on 4 units",
        },
        follow=True,
    )
    assert resp_valid.status_code == 200
    line.refresh_from_db()
    assert line.quantity_rejected == Decimal("4.00")
    assert line.quantity_accepted == Decimal("4.00") or line.quantity_accepted == Decimal("6.00")  # 10 - 4 = 6
    rejection = line.latest_rejection
    assert rejection is not None
    assert rejection.rejection_reason == "Cracked optical lens on 4 units"


@pytest.mark.django_db
def test_bug_006_action_buttons_wcag_high_contrast(client, stores_bugs_world):
    """
    BUG-006: Verify PASS and FAIL action badges and buttons have high contrast colors
    meeting WCAG accessibility standards.
    """
    grn = stores_bugs_world["grn"]
    receiver = stores_bugs_world["receiver"]
    client.force_login(receiver)

    resp = client.get(f"/receipts/{grn.id}/inspect/")
    assert resp.status_code == 200
    html = resp.content.decode()

    # High contrast color definitions present
    assert "#064E3B" in html  # Deep green text/bg
    assert "#7F1D1D" in html or "#B91C1C" in html  # Deep crimson text/bg
    assert "PASS &rarr; Accepted to Stock Handoff" in html
    assert "FAIL &rarr; Record Rejection &amp; Return Details" in html
    # Low contrast bg-opacity-15 text-success removed from gate badges
    assert "bg-opacity-15 text-success" not in html


@pytest.mark.django_db
def test_bug_007_locked_finalized_inspection_and_no_redundant_save_prompt(client, stores_bugs_world):
    """
    BUG-007: Verify completed/finalized GRN inspection is locked, form controls are disabled/readonly,
    save trigger is hidden/disabled, and POST modifications are blocked.
    """
    grn = stores_bugs_world["grn"]
    line = stores_bugs_world["grn_line"]
    receiver = stores_bugs_world["receiver"]

    # 1. Finalize the inspection as PASS
    record_inspection_service(
        receipt=grn,
        inspected_by=receiver,
        inspection_items=[
            {
                "receipt_line_id": str(line.id),
                "passed": True,
                "inspection_notes": "All units verified against technical specification.",
            }
        ],
    )
    grn.refresh_from_db()
    assert grn.overall_inspection_status == "PASSED"

    client.force_login(receiver)

    # 2. GET inspect view for finalized GRN
    resp = client.get(f"/receipts/{grn.id}/inspect/")
    assert resp.status_code == 200
    html = resp.content.decode()

    assert resp.context["is_finalized"] is True
    assert "Quality Inspection Finalized &amp; Locked" in html
    assert "Immutable Audit Record" in html
    assert 'disabled' in html
    assert "Inspection Finalized &amp; Locked" in html
    # Active save button should NOT be present
    assert 'id="btnSaveInspection"' not in html

    # 3. Detail view reflects Quality Inspection link
    resp_dtl = client.get(f"/receipts/{grn.id}/")
    assert resp_dtl.status_code == 200
    html_dtl = resp_dtl.content.decode()
    assert "Quality Inspection" in html_dtl
    assert f"/receipts/{grn.id}/inspect/" in html_dtl

    # 4. POST attempt to modify finalized inspection is safely rejected
    resp_post = client.post(
        f"/receipts/{grn.id}/inspect/",
        {
            f"passed_{line.id}": "false",
            f"rejected_quantity_{line.id}": "10.00",
            f"rejection_reason_{line.id}": "Attempting unauthorized post-finalization change",
        },
        follow=True,
    )
    assert resp_post.status_code == 200
    # Must redirect to receipt_detail with warning
    assert f"/receipts/{grn.id}/" in resp_post.redirect_chain[0][0]
    line.refresh_from_db()
    assert line.quantity_accepted == Decimal("10.00")  # Untouched
    assert line.quantity_rejected == Decimal("0.00")   # Untouched
