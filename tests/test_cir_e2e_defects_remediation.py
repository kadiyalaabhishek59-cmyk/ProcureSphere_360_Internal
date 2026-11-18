import datetime
from decimal import Decimal

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.core.views import get_dashboard_url_for_user
from apps.organization.models import CostCenter, Department, Organization
from apps.vendors.models import Vendor, VendorCategory


@pytest.fixture
def cir_test_setup(db):
    org = Organization.objects.create(name="CIR Test Org", code="CIR-ORG")
    dept = Department.objects.create(name="Legal & Audit", code="LGA1", organization=org)
    cc = CostCenter.objects.create(name="LGA Cost Center", code="CC-LGA-01", department=dept)

    super_role, _ = Role.objects.get_or_create(
        code=Role.SUPER_ADMIN, defaults={"name": "Super Admin"}
    )
    aud_role, _ = Role.objects.get_or_create(
        code=Role.AUDITOR, defaults={"name": "Compliance Auditor"}
    )
    legal_role, _ = Role.objects.get_or_create(
        code=Role.LEGAL_MGR, defaults={"name": "Legal Manager"}
    )

    admin_user = User.objects.create_superuser(
        email="cir_admin@example.com", password="Pass123!Secure", role=super_role
    )
    auditor_user = User.objects.create_user(
        email="cir_auditor@example.com", password="Pass123!Secure", role=aud_role, department=dept
    )
    legal_user = User.objects.create_user(
        email="cir_legal@example.com", password="Pass123!Secure", role=legal_role, department=dept
    )

    cat = VendorCategory.objects.create(name="IT Services", code="IT_SERV_CIR")
    vendor = Vendor.objects.create(
        legal_name="CIR Test Vendor Inc",
        trade_name="CIR Vendor",
        vendor_number="VND-CIR-001",
        tax_identification_number="TIN-CIR-001",
        category=cat,
        organization=org,
        status=Vendor.STATUS_ACTIVE,
    )

    return {
        "org": org,
        "dept": dept,
        "cc": cc,
        "admin": admin_user,
        "auditor": auditor_user,
        "legal": legal_user,
        "vendor": vendor,
        "cat": cat,
    }


# ==============================================================================
# DEF-001: E2E-CON-086 - Duplicate Contract Payload Prevention
# ==============================================================================
@pytest.mark.django_db
def test_def_001_contract_duplicate_payload_prevention(cir_test_setup):
    """
    E2E-CON-086 / DEF-001:
    Posting the identical contract payload twice must reject the second POST (HTTP 400).
    A draft contract must not be excluded from the uniqueness check.
    """
    data = cir_test_setup
    client = APIClient()
    client.force_authenticate(user=data["legal"])

    payload = {
        "title": "Master Services Agreement 2026",
        "vendor": str(data["vendor"].id),
        "contract_value": "150000.00",
        "start_date": "2026-12-01",
        "end_date": "2027-12-01",
        "renewal_notice_days": 30,
    }

    # First creation should succeed (HTTP 201)
    res1 = client.post("/api/v1/contracts/", payload, format="json")
    assert res1.status_code == status.HTTP_201_CREATED, f"First POST failed: {res1.data}"
    assert res1.data["status"] == "DRAFT"

    # Second creation with identical payload must be rejected with HTTP 400
    res2 = client.post("/api/v1/contracts/", payload, format="json")
    assert (
        res2.status_code == status.HTTP_400_BAD_REQUEST
    ), f"Expected 400 on duplicate submission, but got {res2.status_code}: {res2.data}"


