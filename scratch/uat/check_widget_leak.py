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

U = get_user_model()
proc = U.objects.get(email="procexec@hpe.com")
req = U.objects.get(email="requester@hpe.com")

for path in ("/notifications/htmx/feed/", "/notifications/htmx/pending-actions/"):
    c = Client()
    c.force_login(proc)
    r1 = c.get(path)
    c.logout()
    c.force_login(req)
    r2 = c.get(path)
    print("PATH:", path)
    print("  procexec status:", r1.status_code, "bytes:", len(r1.content))
    print("  requester status:", r2.status_code, "bytes:", len(r2.content))
    print("  requester content mentions procexec?:", b"procexec" in r2.content)
    # show the first bit of requester content
    print("  requester snippet:", r2.content[:400].decode("utf-8", "ignore").replace("\n", " ")[:380])
