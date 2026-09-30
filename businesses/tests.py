from django.test import SimpleTestCase
from django.urls import resolve, reverse
from rest_framework.test import APIRequestFactory

from .models import BulkBuyer


class BulkBuyerTests(SimpleTestCase):
    def test_bulk_buyer_uses_renamed_table(self):
        self.assertEqual(BulkBuyer._meta.db_table, "BULK_BUYERS")


class BulkBuyerRegistrationTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()

    def test_registration_routes_belong_to_businesses_app(self):
        routes = {
            "businesses_api:register": (
                "/api/businesses/register/",
                "businesses.views",
            ),
            "businesses_api:verify_code": (
                "/api/businesses/verify-code/",
                "businesses.views",
            ),
        }

        for route_name, (expected_path, module_name) in routes.items():
            with self.subTest(route_name=route_name):
                self.assertEqual(reverse(route_name), expected_path)
                self.assertEqual(resolve(expected_path).func.__module__, module_name)

    def test_bulk_buyer_registration_rejects_logistics_role(self):
        from .views import register

        data = {
            "username": "buyer",
            "password": "password",
            "first_name": "First",
            "last_name": "Last",
            "date_of_birth": "2000-01-01",
            "phone_number": "5550000",
            "business_name": "Market",
            "role": "Logistics_Manager",
            "personal_address": {
                "street_address": "1 Main St",
                "barangay": "Central",
                "municipality_city": "City",
                "province": "Province",
                "postal_code": "1000",
            },
            "business_address": {
                "street_address": "2 Main St",
                "barangay": "Central",
                "municipality_city": "City",
                "province": "Province",
                "postal_code": "1000",
            },
            "documents": [
                {"type": document_type, "url": "https://example.com/document"}
                for document_type in (
                    "birth_certificate",
                    "business_utility_bill",
                    "business_permit",
                    "national_id",
                )
            ],
        }
        request = self.factory.post("/api/businesses/register/", data, format="json")

        response = register(request)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            [str(error) for error in response.data["role"]],
            ["Must be Bulk_Buyer."],
        )

    def test_bulk_buyer_registration_reports_missing_fields(self):
        from .views import register

        response = register(
            self.factory.post("/api/businesses/register/", {}, format="json")
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["username"], ["This field is required."])

    def test_registration_reports_nested_address_errors(self):
        from .views import register

        data = {
            "username": "buyer",
            "password": "password",
            "first_name": "First",
            "last_name": "Last",
            "date_of_birth": "2000-01-01",
            "phone_number": "5550000",
            "business_name": "Market",
            "role": "Bulk_Buyer",
            "personal_address": {
                "street_address": "1 Main St",
                "barangay": "Central",
                "municipality_city": "City",
                "province": "Province",
            },
            "business_address": {
                "street_address": "2 Main St",
                "barangay": "Central",
                "municipality_city": "City",
                "province": "Province",
                "postal_code": "1000",
            },
            "documents": [
                {"type": document_type, "url": "https://example.com/document"}
                for document_type in (
                    "birth_certificate",
                    "business_utility_bill",
                    "business_permit",
                    "national_id",
                )
            ],
        }

        response = register(
            self.factory.post("/api/businesses/register/", data, format="json")
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            str(response.data["personal_address"]["postal_code"][0]),
            "This field is required.",
        )

    def test_duplicate_username_returns_field_error(self):
        from unittest.mock import patch

        from .views import register

        data = {
            "username": "buyer",
            "password": "password",
            "first_name": "First",
            "last_name": "Last",
            "date_of_birth": "2000-01-01",
            "phone_number": "5550000",
            "business_name": "Market",
            "role": "Bulk_Buyer",
            "personal_address": {
                "street_address": "1 Main St",
                "barangay": "Central",
                "municipality_city": "City",
                "province": "Province",
                "postal_code": "1000",
            },
            "business_address": {
                "street_address": "2 Main St",
                "barangay": "Central",
                "municipality_city": "City",
                "province": "Province",
                "postal_code": "1000",
            },
            "documents": [
                {"type": document_type, "url": "https://example.com/document"}
                for document_type in (
                    "birth_certificate",
                    "business_utility_bill",
                    "business_permit",
                    "national_id",
                )
            ],
        }

        with (
            patch("businesses.views.resolve_enum_order_id", return_value=1),
            patch("businesses.views.User.objects") as user_manager,
        ):
            user_manager.filter.return_value.exists.return_value = True
            response = register(
                self.factory.post("/api/businesses/register/", data, format="json")
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            [str(error) for error in response.data["username"]],
            ["This username is already in use."],
        )