# ==============================================================================
# DEF-002: E2E-VEN-115 - Vendor Pagination Disjointness (Deterministic Ordering)
# ==============================================================================
@pytest.mark.django_db
def test_def_002_vendor_list_pagination_disjoint(cir_test_setup):
    """
    E2E-VEN-115 / DEF-002:
    GET /api/v1/vendors/?page=1 and ?page=2 must have disjoint results.
    Rows from page 1 must never reappear on page 2 even when vendors share legal names.
    """
    data = cir_test_setup
    # Create 35 vendors with identical or similar names to induce tie-breaking ambiguity
    vendors = []
    for i in range(35):
        vendors.append(
            Vendor(
                legal_name=f"Shared Vendor Name {i // 5}",
                trade_name="Shared Trade",
                vendor_number=f"VND-PAG-{i:04d}",
                tax_identification_number=f"TIN-PAG-{i:04d}",
                category=data["cat"],
                organization=data["org"],
                status=Vendor.STATUS_ACTIVE,
            )
        )
    Vendor.objects.bulk_create(vendors)

    client = APIClient()
    client.force_authenticate(user=data["admin"])

    # DRF default page size is 25
    resp1 = client.get("/api/v1/vendors/?page=1")
    assert resp1.status_code == status.HTTP_200_OK
    data1 = resp1.data.get("results", [])
    ids1 = {item["id"] for item in data1}
    assert len(data1) == 25

    resp2 = client.get("/api/v1/vendors/?page=2")
    assert resp2.status_code == status.HTTP_200_OK
    data2 = resp2.data.get("results", [])
    ids2 = {item["id"] for item in data2}
    assert len(data2) >= 10

    # Pages must be strictly disjoint
    overlap = ids1.intersection(ids2)
    assert not overlap, f"Pages 1 and 2 overlap! Overlapping IDs: {overlap}"


# ==============================================================================
# DEF-003: E2E-AUT-040 - Auditor Post-Login Redirect to /audit/
# ==============================================================================
@pytest.mark.django_db
def test_def_003_auditor_post_login_redirect(cir_test_setup):
    """
    E2E-AUT-040 / DEF-003:
    AUDITOR role must land on the documented auditor portal '/audit/', NOT '/auditor/'.
    """
    data = cir_test_setup
    auditor = data["auditor"]

    # 1. get_dashboard_url_for_user must return '/audit/'
    url = get_dashboard_url_for_user(auditor)
    assert url == "/audit/", f"Expected '/audit/', got '{url}'"

    # 2. /dashboard/ redirect view must route auditor to '/audit/'
    from django.test import Client

    django_client = Client()
    django_client.force_login(auditor)
    resp = django_client.get("/dashboard/")
    assert resp.status_code == status.HTTP_302_FOUND
    assert resp.url == "/audit/"

    # 3. Portal login view redirects auditor to '/audit/'
    login_client = Client()
    login_resp = login_client.post(
        "/login/", {"email": auditor.email, "password": "Pass123!Secure"}
    )
    assert login_resp.status_code == status.HTTP_302_FOUND
    assert login_resp.url == "/audit/"

    # 4. AJAX login returns redirect URL '/audit/'
    ajax_client = Client()
    ajax_resp = ajax_client.post(
        "/login/",
        {"email": auditor.email, "password": "Pass123!Secure"},
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )
    assert ajax_resp.status_code == status.HTTP_200_OK
    assert ajax_resp.json().get("redirect") == "/audit/"


