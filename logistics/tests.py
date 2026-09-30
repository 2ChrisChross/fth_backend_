from django.test import SimpleTestCase
from django.urls import resolve, reverse
from rest_framework.test import APIRequestFactory

from .models import LogisticsCompany


class LogisticsCompanyTests(SimpleTestCase):
    def test_logistics_company_uses_renamed_table(self):
        self.assertEqual(LogisticsCompany._meta.db_table, "LOGISTICS_COMPANIES")


class LogisticsRegistrationTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()

    def test_registration_routes_belong_to_logistics_app(self):
        routes = {
            "logistics_api:register": ("/api/logistics/register/", "logistics.views"),
            "logistics_api:verify_code": (
                "/api/logistics/verify-code/",
                "logistics.views",
            ),
        }

        for route_name, (expected_path, module_name) in routes.items():
            with self.subTest(route_name=route_name):
                self.assertEqual(reverse(route_name), expected_path)
                self.assertEqual(resolve(expected_path).func.__module__, module_name)

    def test_logistics_registration_rejects_bulk_buyer_role(self):
        from .views import register

        data = {
            "username": "manager",
            "password": "password",
            "first_name": "First",
            "last_name": "Last",
            "date_of_birth": "2000-01-01",
            "phone_number": "5550000",
            "company_name": "Fleet",
            "company_phone": "5550001",
            "company_email": "fleet@example.com",
            "role": "Bulk_Buyer",
        }
        request = self.factory.post("/api/logistics/register/", data, format="json")
        response = register(request)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            [str(error) for error in response.data["role"]],
            ["Must be Logistics_Manager."],
        )

    def test_logistics_registration_reports_missing_fields(self):
        from .views import register

        response = register(
            self.factory.post("/api/logistics/register/", {}, format="json")
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["username"], ["This field is required."])

    def test_registration_reports_invalid_company_email(self):
        from .views import register

        data = {
            "username": "manager",
            "password": "password",
            "first_name": "First",
            "last_name": "Last",
            "date_of_birth": "2000-01-01",
            "phone_number": "5550000",
            "company_name": "Fleet",
            "company_phone": "5550001",
            "company_email": "not-an-email",
            "role": "Logistics_Manager",
            "personal_address": {
                "street_address": "1 Main St",
                "barangay": "Central",
                "municipality_city": "City",
                "province": "Province",
                "postal_code": "1000",
            },
            "company_address": {
                "street_address": "2 Main St",
                "barangay": "Central",
                "municipality_city": "City",
                "province": "Province",
                "postal_code": "1000",
            },
            "documents": [
                {"type": document_type, "url": "https://example.com/document"}
                for document_type in (
                    "ltfrb_franchise_for_trucking",
                    "vehicle_photo",
                    "vehicle_driver_license",
                    "national_id",
                    "official_receipt",
                    "certificate_of_registration",
                    "nbi_clearance",
                )
            ],
            "vehicle": {
                "model": "Truck",
                "plate_number": "ABC123",
                "max_weight_capacity_kg": "1000",
                "max_volume_capacity_m3": "10",
                "body_type": "Other",
                "is_refrigerated": True,
            },
        }

        response = register(
            self.factory.post("/api/logistics/register/", data, format="json")
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            str(response.data["company_email"][0]),
            "Enter a valid email address.",
        )

    def test_duplicate_username_returns_field_error(self):
        from unittest.mock import patch

        from .views import register

        data = {
            "username": "manager",
            "password": "password",
            "first_name": "First",
            "last_name": "Last",
            "date_of_birth": "2000-01-01",
            "phone_number": "5550000",
            "company_name": "Fleet",
            "company_phone": "5550001",
            "company_email": "fleet@example.com",
            "role": "Logistics_Manager",
            "personal_address": {
                "street_address": "1 Main St",
                "barangay": "Central",
                "municipality_city": "City",
                "province": "Province",
                "postal_code": "1000",
            },
            "company_address": {
                "street_address": "2 Main St",
                "barangay": "Central",
                "municipality_city": "City",
                "province": "Province",
                "postal_code": "1000",
            },
            "documents": [
                {"type": document_type, "url": "https://example.com/document"}
                for document_type in (
                    "ltfrb_franchise_for_trucking",
                    "vehicle_photo",
                    "vehicle_driver_license",
                    "national_id",
                    "official_receipt",
                    "certificate_of_registration",
                    "nbi_clearance",
                )
            ],
            "vehicle": {
                "model": "Truck",
                "plate_number": "ABC123",
                "max_weight_capacity_kg": "1000",
                "max_volume_capacity_m3": "10",
                "body_type": "Other",
                "is_refrigerated": True,
            },
        }

        with (
            patch("logistics.views.resolve_enum_order_id", return_value=1),
            patch("logistics.views.User.objects") as user_manager,
        ):
            user_manager.filter.return_value.exists.return_value = True
            response = register(
                self.factory.post("/api/logistics/register/", data, format="json")
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.data, {"username": ["This username is already in use."]}
        )
