from unittest.mock import MagicMock, patch

from django.contrib.auth.hashers import check_password, make_password
from django.test import SimpleTestCase
from django.urls import resolve, reverse
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework_simplejwt.exceptions import TokenError

from shared.models import User

from . import authentication, views, workflows
from .models import FarmerCodeRequest
from .serializers import (
    FarmerDashboardRegistrationSerializer,
    FarmerDashboardUpdateSerializer,
    FarmerProfileSerializer,
    FarmerRegistrationSerializer,
)
from .tokens import FarmerRefreshToken


class FarmerRegistrationRouteTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()

    def valid_registration_data(self):
        return {
            "phonenumber": "+639123456789",
            "username": "test-farmer",
            "password": "InitialPass!123",
            "firstname": "Juan",
            "lastname": "Dela Cruz",
            "region": "Region I",
            "province": "Ilocos Norte",
            "municipality": "Laoag City",
            "baranggay": "Barangay 1",
            "house_number": "12",
            "street": "Main Street",
            "postal_code": "2900",
            "farm_size": "2.5",
            "farm_region": "Region I",
            "farm_province": "Ilocos Norte",
            "farm_municipality": "Laoag City",
            "farm_barangay": "Barangay 1",
            "farm_house_number": "13",
            "farm_street": "Farm Road",
            "farm_postal_code": "2900",
            "role": "Farmer",
            "documents": [
                "https://files.example/one.jpg",
                "https://files.example/two.jpg",
                "https://files.example/three.jpg",
                "https://files.example/four.jpg",
            ],
            "document_types": [
                "Utility Bills",
                "Valid_ID",
                "Owner_Address",
                "Farm_Ownership",
            ],
        }

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
        data["phonenumber"] = "09123456789"
        data["username"] = "test-farmer"
        data["postal_code"] = "1000"
        data["farm_postal_code"] = "1000"
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
        data["phonenumber"] = "09123456789"
        data["username"] = "test-farmer"
        data["postal_code"] = "1000"
        data["farm_postal_code"] = "1000"
        data["farm_size"] = "10"
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
        data["phonenumber"] = "09123456789"
        data["username"] = "test-farmer"
        data["postal_code"] = "1000"
        data["farm_postal_code"] = "1000"
        data["farm_size"] = "not-a-number"
        data["role"] = "Farmer"

        response = register_user(
            self.factory.post("/api/farmers/register/", data, format="json")
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, {"farm_size": ["Enter a valid number."]})

    def test_registration_rejects_invalid_phone_and_document_urls(self):
        data = self.valid_registration_data()
        data["phonenumber"] = "call me"
        serializer = FarmerRegistrationSerializer(data=data)

        self.assertFalse(serializer.is_valid())
        self.assertIn("phonenumber", serializer.errors)

        data = self.valid_registration_data()
        data["documents"][0] = "not-a-url"
        serializer = FarmerRegistrationSerializer(data=data)

        self.assertFalse(serializer.is_valid())
        self.assertIn("documents", serializer.errors)

    def test_registration_rejects_unsupported_document_type(self):
        data = self.valid_registration_data()
        data["document_types"][0] = "Other"
        serializer = FarmerRegistrationSerializer(data=data)

        self.assertFalse(serializer.is_valid())
        self.assertIn("document_types", serializer.errors)

    @patch("farmers.serializers.User.objects.filter")
    def test_dashboard_registration_requires_numeric_preferences_and_all_document_types(
        self, filter_users
    ):
        filter_users.return_value.exists.return_value = False
        data = self.valid_registration_data()
        data["language"] = "English"
        serializer = FarmerDashboardRegistrationSerializer(data=data)

        self.assertFalse(serializer.is_valid())
        self.assertIn("language", serializer.errors)

        data = self.valid_registration_data()
        data["document_types"] = ["Utility Bills", "", "Owner_Address", "Farm_Ownership"]
        serializer = FarmerDashboardRegistrationSerializer(data=data)

        self.assertFalse(serializer.is_valid())
        self.assertIn("document_types", serializer.errors)

    @patch("farmers.serializers.User.objects.filter")
    def test_farmer_dashboard_edit_does_not_require_a_new_password(
        self, filter_users
    ):
        filter_users.return_value.exclude.return_value.exists.return_value = False
        data = self.valid_registration_data()
        data.pop("password")
        serializer = FarmerDashboardUpdateSerializer(
            instance=User(user_id=12), data=data
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)


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


