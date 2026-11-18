from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from django.urls import reverse

from farmers.models import FarmerCodeRequest
from shared.models import AccountCodeRequest, User


class CombinedVerificationQueueTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user(
            username="queue_staff", password="unused", is_staff=True
        )
        self.client.force_login(self.staff)
        farmer = User.objects.create(first_name="Farmer", last_name="Applicant")
        buyer = User.objects.create(first_name="Buyer", last_name="Applicant")
        logistics = User.objects.create(first_name="Logistics", last_name="Applicant")
        self.farmer = FarmerCodeRequest.objects.create(
            user=farmer, purpose=FarmerCodeRequest.Purpose.RECOVERY
        )
        self.buyer = AccountCodeRequest.objects.create(user=buyer, kind="businesses")
        self.logistics = AccountCodeRequest.objects.create(
            user=logistics, kind="logistics"
        )
        self.url = reverse("dashboard_verification_requests")

    def test_all_types_filters_status_and_farmer_scope(self):
        response = self.client.get(self.url)
        self.assertContains(
            response,
            '<noscript><button type="submit">Apply filters</button></noscript>',
        )
        self.assertContains(response, 'title="Accounts with pending reviews">3</span>')
        for value in (
            "Farmer Applicant",
            "Buyer Applicant",
            "Logistics Applicant",
            "Account recovery",
        ):
            self.assertContains(response, value)
        for kind, expected, excluded in (
            ("farmers", "Farmer Applicant", ("Buyer Applicant", "Logistics Applicant")),
            (
                "businesses",
                "Buyer Applicant",
                ("Farmer Applicant", "Logistics Applicant"),
            ),
            (
                "logistics",
                "Logistics Applicant",
                ("Farmer Applicant", "Buyer Applicant"),
            ),
        ):
            with self.subTest(kind=kind):
                response = self.client.get(self.url, {"type": kind})
                self.assertContains(response, expected)
                for value in excluded:
                    self.assertNotContains(response, value)
        self.buyer.status = AccountCodeRequest.Status.APPROVED
        self.buyer.save(update_fields=["status"])
        response = self.client.get(self.url, {"status": "approved"})
        self.assertContains(response, "Buyer Applicant")
        self.assertNotContains(response, "Farmer Applicant")
        self.assertNotContains(response, "Logistics Applicant")
        response = self.client.get(self.url, {"farmer_id": self.farmer.user_id})
        self.assertContains(response, "Farmer Applicant")
        self.assertNotContains(response, "Buyer Applicant")
        self.assertContains(
            response, f'name="farmer_id" value="{self.farmer.user_id}"'
        )
        response = self.client.get(
            self.url,
            {"type": "businesses", "farmer_id": self.farmer.user_id},
        )
        self.assertContains(response, "Buyer Applicant")
        self.assertNotContains(response, "Farmer Applicant")
        self.assertNotContains(response, 'name="farmer_id"')

    def test_actions_return_to_filter_and_target_correct_request_type(self):
        query = "?queue=unified&type=all&status=all&page=1"
        response = self.client.post(
            reverse("dashboard_code_requests") + query,
            {"request_id": self.farmer.pk, "action": "approve"},
        )
        self.assertRedirects(
            response,
            self.url + "?type=all&status=all&page=1",
            fetch_redirect_response=False,
        )
        self.farmer.refresh_from_db()
        self.buyer.refresh_from_db()
        self.assertEqual(self.farmer.status, FarmerCodeRequest.Status.APPROVED)
        self.assertEqual(self.buyer.status, AccountCodeRequest.Status.PENDING_REVIEW)
        response = self.client.post(
            reverse("dashboard_account_code_requests", args=["businesses"]) + query,
            {"request_id": self.buyer.pk, "action": "reject", "reason": "Missing ID"},
        )
        self.assertRedirects(
            response,
            self.url + "?type=all&status=all&page=1",
            fetch_redirect_response=False,
        )
        self.buyer.refresh_from_db()
        self.assertEqual(self.buyer.status, AccountCodeRequest.Status.REJECTED)

    def test_issued_codes_are_shown_once_on_combined_page(self):
        session = self.client.session
        session["issued_farmer_code"] = {
            "request_id": self.farmer.pk,
            "code": "FARMCODE",
        }
        session["issued_account_code"] = {
            "request_id": self.buyer.pk,
            "code": "BUYERCODE",
            "kind": "businesses",
        }
        session.save()
        response = self.client.get(self.url, {"type": "logistics"})
        self.assertContains(response, "FARMCODE")
        self.assertContains(response, "BUYERCODE")
        response = self.client.get(self.url)
        self.assertNotContains(response, "FARMCODE")
        self.assertNotContains(response, "BUYERCODE")

    def test_invalid_filters_are_reported(self):
        self.assertEqual(
            self.client.get(self.url, {"type": "unknown"}).status_code, 400
        )
        self.assertEqual(
            self.client.get(self.url, {"status": "unknown"}).status_code, 400
        )

    def test_code_is_not_shown_without_issue_permission(self):
        group = Group.objects.create(name="queue_viewer")
        group.permissions.add(
            Permission.objects.get(codename="view_farmer_code_requests")
        )
        self.staff.groups.add(group)
        session = self.client.session
        session["issued_farmer_code"] = {"request_id": self.farmer.pk, "code": "SECRET"}
        session.save()
        self.assertNotContains(self.client.get(self.url), "SECRET")
        self.assertNotIn("issued_farmer_code", self.client.session)

    def test_pagination_covers_all_types_without_id_collisions(self):
        FarmerCodeRequest.objects.bulk_create(
            [
                FarmerCodeRequest(
                    user=self.farmer.user,
                    purpose=FarmerCodeRequest.Purpose.VERIFICATION,
                )
                for _ in range(50)
            ]
        )
        first = self.client.get(self.url)
        second = self.client.get(self.url, {"page": 2})
        first_items = first.context["code_requests"]
        second_items = second.context["code_requests"]
        self.assertEqual(len(first_items), 50)
        self.assertEqual(len(second_items), 3)
        keys = {(item.queue_kind, item.pk) for item in [*first_items, *second_items]}
        self.assertEqual(len(keys), 53)
        self.assertIn(("businesses", self.buyer.pk), keys)
        self.assertIn(("logistics", self.logistics.pk), keys)
