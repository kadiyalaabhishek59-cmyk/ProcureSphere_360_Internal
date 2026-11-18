"""
Authentication manager for Localhost and Render API performance benchmarking.
Handles role-based session login, CSRF tokens, and cookie management.
"""

import logging
import requests
from .config import LOCAL_BASE_URL, RENDER_BASE_URL, ROLE_CREDENTIALS, REQUEST_TIMEOUT

logger = logging.getLogger("benchmark.auth")


class AuthManager:
    def __init__(self):
        self._sessions = {
            "local": {},
            "render": {},
        }
        self.base_urls = {
            "local": LOCAL_BASE_URL.rstrip("/"),
            "render": RENDER_BASE_URL.rstrip("/"),
        }

    def login_role(self, env: str, role: str) -> requests.Session:
        """Authenticate as the given role in the specified environment."""
        if role in self._sessions[env]:
            return self._sessions[env][role]

        session = requests.Session()
        base_url = self.base_urls[env]

        if not role or role == "Anonymous":
            self._sessions[env][role] = session
            return session

        creds = ROLE_CREDENTIALS.get(role)
        if not creds:
            # Fallback to Super Admin credentials if specific role not found
            creds = ROLE_CREDENTIALS.get("Super Admin")

        login_url = f"{base_url}/api/v1/auth/token/"
        try:
            resp = session.post(
                login_url,
                json={"email": creds["email"], "password": creds["password"]},
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code == 200:
                data = resp.json()
                csrf = data.get("csrf_token") or session.cookies.get("csrftoken")
                session.headers.update({
                    "X-CSRFToken": csrf or "",
                    "Referer": base_url,
                    "Accept": "application/json",
                })
                self._sessions[env][role] = session
                logger.info(f"[{env.upper()}] Successfully logged in as {role} ({creds['email']})")
                return session
            else:
                logger.error(
                    f"[{env.upper()}] Failed to log in as {role}: HTTP {resp.status_code} - {resp.text[:100]}"
                )
                self._sessions[env][role] = session
                return session
        except Exception as exc:
            logger.error(f"[{env.upper()}] Exception during login for {role}: {exc}")
            self._sessions[env][role] = session
            return session

    def get_session(self, env: str, role: str) -> requests.Session:
        """Retrieve existing authenticated session or create a new one."""
        if role in self._sessions[env]:
            return self._sessions[env][role]
        return self.login_role(env, role)

    def warm_up_render(self) -> dict:
        """Execute initial request to Render to handle cold start and record timing."""
        url = f"{self.base_urls['render']}/api/v1/health/"
        import time
        t0 = time.perf_counter()
        cold_start_time = None
        status = None
        err = None
        try:
            resp = requests.get(url, timeout=40.0)
            t1 = time.perf_counter()
            cold_start_time = round((t1 - t0) * 1000.0, 2)
            status = resp.status_code
        except Exception as e:
            t1 = time.perf_counter()
            cold_start_time = round((t1 - t0) * 1000.0, 2)
            err = str(e)

        return {
            "first_request_ms": cold_start_time,
            "status_code": status,
            "error": err,
            "is_cold_start": cold_start_time > 1500.0 if cold_start_time else True,
        }