class FarmerCodeRequestAuditLogTests(SimpleTestCase):
    def setUp(self):
        self.staff = MagicMock()
        self.code_request = MagicMock()
        self.code_request.request_id = 7
        self.code_request.status = FarmerCodeRequest.Status.PENDING_REVIEW
        self.code_request.purpose = FarmerCodeRequest.Purpose.VERIFICATION
        self.code_request.review_reason = ""
        self.code_request.code_expires_at = None
        queryset = MagicMock()
        queryset.select_related.return_value.get.return_value = self.code_request
        patches = [
            patch.object(
                workflows.FarmerCodeRequest.objects,
                "select_for_update",
                return_value=queryset,
            ),
            patch.object(workflows.transaction, "atomic"),
            patch.object(workflows.FarmerAdminAuditEvent.objects, "create"),
            patch.object(workflows, "log_staff_audit_change"),
        ]
        self.audit = patches[3].start()
        for item in patches[:3]:
            item.start()
        for item in patches:
            self.addCleanup(item.stop)

    def _logged(self):
        self.assertEqual(self.audit.call_count, 1)
        return self.audit.call_args.kwargs

    def test_approve_is_written_to_the_audit_log(self):
        request = MagicMock()
        workflows.review_farmer_code_request(
            7, self.staff, "approve", request=request
        )

        logged = self._logged()
        self.assertEqual(logged["action_type"], "CODE_REQUEST_APPROVED")
        self.assertEqual(logged["target_table"], "FARMER_CODE_REQUESTS")
        self.assertEqual(logged["target_id"], 7)
        self.assertIs(logged["staff_user"], self.staff)
        self.assertIs(logged["request"], request)
        self.assertEqual(
            logged["old_values"]["status"], FarmerCodeRequest.Status.PENDING_REVIEW
        )

    def test_reject_logs_the_reason(self):
        workflows.review_farmer_code_request(
            7, self.staff, "reject", "Documents unclear"
        )

        logged = self._logged()
        self.assertEqual(logged["action_type"], "CODE_REQUEST_REJECTED")
        self.assertEqual(logged["new_values"]["reason"], "Documents unclear")

    def test_invalid_review_is_not_logged(self):
        with self.assertRaises(workflows.FarmerWorkflowValidationError):
            workflows.review_farmer_code_request(7, self.staff, "reject")

        self.audit.assert_not_called()

    def test_mailing_is_written_to_the_audit_log(self):
        self.code_request.status = FarmerCodeRequest.Status.CODE_ISSUED
        self.code_request.code_expires_at = workflows.timezone.now() + (
            workflows.timedelta(days=1)
        )

        workflows.mark_farmer_code_mailed(7, self.staff)

        self.assertEqual(self._logged()["action_type"], "CODE_MAILED")

    def test_expired_code_is_logged_as_expired(self):
        self.code_request.status = FarmerCodeRequest.Status.CODE_ISSUED
        self.code_request.code_expires_at = workflows.timezone.now() - (
            workflows.timedelta(days=1)
        )

        with self.assertRaises(workflows.FarmerWorkflowConflict):
            workflows.mark_farmer_code_mailed(7, self.staff)

        self.assertEqual(self._logged()["action_type"], "CODE_EXPIRED")

    @patch.object(workflows, "ensure_no_pending_document_requests")
    @patch.object(workflows, "resolve_enum_order_id", return_value=1)
    def test_issued_code_is_logged_without_the_code_itself(self, _role, _pending):
        self.code_request.status = FarmerCodeRequest.Status.APPROVED
        self.code_request.user.role = 1
        self.code_request.user.is_verified = 0

        _, code, _ = workflows.issue_farmer_code(7, self.staff)

        logged = self._logged()
        self.assertEqual(logged["action_type"], "CODE_ISSUED")
        self.assertNotIn(code, str(logged["old_values"]) + str(logged["new_values"]))
        self.assertNotIn(
            self.code_request.user.verification_code,
            str(logged["new_values"]),
        )


