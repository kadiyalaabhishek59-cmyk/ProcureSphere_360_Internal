import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src")))

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
django.setup()

from django.contrib.auth import get_user_model
from django.db import connection

U = get_user_model()
print("users:", U.objects.count())
try:
    with connection.cursor() as c:
        c.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
        print("tables:", c.fetchone()[0])
except Exception as e:
    print("db error:", e)
for u in U.objects.all().order_by("email"):
    print(u.email, "|", u.role, "| org:", getattr(u, "organization", None))
