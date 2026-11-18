from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.budgets.models import Budget
from apps.invoices.models import SupplierInvoice
from apps.orders.models import POLine, PurchaseOrder
from apps.organization.models import CostCenter, Department, FiscalPeriod, Organization
from apps.vendors.models import Vendor, VendorCategory


@pytest.fixture
def invoice_test_env(db):
    org = Organization.objects.create(name="Finance Test Org", code="ORG-FIN-01")
    dept = Department.objects.create(organization=org, name="Information Tech", code="DEPT-IT-01")
    cc = CostCenter.objects.create(department=dept, code="CC-IT-01", name="IT Infra")
    today = timezone.now().date()
    fp = FiscalPeriod.objects.create(
        organization=org,
        year=today.year,
        period_number=1,
        name=f"FY{today.year}-P1",
        start_date=today.replace(month=1, day=1),
        end_date=today.replace(month=12, day=31),
    )
    Budget.objects.create(
        cost_center=cc,
        fiscal_period=fp,
        allocated_amount=Decimal("1000000.00"),
    )
    cat = VendorCategory.objects.create(name="IT Hardware", code="CAT-HW-01")
    vendor = Vendor.objects.create(
        legal_name="Cisco Global Systems",
        trade_name="Cisco",
        vendor_number="VND-CISCO-001",
        tax_identification_number="TIN-CISCO-001",
        status=Vendor.STATUS_ACTIVE,
        category=cat,
        organization=org,
    )
    po = PurchaseOrder.objects.create(
        po_number="PO-2026-8801",
        vendor=vendor,
        cost_center=cc,
        status=PurchaseOrder.STATUS_ISSUED,
        total_amount=Decimal("10000.00"),
    )
    po_line = POLine.objects.create(
        po=po,
        item_description="Enterprise Router",
        quantity=Decimal("2.00"),
        unit_price=Decimal("5000.00"),
        line_total=Decimal("10000.00"),
    )

    finance_role, _ = Role.objects.get_or_create(
        code=Role.FINANCE_AP, defaults={"name": "Finance / AP"}
    )
    finance_user = User.objects.create_user(
        email="ap_officer@example.com",
        password="Password123!",
        role=finance_role,
        organization=org,
    )

    ready_invoice = SupplierInvoice.objects.create(
        vendor=vendor,
        po=po,
        invoice_number="INV-READY-001",
        invoice_date=timezone.now().date(),
        due_date=timezone.now().date(),
        status=SupplierInvoice.STATUS_READY_FOR_PAYMENT,
        subtotal=Decimal("10000.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal("10000.00"),
    )

    return {
        "org": org,
        "vendor": vendor,
        "po": po,
        "po_line": po_line,
        "finance_user": finance_user,
        "ready_invoice": ready_invoice,
    }


# ==============================================================================
# BUG-005: UTR / Payment Reference Validation Tests
# ==============================================================================


@pytest.mark.django_db
@pytest.mark.parametrize(
    "invalid_utr, expected_phrase",
    [
        ("445546!@#$%^&*()", "Special characters"),
        ("123", "between 6 and 50 characters"),
        ("-UTR12345", "Invalid Transaction Reference / UTR format"),
        ("<script>alert(1)</script>", "HTML"),
        ("   ", "Transaction / Payment Reference ID (UTR / Check #) is required"),
    ],
)
def test_bug_005_disburse_payment_rejects_invalid_utr_strings(
    client, invoice_test_env, invalid_utr, expected_phrase
):
    """Verify backend pay_invoice_view rejects invalid, malicious, or special-char UTR strings with clean messages."""
    client.force_login(invoice_test_env["finance_user"])
    invoice = invoice_test_env["ready_invoice"]

    resp = client.post(
        reverse("pay_invoice", kwargs={"invoice_id": invoice.id}),
        data={
            "payment_reference": invalid_utr,
            "payment_method": "ACH_TRANSFER",
            "payment_date": timezone.now().date().isoformat(),
        },
        follow=True,
    )
    assert resp.status_code == 200
    invoice.refresh_from_db()
    assert invoice.status == SupplierInvoice.STATUS_READY_FOR_PAYMENT  # Did not mark paid

    messages = [str(m) for m in resp.context["messages"]]
    assert any("Payment Validation Error" in m for m in messages)
    assert any(expected_phrase.lower() in m.lower() for m in messages)


@pytest.mark.django_db
def test_bug_005_disburse_payment_accepts_valid_utr(client, invoice_test_env):
    """Verify backend pay_invoice_view marks invoice PAID when given a valid UTR format."""
    client.force_login(invoice_test_env["finance_user"])
    invoice = invoice_test_env["ready_invoice"]

    resp = client.post(
        reverse("pay_invoice", kwargs={"invoice_id": invoice.id}),
        data={
            "payment_reference": "UTR-2026-981023",
            "payment_method": "ACH_TRANSFER",
            "payment_date": timezone.now().date().isoformat(),
        },
        follow=True,
    )
    assert resp.status_code == 200
    messages = [str(m) for m in resp.context["messages"]]
    print("PAY INVOICE MESSAGES:", messages)
    invoice.refresh_from_db()
    assert invoice.status == SupplierInvoice.STATUS_PAID
    assert invoice.payment_record is not None
    assert invoice.payment_record.payment_reference == "UTR-2026-981023"


def test_bug_005_templates_render_invalid_feedback_and_realtime_validation(
    client, invoice_test_env
):
    """Verify ready_list.html and detail.html render real-time validation elements and invalid-feedback containers."""
    client.force_login(invoice_test_env["finance_user"])
    invoice = invoice_test_env["ready_invoice"]

    # Check ready_list.html
    resp = client.get(reverse("ready_list"))
    assert resp.status_code == 200
    content = resp.content.decode()
    assert 'class="invalid-feedback fw-semibold"' in content
    assert f'id="pref_feedback_{invoice.id}"' in content
    assert "validateUtr" in content
    assert "addEventListener" in content
    assert "input" in content

    # Check detail.html
    resp = client.get(reverse("invoice_detail", kwargs={"invoice_id": invoice.id}))
    assert resp.status_code == 200
    content = resp.content.decode()
    assert 'id="detail_pref_feedback"' in content
    assert "validateDetailUtr" in content


# ==============================================================================
# BUG-007: Invoice Number Format Validation & Clear Messaging Tests
# ==============================================================================


@pytest.mark.django_db
@pytest.mark.parametrize(
    "invalid_inv, expected_phrase",
    [
        ("INV-10123!@#", "Special characters"),
        ("12", "between 3 and 50 characters"),
        ("<script>", "HTML"),
        ("-INV-10123", "must be alphanumeric"),
    ],
)
def test_bug_007_create_invoice_rejects_invalid_invoice_number_formats(
    client, invoice_test_env, invalid_inv, expected_phrase
):
    """Verify backend create_invoice_view rejects arbitrary/invalid invoice number strings with user-friendly error."""
    client.force_login(invoice_test_env["finance_user"])
    vendor = invoice_test_env["vendor"]
    po = invoice_test_env["po"]

    resp = client.post(
        reverse("create_invoice"),
        data={
            "vendor_id": str(vendor.id),
            "po_id": str(po.id),
            "invoice_number": invalid_inv,
            "invoice_date": timezone.now().date().isoformat(),
            "due_date": timezone.now().date().isoformat(),
            "quantity": "2.00",
            "unit_price": "5000.00",
        },
        follow=True,
    )
    assert resp.status_code == 200
    messages = [str(m) for m in resp.context["messages"]]
    assert any("Invoice Number" in m for m in messages)
    assert any(expected_phrase.lower() in m.lower() for m in messages)


@pytest.mark.django_db
def test_bug_007_create_invoice_accepts_valid_invoice_number(client, invoice_test_env):
    """Verify backend create_invoice_view accepts valid alphanumeric invoice numbers (e.g. INV-10123)."""
    client.force_login(invoice_test_env["finance_user"])
    vendor = invoice_test_env["vendor"]
    po = invoice_test_env["po"]

    resp = client.post(
        reverse("create_invoice"),
        data={
            "vendor_id": str(vendor.id),
            "po_id": str(po.id),
            "invoice_number": "INV-10123",
            "invoice_date": timezone.now().date().isoformat(),
            "due_date": timezone.now().date().isoformat(),
            "quantity": "2.00",
            "unit_price": "5000.00",
        },
        follow=True,
    )
    assert resp.status_code == 200
    assert SupplierInvoice.objects.filter(invoice_number="INV-10123", vendor=vendor).exists()


def test_bug_007_create_template_renders_realtime_validation(client, invoice_test_env):
    """Verify create.html renders real-time input validation for the invoice number field."""
    client.force_login(invoice_test_env["finance_user"])
    resp = client.get(reverse("create_invoice"))
    assert resp.status_code == 200
    content = resp.content.decode()

    assert 'id="invoiceNumberInput"' in content
    assert "validateInvoiceNumber" in content
    assert "input" in content
    assert "keyup" in content
    assert "blur" in content
