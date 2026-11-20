import pytest
from django.test import Client


@pytest.mark.django_db
class TestLandingCardModalStacking:
    def test_home_page_contains_card_modal_with_high_z_index(self):
        client = Client()
        response = client.get("/")
        assert response.status_code == 200
        content = response.content.decode("utf-8")

        # Verify modal element exists with z-index: 100000
        assert 'id="cap-module-modal"' in content
        assert "z-index:100000" in content

        # Verify modal inner has scroll containment
        assert "max-height:90vh" in content
        assert "overflow-y:auto" in content

        # Verify core_capabilities.js script tag has cache-busting version
        assert "core_capabilities.js?v=" in content

    def test_core_capabilities_js_teleports_modal_to_body(self):
        with open("static/landing/js/core_capabilities.js", "r", encoding="utf-8") as f:
            js_code = f.read()

        # Must ensure modal is appended to document.body to escape section stacking contexts
        assert "document.body.appendChild(modal)" in js_code
        assert "if (modal && modal.parentElement !== document.body)" in js_code

    def test_solutions_page_contains_modal_with_high_z_index(self):
        client = Client()
        response = client.get("/solutions/")
        assert response.status_code == 200
        content = response.content.decode("utf-8")

        # Verify modal overlay has high z-index and teleport logic
        assert 'id="sol-module-modal"' in content
        assert "z-index: 100000;" in content
        assert "document.body.appendChild(overlay)" in content
