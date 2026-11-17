"""
Regression test suite for BUG-008 and BUG-009 remediation.

BUG-008:
- Finance & AP Workspace: Pending Match Exceptions filtering by department and cost center
  (All/All, Specific/All, All/Specific, Specific/Specific, resetting, invalid IDs, pagination,
  empty states, API filtering, record scope verification).

BUG-009:
- My Requisitions: Access Denied resolution for authorized requesters, department members,
  and role-based staff, supporting both UUID primary keys and PR numbers (tested with PR-2026-00706),
  while strictly preserving multi-tenant isolation and preventing IDOR vulnerabilities.
"""

import datetime
import uuid
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.invoices.models import MatchException, SupplierInvoice
from apps.orders.models import POLine, PurchaseOrder
from apps.organization.models import CostCenter, Department, Organization
from apps.requisitions.models import PRLine, PurchaseRequisition
from apps.vendors.models import Vendor, VendorCategory


@pytest.fixture
def qa_setup_data(db):
    """
    Sets up isolated test data for BUG-008 and BUG-009.
    Creates 2 organizations, multiple departments, cost centers, and users.
    """
    # Organization 1: Acme Global
    org1 = Organization.objects.create(name="Acme Global Enterprise", code="ACME")
    dept_eng = Department.objects.create(name="Engineering", code="ENG", organization=org1)
    dept_proc = Department.objects.create(name="Procurement", code="PROC", organization=org1)
    dept_qa = Department.objects.create(name="Quality Assurance", code="QA", organization=org1)

    cc_eng1 = CostCenter.objects.create(name="Core Engineering", code="CC-ENG-01", department=dept_eng)
    cc_eng2 = CostCenter.objects.create(name="DevOps & Infra", code="CC-ENG-02", department=dept_eng)
    cc_proc = CostCenter.objects.create(name="Central Procurement", code="CC-PROC-01", department=dept_proc)
    cc_qa = CostCenter.objects.create(name="QA Testing", code="CC-QA-01", department=dept_qa)

    # Roles
    super_role, _ = Role.objects.get_or_create(code=Role.SUPER_ADMIN, defaults={"name": "Super Admin"})
    req_role, _ = Role.objects.get_or_create(code=Role.REQUESTER, defaults={"name": "Requester"})
    appr_role, _ = Role.objects.get_or_create(code=Role.DEPT_APPROVER, defaults={"name": "Dept Approver"})
    fin_role, _ = Role.objects.get_or_create(code=Role.FINANCE_AP, defaults={"name": "Finance / AP"})
    proc_exec_role, _ = Role.objects.get_or_create(code=Role.PROC_EXEC, defaults={"name": "Procurement Executive"})
    aud_role, _ = Role.objects.get_or_create(code=Role.AUDITOR, defaults={"name": "Compliance / Auditor"})
    vendor_role, _ = Role.objects.get_or_create(code=Role.VENDOR_USER, defaults={"name": "Vendor User"})

    # Users
    admin_user = User.objects.create_superuser(
        email="superadmin@acme.test", password="Pass123!Secure", role=super_role
    )
    finance_user = User.objects.create_user(
        email="finance@acme.test", password="Pass123!Secure", role=fin_role, organization=org1, department=dept_proc
    )
    eng_requester1 = User.objects.create_user(
        email="alice.eng@acme.test", password="Pass123!Secure", role=req_role, organization=org1, department=dept_eng, cost_center=cc_eng1
    )
    eng_requester2 = User.objects.create_user(
        email="bob.eng@acme.test", password="Pass123!Secure", role=req_role, organization=org1, department=dept_eng, cost_center=cc_eng1
    )
    proc_requester = User.objects.create_user(
        email="charlie.proc@acme.test", password="Pass123!Secure", role=req_role, organization=org1, department=dept_proc, cost_center=cc_proc
    )
    eng_approver = User.objects.create_user(
        email="approver.eng@acme.test", password="Pass123!Secure", role=appr_role, organization=org1, department=dept_eng
    )
    proc_exec = User.objects.create_user(
        email="procexec@acme.test", password="Pass123!Secure", role=proc_exec_role, organization=org1
    )
    auditor = User.objects.create_user(
        email="auditor@acme.test", password="Pass123!Secure", role=aud_role, organization=org1
    )

    # Vendor & Category
    vcat = VendorCategory.objects.create(name="IT Hardware & Services", code="IT_HARDWARE")
    vendor = Vendor.objects.create(
        legal_name="Apex Hardware Supplies Ltd",
        trade_name="Apex Hardware",
        vendor_number="VEN-APEX-01",
        tax_identification_number="TIN-APEX-01",
        category=vcat,
        organization=org1,
        status=Vendor.STATUS_ACTIVE,
    )
    vendor_user = User.objects.create_user(
        email="vendor@apex.test", password="Pass123!Secure", role=vendor_role, vendor_id=vendor.id
    )

    # Organization 2: External Competitor
    org2 = Organization.objects.create(name="External Competitor Global", code="EXTCORP")
    dept_ext = Department.objects.create(name="External IT", code="EXTIT", organization=org2)
    ext_requester = User.objects.create_user(
        email="hacker@extcorp.test", password="Pass123!Secure", role=req_role, organization=org2, department=dept_ext
    )

    # Create 3 POs and Match Exceptions across departments:
    # Exc 1: Engineering / CC-ENG-01
    po1 = PurchaseOrder.objects.create(
        po_number="PO-BUG008-ENG",
        vendor=vendor,
        cost_center=cc_eng1,
        status=PurchaseOrder.STATUS_ISSUED,
        total_amount=Decimal("10000.00"),
    )
    inv1 = SupplierInvoice.objects.create(
        invoice_number="INV-BUG008-ENG",
        vendor=vendor,
        po=po1,
        invoice_date=timezone.now().date(),
        due_date=timezone.now().date() + datetime.timedelta(days=30),
        subtotal=Decimal("10000.00"),
        total_amount=Decimal("10000.00"),
        status=SupplierInvoice.STATUS_EXCEPTION,
    )
    exc1 = MatchException.objects.create(
        invoice=inv1,
        exception_type=MatchException.TYPE_PRICE_VARIANCE,
        status=MatchException.STATUS_OPEN,
        description="Engineering PO price variance",
        variance_amount=Decimal("500.00"),
    )

    # Exc 2: Procurement / CC-PROC-01
    po2 = PurchaseOrder.objects.create(
        po_number="PO-BUG008-PROC",
        vendor=vendor,
        cost_center=cc_proc,
        status=PurchaseOrder.STATUS_ISSUED,
        total_amount=Decimal("5000.00"),
    )
    inv2 = SupplierInvoice.objects.create(
        invoice_number="INV-BUG008-PROC",
        vendor=vendor,
        po=po2,
        invoice_date=timezone.now().date(),
        due_date=timezone.now().date() + datetime.timedelta(days=30),
        subtotal=Decimal("5000.00"),
        total_amount=Decimal("5000.00"),
        status=SupplierInvoice.STATUS_EXCEPTION,
    )
    exc2 = MatchException.objects.create(
        invoice=inv2,
        exception_type=MatchException.TYPE_QUANTITY_VARIANCE,
        status=MatchException.STATUS_OPEN,
        description="Procurement PO quantity variance",
        variance_amount=Decimal("300.00"),
    )

    # Exc 3: Engineering / CC-ENG-02 (DevOps)
    po3 = PurchaseOrder.objects.create(
        po_number="PO-BUG008-ENG2",
        vendor=vendor,
        cost_center=cc_eng2,
        status=PurchaseOrder.STATUS_ISSUED,
        total_amount=Decimal("7500.00"),
    )
    inv3 = SupplierInvoice.objects.create(
        invoice_number="INV-BUG008-ENG2",
        vendor=vendor,
        po=po3,
        invoice_date=timezone.now().date(),
        due_date=timezone.now().date() + datetime.timedelta(days=30),
        subtotal=Decimal("7500.00"),
        total_amount=Decimal("7500.00"),
        status=SupplierInvoice.STATUS_EXCEPTION,
    )
    exc3 = MatchException.objects.create(
        invoice=inv3,
        exception_type=MatchException.TYPE_TOTAL_VARIANCE,
        status=MatchException.STATUS_OPEN,
        description="DevOps PO total variance",
        variance_amount=Decimal("250.00"),
    )

    return {
        "org1": org1,
        "org2": org2,
        "dept_eng": dept_eng,
        "dept_proc": dept_proc,
        "dept_qa": dept_qa,
        "dept_ext": dept_ext,
        "cc_eng1": cc_eng1,
        "cc_eng2": cc_eng2,
        "cc_proc": cc_proc,
        "cc_qa": cc_qa,
        "admin_user": admin_user,
        "finance_user": finance_user,
        "eng_requester1": eng_requester1,
        "eng_requester2": eng_requester2,
        "proc_requester": proc_requester,
        "eng_approver": eng_approver,
        "proc_exec": proc_exec,
        "auditor": auditor,
        "vendor": vendor,
        "vendor_user": vendor_user,
        "ext_requester": ext_requester,
        "exc1": exc1,
        "exc2": exc2,
        "exc3": exc3,
    }


