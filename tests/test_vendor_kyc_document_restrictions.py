"""
Tests for Restricting File Uploads to Approved KYC Document Formats in Vendor Portal (BUG-028 & BUG-029).

Covers:
1. Modal UI rendering and accept attribute on /vendor/documents/:
   - Permits secure compliance formats: PDF, PNG, JPG, JPEG, DOC, DOCX.
   - Strictly excludes editable spreadsheets: XLSX, XLS, CSV.
2. Successful document uploads for PDF and image formats (PNG, JPG, JPEG).
3. Rejection of editable spreadsheet files (XLSX, XLS, CSV).
4. Rejection of past expiry dates on KYC uploads (BUG-028).
5. Rejection of files exceeding the 10 MB limit.
6. Preservation of document classification, title, and pending review state.
"""

from datetime import datetime, timedelta
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.vendors.models import Vendor, VendorCategory, VendorDocument


@pytest.fixture
def vendor_portal_world(db, db_roles):
    category = VendorCategory.objects.create(name="IT Services", code="CAT-IT-TEST")
    vendor = Vendor.objects.create(
        legal_name="Apex Logistics Ltd",
        trade_name="Apex",
        vendor_number="VND-2026-APEX",
        tax_identification_number="TIN-APEX-12345",
        category=category,
        email="contact@apex.local",
        address="100 Tech Park, Apex Way",
        status=Vendor.STATUS_SUBMITTED,
    )
    vendor_user = User.objects.create_user(
        email="portal.user@apex.local",
        password="Password123!",
        role=db_roles[Role.VENDOR_USER],
        vendor=vendor,
    )
    return {
        "vendor": vendor,
        "vendor_user": vendor_user,
        "category": category,
    }


