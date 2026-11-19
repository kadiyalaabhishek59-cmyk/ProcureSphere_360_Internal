import pytest
from django.test import Client

from apps.accounts.models import Role, User
from apps.reports.models import ExportJob
from apps.reports.services import REPORT_DISPATCHER, generate_export_job_service


@pytest.fixture
def admin_user(db):
    role_sa, _ = Role.objects.get_or_create(code=Role.SUPER_ADMIN, defaults={"name": "Super Admin"})
    user = User.objects.create_superuser(
        email="test_superadmin_reports@example.com",
        password="Password123!",
        role=role_sa,
    )
    return user


@pytest.mark.django_db
def test_all_reports_and_formats_generation(admin_user):
    client = Client()
    client.force_login(admin_user)

    # 1. Test dashboard renders with reports
    resp = client.get("/superadmin/reports/")
    assert resp.status_code == 200
    content = resp.content.decode("utf-8")
    assert 'name="report_type"' in content
    assert 'name="format_type"' in content
    assert 'value="CSV"' in content
    assert 'value="XLSX"' in content
    assert 'value="PDF"' in content

    # 2. Test generation of each report in each format
    report_modules = [
        "spend_analytics",
        "pr_aging",
        "sourcing_cycle",
        "po_status",
        "receipt_rejection",
        "invoice_exception_aging",
        "contract_expiry",
        "contract_obligation",
        "supplier_scorecard",
        "audit_log",
    ]
    formats = ["CSV", "XLSX", "PDF"]

    for rm in report_modules:
        for fmt in formats:
            resp_gen = client.post(
                "/reports/generate/",
                data={"report_type": rm, "format_type": fmt},
            )
            assert resp_gen.status_code == 302, f"Failed for {rm} {fmt}"
            job = ExportJob.objects.filter(requested_by=admin_user, report_type=rm, export_format=fmt).latest("id")
            assert job.status == ExportJob.STATUS_COMPLETED, f"Job failed for {rm} {fmt}: {job.error_message}"
            assert job.result_file, f"Result file missing for {rm} {fmt}"

            # Test file download link
            file_resp = client.get(job.result_file.url)
            assert file_resp.status_code == 200, f"Cannot download {job.result_file.url} for {rm} {fmt}"