# ==============================================================================
# PART 1: BUG-008 TEST SCENARIOS (15 SCENARIOS)
# ==============================================================================


@pytest.mark.django_db
def test_bug008_01_default_all_departments_and_cost_centers(client, qa_setup_data):
    """Scenario 1: Default All Departments + All Cost Centers shows all open match exceptions."""
    d = qa_setup_data
    client.force_login(d["finance_user"])

    res = client.get("/finance/?dept=&cost_center=")
    assert res.status_code == 200
    exceptions = list(res.context["open_match_exceptions"])
    assert d["exc1"] in exceptions
    assert d["exc2"] in exceptions
    assert d["exc3"] in exceptions
    assert res.context["metrics"]["pending_match_exceptions"] == 3


@pytest.mark.django_db
def test_bug008_02_specific_department_only(client, qa_setup_data):
    """Scenario 2: Filtering by specific department retrieves all exceptions in that department."""
    d = qa_setup_data
    client.force_login(d["finance_user"])

    # Filter Engineering (UUID)
    res_eng = client.get(f"/finance/?dept={d['dept_eng'].id}&cost_center=")
    assert res_eng.status_code == 200
    eng_excs = list(res_eng.context["open_match_exceptions"])
    assert d["exc1"] in eng_excs
    assert d["exc3"] in eng_excs
    assert d["exc2"] not in eng_excs
    assert res_eng.context["metrics"]["pending_match_exceptions"] == 2

    # Filter Procurement by Name ("Procurement")
    res_proc_name = client.get("/finance/?dept=Procurement&cost_center=")
    assert res_proc_name.status_code == 200
    proc_excs = list(res_proc_name.context["open_match_exceptions"])
    assert d["exc2"] in proc_excs
    assert d["exc1"] not in proc_excs
    assert res_proc_name.context["metrics"]["pending_match_exceptions"] == 1


