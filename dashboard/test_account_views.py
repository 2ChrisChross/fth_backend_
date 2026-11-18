from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.test import Client, RequestFactory, SimpleTestCase
from django.urls import reverse

from .account_views import (
    AccountWorkflowConflict,
    AccountWorkflowValidationError,
    account_code_request_detail,
    account_code_requests,
)


class AccountCodeDashboardTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.nav = patch(
            "dashboard.account_views.dashboard_navigation", return_value=[]
        )
        self.nav.start()
        self.addCleanup(self.nav.stop)
        ready = patch("dashboard.account_views._table_ready", return_value=True)
        ready.start()
        self.addCleanup(ready.stop)

    def request(self, method="get", data=None, permissions=None):
        path = reverse("dashboard_account_code_requests", args=["businesses"])
        request = getattr(self.factory, method)(path, data or {})
        groups = MagicMock()
        groups.exists.return_value = True
        request.user = SimpleNamespace(
            is_authenticated=True,
            is_active=True,
            is_staff=True,
            is_superuser=False,
            groups=groups,
            has_perm=lambda permission: permission in (permissions or set()),
        )
        request.session = {}
        request._messages = FallbackStorage(request)
        return request

    @patch("dashboard.account_views.AccountCodeRequest.objects")
    def test_queue_scopes_kind_filters_and_paginates(self, objects):
        phones = MagicMock()
        phones.all.return_value = [SimpleNamespace(mobile_number="123")]
        account = SimpleNamespace(
            first_name="Test", last_name="Buyer", phone_numbers=phones
        )
        item = SimpleNamespace(
            request_id=5,
            user=account,
            status="pending_review",
            get_status_display=lambda: "Pending",
        )
        selected = objects.filter.return_value.select_related.return_value
        prefetched = selected.prefetch_related
        queryset = prefetched.return_value.order_by.return_value
        queryset.filter.return_value = [item] * 51
        request = self.request(
            data={"status": "pending_review", "page": "1"},
            permissions={
                "farmers.view_farmer_code_requests",
                "farmers.review_farmer_code_requests",
                "farmers.view_farmer_applications",
            },
        )
        response = account_code_requests(request, "businesses")
        objects.filter.assert_called_once_with(kind="businesses")
        queryset.filter.assert_called_once_with(status="pending_review")
        self.assertContains(response, "Account verification")
        self.assertContains(response, "123")
        self.assertContains(response, "page=2")
        self.assertContains(response, "/dashboard/account-code-requests/businesses/5/")

    @patch("dashboard.account_views.get_object_or_404")
    @patch("dashboard.account_views.review_account_code_request")
    def test_review_and_permission_enforcement(self, review, get_object):
        get_object.return_value = SimpleNamespace(request_id=7)
        review.return_value = SimpleNamespace(status="rejected")
        perms = {
            "farmers.view_farmer_code_requests",
            "farmers.review_farmer_code_requests",
        }
        request = self.request(
            "post",
            {"request_id": "7", "action": "reject", "reason": " missing "},
            perms,
        )
        response = account_code_requests(request, "logistics")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            get_object.call_args.kwargs, {"request_id": 7, "kind": "logistics"}
        )
        review.assert_called_once_with(
            7, request.user, "reject", "missing", request=request
        )
        clerk = self.request(
            "post",
            {"request_id": "7", "action": "approve"},
            {
                "farmers.view_farmer_code_requests",
                "farmers.issue_farmer_codes",
            },
        )
        with self.assertRaises(PermissionDenied):
            account_code_requests(clerk, "businesses")

    @patch("dashboard.account_views.get_object_or_404")
    @patch("dashboard.account_views.review_account_code_request")
    def test_workflow_errors_are_shown_without_issuing_code(self, review, get_object):
        get_object.return_value = SimpleNamespace(request_id=7)
        perms = {
            "farmers.view_farmer_code_requests",
            "farmers.review_farmer_code_requests",
        }
        for error in (
            AccountWorkflowValidationError("Reason required"),
            AccountWorkflowConflict("Already reviewed"),
        ):
            with self.subTest(error=error):
                review.side_effect = error
                request = self.request(
                    "post", {"request_id": "7", "action": "reject"}, perms
                )
                response = account_code_requests(request, "businesses")
                self.assertEqual(response.status_code, 302)
                self.assertIn(str(error), [str(item) for item in request._messages])
                self.assertNotIn("issued_account_code", request.session)

    @patch("dashboard.account_views.get_object_or_404")
    @patch("dashboard.account_views.issue_account_code")
    @patch("dashboard.account_views.AccountCodeRequest.objects")
    def test_issued_code_is_shown_once_only_to_issuer(self, objects, issue, get_object):
        get_object.return_value = SimpleNamespace(request_id=7)
        issue.return_value = (
            SimpleNamespace(request_id=7),
            "SECRET123",
            datetime(2030, 1, 1, tzinfo=timezone.utc),
        )
        perms = {"farmers.view_farmer_code_requests", "farmers.issue_farmer_codes"}
        request = self.request("post", {"request_id": "7", "action": "issue"}, perms)
        account_code_requests(request, "businesses")
        issue.assert_called_once_with(7, request.user, request=request)
        selected = objects.filter.return_value.select_related.return_value
        prefetched = selected.prefetch_related
        ordered = prefetched.return_value.order_by
        ordered.return_value = []
        request.method = "GET"
        self.assertContains(account_code_requests(request, "businesses"), "SECRET123")
        self.assertNotContains(
            account_code_requests(request, "businesses"), "SECRET123"
        )
        self.assertNotIn("issued_account_code", request.session)

    @patch("dashboard.account_views.AccountCodeRequest.objects")
    def test_code_not_disclosed_if_issue_permission_was_removed(self, objects):
        selected = objects.filter.return_value.select_related.return_value
        selected.prefetch_related.return_value.order_by.return_value = []
        request = self.request(permissions={"farmers.view_farmer_code_requests"})
        request.session["issued_account_code"] = {
            "kind": "businesses",
            "code": "SECRET123",
        }
        response = account_code_requests(request, "businesses")
        self.assertNotContains(response, "SECRET123")
        self.assertNotIn("issued_account_code", request.session)

    @patch("dashboard.account_views.AccountCodeRequest.objects")
    def test_invalid_status_does_not_query_requests(self, objects):
        request = self.request(
            data={"status": "invalid"},
            permissions={"farmers.view_farmer_code_requests"},
        )
        response = account_code_requests(request, "logistics")
        self.assertContains(response, "Select a valid status filter.")
        objects.filter.assert_not_called()

    @patch("dashboard.account_views.get_object_or_404")
    @patch("dashboard.account_views.mark_account_code_mailed")
    def test_mark_mailed_uses_issue_permission(self, mailed, get_object):
        get_object.return_value = SimpleNamespace(request_id=9)
        request = self.request(
            "post",
            {"request_id": "9", "action": "mark_mailed"},
            {
                "farmers.view_farmer_code_requests",
                "farmers.issue_farmer_codes",
            },
        )
        account_code_requests(request, "logistics")
        mailed.assert_called_once_with(9, request.user, request=request)

    @patch("dashboard.account_views.AuditLog.objects")
    @patch("dashboard.account_views.BulkBuyer.objects")
    @patch("dashboard.account_views.EmailAddress.objects")
    @patch("dashboard.account_views.get_object_or_404")
    def test_detail_requires_reviewer_and_application_access(
        self, get_object, emails, buyers, audit
    ):
        buyer_ordered = buyers.filter.return_value.select_related.return_value.order_by
        buyer_ordered.return_value.first.return_value = None
        emails.filter.return_value.order_by.return_value.first.return_value = None
        audit.filter.return_value.order_by.return_value.values.return_value = []
        docs = MagicMock()
        docs.filter.return_value = [
            SimpleNamespace(
                doc_title="License", file_url="https://example.org/license"
            ),
            SimpleNamespace(doc_title="Unsafe", file_url="javascript:alert(1)"),
            SimpleNamespace(doc_title="Relative", file_url="/private/document"),
        ]
        phone = MagicMock()
        phone.order_by.return_value.first.return_value = SimpleNamespace(
            mobile_number="123"
        )
        user = SimpleNamespace(
            first_name="A",
            middle_name="",
            last_name="B",
            username="buyer",
            is_verified=0,
            phone_numbers=phone,
            electronic_documents=docs,
        )
        get_object.return_value = SimpleNamespace(
            request_id=3,
            user=user,
            review_reason="",
            get_status_display=lambda: "Pending",
        )
        perms = {
            "farmers.view_farmer_code_requests",
            "farmers.review_farmer_code_requests",
            "farmers.view_farmer_applications",
        }
        response = account_code_request_detail(
            self.request(permissions=perms), "businesses", 3
        )
        self.assertContains(response, "https://example.org/license")
        self.assertNotContains(response, "javascript:alert(1)")
        self.assertContains(response, "Unsafe (no safe file link)")
        self.assertContains(response, "Relative (no safe file link)")
        docs.filter.assert_called_once_with(date_time_deleted__isnull=True)
        for missing in (
            "farmers.review_farmer_code_requests",
            "farmers.view_farmer_applications",
        ):
            with self.subTest(missing=missing), self.assertRaises(PermissionDenied):
                account_code_request_detail(
                    self.request(permissions=perms - {missing}), "businesses", 3
                )

    @patch("dashboard.account_views.get_object_or_404")
    @patch("dashboard.account_views.manually_verify_account")
    def test_manual_verify_requires_permission_and_reason(self, verify, get_object):
        get_object.return_value = SimpleNamespace(user=SimpleNamespace())
        perms = {
            "farmers.view_farmer_code_requests",
            "farmers.review_farmer_code_requests",
            "farmers.view_farmer_applications",
        }
        data = {"action": "manual_verify", "reason": "proof checked"}
        with self.assertRaises(PermissionDenied):
            account_code_request_detail(
                self.request("post", data, perms), "businesses", 3
            )
        perms.add("farmers.manually_verify_farmer")
        request = self.request(
            "post", {"action": "manual_verify", "reason": " "}, perms
        )
        response = account_code_request_detail(request, "businesses", 3)
        self.assertEqual(response.status_code, 302)
        self.assertIn(
            "A reason is required.", [str(item) for item in request._messages]
        )
        verify.assert_not_called()
        request = self.request("post", data, perms)
        response = account_code_request_detail(request, "businesses", 3)
        self.assertEqual(response.status_code, 302)
        verify.assert_called_once_with(
            3, request.user, "proof checked", request=request
        )
        self.assertIn(
            "Account manually verified.", [str(item) for item in request._messages]
        )

    @patch("dashboard.account_views.get_object_or_404")
    @patch("dashboard.account_views.manually_verify_account")
    def test_manual_verify_surfaces_workflow_errors(self, verify, get_object):
        get_object.return_value = SimpleNamespace(user=SimpleNamespace())
        perms = {
            "farmers.view_farmer_code_requests",
            "farmers.review_farmer_code_requests",
            "farmers.view_farmer_applications",
            "farmers.manually_verify_farmer",
        }
        for error in (
            AccountWorkflowValidationError("Invalid reason"),
            AccountWorkflowConflict("Already verified"),
        ):
            with self.subTest(error=error):
                verify.side_effect = error
                request = self.request(
                    "post", {"action": "manual_verify", "reason": "checked"}, perms
                )
                response = account_code_request_detail(request, "logistics", 3)
                self.assertEqual(response.status_code, 302)
                self.assertIn(str(error), [str(item) for item in request._messages])

    def test_bad_kind_and_csrf(self):
        perms = {"farmers.view_farmer_code_requests"}
        with self.assertRaises(Http404):
            account_code_requests(self.request(permissions=perms), "farmers")
        response = Client(enforce_csrf_checks=True).post(
            reverse("dashboard_account_code_requests", args=["businesses"]),
            {"request_id": "1", "action": "approve"},
        )
        self.assertEqual(response.status_code, 403)