@pytest.mark.django_db
class TestKycDocumentOnlyUploadModal:
    """Tests the /vendor/documents/ modal UI and compliance validation constraints."""

    def test_modal_file_input_permits_kyc_formats_and_restricts_spreadsheets(self, client, vendor_portal_world):
        """Accepted file types in HTML file input must include secure formats (PDF, PNG, JPG) and exclude spreadsheets."""
        client.force_login(vendor_portal_world["vendor_user"])
        resp = client.get(reverse("vendor_documents"))
        assert resp.status_code == 200
        content = resp.content.decode()

        # Check modal structure
        assert 'id="uploadKycModal"' in content
        assert 'name="action" value="upload_kyc"' in content
        assert 'name="document_type"' in content
        assert 'name="title"' in content
        assert 'name="expiry_date"' in content

        # Check file input accept attribute
        assert 'id="kycFileInput"' in content
        assert 'name="kyc_file"' in content
        assert 'accept="' in content

        import re
        match = re.search(r'id="kycFileInput"[^>]*accept="([^"]+)"', content)
        if not match:
            match = re.search(r'accept="([^"]+)"[^>]*id="kycFileInput"', content)
        assert match is not None, "kycFileInput must have accept attribute"
        accept_val = match.group(1).lower()

        # Allowed secure formats must be present
        for allowed in [".pdf", ".png", ".jpg", ".jpeg", ".doc", ".docx"]:
            assert allowed in accept_val, f"Format '{allowed}' must be in file input accept attribute"

        # Spreadsheet extensions must NOT be present in accept attribute
        for spreadsheet in [".xlsx", ".xls", ".csv", "spreadsheetml", "text/csv"]:
            assert spreadsheet not in accept_val, f"Spreadsheet format '{spreadsheet}' must not be in accept attribute"

    def test_pdf_upload_succeeds(self, client, vendor_portal_world):
        """Valid PDF upload is accepted and creates a pending VendorDocument."""
        client.force_login(vendor_portal_world["vendor_user"])
        vendor = vendor_portal_world["vendor_user"].vendor

        pdf_content = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"
        upload_file = SimpleUploadedFile("incorporation_cert.pdf", pdf_content, content_type="application/pdf")

        future_date = (timezone.now().date() + timedelta(days=365)).strftime("%Y-%m-%d")

        resp = client.post(
            reverse("vendor_profile"),
            {
                "action": "upload_kyc",
                "next": reverse("vendor_documents"),
                "document_type": VendorDocument.DOC_TYPE_INC,
                "title": "Certificate of Incorporation 2026",
                "expiry_date": future_date,
                "kyc_file": upload_file,
            },
            follow=True,
        )
        assert resp.status_code == 200

        doc = VendorDocument.objects.filter(vendor=vendor, document_type=VendorDocument.DOC_TYPE_INC).first()
        assert doc is not None
        assert doc.title == "Certificate of Incorporation 2026"
        assert doc.status == VendorDocument.STATUS_PENDING
        assert doc.is_verified is False

        resp_docs = client.get(reverse("vendor_documents"))
        assert "Certificate of Incorporation 2026" in resp_docs.content.decode()

    @pytest.mark.parametrize(
        "filename,mime,header",
        [
            ("tax_scan.png", "image/png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"),
            ("photo.jpg", "image/jpeg", b"\xff\xd8\xff\xe0\x00\x10JFIF"),
            ("id_card.jpeg", "image/jpeg", b"\xff\xd8\xff\xe0\x00\x10JFIF"),
        ],
    )
    def test_image_uploads_succeed(self, client, vendor_portal_world, filename, mime, header):
        """Valid PNG, JPG, and JPEG KYC document scans succeed and create pending VendorDocuments (BUG-029)."""
        client.force_login(vendor_portal_world["vendor_user"])
        vendor = vendor_portal_world["vendor_user"].vendor

        upload_file = SimpleUploadedFile(filename, header + b" dummy photo scan content", content_type=mime)
        future_date = (timezone.now().date() + timedelta(days=180)).strftime("%Y-%m-%d")

        resp = client.post(
            reverse("vendor_profile"),
            {
                "action": "upload_kyc",
                "next": reverse("vendor_documents"),
                "document_type": VendorDocument.DOC_TYPE_OTHER,
                "title": f"Scan Proof {filename}",
                "expiry_date": future_date,
                "kyc_file": upload_file,
            },
            follow=True,
        )
        assert resp.status_code == 200

        doc = VendorDocument.objects.filter(vendor=vendor, title=f"Scan Proof {filename}").first()
        assert doc is not None, f"Document '{filename}' should be successfully created"
        assert doc.status == VendorDocument.STATUS_PENDING

    @pytest.mark.parametrize(
        "filename,mime,content_bytes",
        [
            ("financials.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", b"PK\x03\x04sheetdata"),
            ("accounts.xls", "application/vnd.ms-excel", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1excel"),
            ("ledger.csv", "text/csv", b"col1,col2\nval1,val2\n"),
        ],
    )
    def test_spreadsheet_uploads_are_rejected(self, client, vendor_portal_world, filename, mime, content_bytes):
        """Spreadsheets (XLSX, XLS, CSV) are strictly rejected for KYC compliance (BUG-029)."""
        client.force_login(vendor_portal_world["vendor_user"])
        vendor = vendor_portal_world["vendor_user"].vendor
        before_count = vendor.documents.count()

        upload_file = SimpleUploadedFile(filename, content_bytes, content_type=mime)

        resp = client.post(
            reverse("vendor_profile"),
            {
                "action": "upload_kyc",
                "next": reverse("vendor_documents"),
                "document_type": VendorDocument.DOC_TYPE_OTHER,
                "title": f"Attempt {filename}",
                "kyc_file": upload_file,
            },
            follow=True,
        )
        assert resp.status_code == 200
        content = resp.content.decode()

        # Document must NOT be created
        assert vendor.documents.count() == before_count
        assert not VendorDocument.objects.filter(title=f"Attempt {filename}").exists()

        # Rejection message must indicate spreadsheets are prohibited
        assert "spreadsheet" in content.lower() or "prohibited" in content.lower() or "not permitted" in content.lower()

    def test_past_expiry_date_rejected(self, client, vendor_portal_world):
        """BUG-028: Uploading a KYC document with an expiry date in the past is rejected."""
        client.force_login(vendor_portal_world["vendor_user"])
        vendor = vendor_portal_world["vendor_user"].vendor
        before_count = vendor.documents.count()

        pdf_content = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"
        upload_file = SimpleUploadedFile("expired_cert.pdf", pdf_content, content_type="application/pdf")

        past_date = (timezone.now().date() - timedelta(days=30)).strftime("%Y-%m-%d")

        resp = client.post(
            reverse("vendor_profile"),
            {
                "action": "upload_kyc",
                "next": reverse("vendor_documents"),
                "document_type": VendorDocument.DOC_TYPE_OTHER,
                "title": "Expired Certificate",
                "expiry_date": past_date,
                "kyc_file": upload_file,
            },
            follow=True,
        )
        assert resp.status_code == 200
        content = resp.content.decode()

        assert vendor.documents.count() == before_count
        assert not VendorDocument.objects.filter(title="Expired Certificate").exists()
        assert "past" in content.lower() or "valid future date" in content.lower()

    def test_oversized_file_rejected(self, client, vendor_portal_world):
        """Files larger than 10 MB are rejected with size limit message."""
        client.force_login(vendor_portal_world["vendor_user"])
        vendor = vendor_portal_world["vendor_user"].vendor
        before_count = vendor.documents.count()

        oversized_data = b"%PDF-1.4 " + b"0" * (10 * 1024 * 1024 + 500)
        upload_file = SimpleUploadedFile("large_contract.pdf", oversized_data, content_type="application/pdf")

        resp = client.post(
            reverse("vendor_profile"),
            {
                "action": "upload_kyc",
                "next": reverse("vendor_documents"),
                "document_type": VendorDocument.DOC_TYPE_OTHER,
                "title": "Oversized PDF",
                "kyc_file": upload_file,
            },
            follow=True,
        )
        assert resp.status_code == 200
        content = resp.content.decode()

        # Must not be created
        assert vendor.documents.count() == before_count
        assert "10mb" in content.lower() or "10 mb" in content.lower() or "exceeds" in content.lower()