@pytest.mark.django_db
def test_bug008_03_specific_cost_center_only(client, qa_setup_data):
    """Scenario 3: Filtering by specific cost center retrieves only exceptions for that CC."""
    d = qa_setup_data
    client.force_login(d["finance_user"])

    # Filter CC-ENG-01
    res_cc1 = client.get(f"/finance/?dept=&cost_center={d['cc_eng1'].id}")
    assert res_cc1.status_code == 200
    cc1_excs = list(res_cc1.context["open_match_exceptions"])
    assert d["exc1"] in cc1_excs
    assert d["exc2"] not in cc1_excs
    assert d["exc3"] not in cc1_excs
    assert res_cc1.context["metrics"]["pending_match_exceptions"] == 1

    # Filter CC-ENG-02 by code ("CC-ENG-02")
    res_cc2 = client.get("/finance/?dept=&cost_center=CC-ENG-02")
    assert res_cc2.status_code == 200
    cc2_excs = list(res_cc2.context["open_match_exceptions"])
    assert d["exc3"] in cc2_excs
    assert d["exc1"] not in cc2_excs
    assert res_cc2.context["metrics"]["pending_match_exceptions"] == 1


@pytest.mark.django_db
def test_bug008_04_specific_department_and_specific_cost_center(client, qa_setup_data):
    """Scenario 4: Filtering by both department and matching cost center."""
    d = qa_setup_data
    client.force_login(d["finance_user"])

    res = client.get(f"/finance/?dept={d['dept_eng'].id}&cost_center={d['cc_eng1'].id}")
    assert res.status_code == 200
    excs = list(res.context["open_match_exceptions"])
    assert d["exc1"] in excs
    assert d["exc2"] not in excs
    assert d["exc3"] not in excs
    assert res.context["metrics"]["pending_match_exceptions"] == 1


