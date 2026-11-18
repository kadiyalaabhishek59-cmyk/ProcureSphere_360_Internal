import os
import pytest
from datetime import date, timedelta
from decimal import Decimal
from django.urls import reverse
from django.test import RequestFactory

from apps.accounts.models import Role, User
from apps.contracts.forms import ContractCreateForm
from apps.contracts.models import Contract
from apps.organization.models import Organization
from apps.vendors.models import Vendor, VendorCategory, VendorDocument, VendorCredentialDispatch
from apps.core.views import custom_404_view, protected_media_view
from apps.vendors.views import vendor_document_download_view


@pytest.fixture
def org_and_roles(db):
    org = Organization.objects.create(name="HPE Test Org", code="ORG-HPE-TEST")
    legal_role, _ = Role.objects.get_or_create(code=Role.LEGAL_MGR, defaults={"name": "Legal Manager"})
    admin_role, _ = Role.objects.get_or_create(code=Role.SUPER_ADMIN, defaults={"name": "Super Admin"})
    vendor_role, _ = Role.objects.get_or_create(code=Role.VENDOR_USER, defaults={"name": "Vendor User"})

    legal_user = User.objects.create_user(
        email="legal_tester@hpe.com",
        password="TestPassword123!",
        role=legal_role,
        organization=org,
    )
    admin_user = User.objects.create_user(
        email="admin_tester@hpe.com",
        password="TestPassword123!",
        role=admin_role,
        organization=org,
        is_superuser=True,
    )
    cat = VendorCategory.objects.create(name="IT Services", code="IT-01")
    return {
        "org": org,
        "legal_user": legal_user,
        "admin_user": admin_user,
        "cat": cat,
    }


