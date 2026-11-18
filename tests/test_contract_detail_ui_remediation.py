from decimal import Decimal
from datetime import date, timedelta
import pytest
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.contracts.models import Contract
from apps.contracts.forms import ContractCreateForm, ContractAmendmentForm
from apps.contracts.services import create_contract_service
from apps.vendors.models import VendorCategory
from apps.vendors.services import register_vendor_service


def _get_or_create_role(code, name):
    role = Role.objects.filter(code=code).first()
    if not role:
        try:
            role, _ = Role.objects.get_or_create(code=code, defaults={"name": name})
        except Exception:
            role = Role.objects.filter(code=code).first()
    return role


@pytest.fixture
def legal_env(db):
    legal_role = _get_or_create_role(Role.LEGAL_MGR, "Legal Manager")
    user = User.objects.create_user(
        email="legal.tester@hpe.com",
        password="Password123!",
        role=legal_role,
    )
    cat = VendorCategory.objects.create(name="Enterprise Tech Services", code="CAT-TECH-01")
    vendor = register_vendor_service(
        legal_name="Acme Enterprise Tech Solutions",
        tax_identification_number="TAX-ACME-9999",
        category=cat,
        email="vendor@acmetech.com",
        address="100 Tech Blvd",
    )
    return {"user": user, "vendor": vendor}


@pytest.mark.django_db
def test_contract_detail_header_ui_formatting_and_overflow_protection(client, legal_env):
    """
    Validates:
    1. Contract value rendered with comma separation (intcomma) to prevent long raw digit runs.
    2. Header card container has overflow-hidden preventing border breaches.
    3. Monospace contract number badge without unreadable nested <code> pink text.
    4. Contract title has text-break to support unbroken digit/character sequences (e.g. 111111).
    5. Agreement Summary Details table displays formatted currency with commas.
    """
    user = legal_env["user"]
    vendor = legal_env["vendor"]

    contract = create_contract_service(
        title="111111",
        vendor=vendor,
        contract_value=Decimal("100000000000.00"),
        start_date=date.today(),
        end_date=date.today() + timedelta(days=365),
        renewal_notice_days=30,
        contract_owner=user,
    )

    client.force_login(user)
    resp = client.get(reverse("contract_detail", kwargs={"contract_id": contract.id}))
    assert resp.status_code == 200

    html = resp.content.decode("utf-8")

    # 1. Comma-separated currency formatting (e.g. 100,000,000,000.00)
    assert "100,000,000,000.00" in html

    # 2. Card has overflow-hidden
    assert "glass-card-dark p-4 mb-4 shadow-sm overflow-hidden" in html

    # 3. Monospace badge without nested <code>
    assert f'<span class="badge bg-secondary text-white rounded-pill px-3 py-1 fw-bold font-monospace">{contract.contract_number}</span>' in html
    assert f'<code>{contract.contract_number}</code>' not in html

    # 4. Title has text-break
    assert 'class="fw-bold text-white mb-2 text-break"' in html
    assert "111111" in html

    # 5. Contract Value container has responsive sizing & word-break
    assert 'overflow-wrap: anywhere;' in html
    assert 'clamp(' in html


@pytest.mark.django_db
def test_contract_register_list_number_formatting(client, legal_env):
    """
    Validates that contract register list displays formatted numbers with intcomma and monospace badges.
    """
    user = legal_env["user"]
    vendor = legal_env["vendor"]

    contract = create_contract_service(
        title="Telecom Infra SLA",
        vendor=vendor,
        contract_value=Decimal("7500000.00"),
        start_date=date.today(),
        end_date=date.today() + timedelta(days=730),
        renewal_notice_days=45,
        contract_owner=user,
    )

    client.force_login(user)
    resp = client.get(reverse("contracts_list"))
    assert resp.status_code == 200

    html = resp.content.decode("utf-8")
    assert "7,500,000.00" in html
    assert contract.contract_number in html
    assert f'<code>{contract.contract_number}</code>' not in html


@pytest.mark.django_db
def test_contract_form_contract_value_validation(legal_env):
    """
    Validates that contract forms reject non-positive contract values.
    """
    vendor = legal_env["vendor"]
    form_data = {
        "title": "Invalid Value Contract",
        "vendor": vendor.id,
        "contract_value": "-500.00",
        "start_date": str(date.today()),
        "end_date": str(date.today() + timedelta(days=100)),
        "renewal_notice_days": 30,
    }
    form = ContractCreateForm(data=form_data)
    assert not form.is_valid()
    assert "contract_value" in form.errors
    assert "greater than zero" in form.errors["contract_value"][0]

    # Valid value
    form_data["contract_value"] = "1000000000.00"
    form_valid = ContractCreateForm(data=form_data)
    assert form_valid.is_valid(), form_valid.errors