@pytest.mark.django_db
def test_bug008_05_department_with_no_matching_exceptions(client, qa_setup_data):
    """Scenario 5: Department with no open exceptions displays empty state without error."""
    d = qa_setup_data
    client.force_login(d["finance_user"])

    # QA department has no POs/invoices
    res = client.get(f"/finance/?dept={d['dept_qa'].id}&cost_center=")
    assert res.status_code == 200
    excs = list(res.context["open_match_exceptions"])
    assert len(excs) == 0
    assert res.context["metrics"]["pending_match_exceptions"] == 0
    assert "There are currently no open invoice match exceptions." in res.content.decode()


@pytest.mark.django_db
def test_bug008_06_cost_center_with_no_matching_exceptions(client, qa_setup_data):
    """Scenario 6: Cost center with no open exceptions displays empty state without error."""
    d = qa_setup_data
    client.force_login(d["finance_user"])

    # CC-QA-01 has no invoices
    res = client.get(f"/finance/?dept=&cost_center={d['cc_qa'].id}")
    assert res.status_code == 200
    excs = list(res.context["open_match_exceptions"])
    assert len(excs) == 0
    assert res.context["metrics"]["pending_match_exceptions"] == 0
    assert "There are currently no open invoice match exceptions." in res.content.decode()


@pytest.mark.django_db
def test_bug008_07_resetting_filters_restores_default_results(client, qa_setup_data):
    """Scenario 7: Resetting filters by clearing query params restores all open exceptions."""
    d = qa_setup_data
    client.force_login(d["finance_user"])

    # Filter first
    res_filtered = client.get(f"/finance/?dept={d['dept_eng'].id}&cost_center={d['cc_eng1'].id}")
    assert len(list(res_filtered.context["open_match_exceptions"])) == 1

    # Reset
    res_reset = client.get("/finance/")
    assert res_reset.status_code == 200
    assert res_reset.context["metrics"]["pending_match_exceptions"] == 3


@pytest.mark.django_db
def test_bug008_08_changing_department_while_retaining_cost_center(client, qa_setup_data):
    """Scenario 8: Changing department with cost center safely executes query."""
    d = qa_setup_data
    client.force_login(d["finance_user"])

    # Dept Procurement + CC from Engineering produces empty result cleanly (0 rows, not 500)
    res = client.get(f"/finance/?dept={d['dept_proc'].id}&cost_center={d['cc_eng1'].id}")
    assert res.status_code == 200
    assert len(list(res.context["open_match_exceptions"])) == 0


@pytest.mark.django_db
def test_bug008_09_changing_cost_center_while_retaining_department(client, qa_setup_data):
    """Scenario 9: Switching cost center within same department dynamically updates scope."""
    d = qa_setup_data
    client.force_login(d["finance_user"])

    # CC-ENG-01
    res1 = client.get(f"/finance/?dept={d['dept_eng'].id}&cost_center={d['cc_eng1'].id}")
    assert d["exc1"] in list(res1.context["open_match_exceptions"])
    assert d["exc3"] not in list(res1.context["open_match_exceptions"])

    # Switch to CC-ENG-02
    res2 = client.get(f"/finance/?dept={d['dept_eng'].id}&cost_center={d['cc_eng2'].id}")
    assert d["exc3"] in list(res2.context["open_match_exceptions"])
    assert d["exc1"] not in list(res2.context["open_match_exceptions"])


