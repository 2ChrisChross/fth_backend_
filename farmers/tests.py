from unittest.mock import patch

from django.contrib.auth.hashers import check_password, make_password
from django.test import SimpleTestCase
from django.urls import resolve, reverse
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APIRequestFactory
from rest_framework_simplejwt.exceptions import TokenError

from shared.models import User

from . import authentication
from .serializers import FarmerProfileSerializer
from .tokens import FarmerRefreshToken


class FarmerRegistrationRouteTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()

    def test_farmer_registration_routes_are_owned_by_farmers_app(self):
        routes = {
            "farmers_api:register": "/api/farmers/register/",
            "farmers_api:verify_code": "/api/farmers/verify-code/",
            "farmers_api:login": "/api/farmers/login/",
            "farmers_api:me": "/api/farmers/me/",
            "farmers_api:code_request": "/api/farmers/code-requests/",
            "farmers_api:recover": "/api/farmers/recover/",
            "farmers_api:admin_code_requests": "/api/farmers/admin/code-requests/",
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


class FarmerJWTAuthenticationTests(SimpleTestCase):
    @patch("farmers.authentication.resolve_enum_order_id", return_value=7)
    @patch("farmers.authentication.User.objects.filter")
    def test_authentication_resolves_verified_farmer(self, filter_users, resolve_role):
        user = User(user_id=12, role=7, is_verified=1)
        filter_users.return_value.first.return_value = user

        authenticated_user = authentication.FarmerJWTAuthentication().get_user(
            {"user_id": 12}
        )

        self.assertIs(authenticated_user, user)
        self.assertTrue(authenticated_user.is_authenticated)
        resolve_role.assert_called_once_with("role", "Farmer")

    @patch("farmers.authentication.resolve_enum_order_id", return_value=7)
    @patch("farmers.authentication.User.objects.filter")
    def test_authentication_rejects_unverified_farmer(self, filter_users, resolve_role):
        filter_users.return_value.first.return_value = None

        with self.assertRaises(AuthenticationFailed):
            authentication.FarmerJWTAuthentication().get_user({"user_id": 12})

    def test_refresh_token_uses_farmer_identifier(self):
        token = FarmerRefreshToken.for_user(User(user_id=12))

        self.assertEqual(token["user_id"], "12")

    @patch("farmers.tokens.FarmerRevokedRefreshToken.objects.filter")
    def test_refresh_token_rejects_revoked_jti(self, filter_revoked):
        token = FarmerRefreshToken.for_user(User(user_id=12))
        filter_revoked.return_value.exists.return_value = True

        with self.assertRaises(TokenError):
            FarmerRefreshToken(str(token))


class FarmerCredentialTests(SimpleTestCase):
    @patch("farmers.views.FarmerRefreshToken.for_user")
    @patch("farmers.views.resolve_enum_order_id", return_value=7)
    @patch("farmers.views.User.objects.filter")
    def test_login_returns_tokens_for_verified_farmer(
        self, filter_users, resolve_role, create_refresh
    ):
        from .views import login_user

        user = User(
            user_id=12,
            username="farmer12",
            password_hash=make_password("FarmPass!7821"),
            role=7,
            is_verified=1,
        )
        filter_users.return_value.first.return_value = user
        refresh = type("Refresh", (), {"access_token": "access-token"})()
        create_refresh.return_value = refresh
        refresh.__class__.__str__ = lambda self: "refresh-token"

        response = login_user(
            APIRequestFactory().post(
                "/api/farmers/login/",
                {"username": "farmer12", "password": "FarmPass!7821"},
                format="json",
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            {"access": "access-token", "refresh": "refresh-token"},
        )
        resolve_role.assert_called_once_with("role", "Farmer")

    @patch("farmers.views.FarmerRefreshToken.for_user")
    @patch("farmers.views.User.objects.filter")
    def test_login_rejects_unverified_farmer(self, filter_users, create_refresh):
        from .views import login_user

        user = User(
            username="farmer12",
            password_hash=make_password("FarmPass!7821"),
            is_verified=0,
        )
        filter_users.return_value.first.return_value = user

        response = login_user(
            APIRequestFactory().post(
                "/api/farmers/login/",
                {"username": "farmer12", "password": "FarmPass!7821"},
                format="json",
            )
        )

        self.assertEqual(response.status_code, 403)
        create_refresh.assert_not_called()

    def test_profile_update_hashes_new_password(self):
        user = User(
            user_id=12,
            username="farmer12",
            first_name="Farmer",
            last_name="Twelve",
            password_hash=make_password("OldPass!7821"),
        )
        serializer = FarmerProfileSerializer(
            user,
            data={"new_password": "ChangedPass!827"},
            partial=True,
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        with patch.object(user, "save") as save_user:
            serializer.save()

        self.assertTrue(check_password("ChangedPass!827", user.password_hash))
        save_user.assert_called_once_with(update_fields=["password_hash"])
