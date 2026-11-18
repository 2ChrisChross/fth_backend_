import json
from types import SimpleNamespace
from unittest.mock import patch

from django.http import Http404
from django.template.loader import get_template
from django.test import RequestFactory, SimpleTestCase, override_settings
from rest_framework.response import Response

from shared.models import User

from .simulator import (
    simulator_allowed,
    simulator_farmer_api,
    simulator_farmer_detail,
    simulator_farmers,
    simulator_page,
    simulator_register,
)


class SimulatorAccessTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.request = self.factory.get("/", REMOTE_ADDR="127.0.0.1")
        self.request.user = SimpleNamespace()
        self.local_database = {"default": {"HOST": "127.0.0.1"}}

    @override_settings(DEBUG=True, ENABLE_LOCAL_SIMULATOR=True)
    @patch("dashboard.simulator.has_dashboard_permission", return_value=True)
    def test_requires_local_connection_and_local_database(self, permission):
        with patch("dashboard.simulator.settings.DATABASES", self.local_database):
            self.assertTrue(simulator_allowed(self.request))
            self.request.META["REMOTE_ADDR"] = "192.0.2.1"
            self.assertFalse(simulator_allowed(self.request))
            self.request.META["REMOTE_ADDR"] = "127.0.0.1"
            self.request.META["HTTP_X_FORWARDED_FOR"] = "192.0.2.1"
            self.assertFalse(simulator_allowed(self.request))
            del self.request.META["HTTP_X_FORWARDED_FOR"]
        with patch(
            "dashboard.simulator.settings.DATABASES",
            {"default": {"HOST": "db.example"}},
        ):
            self.assertFalse(simulator_allowed(self.request))

    @patch("dashboard.simulator.has_dashboard_permission", return_value=True)
    def test_disabled_without_both_debug_and_explicit_flag(self, permission):
        with patch("dashboard.simulator.settings.DATABASES", self.local_database):
            for debug, enabled in ((False, True), (True, False)):
                with self.subTest(debug=debug, enabled=enabled):
                    with override_settings(DEBUG=debug, ENABLE_LOCAL_SIMULATOR=enabled):
                        self.assertFalse(simulator_allowed(self.request))

    @override_settings(DEBUG=True, ENABLE_LOCAL_SIMULATOR=True)
    @patch("dashboard.simulator.has_dashboard_permission", return_value=False)
    def test_rejects_users_without_dashboard_permission(self, permission):
        with patch("dashboard.simulator.settings.DATABASES", self.local_database):
            self.assertFalse(simulator_allowed(self.request))

    @override_settings(
        DEBUG=False, ENABLE_LOCAL_SIMULATOR=False, ENABLE_LIVE_SIMULATOR=True
    )
    @patch("dashboard.simulator.has_dashboard_permission")
    def test_live_switch_allows_only_authorized_staff_behind_proxy(self, permission):
        self.request.META["REMOTE_ADDR"] = "192.0.2.1"
        self.request.META["HTTP_X_FORWARDED_FOR"] = "198.51.100.1"
        permission.return_value = True
        self.assertTrue(simulator_allowed(self.request))
        permission.return_value = False
        self.assertFalse(simulator_allowed(self.request))
        permission.assert_called_with(
            self.request.user, "farmers.manage_dashboard_records"
        )

    @override_settings(
        DEBUG=False, ENABLE_LOCAL_SIMULATOR=False, ENABLE_LIVE_SIMULATOR=False
    )
    @patch("dashboard.simulator.has_dashboard_permission", return_value=True)
    def test_live_access_is_off_by_default(self, permission):
        self.request.META["REMOTE_ADDR"] = "192.0.2.1"
        self.assertFalse(simulator_allowed(self.request))

    @override_settings(ENABLE_LIVE_SIMULATOR=True)
    @patch("dashboard.simulator.dashboard_navigation", return_value=[])
    @patch("dashboard.simulator.simulator_allowed", return_value=True)
    def test_live_page_warns_that_actions_affect_records(self, allowed, navigation):
        html = simulator_page(self.request, "farmers").content.decode()
        self.assertIn("Live database warning.", html)
        self.assertIn("can affect real users", html)
        self.assertNotIn("Local testing only.", html)

    @override_settings(DEBUG=True, ENABLE_LOCAL_SIMULATOR=False)
    def test_page_and_registration_are_unavailable_when_disabled(self):
        page = self.factory.get("/dashboard/local-test/businesses/")
        post = self.factory.post(
            "/dashboard/local-test/businesses/register/",
            data="{}",
            content_type="application/json",
        )
        with self.assertRaises(Http404):
            simulator_page(page, "businesses")
        with self.assertRaises(Http404):
            simulator_register(post, "businesses")

    def test_title_link_is_shown_only_when_enabled(self):
        template = get_template("dashboard/records.html")
        context = {
            "section": "businesses",
            "section_title": "Bulk Buyers",
            "sections": [],
            "db_error": "Not available",
        }
        rendered = template.render(context)
        self.assertNotIn("/dashboard/local-test/businesses/", rendered)
        rendered = template.render({**context, "local_simulator_enabled": True})
        self.assertIn('href="/dashboard/local-test/businesses/"', rendered)
        self.assertIn("Bulk Buyers</a>", rendered)

    def test_farmer_title_link_is_shown_only_when_enabled(self):
        template = get_template("dashboard/records.html")
        context = {
            "section": "farmers",
            "section_title": "Farmers",
            "sections": [],
            "db_error": "Not available",
        }
        self.assertNotIn("/dashboard/local-test/farmers/", template.render(context))
        rendered = template.render({**context, "local_simulator_enabled": True})
        self.assertIn('href="/dashboard/local-test/farmers/"', rendered)

    @patch("dashboard.simulator.dashboard_navigation", return_value=[])
    @patch("dashboard.simulator.simulator_allowed", return_value=True)
    def test_farmer_list_keeps_registration_and_verification_separate(
        self, allowed, navigation
    ):
        self.request.user = SimpleNamespace()
        response = simulator_page(self.request, "farmers")
        html = response.content.decode()
        for form in (
            "farmer-search-form",
            "register-form",
            "verify-form",
            "recover-form",
        ):
            self.assertIn(f'id="{form}"', html)
        for form in (
            "farm-form",
            "farmer-listing-form",
            "document-list-form",
            "document-submit-form",
            "profile-form",
            "login-form",
        ):
            self.assertNotIn(f'id="{form}"', html)
        self.assertNotIn('id="vehicle-form"', html)
        self.assertIn('name="farm_size"', html)
        self.assertIn("without their password", html)
        self.assertIn('data-farmer-detail-url="/dashboard/local-test/farmers/0/"', html)

    @patch("dashboard.simulator.get_object_or_404")
    @patch("dashboard.simulator.resolve_enum_order_id", return_value=1)
    @patch("dashboard.simulator.dashboard_navigation", return_value=[])
    @patch("dashboard.simulator.simulator_allowed", return_value=True)
    def test_selected_farmer_page_has_workflows_and_back_link(
        self, allowed, navigation, role, get_farmer
    ):
        get_farmer.return_value = SimpleNamespace(user_id=42, username="test_farmer")
        html = simulator_farmer_detail(self.request, 42).content.decode()
        get_farmer.assert_called_once_with(
            User, user_id=42, role=1, deleted_at__isnull=True
        )
        for form in (
            "farm-form",
            "farmer-listing-form",
            "profile-form",
            "login-form",
            "document-list-form",
            "document-submit-form",
        ):
            self.assertIn(f'id="{form}"', html)
        self.assertNotIn('id="farmer-search-form"', html)
        self.assertNotIn('id="register-form"', html)
        self.assertIn('data-farmer-id="42"', html)
        self.assertIn('data-farmer-username="test_farmer"', html)
        self.assertIn('href="/dashboard/local-test/farmers/"', html)
        self.assertIn('value="test_farmer"', html)
        self.assertIn('data-get="orders/"', html)
        self.assertIn('data-get="messages/"', html)
        self.assertIn("Test farmer login", html)
        self.assertIn('id="farmer-farms"', html)
        self.assertIn('id="farmer-listings"', html)
        self.assertIn('id="farmer-crops"', html)
        self.assertIn('id="refresh-crops"', html)
        self.assertIn('id="refresh-farms"', html)
        self.assertIn('id="refresh-listings"', html)
        self.assertIn('data-action="add"', html)
        self.assertIn('data-action="update"', html)
        self.assertIn('id="crop-expense-form"', html)
        self.assertNotIn("Listing ID (update only)", html)
        self.assertNotIn("Existing crop ID (new listing)", html)

    @patch("dashboard.simulator.simulator_allowed", return_value=False)
    def test_farmer_page_and_registration_are_unavailable_when_not_allowed(
        self, allowed
    ):
        with self.assertRaises(Http404):
            simulator_page(self.request, "farmers")
        request = self.factory.post("/", data="{}", content_type="application/json")
        with self.assertRaises(Http404):
            simulator_register(request, "farmers")
        with self.assertRaises(Http404):
            simulator_farmers(self.request)
        with self.assertRaises(Http404):
            simulator_farmer_api(self.request, 1, "me/")
        with self.assertRaises(Http404):
            simulator_farmer_detail(self.request, 1)

    @patch("dashboard.simulator.dashboard_navigation", return_value=[])
    @patch("dashboard.simulator.simulator_allowed", return_value=True)
    def test_buyer_and_logistics_have_message_form(self, allowed, navigation):
        for section in ("businesses", "logistics"):
            with self.subTest(section=section):
                html = simulator_page(self.request, section).content.decode()
                self.assertIn('id="farmer-message-form"', html)
                self.assertNotIn('id="farmer-search-form"', html)
                self.assertIn('id="refresh-token"', html)


class SimulatorRegistrationTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        address_validation = patch(
            "dashboard.simulator.validate_address", return_value=None
        )
        address_validation.start()
        self.addCleanup(address_validation.stop)

    @patch("dashboard.simulator.register_farmer")
    @patch("dashboard.simulator.check_simulator")
    def test_farmer_registration_calls_farmer_api_and_returns_request_id(
        self, check, register
    ):
        register.return_value = Response(
            {"user_id": 4, "code_request_id": 9}, status=201
        )
        request = self.factory.post(
            "/dashboard/local-test/farmers/register/",
            data=json.dumps({"username": "farmer"}),
            content_type="application/json",
        )
        response = simulator_register(request, "farmers")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(json.loads(response.content)["code_request_id"], 9)
        register.assert_called_once_with(request)

    @patch("dashboard.simulator.register_farmer")
    @patch("dashboard.simulator.check_simulator")
    def test_farmer_registration_returns_api_validation_errors(self, check, register):
        register.return_value = Response({"farm_size": ["Required."]}, status=400)
        request = self.factory.post("/", data="{}", content_type="application/json")
        response = simulator_register(request, "farmers")
        self.assertEqual(response.status_code, 400)
        self.assertIn("farm_size", json.loads(response.content))

    @patch("dashboard.simulator.register_buyer", return_value=Response(status=201))
    @patch("dashboard.simulator.check_simulator")
    def test_successful_registration_requires_staff_review(self, check, register):
        request = self.factory.post(
            "/dashboard/local-test/businesses/register/",
            data=json.dumps({"username": "buyer"}),
            content_type="application/json",
        )
        response = simulator_register(request, "businesses")
        self.assertEqual(response.status_code, 201)
        self.assertIn("staff member", json.loads(response.content)["detail"])
        self.assertNotIn("verification_code", json.loads(response.content))
        register.assert_called_once_with(request)

    @patch("dashboard.simulator.register_buyer")
    @patch("dashboard.simulator.check_simulator")
    def test_failed_registration_does_not_read_any_verification_code(
        self, check, register
    ):
        register.return_value = Response({"username": ["Already used."]}, status=409)
        request = self.factory.post(
            "/dashboard/local-test/businesses/register/",
            data=json.dumps({"username": "existing"}),
            content_type="application/json",
        )
        response = simulator_register(request, "businesses")
        self.assertEqual(response.status_code, 409)
        self.assertNotIn("verification_code", json.loads(response.content))