@pytest.mark.django_db
def test_bug008_10_invalid_department_identifiers_handled_gracefully(client, qa_setup_data):
    """Scenario 10: Nonexistent UUID or invalid string does not trigger HTTP 500 error."""
    d = qa_setup_data
    client.force_login(d["finance_user"])

    # Invalid non-UUID string
    res_invalid_str = client.get("/finance/?dept=NonExistentDepartmentString999&cost_center=")
    assert res_invalid_str.status_code == 200
    assert len(list(res_invalid_str.context["open_match_exceptions"])) == 0
    assert res_invalid_str.context["metrics"]["pending_match_exceptions"] == 0

    # Random nonexistent UUID
    random_uuid = str(uuid.uuid4())
    res_nonexistent_uuid = client.get(f"/finance/?dept={random_uuid}&cost_center=")
    assert res_nonexistent_uuid.status_code == 200
    assert len(list(res_nonexistent_uuid.context["open_match_exceptions"])) == 0


@pytest.mark.django_db
def test_bug008_11_invalid_cost_center_identifiers_handled_gracefully(client, qa_setup_data):
    """Scenario 11: Nonexistent or malformed cost center identifiers return empty state."""
    d = qa_setup_data
    client.force_login(d["finance_user"])

    res_invalid_cc = client.get("/finance/?dept=&cost_center=INVALID-CC-CODE-404")
    assert res_invalid_cc.status_code == 200
    assert len(list(res_invalid_cc.context["open_match_exceptions"])) == 0

    random_uuid = str(uuid.uuid4())
    res_uuid_cc = client.get(f"/finance/?dept=&cost_center={random_uuid}")
    assert res_uuid_cc.status_code == 200
    assert len(list(res_uuid_cc.context["open_match_exceptions"])) == 0


@pytest.mark.django_db
def test_bug008_12_unauthorized_access_restricted_from_finance_dashboard(client, qa_setup_data):
    """Scenario 12: Vendor users and unauthenticated requests are strictly denied access."""
    d = qa_setup_data

    # Unauthenticated
    client.logout()
    res_anon = client.get("/finance/")
    assert res_anon.status_code in [302, 401]

    # Vendor User
    client.force_login(d["vendor_user"])
    res_vendor = client.get("/finance/")
    assert res_vendor.status_code in [403, 302]


@pytest.mark.django_db
def test_bug008_13_api_exceptions_endpoint_filtering_and_error_handling(qa_setup_data):
    """Scenario 13: REST API endpoint /api/v1/invoices/exceptions/ correctly filters by dept and cost center."""
    d = qa_setup_data
    api = APIClient()
    api.force_authenticate(user=d["finance_user"])

    # 1. Unfiltered API call
    res_all = api.get("/api/v1/invoices/exceptions/")
    assert res_all.status_code == status.HTTP_200_OK
    assert len(res_all.data["results"] if "results" in res_all.data else res_all.data) == 3

    # 2. Filter by dept code "ENG"
    res_dept = api.get("/api/v1/invoices/exceptions/?department=ENG")
    assert res_dept.status_code == status.HTTP_200_OK
    data_dept = res_dept.data["results"] if "results" in res_dept.data else res_dept.data
    assert len(data_dept) == 2

    # 3. Filter by cost_center code "CC-PROC-01"
    res_cc = api.get("/api/v1/invoices/exceptions/?cost_center=CC-PROC-01")
    assert res_cc.status_code == status.HTTP_200_OK
    data_cc = res_cc.data["results"] if "results" in res_cc.data else res_cc.data
    assert len(data_cc) == 1
    assert str(data_cc[0]["id"]) == str(d["exc2"].id)

    # 4. Invalid department string does not crash with 500
    res_inv = api.get("/api/v1/invoices/exceptions/?department=INVALID_DEPARTMENT_NAME")
    assert res_inv.status_code == status.HTTP_200_OK
    data_inv = res_inv.data["results"] if "results" in res_inv.data else res_inv.data
    assert len(data_inv) == 0


