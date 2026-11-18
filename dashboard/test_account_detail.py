from datetime import date

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from businesses.models import BulkBuyer
from logistics.models import LogisticsCompany, Vehicle
from shared.models import (
    AccountCodeRequest,
    Address,
    AuditLog,
    EmailAddress,
    EnumeratedValue,
    PhoneNumber,
    User,
)


class AccountDetailIntegrationTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user(
            username="reviewer", password="unused", is_staff=True
        )
        self.client.force_login(self.staff)
        self.personal = Address.objects.create(
            street_address="Home Street",
            barangay="Home Barangay",
            municipality_city="Home City",
            province="Home Province",
            postal_code="1000",
        )
        self.account = User.objects.create(
            first_name="Applicant",
            last_name="Example",
            date_of_birth=date(1990, 4, 3),
            personal_address=self.personal,
        )
        PhoneNumber.objects.create(user=self.account, mobile_number="555123")
        EmailAddress.objects.create(
            user=self.account,
            email_address="deleted@example.org",
            deleted_at=timezone.now(),
        )
        EmailAddress.objects.create(
            user=self.account, email_address="buyer@example.org"
        )
        self.address = Address.objects.create(
            street_address="Business Street",
            municipality_city="Business City",
            province="Business Province",
            postal_code="2000",
        )

    def detail(self, kind, code_request):
        return self.client.get(
            reverse(
                "dashboard_account_code_request_detail", args=[kind, code_request.pk]
            )
        )

    def test_buyer_address_and_scoped_audit_without_secret_values(self):
        code_request = AccountCodeRequest.objects.create(
            user=self.account, kind="businesses"
        )
        BulkBuyer.objects.create(
            user=self.account,
            business_name="Deleted Buyer",
            date_time_deleted=timezone.now(),
        )
        BulkBuyer.objects.create(
            user=self.account,
            business_name="Fresh Buyer",
            address=self.address,
            registration_number="REG42",
        )
        AuditLog.objects.create(
            target_table="ACCOUNT_CODE_REQUESTS",
            target_id=code_request.pk,
            staff_user=self.staff,
            action_type="CODE_ISSUED",
            old_values='{"code": "old-secret"}',
            new_values='{"code": "new-secret"}',
            created_at=timezone.now(),
        )
        AuditLog.objects.create(
            target_table="ACCOUNT_CODE_REQUESTS",
            target_id=code_request.pk + 100,
            staff_user=self.staff,
            action_type="CODE_MAILED",
            created_at=timezone.now(),
        )
        AuditLog.objects.create(
            target_table="OTHER",
            target_id=code_request.pk,
            staff_user=self.staff,
            action_type="CODE_REQUEST_REJECTED",
            created_at=timezone.now(),
        )
        response = self.detail("businesses", code_request)
        for value in (
            "1990-04-03",
            "Home Street",
            "Home City",
            "Fresh Buyer",
            "Business Street",
            "Business City",
            "REG42",
            "555123",
            "buyer@example.org",
            "Code issued",
            "reviewer",
        ):
            self.assertContains(response, value)
        for value in (
            "Deleted Buyer",
            "deleted@example.org",
            "old-secret",
            "new-secret",
            "Mailing recorded",
            "Request rejected",
        ):
            self.assertNotContains(response, value)

    def test_missing_buyer_and_deleted_applicant_are_identified(self):
        code_request = AccountCodeRequest.objects.create(
            user=self.account, kind="businesses"
        )
        self.account.deleted_at = timezone.now()
        self.account.save(update_fields=["deleted_at"])
        response = self.detail("businesses", code_request)
        self.assertContains(response, "No active buyer business record available.")
        self.assertContains(response, "<td>Deleted</td>", html=True)
        self.assertNotContains(response, "Verify account</button>")

    def test_company_contact_initial_active_vehicle_and_missing_relations(self):
        code_request = AccountCodeRequest.objects.create(
            user=self.account, kind="logistics"
        )
        company = LogisticsCompany.objects.create(
            user=self.account,
            business_name="Cargo Company",
            address=self.address,
            contact_phone="555999",
            contact_email="cargo@example.org",
        )
        Vehicle.objects.create(
            user=self.account,
            logistics_business=company,
            truck_model="Deleted Truck",
            deleted_at=timezone.now(),
        )
        Vehicle.objects.create(
            user=self.account,
            logistics_business=company,
            truck_model="First Truck",
            plate_number="PLATE1",
            max_weight_capacity_kg=10,
            max_volume_capacity_m3=2,
            is_refrigerated=1,
        )
        Vehicle.objects.create(
            user=self.account, logistics_business=company, truck_model="Later Truck"
        )
        response = self.detail("logistics", code_request)
        for value in (
            "Cargo Company",
            "Business Street",
            "555999",
            "cargo@example.org",
            "First Truck",
            "PLATE1",
            "10.00",
        ):
            self.assertContains(response, value)
        self.assertNotContains(response, "Deleted Truck")
        self.assertNotContains(response, "Later Truck")

        company.date_time_deleted = timezone.now()
        company.save(update_fields=["date_time_deleted"])
        self.account.personal_address = None
        self.account.save(update_fields=["personal_address"])
        response = self.detail("logistics", code_request)
        self.assertContains(response, "No active logistics company record available.")
        self.assertContains(response, "No active vehicle record available.")
        self.assertContains(response, "Not available")
        self.assertNotContains(response, "Cargo Company")
        self.assertNotContains(response, "First Truck")

    def test_manual_verification_persists_and_is_audited(self):
        role, _ = EnumeratedValue.objects.get_or_create(
            type="role", value="Bulk_Buyer", defaults={"ordering": 1}
        )
        self.account.role = role.ordering
        self.account.is_verified = 0
        self.account.verification_code = "old-secret"
        self.account.save(update_fields=["role", "is_verified", "verification_code"])
        code_request = AccountCodeRequest.objects.create(
            user=self.account, kind="businesses"
        )
        url = reverse(
            "dashboard_account_code_request_detail",
            args=["businesses", code_request.pk],
        )
        response = self.client.post(url, {"reason": "Identity checked"})
        self.assertRedirects(response, url)
        self.account.refresh_from_db()
        code_request.refresh_from_db()
        self.assertEqual(self.account.is_verified, 1)
        self.assertIsNone(self.account.verification_code)
        self.assertEqual(code_request.status, AccountCodeRequest.Status.COMPLETED)
        self.assertContains(self.client.get(url), "Account manually verified")

    def test_manual_verification_requires_csrf(self):
        code_request = AccountCodeRequest.objects.create(
            user=self.account, kind="businesses"
        )
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.staff)
        url = reverse(
            "dashboard_account_code_request_detail",
            args=["businesses", code_request.pk],
        )
        response = client.post(url, {"reason": "Identity checked"})
        self.assertEqual(response.status_code, 403)
        code_request.refresh_from_db()
        self.assertEqual(code_request.status, AccountCodeRequest.Status.PENDING_REVIEW)
