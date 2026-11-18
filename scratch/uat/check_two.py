import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src")))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django

django.setup()
from django.test.utils import setup_test_environment

setup_test_environment()

from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone as tz

from apps.audit.models import AuditLog

U = get_user_model()
u = U.objects.get(email="admin@hpe.com")
c = Client()
c.force_login(u)
before = tz.now()
r = c.get("/superadmin/", follow=True)
after = tz.now()
new = AuditLog.objects.filter(timestamp__gte=before, timestamp__lte=after)
print("status:", r.status_code, "| new audit rows during GET:", new.count())
for a in new[:5]:
    print("  ", a.action, "|", a.target_model, "|", a.actor)

import re
html = r.content.decode("utf-8", "ignore")
opts = re.findall(r'<option[^>]*value="([^"]*)"', html)
print("option values:", opts[:20])
