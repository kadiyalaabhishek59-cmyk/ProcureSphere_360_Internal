import datetime
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.invoices.models import SupplierInvoice
from apps.orders.models import POLine, PurchaseOrder
from apps.organization.models import CostCenter, Department, Organization
from apps.vendors.models import Vendor, VendorCategory


@pytest.fixture
def invoice_test_env(db, db_roles):
    org = Organization.objects.create(name="HPE Test Org", code="HPE-INV-01")
    dept = Department.objects.create(organization=org, name="Finance Dept", code="FIN-INV-01")
    cost_center = CostCenter.objects.create(department=dept, code="CC-INV-01", name="Finance Ops")

    category = VendorCategory.objects.create(name="Networking", code="CAT-NET-01")
    vendor_cisco = Vendor.objects.create(
        legal_name="Cisco Systems Inc",
        trade_name="Cisco",
        vendor_number="VND-CISCO-01",
        tax_identification_number="TIN-CISCO-01",
        category=category,
        status=Vendor.STATUS_ACTIVE,
        organization=org,
    )
    vendor_nexus = Vendor.objects.create(
        legal_name="Nexus Solutions",
        trade_name="Nexus",
        vendor_number="VND-NEXUS-01",
        tax_identification_number="TIN-NEXUS-01",
        category=category,
        status=Vendor.STATUS_ACTIVE,
        organization=org,
    )

    finance_user = User.objects.create_user(
        email="finance_invoicer@hpe.com",
        password="Password123!",
        role=db_roles[Role.FINANCE_AP],
        organization=org,
    )

    po_cisco = PurchaseOrder.objects.create(
        po_number="PO-CISCO-001",
        version=1,
        vendor=vendor_cisco,
        cost_center=cost_center,
        status=PurchaseOrder.STATUS_ISSUED,
        subtotal=Decimal("1000.00"),
        tax_amount=Decimal("100.00"),
        total_amount=Decimal("1100.00"),
    )
    po_line = POLine.objects.create(
        po=po_cisco,
        item_description="Catalyst Switches",
        quantity=Decimal("10.00"),
        quantity_received=Decimal("10.00"),
        unit_price=Decimal("100.00"),
    )

    po_nexus = PurchaseOrder.objects.create(
        po_number="PO-NEXUS-001",
        version=1,
        vendor=vendor_nexus,
        cost_center=cost_center,
        status=PurchaseOrder.STATUS_ISSUED,
        subtotal=Decimal("500.00"),
        tax_amount=Decimal("50.00"),
        total_amount=Decimal("550.00"),
    )

    po_empty = PurchaseOrder.objects.create(
        po_number="PO-EMPTY-LINES-001",
        version=1,
        vendor=vendor_cisco,
        cost_center=cost_center,
        status=PurchaseOrder.STATUS_ISSUED,
        subtotal=Decimal("100.00"),
        tax_amount=Decimal("10.00"),
        total_amount=Decimal("110.00"),
    )

    return {
        "org": org,
        "finance_user": finance_user,
        "vendor_cisco": vendor_cisco,
        "vendor_nexus": vendor_nexus,
        "po_cisco": po_cisco,
        "po_line": po_line,
        "po_nexus": po_nexus,
        "po_empty": po_empty,
    }


@pytest.mark.django_db
def test_invoice_create_rejects_vendor_mismatch(client, invoice_test_env):
    """
    Error 1 Prevention:
    Selecting Cisco as vendor but a Nexus PO must return a clear validation error.
    """
    env = invoice_test_env
    client.force_login(env["finance_user"])

    response = client.post(
        "/invoices/create/",
        {
            "vendor_id": str(env["vendor_cisco"].id),
            "po_id": str(env["po_nexus"].id),
            "invoice_number": "INV-MISMATCH-01",
            "invoice_date": timezone.now().date().isoformat(),
            "due_date": (timezone.now().date() + datetime.timedelta(days=30)).isoformat(),
            "quantity": "5.00",
            "unit_price": "100.00",
        },
    )

    assert response.status_code == 200
    content = response.content.decode()
    assert "does not belong to vendor" in content
    assert not SupplierInvoice.objects.filter(invoice_number="INV-MISMATCH-01").exists()


@pytest.mark.django_db
def test_invoice_create_rejects_future_invoice_date(client, invoice_test_env):
    """
    Error 2 Prevention (Date):
    Selecting a future invoice date must be rejected.
    """
    env = invoice_test_env
    client.force_login(env["finance_user"])
    future_date = (timezone.now().date() + datetime.timedelta(days=5)).isoformat()
    due_date = (timezone.now().date() + datetime.timedelta(days=30)).isoformat()

    response = client.post(
        "/invoices/create/",
        {
            "vendor_id": str(env["vendor_cisco"].id),
            "po_id": str(env["po_cisco"].id),
            "invoice_number": "INV-FUTURE-01",
            "invoice_date": future_date,
            "due_date": due_date,
            "quantity": "5.00",
            "unit_price": "100.00",
        },
    )

    assert response.status_code == 200
    content = response.content.decode()
    assert "cannot be in the future" in content
    assert not SupplierInvoice.objects.filter(invoice_number="INV-FUTURE-01").exists()


@pytest.mark.django_db
def test_invoice_create_rejects_po_without_lines(client, invoice_test_env):
    """
    Error 2 Prevention (Incomplete Test PO):
    A PO without line items must fail gracefully with a specific error message.
    """
    env = invoice_test_env
    client.force_login(env["finance_user"])

    response = client.post(
        "/invoices/create/",
        {
            "vendor_id": str(env["vendor_cisco"].id),
            "po_id": str(env["po_empty"].id),
            "invoice_number": "INV-NOLINE-01",
            "invoice_date": timezone.now().date().isoformat(),
            "due_date": (timezone.now().date() + datetime.timedelta(days=30)).isoformat(),
            "quantity": "1.00",
            "unit_price": "100.00",
        },
    )

    assert response.status_code == 200
    content = response.content.decode()
    assert "has no line items" in content
    assert not SupplierInvoice.objects.filter(invoice_number="INV-NOLINE-01").exists()


@pytest.mark.django_db
def test_invoice_create_page_contains_vendor_data_attribute(client, invoice_test_env):
    """
    UI Verification:
    HTML page must render data-vendor-id attributes and max date constraint.
    """
    env = invoice_test_env
    client.force_login(env["finance_user"])

    response = client.get("/invoices/create/")
    assert response.status_code == 200
    content = response.content.decode()

    # Verify data-vendor-id is present for dynamic filtering
    assert f'data-vendor-id="{env["vendor_cisco"].id}"' in content
    assert f'data-vendor-id="{env["vendor_nexus"].id}"' in content

    # Verify max date constraint
    today_iso = timezone.now().date().isoformat()
    assert f'max="{today_iso}"' in content
    assert "filterPOsByVendor" in content