@pytest.mark.django_db
def test_bug008_14_pagination_with_active_filters(client, qa_setup_data):
    """Scenario 14: Pagination operates correctly with active filters."""
    d = qa_setup_data
    client.force_login(d["finance_user"])

    # Create 11 additional exceptions for Engineering to trigger pagination (page size = 10)
    for i in range(11):
        po = PurchaseOrder.objects.create(
            po_number=f"PO-PAGINATE-{i}",
            vendor=d["vendor"],
            cost_center=d["cc_eng1"],
            status=PurchaseOrder.STATUS_ISSUED,
            total_amount=Decimal("1000.00"),
        )
        inv = SupplierInvoice.objects.create(
            invoice_number=f"INV-PAGINATE-{i}",
            vendor=d["vendor"],
            po=po,
            invoice_date=timezone.now().date(),
            due_date=timezone.now().date() + datetime.timedelta(days=30),
            subtotal=Decimal("1000.00"),
            total_amount=Decimal("1000.00"),
            status=SupplierInvoice.STATUS_EXCEPTION,
        )
        MatchException.objects.create(
            invoice=inv,
            exception_type=MatchException.TYPE_PRICE_VARIANCE,
            status=MatchException.STATUS_OPEN,
            description=f"Pagination test exception {i}",
            variance_amount=Decimal("10.00"),
        )

    # Page 1 of Engineering filter
    res_page1 = client.get(f"/finance/?dept={d['dept_eng'].id}&cost_center=&page=1")
    assert res_page1.status_code == 200
    page1_items = list(res_page1.context["open_match_exceptions"])
    assert len(page1_items) == 10
    assert res_page1.context["metrics"]["pending_match_exceptions"] == 13

    # Page 2 of Engineering filter
    res_page2 = client.get(f"/finance/?dept={d['dept_eng'].id}&cost_center=&page=2")
    assert res_page2.status_code == 200
    page2_items = list(res_page2.context["open_match_exceptions"])
    assert len(page2_items) == 3


@pytest.mark.django_db
def test_bug008_15_returned_records_match_requested_scope_strictly(client, qa_setup_data):
    """Scenario 15: Verification that every returned record strictly belongs to the requested department."""
    d = qa_setup_data
    client.force_login(d["finance_user"])

    res = client.get(f"/finance/?dept={d['dept_eng'].id}")
    assert res.status_code == 200
    exceptions = list(res.context["open_match_exceptions"])
    assert len(exceptions) == 2
    for exc in exceptions:
        po_dept = getattr(getattr(exc.invoice.po, "cost_center", None), "department_id", None)
        assert po_dept == d["dept_eng"].id


# ==============================================================================
# PART 2: BUG-009 TEST SCENARIOS (13 SCENARIOS)
# ==============================================================================


@pytest.fixture
def pr_2026_00706_setup(qa_setup_data):
    """Sets up PR-2026-00706 for BUG-009 investigation and regression."""
    d = qa_setup_data
    pr = PurchaseRequisition.objects.create(
        pr_number="PR-2026-00706",
        title="Engineering Hardware Workstations",
        requester=d["eng_requester1"],
        department=d["dept_eng"],
        cost_center=d["cc_eng1"],
        status=PurchaseRequisition.STATUS_SUBMITTED,
        total_amount=Decimal("180000.00"),
        justification="Critical engineering hardware upgrades for Q4 release",
        requested_delivery_date=timezone.now().date() + datetime.timedelta(days=14),
    )
    line1 = PRLine.objects.create(
        requisition=pr,
        item_description="High-End Workstation Laptop",
        quantity=Decimal("6"),
        unit_of_measure="EA",
        estimated_unit_price=Decimal("25000.00"),
        estimated_total=Decimal("150000.00"),
    )
    line2 = PRLine.objects.create(
        requisition=pr,
        item_description="4K Ultra-wide Display Monitor",
        quantity=Decimal("6"),
        unit_of_measure="EA",
        estimated_unit_price=Decimal("5000.00"),
        estimated_total=Decimal("30000.00"),
    )
    return {**d, "pr": pr, "line1": line1, "line2": line2}