@pytest.mark.django_db
class TestLegalManagerFourBugsRemediation:
    """
    Validates fixes for:
    - BUG-017 (KYC doc download fallback, 404 internal target routing, session preservation)
    - BUG-003 (Vendor dropdown filters suspended/rejected, omits raw bracketed status tags)
    - BUG-019 (Active navigation state on /vendors/:id/* subroutes)
    - BUG-018 (Reject modal content wrapping and structure)
    """

    def test_bug_003_vendor_dropdown_clean_labels_and_status_exclusion(self, org_and_roles):
        """BUG-003: ContractCreateForm excludes suspended/rejected vendors and formats labels cleanly without [ACTIVE]."""
        cat = org_and_roles["cat"]
        org = org_and_roles["org"]

        # Create active, approved, suspended, and rejected vendors
        v_active = Vendor.objects.create(
            legal_name="Alpha Tech Solutions",
            vendor_number="VND-ALPHA-01",
            tax_identification_number="TAX-ALPHA-01",
            category=cat,
            organization=org,
            status=Vendor.STATUS_ACTIVE,
        )
        v_approved = Vendor.objects.create(
            legal_name="Beta Logistics",
            vendor_number="VND-BETA-02",
            tax_identification_number="TAX-BETA-02",
            category=cat,
            organization=org,
            status=Vendor.STATUS_APPROVED,
        )
        v_suspended = Vendor.objects.create(
            legal_name="Suspended Corp",
            vendor_number="VND-SUSP-03",
            tax_identification_number="TAX-SUSP-03",
            category=cat,
            organization=org,
            status=Vendor.STATUS_SUSPENDED,
        )
        v_rejected = Vendor.objects.create(
            legal_name="Rejected LLC",
            vendor_number="VND-REJ-04",
            tax_identification_number="TAX-REJ-04",
            category=cat,
            organization=org,
            status=Vendor.STATUS_REJECTED,
        )

        form = ContractCreateForm()
        vendor_choices = list(form.fields["vendor"].queryset)

        # Suspended & rejected must be excluded
        assert v_active in vendor_choices
        assert v_approved in vendor_choices
        assert v_suspended not in vendor_choices
        assert v_rejected not in vendor_choices

        # Label formatting must be clean: "Legal Name (VND-XXXX)" without raw brackets like [ACTIVE]
        label = form.fields["vendor"].label_from_instance(v_active)
        assert label == "Alpha Tech Solutions (VND-ALPHA-01)"
        assert "[ACTIVE]" not in label
        assert "[SUSPENDED]" not in label

    def test_bug_017_kyc_document_download_and_resilient_fallback(self, client, org_and_roles):
        """BUG-017: Legal Manager can download/view vendor documents without 404 even if disk file is missing."""
        legal_user = org_and_roles["legal_user"]
        cat = org_and_roles["cat"]
        org = org_and_roles["org"]

        vendor = Vendor.objects.create(
            legal_name="Gamma Cloud Corp",
            vendor_number="VND-GAMMA-01",
            tax_identification_number="TAX-GAMMA-01",
            category=cat,
            organization=org,
            status=Vendor.STATUS_KYC_REVIEW,
        )

        doc = VendorDocument.objects.create(
            vendor=vendor,
            document_type=VendorDocument.DOC_TYPE_PAN,
            title="Permanent Account Number (PAN)",
            file="vendor_docs/test_gamma_pan.pdf",
            status=VendorDocument.STATUS_PENDING,
        )

        client.force_login(legal_user)
        download_url = reverse("vendor_document_download", kwargs={"vendor_id": vendor.id, "doc_id": doc.id})
        response = client.get(download_url)

        # Resilient fallback returns a valid HTTP 200 PDF stream even if physical file is missing from disk
        assert response.status_code == 200
        assert "application/pdf" in response["Content-Type"]
        pdf_bytes = b"".join(response.streaming_content)
        assert len(pdf_bytes) > 0
        assert pdf_bytes.startswith(b"%PDF")

    def test_bug_017_custom_404_view_redirects_to_internal_legal_dashboard(self, client, org_and_roles):
        """BUG-017: 404 error page returns to Legal Dashboard (/legal/) for Legal Manager, never external marketing site."""
        legal_user = org_and_roles["legal_user"]
        client.force_login(legal_user)

        response = client.get("/non-existent-route-for-testing-404/")
        assert response.status_code == 404
        content = response.content.decode("utf-8")

        # Verify Return to Legal Dashboard button exists and points to /legal/
        assert 'href="/legal/"' in content
        assert "Return to Legal Dashboard" in content
        # Must not point to external marketing site or "/"
        assert 'href="/"' not in content
        # Session protection script must be present
        assert "ps_visited_subpage" in content
        assert "ps360_user_signed_out" in content

    def test_bug_019_sidebar_vendor_directory_active_on_subpages(self, client, org_and_roles):
        """BUG-019: Sidebar Vendor Directory link retains active-nav-item class on /vendors/:id/ and subpages."""
        legal_user = org_and_roles["legal_user"]
        cat = org_and_roles["cat"]
        org = org_and_roles["org"]

        vendor = Vendor.objects.create(
            legal_name="Delta Services",
            vendor_number="VND-DELTA-01",
            tax_identification_number="TAX-DELTA-01",
            category=cat,
            organization=org,
            status=Vendor.STATUS_ACTIVE,
        )

        client.force_login(legal_user)
        # Visit vendor detail overview
        detail_url = reverse("vendor_detail", kwargs={"vendor_id": vendor.id})
        response = client.get(detail_url)
        assert response.status_code == 200
        content = response.content.decode("utf-8")

        # In legal_base.html, the Vendor Directory link must have active-nav-item
        assert 'active-nav-item' in content

    def test_bug_018_reject_vendor_modal_wrapping_classes(self, client, org_and_roles):
        """BUG-018: Reject Vendor Modal contains overflow wrapping styles to prevent text blowout."""
        legal_user = org_and_roles["legal_user"]
        cat = org_and_roles["cat"]
        org = org_and_roles["org"]

        vendor = Vendor.objects.create(
            legal_name="Epsilon Manufacturing Extraordinarily Long Name To Test Wrapping",
            vendor_number="VND-EPS-01",
            tax_identification_number="TAX-EPS-01",
            category=cat,
            organization=org,
            status=Vendor.STATUS_KYC_REVIEW,
        )

        dispatch = VendorCredentialDispatch.objects.create(
            vendor=vendor,
            user=legal_user,
            sent_to="very_long_procurement_compliance_officer_email_address_for_testing@extremelylongdomainnamethatwillnotbreaknaturally.com",
            status=VendorCredentialDispatch.STATUS_SENT,
            legal_verification_status=VendorCredentialDispatch.LEGAL_STATUS_PENDING,
        )

        client.force_login(legal_user)
        dashboard_url = reverse("legal_dashboard")
        response = client.get(dashboard_url)
        assert response.status_code == 200
        content = response.content.decode("utf-8")

        # Verify reject modal contains text-break, font-monospace, and overflow constraints
        assert f"rejectCredsModal{dispatch.id}" in content
        assert "text-break" in content
        assert "word-break: break-word" in content
        assert "word-break: break-all" in content

    def test_legal_dashboard_kpi_total_contract_value_overflow_protection(self, client, org_and_roles):
        """Validates that Total Contract Value KPI card in Legal Dashboard uses fluid font sizing, intcomma, and overflow containment."""
        legal_user = org_and_roles["legal_user"]
        cat = org_and_roles["cat"]
        org = org_and_roles["org"]

        vendor = Vendor.objects.create(
            legal_name="Mega Supplier Inc",
            vendor_number="VND-MEGA-01",
            tax_identification_number="TAX-MEGA-01",
            category=cat,
            organization=org,
            status=Vendor.STATUS_ACTIVE,
        )

        # Create large value contract (100 Billion)
        Contract.objects.create(
            contract_number="CON-TEST-MEGA-01",
            title="Mega Enterprise SLA",
            vendor=vendor,
            contract_owner=legal_user,
            contract_value=Decimal("100057850100.00"),
            status=Contract.STATUS_ACTIVE,
            start_date=date.today(),
            end_date=date.today() + timedelta(days=365),
            renewal_notice_days=30,
        )

        client.force_login(legal_user)
        dashboard_url = reverse("legal_dashboard")
        response = client.get(dashboard_url)
        assert response.status_code == 200
        content = response.content.decode("utf-8")

        # Must format with commas and include fluid clamp and text-break
        assert "100,057,850,100.00" in content
        assert "clamp(0.95rem, 1.25vw, 1.45rem)" in content
        assert "overflow-wrap: anywhere" in content
        assert "word-break: break-all" in content
        assert "overflow: hidden" in content

    def test_contract_form_financial_limits_and_repetitive_number_rejection(self, org_and_roles):
        """Validates that ContractCreateForm enforces maximum financial ceilings and rejects dummy repeating numbers."""
        cat = org_and_roles["cat"]
        org = org_and_roles["org"]

        vendor = Vendor.objects.create(
            legal_name="Financial Test Vendor",
            vendor_number="VND-FIN-01",
            tax_identification_number="TAX-FIN-01",
            category=cat,
            organization=org,
            status=Vendor.STATUS_ACTIVE,
        )

        base_data = {
            "title": "Corporate Network Maintenance SLA",
            "vendor": vendor.id,
            "start_date": str(date.today()),
            "end_date": str(date.today() + timedelta(days=365)),
            "renewal_notice_days": 30,
        }

        # 1. Reject value exceeding ₹1 Billion ceiling (e.g., 100 Billion)
        data_excessive = base_data.copy()
        data_excessive["contract_value"] = "100000000000.00"
        form_excessive = ContractCreateForm(data=data_excessive)
        assert not form_excessive.is_valid()
        assert "contract_value" in form_excessive.errors
        assert "cannot exceed" in form_excessive.errors["contract_value"][0]

        # 2. Reject repeating sequence of 9 identical digits (e.g. 111111111)
        data_repeating = base_data.copy()
        data_repeating["contract_value"] = "111111111.00"
        form_repeating = ContractCreateForm(data=data_repeating)
        assert not form_repeating.is_valid()
        assert "contract_value" in form_repeating.errors
        assert "repeating sequence" in form_repeating.errors["contract_value"][0]

        # 3. Reject title with repeating characters (e.g. 111111)
        data_bad_title = base_data.copy()
        data_bad_title["title"] = "111111"
        data_bad_title["contract_value"] = "500000.00"
        form_bad_title = ContractCreateForm(data=data_bad_title)
        assert not form_bad_title.is_valid()
        assert "title" in form_bad_title.errors
        assert "repeating sequence" in form_bad_title.errors["title"][0]

        # 4. Accept valid financial value within limits (e.g. ₹5,000,000.00)
        data_valid = base_data.copy()
        data_valid["contract_value"] = "5000000.00"
        form_valid = ContractCreateForm(data=data_valid)
        assert form_valid.is_valid(), form_valid.errors