# ==============================================================================
# DEF-001 Edge Cases: Self-Update and Terminated Contract Re-creation
# ==============================================================================
@pytest.mark.django_db
def test_def_001_contract_self_update_and_terminated_recreation(cir_test_setup):
    """
    Validates that:
    1. Updating an existing contract (PATCH / PUT) does not raise false duplicate error on itself.
    2. A TERMINATED contract does not block creating a new contract with same title/dates.
    """
    from apps.contracts.models import Contract

    data = cir_test_setup
    client = APIClient()
    client.force_authenticate(user=data["legal"])

    payload = {
        "title": "Cloud Infrastructure Contract",
        "vendor": str(data["vendor"].id),
        "contract_value": "200000.00",
        "start_date": "2026-11-01",
        "end_date": "2027-11-01",
        "renewal_notice_days": 30,
    }

    # 1. Create contract
    res = client.post("/api/v1/contracts/", payload, format="json")
    assert res.status_code == status.HTTP_201_CREATED
    contract_id = res.data["id"]

    # 2. Update same contract (value change) -> should succeed, not fail on title duplicate
    res_update = client.patch(
        f"/api/v1/contracts/{contract_id}/", {"contract_value": "220000.00"}, format="json"
    )
    assert res_update.status_code == status.HTTP_200_OK
    assert float(res_update.data["contract_value"]) == 220000.00

    # 3. Mark contract as TERMINATED
    contract = Contract.objects.get(id=contract_id)
    contract.status = Contract.STATUS_TERMINATED
    contract.save()

    # 4. Now posting the same payload for the same vendor/dates should be permitted
    res_recreate = client.post("/api/v1/contracts/", payload, format="json")
    assert res_recreate.status_code == status.HTTP_201_CREATED


# ==============================================================================
# DEF-002 Edge Cases: Deterministic Pagination with explicit sort_by params
# ==============================================================================
@pytest.mark.django_db
def test_def_002_vendor_pagination_with_explicit_sorts(cir_test_setup):
    """
    Verifies pagination is disjoint when sorting by created_at, legal_name, and status.
    """
    data = cir_test_setup
    vendors = []
    for i in range(30):
        vendors.append(
            Vendor(
                legal_name=f"Tie Vendor {i // 3}",
                trade_name="Trade",
                vendor_number=f"VND-SORT-{i:04d}",
                tax_identification_number=f"TIN-SORT-{i:04d}",
                category=data["cat"],
                organization=data["org"],
                status=Vendor.STATUS_ACTIVE,
            )
        )
    Vendor.objects.bulk_create(vendors)

    client = APIClient()
    client.force_authenticate(user=data["admin"])

    for sort_param in ["created_at", "-created_at", "legal_name", "status"]:
        r1 = client.get(f"/api/v1/vendors/?page=1&sort_by={sort_param}")
        r2 = client.get(f"/api/v1/vendors/?page=2&sort_by={sort_param}")
        assert r1.status_code == status.HTTP_200_OK
        assert r2.status_code == status.HTTP_200_OK
        p1 = {x["id"] for x in r1.data.get("results", [])}
        p2 = {x["id"] for x in r2.data.get("results", [])}
        assert p1.isdisjoint(p2), f"Overlap detected under sort_by={sort_param}"


# ==============================================================================
# E2E-PLT-032: OpenAPI Schema Operations Inventory Consistency
# ==============================================================================
@pytest.mark.django_db
def test_plt_032_openapi_schema_operation_consistency(cir_test_setup):
    """
    Verifies that the alias /api/v1/reports/dashboard/summary/ is excluded from OpenAPI schema
    so schema operations stay in sync with the smoke inventory, while the endpoint remains
    fully functional.
    """
    data = cir_test_setup
    client = APIClient()
    client.force_authenticate(user=data["admin"])

    # 1. Alias endpoint responds with HTTP 200 and valid dashboard data
    res_alias = client.get("/api/v1/reports/dashboard/summary/")
    assert res_alias.status_code == status.HTTP_200_OK
    assert "total_spend" in res_alias.data

    # 2. Canonical endpoint also responds with HTTP 200 and same data
    res_canon = client.get("/api/v1/reports/dashboard-summary/")
    assert res_canon.status_code == status.HTTP_200_OK
    assert res_alias.data["total_spend"] == res_canon.data["total_spend"]

    # 3. OpenAPI schema generated excludes /api/v1/reports/dashboard/summary/
    from drf_spectacular.generators import SchemaGenerator

    generator = SchemaGenerator(title="ProcureSphere 360 ERP API")
    schema = generator.get_schema(request=None, public=True)
    paths = schema.get("paths", {})
    assert "/api/v1/reports/dashboard/summary/" not in paths
    assert "/api/v1/reports/dashboard-summary/" in paths