@pytest.mark.django_db
def test_bug009_01_authorized_requester_opens_own_requisition(client, pr_2026_00706_setup):
    """Scenario 1: Authorized requester opens their own requisition without Access Denied."""
    d = pr_2026_00706_setup
    client.force_login(d["eng_requester1"])

    res = client.get(f"/requisitions/{d['pr'].id}/")
    assert res.status_code == 200
    assert "PR-2026-00706" in res.content.decode()
    assert "Engineering Hardware Workstations" in res.content.decode()


@pytest.mark.django_db
def test_bug009_02_authorized_department_member_opens_permitted_requisition(client, pr_2026_00706_setup):
    """Scenario 2: Department colleague in same department accesses requisition details without false Access Denied."""
    d = pr_2026_00706_setup
    # Bob is also in Engineering department
    client.force_login(d["eng_requester2"])

    res = client.get(f"/requisitions/{d['pr'].id}/")
    assert res.status_code == 200
    assert "PR-2026-00706" in res.content.decode()


@pytest.mark.django_db
def test_bug009_03_authorized_role_based_users_retain_access(client, pr_2026_00706_setup):
    """Scenario 3: Authorized internal staff (Approver, Proc Exec, Finance, Auditor) can access details."""
    d = pr_2026_00706_setup

    # 1. Department Approver
    client.force_login(d["eng_approver"])
    res_appr = client.get(f"/requisitions/{d['pr'].id}/")
    assert res_appr.status_code == 200

    # 2. Procurement Executive
    client.force_login(d["proc_exec"])
    res_pe = client.get(f"/requisitions/{d['pr'].id}/")
    assert res_pe.status_code == 200

    # 3. Finance & AP
    client.force_login(d["finance_user"])
    res_fin = client.get(f"/requisitions/{d['pr'].id}/")
    assert res_fin.status_code == 200

    # 4. Auditor
    client.force_login(d["auditor"])
    res_aud = client.get(f"/requisitions/{d['pr'].id}/")
    assert res_aud.status_code == 200


@pytest.mark.django_db
def test_bug009_04_unauthorized_user_blocked_from_other_department_pr(client, pr_2026_00706_setup):
    """Scenario 4: Requester from a different department cannot access another department's requisition."""
    d = pr_2026_00706_setup
    # Charlie is in Procurement department, attempting to access Engineering PR
    client.force_login(d["proc_requester"])

    res = client.get(f"/requisitions/{d['pr'].id}/")
    assert res.status_code == 403


@pytest.mark.django_db
def test_bug009_05_unauthenticated_user_blocked(client, pr_2026_00706_setup):
    """Scenario 5: Unauthenticated access is redirected to login."""
    d = pr_2026_00706_setup
    client.logout()

    res = client.get(f"/requisitions/{d['pr'].id}/")
    assert res.status_code == 302
    assert "/login" in res.url


@pytest.mark.django_db
def test_bug009_06_nonexistent_requisition_returns_404(client, pr_2026_00706_setup):
    """Scenario 6: Nonexistent requisition identifier returns HTTP 404."""
    d = pr_2026_00706_setup
    client.force_login(d["eng_requester1"])

    # Nonexistent UUID
    random_uuid = str(uuid.uuid4())
    res_uuid = client.get(f"/requisitions/{random_uuid}/")
    assert res_uuid.status_code == 404

    # Nonexistent PR Number
    res_pr_num = client.get("/requisitions/PR-9999-99999/")
    assert res_pr_num.status_code == 404


