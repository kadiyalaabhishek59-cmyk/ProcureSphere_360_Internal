import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src")))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django

django.setup()
from django.test.utils import setup_test_environment

setup_test_environment()

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.test import Client

from apps.audit.models import AuditLog
from apps.organization.models import Organization

U = get_user_model()
org = Organization.objects.first()
u = U.objects.get(email="auditor@hpe.com")

total_all = AuditLog.objects.count()
scoped_actor = AuditLog.objects.filter(Q(actor__organization=org) | Q(actor__department__organization=org)).count()
null_actor = AuditLog.objects.filter(actor__isnull=True).count()
print("total:", total_all, "| actor-in-org:", scoped_actor, "| actor-null:", null_actor,
      "| remainder:", total_all - scoped_actor - null_actor)

c = Client()
c.force_login(U.objects.get(email="procmgr@hpe.com"))
r = c.get("/manager/", follow=True)
html = r.content.decode("utf-8", "ignore")
print("manager status:", r.status_code)
print("has 'Executive Dashboard':", "Executive Dashboard" in html)
idx = html.find("readcrumb")
print("breadcrumb snippet:", html[idx-50:idx+250] if idx > 0 else "none")