class FarmerDocumentRequestWorkflowTests(SimpleTestCase):
    def setUp(self):
        self.staff = MagicMock()
        patches = [
            patch.object(workflows.transaction, "atomic"),
            patch.object(workflows, "log_staff_audit_change"),
            patch.object(workflows, "_log_audit_change"),
            patch.object(
                workflows, "document_type_choices", return_value=[(1, "A"), (2, "B")]
            ),
        ]
        self.staff_audit = patches[1].start()
        self.farmer_audit = patches[2].start()
        patches[0].start()
        patches[3].start()
        for item in patches:
            self.addCleanup(item.stop)

    def test_message_is_required(self):
        with self.assertRaises(workflows.FarmerWorkflowValidationError):
            workflows.request_farmer_documents(1, self.staff, [1], "  ")

    def test_at_least_one_valid_document_type_is_required(self):
        for types in ([], [99], ["x"]):
            with self.assertRaises(workflows.FarmerWorkflowValidationError):
                workflows.request_farmer_documents(1, self.staff, types, "why")

    @patch.object(workflows, "resolve_enum_order_id", return_value=1)
    @patch.object(workflows, "pending_document_requests")
    @patch.object(workflows.FarmerDocumentRequest.objects, "create")
    @patch.object(workflows.User.objects, "select_for_update")
    def test_several_documents_are_requested_and_each_is_audited(
        self, select, create, pending, _role
    ):
        select.return_value.get.return_value = MagicMock(role=1)
        pending.return_value.values_list.return_value = []
        create.side_effect = lambda **kw: MagicMock(
            request_id=len(create.call_args_list),
            status="pending",
            doc_type=kw["doc_type"],
            message=kw["message"],
        )

        created = workflows.request_farmer_documents(
            1, self.staff, [1, 2, 2], "Need a clearer copy"
        )

        self.assertEqual(len(created), 2)
        self.assertEqual(self.staff_audit.call_count, 2)
        kwargs = self.staff_audit.call_args.kwargs
        self.assertEqual(kwargs["action_type"], "DOCUMENT_REQUESTED")
        self.assertEqual(kwargs["new_values"]["reason"], "Need a clearer copy")

    @patch.object(workflows, "resolve_enum_order_id", return_value=1)
    @patch.object(workflows, "pending_document_requests")
    @patch.object(workflows.User.objects, "select_for_update")
    def test_duplicate_pending_request_is_rejected(self, select, pending, _role):
        select.return_value.get.return_value = MagicMock(role=1)
        pending.return_value.values_list.return_value = [1]
        with self.assertRaises(workflows.FarmerWorkflowConflict):
            workflows.request_farmer_documents(1, self.staff, [1], "why")

    def test_revoke_requires_a_reason_and_logs_it(self):
        with self.assertRaises(workflows.FarmerWorkflowValidationError):
            workflows.revoke_farmer_document_request(1, self.staff, "")

        doc_request = MagicMock(
            status=workflows.FarmerDocumentRequest.Status.PENDING,
            request_id=3,
            doc_type=1,
            message="m",
        )
        queryset = MagicMock()
        queryset.select_related.return_value.get.return_value = doc_request
        with patch.object(
            workflows.FarmerDocumentRequest.objects,
            "select_for_update",
            return_value=queryset,
        ):
            workflows.revoke_farmer_document_request(3, self.staff, "Mistake")

        self.assertEqual(doc_request.status, "revoked")
        kwargs = self.staff_audit.call_args.kwargs
        self.assertEqual(kwargs["action_type"], "DOCUMENT_REQUEST_REVOKED")
        self.assertEqual(kwargs["new_values"]["reason"], "Mistake")

    def test_only_pending_requests_can_be_revoked(self):
        doc_request = MagicMock(status="submitted")
        queryset = MagicMock()
        queryset.select_related.return_value.get.return_value = doc_request
        with patch.object(
            workflows.FarmerDocumentRequest.objects,
            "select_for_update",
            return_value=queryset,
        ):
            with self.assertRaises(workflows.FarmerWorkflowConflict):
                workflows.revoke_farmer_document_request(3, self.staff, "x")

    @patch.object(workflows, "pending_document_requests")
    def test_pending_requests_block_verification(self, pending):
        pending.return_value.exists.return_value = True
        with self.assertRaises(workflows.FarmerWorkflowConflict):
            workflows.ensure_no_pending_document_requests(MagicMock())
        pending.return_value.exists.return_value = False
        workflows.ensure_no_pending_document_requests(MagicMock())

    @patch.object(workflows.ElectronicDocument.objects, "create")
    def test_farmer_submission_creates_document_and_logs(self, create_doc):
        doc_request = MagicMock(
            status=workflows.FarmerDocumentRequest.Status.PENDING,
            request_id=4,
            doc_type=2,
            message="m",
        )
        with patch.object(
            workflows.FarmerDocumentRequest.objects, "select_for_update"
        ) as select:
            select.return_value.get.return_value = doc_request
            workflows.submit_farmer_document(4, MagicMock(), "https://x.test/a.jpg")

        self.assertEqual(create_doc.call_args.kwargs["doc_type"], 2)
        self.assertEqual(doc_request.status, "submitted")
        self.assertEqual(
            self.farmer_audit.call_args.kwargs["action_type"], "DOCUMENT_SUBMITTED"
        )

    def test_submission_requires_a_http_url(self):
        with self.assertRaises(workflows.FarmerWorkflowValidationError):
            workflows.submit_farmer_document(4, MagicMock(), "file.jpg")


class AdminDocumentRequestApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.staff = MagicMock(is_authenticated=True)
        perm = patch("farmers.permissions.has_dashboard_permission", return_value=True)
        self.perm = perm.start()
        self.addCleanup(perm.stop)
        choices = patch.object(views, "document_type_choices", return_value=[(1, "A")])
        choices.start()
        self.addCleanup(choices.stop)

    def _call(self, view, method, path, data=None, **kwargs):
        request = getattr(self.factory, method)(path, data, format="json")
        force_authenticate(request, user=self.staff)
        return view(request, **kwargs)

    def _doc_request(self, **overrides):
        values = dict(
            request_id=7, doc_type=1, message="why", status="pending",
            requested_at=None, submitted_at=None, revoked_at=None, revoke_reason="",
        )
        values.update(overrides)
        return MagicMock(**values)

    def test_routes_resolve(self):
        self.assertEqual(
            resolve("/api/farmers/admin/farmers/3/document-requests/").url_name,
            "admin_farmer_document_requests",
        )
        self.assertEqual(
            resolve("/api/farmers/admin/document-requests/4/revoke/").url_name,
            "admin_revoke_document_request",
        )

    def test_staff_without_permission_is_denied(self):
        self.perm.return_value = False
        response = self._call(
            views.admin_farmer_document_requests, "post",
            "/x/", {"doc_types": [1], "message": "m"}, user_id=3,
        )
        self.assertEqual(response.status_code, 403)

    def test_list_and_create_check_different_permissions(self):
        with patch.object(views.FarmerDocumentRequest.objects, "filter") as flt:
            flt.return_value.order_by.return_value = []
            self._call(views.admin_farmer_document_requests, "get", "/x/", user_id=3)
        self.perm.assert_called_with(self.staff, "farmers.view_farmer_applications")
        with patch.object(views, "request_farmer_documents", return_value=[]):
            self._call(
                views.admin_farmer_document_requests, "post",
                "/x/", {"doc_types": [1], "message": "m"}, user_id=3,
            )
        self.perm.assert_called_with(self.staff, "farmers.request_farmer_documents")

    def test_list_returns_requests_and_selectable_types(self):
        with patch.object(views.FarmerDocumentRequest.objects, "filter") as flt:
            flt.return_value.order_by.return_value = [self._doc_request()]
            response = self._call(
                views.admin_farmer_document_requests, "get", "/x/", user_id=3
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"][0]["doc_type_label"], "A")
        self.assertEqual(
            response.data["document_types"], [{"doc_type": 1, "label": "A"}]
        )

    def test_create_returns_201_with_created_requests(self):
        with patch.object(
            views, "request_farmer_documents", return_value=[self._doc_request()]
        ) as create:
            response = self._call(
                views.admin_farmer_document_requests, "post",
                "/x/", {"doc_types": [1], "message": "m"}, user_id=3,
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["results"][0]["request_id"], 7)
        self.assertEqual(create.call_args.args[:4], (3, self.staff, [1], "m"))

    def test_create_requires_a_list_of_types(self):
        response = self._call(
            views.admin_farmer_document_requests, "post",
            "/x/", {"doc_types": 1, "message": "m"}, user_id=3,
        )
        self.assertEqual(response.status_code, 400)

    def test_create_maps_workflow_errors(self):
        cases = [
            (workflows.FarmerWorkflowValidationError("bad"), 400),
            (workflows.FarmerWorkflowConflict("dup"), 409),
            (User.DoesNotExist(), 404),
        ]
        for error, expected in cases:
            with patch.object(views, "request_farmer_documents", side_effect=error):
                response = self._call(
                    views.admin_farmer_document_requests, "post",
                    "/x/", {"doc_types": [1], "message": "m"}, user_id=3,
                )
            self.assertEqual(response.status_code, expected)

    def test_revoke_returns_revoked_request(self):
        revoked = self._doc_request(status="revoked", revoke_reason="oops")
        with patch.object(
            views, "revoke_farmer_document_request", return_value=revoked
        ) as revoke:
            response = self._call(
                views.admin_revoke_document_request, "post",
                "/x/", {"reason": "oops"}, request_id=7,
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "revoked")
        self.assertEqual(revoke.call_args.args[:3], (7, self.staff, "oops"))

    def test_revoke_maps_errors(self):
        cases = [
            (workflows.FarmerWorkflowValidationError("reason"), 400),
            (workflows.FarmerWorkflowConflict("not pending"), 409),
            (views.FarmerDocumentRequest.DoesNotExist(), 404),
        ]
        for error, expected in cases:
            with patch.object(
                views, "revoke_farmer_document_request", side_effect=error
            ):
                response = self._call(
                    views.admin_revoke_document_request, "post",
                    "/x/", {"reason": "r"}, request_id=7,
                )
            self.assertEqual(response.status_code, expected)


class FarmerDocumentTypeChoiceTests(SimpleTestCase):
    def test_only_farmer_types_are_offered_and_labels_are_readable(self):
        with patch.object(
            workflows, "enum_rows", return_value=[(1, "Utility Bills"), (2, "Valid_ID")]
        ) as rows:
            choices = workflows.document_type_choices()
        rows.assert_called_once_with("document_type", workflows.FARMER_DOCUMENT_TYPES)
        self.assertEqual(choices, [(1, "Utility Bills"), (2, "Valid ID")])

    def test_farmer_types_include_the_identity_documents(self):
        for name in ("Birth_Certificate", "National_Id", "Nbi_Clearance"):
            self.assertIn(name, workflows.FARMER_DOCUMENT_TYPES)