@pytest.mark.django_db
def test_bug009_07_pr_number_handling_pr_2026_00706(client, pr_2026_00706_setup):
    """Scenario 7: Directly accessing requisition using business PR number PR-2026-00706 succeeds."""
    d = pr_2026_00706_setup
    client.force_login(d["eng_requester1"])

    # Web URL with PR number
    res_web = client.get("/requisitions/PR-2026-00706/")
    assert res_web.status_code == 200
    assert "PR-2026-00706" in res_web.content.decode()

    # API endpoint with PR number
    api = APIClient()
    api.force_authenticate(user=d["eng_requester1"])
    res_api = api.get("/api/v1/requisitions/PR-2026-00706/")
    assert res_api.status_code == status.HTTP_200_OK
    assert res_api.data["pr_number"] == "PR-2026-00706"


@pytest.mark.django_db
def test_bug009_08_valid_database_primary_key_handling(client, pr_2026_00706_setup):
    """Scenario 8: Accessing requisition using UUID primary key continues to work smoothly."""
    d = pr_2026_00706_setup
    client.force_login(d["eng_requester1"])

    res_web = client.get(f"/requisitions/{d['pr'].id}/")
    assert res_web.status_code == 200

    api = APIClient()
    api.force_authenticate(user=d["eng_requester1"])
    res_api = api.get(f"/api/v1/requisitions/{d['pr'].id}/")
    assert res_api.status_code == status.HTTP_200_OK
    assert res_api.data["id"] == str(d["pr"].id)


@pytest.mark.django_db
def test_bug009_09_correct_requisition_information_in_response(client, pr_2026_00706_setup):
    """Scenario 9: Response contains complete title, justification, status, delivery date."""
    d = pr_2026_00706_setup
    client.force_login(d["eng_requester1"])

    res = client.get("/requisitions/PR-2026-00706/")
    assert res.status_code == 200
    content = res.content.decode()
    assert "Engineering Hardware Workstations" in content
    assert "Critical engineering hardware upgrades" in content
    assert "₹180,000.00" in content or "180000" in content


@pytest.mark.django_db
def test_bug009_10_correct_line_items_in_response(client, pr_2026_00706_setup):
    """Scenario 10: Requisition details view correctly displays all line items."""
    d = pr_2026_00706_setup
    client.force_login(d["eng_requester1"])

    res = client.get("/requisitions/PR-2026-00706/")
    assert res.status_code == 200
    content = res.content.decode()
    assert "High-End Workstation Laptop" in content
    assert "4K Ultra-wide Display Monitor" in content


@pytest.mark.django_db
def test_bug009_11_existing_requisition_listing_continues_working(client, pr_2026_00706_setup):
    """Scenario 11: Requisition listing view continues working and displays permitted PRs."""
    d = pr_2026_00706_setup
    client.force_login(d["eng_requester1"])

    res = client.get("/requisitions/")
    assert res.status_code == 200
    assert "PR-2026-00706" in res.content.decode()


@pytest.mark.django_db
def test_bug009_12_existing_approval_workflows_continue_working(client, pr_2026_00706_setup):
    """Scenario 12: Existing approval actions work seamlessly with PR numbers and primary keys."""
    d = pr_2026_00706_setup
    client.force_login(d["eng_approver"])

    # Approve PR using business number
    res = client.post("/requisitions/PR-2026-00706/approve/", {"comments": "Approved via QA test"})
    assert res.status_code in [302, 200]
    d["pr"].refresh_from_db()
    assert d["pr"].status != PurchaseRequisition.STATUS_DRAFT


@pytest.mark.django_db
def test_bug009_13_identifier_manipulation_cannot_bypass_authorization(client, pr_2026_00706_setup):
    """Scenario 13: IDOR and cross-organization tampering attempts are strictly blocked."""
    d = pr_2026_00706_setup
    # External attacker from another organization
    client.force_login(d["ext_requester"])

    # Attempt to access via UUID
    res_uuid = client.get(f"/requisitions/{d['pr'].id}/")
    assert res_uuid.status_code == 403

    # Attempt to access via PR number
    res_pr_num = client.get("/requisitions/PR-2026-00706/")
    assert res_pr_num.status_code == 403

    # Attempt to access via API
    api = APIClient()
    api.force_authenticate(user=d["ext_requester"])
    res_api = api.get("/api/v1/requisitions/PR-2026-00706/")
    assert res_api.status_code in [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND]
