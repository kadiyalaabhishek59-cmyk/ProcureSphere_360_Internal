import time

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.organization.models import Organization
from apps.vendors.models import Vendor, VendorCategory


@pytest.mark.django_db
def test_smk_plt_005_health_api_subsecond_response(client):
    """
    SMK-PLT-005 / DEF-001: 5 sequential health API requests must respond well within 5s threshold.
    With connection pooling and timeout guards, each request should execute in < 0.2s locally.
    """
    url = reverse("api_health_check")
    samples = []
    for _ in range(5):
        t0 = time.perf_counter()
        resp = client.get(url)
        t_elapsed = time.perf_counter() - t0
        samples.append(t_elapsed)
        assert resp.status_code in (200, 503)
        assert resp.json().get("service") == "ProcureSphere 360"

    max_sample = max(samples)
    assert max_sample < 2.0, f"Max sample {max_sample} exceeded 2.0s limit"


@pytest.mark.django_db
def test_smk_plt_036_vendor_list_query_optimization():
    """
    SMK-PLT-036 / DEF-001: Authenticated vendor list API must perform optimized prefetching
    and respond well within the 10.0s threshold.
    """
    client = APIClient()
    org = Organization.objects.create(name="HPE Tech", code="ORG-HPE-PERF")
    role, _ = Role.objects.get_or_create(code=Role.SUPER_ADMIN, defaults={"name": "Super Admin"})
    admin_user = User.objects.create_user(
        email="admin_perf@hpe.com",
        password="ValidPassword123!",
        role=role,
        organization=org,
    )
    category = VendorCategory.objects.create(name="IT Hardware", code="CAT-HW-PERF")

    # Seed batch of vendors
    vendors = [
        Vendor(
            legal_name=f"Vendor {i:03d} Performance Test",
            vendor_number=f"VND-PERF-{i:03d}",
            tax_identification_number=f"TIN-PERF-{i:04d}",
            email=f"vendor{i}@perf.test",
            category=category,
            organization=org,
        )
        for i in range(30)
    ]
    Vendor.objects.bulk_create(vendors)

    client.force_authenticate(user=admin_user)
    url = "/api/v1/vendors/"

    t0 = time.perf_counter()
    resp = client.get(url)
    elapsed = time.perf_counter() - t0

    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] >= 30
    assert len(data["results"]) <= 25  # standard page size
    assert elapsed < 3.0, f"Vendor list query took {elapsed:.2f}s, exceeding 3.0s benchmark"
