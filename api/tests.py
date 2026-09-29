import os
from unittest.mock import patch

from django.conf import settings
from django.core.exceptions import FieldDoesNotExist
from django.test import RequestFactory, SimpleTestCase
from django.urls import resolve, reverse
from rest_framework.test import APIRequestFactory

from .models import Farm, User
from .views import dashboard_users


class SchemaRegressionTests(SimpleTestCase):
    def test_user_model_does_not_define_address_relation(self):
        with self.assertRaises(FieldDoesNotExist):
            User._meta.get_field("address")

        self.assertIsNotNone(Farm._meta.get_field("address"))


class DashboardSidebarTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_default_database_url_is_configured(self):
        expected_url = os.environ.get("DATABASE_URL", "").strip() or f"sqlite:///{settings.BASE_DIR / 'db.sqlite3'}"
        self.assertEqual(settings.DATABASE_URL, expected_url)
        self.assertIn("ENGINE", settings.DATABASES["default"])

    @patch("api.views.database_ready_for_dashboard", return_value=False)
    def test_dashboard_renders_sidebar_sections(self, mock_db):
        request = self.factory.get("/dashboard/", {"section": "logistics"})

        response = dashboard_users(request)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Farmers")
        self.assertContains(response, "Logistics")
        self.assertContains(response, "Businesses")
        self.assertContains(response, "Audit Logs")

    @patch("api.views.database_ready_for_dashboard", return_value=False)
    def test_dashboard_has_create_links_for_businesses_and_logistics(self, mock_db):
        request = self.factory.get("/dashboard/", {"section": "businesses"})

        response = dashboard_users(request)

        self.assertContains(response, "Add New Business")
        self.assertContains(response, "Add New Logistics")


class DashboardAppRouteTests(SimpleTestCase):
    def test_dashboard_routes_belong_to_their_apps(self):
        expected_views = {
            "farmers:dashboard": "farmers.views",
            "businesses:dashboard": "businesses.views",
            "logistics:dashboard": "logistics.views",
        }

        for route_name, module_name in expected_views.items():
            with self.subTest(route_name=route_name):
                self.assertEqual(resolve(reverse(route_name)).func.__module__, module_name)


class FarmerRegistrationRouteTests(SimpleTestCase):
    def test_farmer_registration_routes_are_owned_by_farmers_app(self):
        routes = {
            "farmers_api:register": "/api/farmers/register/",
            "farmers_api:verify_code": "/api/farmers/verify-code/",
        }

        for route_name, expected_path in routes.items():
            with self.subTest(route_name=route_name):
                self.assertEqual(reverse(route_name), expected_path)
                self.assertEqual(resolve(expected_path).func.__module__, "farmers.views")

    def test_legacy_registration_routes_still_resolve_to_farmers_app(self):
        for path in ("/api/register/", "/api/verify-code/"):
            with self.subTest(path=path):
                self.assertEqual(resolve(path).func.__module__, "farmers.views")


class BusinessLogisticsRegistrationRouteTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()

    def test_registration_routes_belong_to_their_apps(self):
        routes = {
            "businesses_api:register": ("/api/businesses/register/", "businesses.views"),
            "businesses_api:verify_code": ("/api/businesses/verify-code/", "businesses.views"),
            "logistics_api:register": ("/api/logistics/register/", "logistics.views"),
            "logistics_api:verify_code": ("/api/logistics/verify-code/", "logistics.views"),
        }

        for route_name, (expected_path, module_name) in routes.items():
            with self.subTest(route_name=route_name):
                self.assertEqual(reverse(route_name), expected_path)
                self.assertEqual(resolve(expected_path).func.__module__, module_name)

    def test_business_registration_rejects_logistics_role(self):
        from businesses.views import register

        request = self.factory.post("/api/businesses/register/", {"role": "Logistics_Manager"}, format="json")

        self.assertEqual(register(request).status_code, 400)

    def test_logistics_registration_rejects_business_role(self):
        from logistics.views import register

        request = self.factory.post("/api/logistics/register/", {"role": "Bulk_Buyer"}, format="json")

        self.assertEqual(register(request).status_code, 400)
