import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src")))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django

django.setup()
from django.test.utils import setup_test_environment

setup_test_environment()

from django.contrib.auth import get_user_model
from django.test import Client

U = get_user_model()
c = Client()
c.force_login(U.objects.get(email="procmgr@hpe.com"))
r = c.get("/reports/", follow=True)
html = r.content.decode("utf-8", "ignore")
print("status:", r.status_code)
opts = re.findall(r'<option[^>]*value="([^"]*)"[^>]*>([^<]*)', html)
print("total options:", len(opts))
for v, t in opts:
    print("  ", repr(v), "|", t.strip()[:60])
