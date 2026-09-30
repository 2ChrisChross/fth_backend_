from unittest.mock import patch

from django.test import SimpleTestCase
from django.urls import resolve, reverse
from rest_framework.test import APIRequestFactory


class FarmerRegistrationRouteTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()

    def test_farmer_registration_routes_are_owned_by_farmers_app(self):
        routes = {
            "farmers_api:register": "/api/farmers/register/",
            "farmers_api:verify_code": "/api/farmers/verify-code/",
        }

        for route_name, expected_path in routes.items():
            with self.subTest(route_name=route_name):
                self.assertEqual(reverse(route_name), expected_path)
                self.assertEqual(
                    resolve(expected_path).func.__module__, "farmers.views"
                )

    def test_legacy_registration_routes_still_resolve_to_farmers_app(self):
        for path in ("/api/register/", "/api/verify-code/"):
            with self.subTest(path=path):
                self.assertEqual(resolve(path).func.__module__, "farmers.views")

    def test_registration_reports_missing_fields(self):
        from .views import register_user

        response = register_user(
            self.factory.post("/api/farmers/register/", {}, format="json")
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["phonenumber"], ["This field is required."])

    def test_registration_requires_four_real_document_urls(self):
        from .views import register_user

        required_fields = (
            "phonenumber",
            "username",
            "password",
            "firstname",
            "lastname",
            "region",
            "province",
            "municipality",
            "baranggay",
            "house_number",
            "street",
            "postal_code",
            "farm_size",
            "farm_region",
            "farm_province",
            "farm_municipality",
            "farm_barangay",
            "farm_house_number",
            "farm_street",
            "farm_postal_code",
        )
        data = {field: "value" for field in required_fields}
        data["farm_size"] = "10"
        data["role"] = "Farmer"

        response = register_user(
            self.factory.post("/api/farmers/register/", data, format="json")
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            [str(error) for error in response.data["documents"]],
            ["Provide at least four document URLs."],
        )

    def test_registration_reports_invalid_role(self):
        from .views import register_user

        required_fields = (
            "phonenumber",
            "username",
            "password",
            "firstname",
            "lastname",
            "region",
            "province",
            "municipality",
            "baranggay",
            "house_number",
            "street",
            "postal_code",
            "farm_size",
            "farm_region",
            "farm_province",
            "farm_municipality",
            "farm_barangay",
            "farm_house_number",
            "farm_street",
            "farm_postal_code",
        )
        data = {field: "1" for field in required_fields}
        data["role"] = "Bulk_Buyer"

        response = register_user(
            self.factory.post("/api/farmers/register/", data, format="json")
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, {"role": ["Must be Farmer."]})

    @patch("farmers.views.resolve_enum_order_id", return_value=1)
    def test_registration_reports_invalid_farm_size(self, resolve_enum):
        from .views import register_user

        required_fields = (
            "phonenumber",
            "username",
            "password",
            "firstname",
            "lastname",
            "region",
            "province",
            "municipality",
            "baranggay",
            "house_number",
            "street",
            "postal_code",
            "farm_size",
            "farm_region",
            "farm_province",
            "farm_municipality",
            "farm_barangay",
            "farm_house_number",
            "farm_street",
            "farm_postal_code",
        )
        data = {field: "value" for field in required_fields}
        data["farm_size"] = "not-a-number"
        data["role"] = "Farmer"

        response = register_user(
            self.factory.post("/api/farmers/register/", data, format="json")
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, {"farm_size": ["Enter a valid number."]})
