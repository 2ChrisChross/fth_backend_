import os
from decimal import Decimal
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from businesses.models import BulkBuyer
from farmers.models import Crop, CropCalendar, Farm, MarketplaceListing
from logistics.models import LogisticsCompany, Vehicle
from shared.code_workflows import (
    AccountWorkflowConflict,
    AccountWorkflowValidationError,
    issue_account_code,
    manually_verify_account,
    mark_account_code_mailed,
    review_account_code_request,
)
from shared.models import AccountCodeRequest, Address, AuditLog, PhoneNumber, User
from shared.registration import resolve_enum_order_id

RUN_DATABASE_TESTS = os.environ.get("FTH_DATABASE_TESTS") == "1"


@skipUnless(RUN_DATABASE_TESTS, "Requires a preinitialized PostgreSQL test database")
class BuyerLogisticsWorkflowTests(TestCase):
    databases = {"default"} if RUN_DATABASE_TESTS else set()

    @classmethod
    def setUpTestData(cls):
        cls.password = "TestPassword!482"
        buyer_role = resolve_enum_order_id("role", "Bulk_Buyer")
        logistics_role = resolve_enum_order_id("role", "Logistics_Manager")
        cls.buyer = User.objects.create(
            username="workflow_buyer",
            password_hash=make_password(cls.password),
            role=buyer_role,
            is_verified=1,
        )
        cls.manager = User.objects.create(
            username="workflow_manager",
            password_hash=make_password(cls.password),
            role=logistics_role,
            is_verified=1,
        )
        cls.other = User.objects.create(
            username="workflow_other",
            password_hash=make_password(cls.password),
            role=logistics_role,
            is_verified=1,
        )
        pickup = Address.objects.create(street_address="Pickup")
        destination = Address.objects.create(street_address="Destination")
        BulkBuyer.objects.create(
            user=cls.buyer, address=destination, business_name="Buyer"
        )
        cls.company = LogisticsCompany.objects.create(
            user=cls.manager,
            business_name="Carrier",
            contact_phone="123",
            contact_email="carrier@example.com",
        )
        LogisticsCompany.objects.create(
            user=cls.other,
            business_name="Other",
            contact_phone="456",
            contact_email="other@example.com",
        )
        farm = Farm.objects.create(user=cls.buyer, address=pickup)
        cls.crop = Crop.objects.create(farm=farm, available_stock_kg=Decimal("100"))
        calendar = CropCalendar.objects.create(crop=cls.crop, pickup_address=pickup)
        cls.listing = MarketplaceListing.objects.create(
            crop=cls.crop,
            calendar=calendar,
            listing_title="Mango",
            listing_price_per_kg=Decimal("4.25"),
            is_active=1,
        )
        cls.vehicle = Vehicle.objects.create(
            user=cls.manager,
            logistics_business=cls.company,
            plate_number="ABC",
            max_weight_capacity_kg=Decimal("30"),
            max_volume_capacity_m3=Decimal("10"),
            body_type=1,
        )

    def login(self, role, username):
        client = APIClient()
        response = client.post(
            f"/api/{role}/login/",
            {"username": username, "password": self.password},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        tokens = response.data
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        return client, tokens

    def review_and_mail(self, client, staff, username, phone, kind):
        user = User.objects.get(username=username)
        code_request = AccountCodeRequest.objects.get(user=user, kind=kind)
        self.assertIsNone(user.verification_code)
        with self.assertRaises(AccountWorkflowConflict):
            issue_account_code(code_request.pk, staff)
        with self.assertRaises(AccountWorkflowValidationError):
            review_account_code_request(code_request.pk, staff, "reject", " ")
        queue_url = f"/dashboard/account-code-requests/{kind}/"
        response = client.post(
            queue_url, {"request_id": code_request.pk, "action": "approve"}
        )
        self.assertEqual(response.status_code, 302)
        code_request.refresh_from_db()
        self.assertEqual(code_request.status, AccountCodeRequest.Status.APPROVED)
        response = client.post(
            queue_url, {"request_id": code_request.pk, "action": "issue"}
        )
        self.assertEqual(response.status_code, 302)
        code = client.session["issued_account_code"]["code"]
        self.assertContains(client.get(queue_url), code)
        self.assertNotContains(client.get(queue_url), code)
        user.refresh_from_db()
        self.assertNotEqual(user.verification_code, code)
        before_mailing = client.post(
            f"/api/{kind}/verify-code/",
            {"phone_number": phone, "verification_code": code},
            format="json",
        )
        self.assertFalse(before_mailing.data["valid"])
        response = client.post(
            queue_url, {"request_id": code_request.pk, "action": "mark_mailed"}
        )
        self.assertEqual(response.status_code, 302)
        code_request.refresh_from_db()
        self.assertEqual(code_request.status, AccountCodeRequest.Status.MAILED)
        return code_request, code

    def test_orders_reserve_and_restore_stock_and_isolate_roles(self):
        buyer, _ = self.login("businesses", "workflow_buyer")
        self.assertEqual(buyer.get("/api/logistics/vehicles/").status_code, 401)
        response = buyer.post(
            "/api/businesses/orders/",
            {"listing_id": self.listing.pk, "quantity_kg": "101"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        response = buyer.post(
            "/api/businesses/orders/",
            {"listing_id": self.listing.pk, "quantity_kg": "5"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Decimal(response.data["total_payment"]), Decimal("21.25"))
        self.crop.refresh_from_db()
        self.assertEqual(self.crop.available_stock_kg, Decimal("95"))
        url = f"/api/businesses/orders/{response.data['order_id']}/cancel/"
        self.assertEqual(buyer.post(url, {}, format="json").status_code, 200)
        self.assertEqual(buyer.post(url, {}, format="json").status_code, 409)
        self.crop.refresh_from_db()
        self.assertEqual(self.crop.available_stock_kg, Decimal("100"))

    def test_assigned_delivery_requires_company_and_sequential_transitions(self):
        buyer, _ = self.login("businesses", "workflow_buyer")
        manager, _ = self.login("logistics", "workflow_manager")
        other, _ = self.login("logistics", "workflow_other")
        response = buyer.post(
            "/api/businesses/orders/",
            {
                "listing_id": self.listing.pk,
                "quantity_kg": "10",
                "delivery_company_id": self.company.pk,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        order_id = response.data["order_id"]
        self.assertEqual(other.get("/api/logistics/deliveries/").data, [])
        self.assertEqual(
            manager.get("/api/logistics/deliveries/").data[0]["destination_address"][
                "street_address"
            ],
            "Destination",
        )
        payload = {"vehicle_id": self.vehicle.pk, "order_ids": [order_id]}
        self.assertEqual(
            other.post("/api/logistics/trips/", payload, format="json").status_code, 404
        )
        response = manager.post("/api/logistics/trips/", payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        trip_url = f"/api/logistics/trips/{response.data['trip_id']}/"
        vehicle_url = f"/api/logistics/vehicles/{self.vehicle.pk}/"
        self.assertEqual(
            manager.patch(
                vehicle_url, {"plate_number": "NEW"}, format="json"
            ).status_code,
            409,
        )
        self.assertEqual(
            buyer.post(f"/api/businesses/orders/{order_id}/cancel/").status_code, 409
        )
        self.assertEqual(
            manager.patch(trip_url, {"trip_status": 3}, format="json").status_code, 409
        )
        self.assertEqual(
            manager.patch(trip_url, {"trip_status": 2}, format="json").status_code, 200
        )
        self.assertEqual(
            manager.patch(trip_url, {"trip_status": 3}, format="json").status_code, 200
        )
        self.assertEqual(
            buyer.get("/api/businesses/orders/").data[0]["reservation_status"],
            "delivered",
        )

    def test_refresh_rotation_and_logout_revoke_tokens(self):
        buyer, tokens = self.login("businesses", "workflow_buyer")
        refresh_url = "/api/businesses/token/refresh/"
        rotated = buyer.post(refresh_url, {"refresh": tokens["refresh"]}, format="json")
        self.assertEqual(rotated.status_code, 200, rotated.data)
        self.assertEqual(
            buyer.post(
                refresh_url, {"refresh": tokens["refresh"]}, format="json"
            ).status_code,
            401,
        )
        self.assertEqual(
            buyer.post(
                "/api/businesses/logout/",
                {"refresh": rotated.data["refresh"]},
                format="json",
            ).status_code,
            204,
        )
        self.assertEqual(
            buyer.post(
                refresh_url, {"refresh": rotated.data["refresh"]}, format="json"
            ).status_code,
            401,
        )

    def test_password_change_invalidates_access_and_refresh(self):
        buyer, tokens = self.login("businesses", "workflow_buyer")
        response = buyer.patch(
            "/api/businesses/me/", {"new_password": "NewSecret!8394"}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(buyer.get("/api/businesses/me/").status_code, 401)
        self.assertEqual(
            buyer.post(
                "/api/businesses/token/refresh/",
                {"refresh": tokens["refresh"]},
                format="json",
            ).status_code,
            401,
        )

    def test_trip_rejects_over_capacity_and_duplicate_orders(self):
        buyer, _ = self.login("businesses", "workflow_buyer")
        manager, _ = self.login("logistics", "workflow_manager")
        order = buyer.post(
            "/api/businesses/orders/",
            {
                "listing_id": self.listing.pk,
                "quantity_kg": "31",
                "delivery_company_id": self.company.pk,
            },
            format="json",
        )
        self.assertEqual(order.status_code, 201, order.data)
        order_id = order.data["order_id"]
        response = manager.post(
            "/api/logistics/trips/",
            {"vehicle_id": self.vehicle.pk, "order_ids": [order_id]},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        response = manager.post(
            "/api/logistics/trips/",
            {"vehicle_id": self.vehicle.pk, "order_ids": [order_id, order_id]},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIsNone(buyer.get("/api/businesses/orders/").data[0]["trip_id"])

    def test_vehicle_management_is_restricted_to_the_owning_company(self):
        manager, _ = self.login("logistics", "workflow_manager")
        other, _ = self.login("logistics", "workflow_other")
        response = manager.post(
            "/api/logistics/vehicles/",
            {
                "truck_model": "Lorry",
                "plate_number": "NEW-123",
                "max_weight_capacity_kg": "50",
                "max_volume_capacity_m3": "10",
                "body_type": 1,
                "is_refrigerated": 0,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        url = f"/api/logistics/vehicles/{response.data['vehicle_id']}/"
        self.assertEqual(
            other.patch(url, {"plate_number": "STOLEN"}, format="json").status_code, 404
        )
        self.assertEqual(
            manager.patch(
                url, {"max_weight_capacity_kg": "-1"}, format="json"
            ).status_code,
            400,
        )
        self.assertEqual(
            manager.patch(url, {"plate_number": "UPDATED"}, format="json").status_code,
            200,
        )
        self.assertEqual(manager.delete(url).status_code, 204)
        self.assertEqual(manager.delete(url).status_code, 404)

    @override_settings(DEBUG=True, ENABLE_LOCAL_SIMULATOR=True)
    def test_local_simulator_registers_and_verifies_through_existing_api(self):
        staff = get_user_model().objects.create_superuser(
            username="simulator_staff", password="LocalStaff!482"
        )
        client = APIClient()
        client.force_login(staff)
        address = {
            "street_address": "Test Street",
            "barangay": "Barangay I",
            "municipality_city": "Baler",
            "province": "Aurora",
            "postal_code": "3200",
            "country": "Philippines",
            "gps_coordinates": "15.75999, 121.56087",
        }
        documents = [
            {"type": kind, "url": "https://example.com/document.jpg"}
            for kind in (
                "birth_certificate",
                "business_utility_bill",
                "business_permit",
                "national_id",
            )
        ]
        payload = {
            "username": "simulator_buyer",
            "password": "SampleBuyer!482",
            "first_name": "Test",
            "last_name": "Buyer",
            "date_of_birth": "2000-01-01",
            "phone_number": "5550123",
            "business_name": "Test Business",
            "role": "Bulk_Buyer",
            "personal_address": address,
            "business_address": address,
            "documents": documents,
        }
        response = client.post(
            "/dashboard/local-test/businesses/register/", payload, format="json"
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(
            User.objects.get(username=payload["username"]).personal_address.gps_coordinates,
            address["gps_coordinates"],
        )
        self.assertNotIn("verification_code", response.json())
        code_request, code = self.review_and_mail(
            client, staff, payload["username"], payload["phone_number"], "businesses"
        )
        response = client.post(
            "/api/businesses/verify-code/",
            {"phone_number": payload["phone_number"], "verification_code": code},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["valid"])
        code_request.refresh_from_db()
        self.assertEqual(code_request.status, AccountCodeRequest.Status.COMPLETED)
        self.assertFalse(
            client.post(
                "/api/businesses/verify-code/",
                {"phone_number": payload["phone_number"], "verification_code": code},
                format="json",
            ).data["valid"]
        )
        response = client.post(
            "/api/businesses/login/",
            {"username": payload["username"], "password": payload["password"]},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)

    @override_settings(DEBUG=True, ENABLE_LOCAL_SIMULATOR=True)
    def test_local_logistics_simulator_uses_registration_and_verification(self):
        staff = get_user_model().objects.create_superuser(
            username="logistics_simulator_staff", password="LocalStaff!482"
        )
        client = APIClient()
        client.force_login(staff)
        address = {
            "street_address": "Test Street",
            "barangay": "Barangay I",
            "municipality_city": "Baler",
            "province": "Aurora",
            "postal_code": "3200",
            "country": "Philippines",
            "gps_coordinates": "15.75999, 121.56087",
        }
        documents = [
            {"type": kind, "url": "https://example.com/document.jpg"}
            for kind in (
                "ltfrb_franchise_for_trucking",
                "vehicle_photo",
                "vehicle_driver_license",
                "national_id",
                "official_receipt",
                "certificate_of_registration",
                "nbi_clearance",
            )
        ]
        payload = {
            "username": "simulator_logistics",
            "password": "SampleLogistics!482",
            "first_name": "Test",
            "last_name": "Manager",
            "date_of_birth": "2000-01-01",
            "phone_number": "5550124",
            "company_name": "Test Carrier",
            "company_phone": "5550124",
            "company_email": "carrier@example.com",
            "role": "Logistics_Manager",
            "personal_address": address,
            "company_address": address,
            "documents": documents,
            "vehicle": {
                "model": "Test Truck",
                "plate_number": "TEST-123",
                "max_weight_capacity_kg": "50",
                "max_volume_capacity_m3": "10",
                "body_type": "Other",
                "is_refrigerated": False,
            },
        }
        response = client.post(
            "/dashboard/local-test/logistics/register/", payload, format="json"
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(
            User.objects.get(username=payload["username"]).personal_address.gps_coordinates,
            address["gps_coordinates"],
        )
        self.assertNotIn("verification_code", response.json())
        code_request, code = self.review_and_mail(
            client, staff, payload["username"], payload["phone_number"], "logistics"
        )
        response = client.post(
            "/api/logistics/verify-code/",
            {"phone_number": payload["phone_number"], "verification_code": code},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["valid"])
        code_request.refresh_from_db()
        self.assertEqual(code_request.status, AccountCodeRequest.Status.COMPLETED)
        response = client.post(
            "/api/logistics/login/",
            {"username": payload["username"], "password": payload["password"]},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)

    def test_expired_code_can_be_requested_again_and_legacy_code_still_works(self):
        staff = get_user_model().objects.create_superuser(
            username="review_staff", password="LocalStaff!482"
        )
        user = User.objects.create(
            username="pending_buyer",
            password_hash=make_password("Password!482"),
            role=resolve_enum_order_id("role", "Bulk_Buyer"),
            is_verified=0,
        )
        PhoneNumber.objects.create(user=user, mobile_number="5551000")
        code_request = AccountCodeRequest.objects.create(user=user, kind="businesses")
        review_account_code_request(code_request.pk, staff, "approve")
        _, code, _ = issue_account_code(code_request.pk, staff)
        mark_account_code_mailed(code_request.pk, staff)
        AccountCodeRequest.objects.filter(pk=code_request.pk).update(
            code_expires_at=timezone.now()
        )
        client = APIClient()
        verify_url = "/api/businesses/verify-code/"
        self.assertFalse(
            client.post(
                verify_url,
                {"phone_number": "5551000", "verification_code": code},
                format="json",
            ).data["valid"]
        )
        self.assertEqual(
            client.post(
                "/api/businesses/code-requests/",
                {"username": user.username, "password": "incorrect"},
                format="json",
            ).status_code,
            202,
        )
        self.assertEqual(AccountCodeRequest.objects.filter(user=user).count(), 1)
        self.assertEqual(
            client.post(
                "/api/businesses/code-requests/",
                {"username": user.username, "password": "Password!482"},
                format="json",
            ).status_code,
            202,
        )
        code_request.refresh_from_db()
        self.assertEqual(code_request.status, AccountCodeRequest.Status.EXPIRED)
        self.assertEqual(
            AccountCodeRequest.objects.filter(
                user=user, status=AccountCodeRequest.Status.PENDING_REVIEW
            ).count(),
            1,
        )
        legacy = User.objects.create(
            username="legacy_buyer",
            role=resolve_enum_order_id("role", "Bulk_Buyer"),
            is_verified=0,
            verification_code="LEGACY01",
        )
        PhoneNumber.objects.create(user=legacy, mobile_number="5551001")
        self.assertTrue(
            client.post(
                verify_url,
                {"phone_number": "5551001", "verification_code": "LEGACY01"},
                format="json",
            ).data["valid"]
        )
        self.assertFalse(AccountCodeRequest.objects.filter(user=legacy).exists())

    def test_manual_verification_requires_reason_and_invalidates_issued_code(self):
        staff = get_user_model().objects.create_superuser(
            username="manual_review_staff", password="LocalStaff!482"
        )
        for kind, role in (
            ("businesses", "Bulk_Buyer"),
            ("logistics", "Logistics_Manager"),
        ):
            with self.subTest(kind=kind):
                user = User.objects.create(
                    username=f"manual_{kind}",
                    role=resolve_enum_order_id("role", role),
                    is_verified=0,
                )
                phone = PhoneNumber.objects.create(user=user, mobile_number="5552000")
                request = AccountCodeRequest.objects.create(user=user, kind=kind)
                review_account_code_request(request.pk, staff, "approve")
                _, code, _ = issue_account_code(request.pk, staff)
                mark_account_code_mailed(request.pk, staff)
                with self.assertRaises(AccountWorkflowValidationError):
                    manually_verify_account(request.pk, staff, " ")
                manually_verify_account(request.pk, staff, "Documents reviewed")
                user.refresh_from_db()
                phone.refresh_from_db()
                request.refresh_from_db()
                self.assertEqual(user.is_verified, 1)
                self.assertIsNone(user.verification_code)
                self.assertEqual(phone.is_verified, 1)
                self.assertEqual(request.status, AccountCodeRequest.Status.COMPLETED)
                audit = AuditLog.objects.get(
                    target_table="ACCOUNT_CODE_REQUESTS",
                    target_id=request.pk,
                    action_type="ACCOUNT_MANUALLY_VERIFIED",
                )
                self.assertIn("Documents reviewed", audit.new_values)
                self.assertNotIn(code, audit.new_values)
                with self.assertRaises(AccountWorkflowConflict):
                    manually_verify_account(request.pk, staff, "Duplicate")

    def test_rejected_application_can_be_resubmitted(self):
        staff = get_user_model().objects.create_superuser(
            username="rejection_staff", password="LocalStaff!482"
        )
        user = User.objects.create(
            username="rejected_logistics",
            password_hash=make_password("Password!482"),
            role=resolve_enum_order_id("role", "Logistics_Manager"),
            is_verified=0,
        )
        code_request = AccountCodeRequest.objects.create(user=user, kind="logistics")
        review_account_code_request(code_request.pk, staff, "reject", "Unreadable ID")
        response = APIClient().post(
            "/api/logistics/code-requests/",
            {"username": user.username, "password": "Password!482"},
            format="json",
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(
            AccountCodeRequest.objects.filter(
                user=user, status=AccountCodeRequest.Status.PENDING_REVIEW
            ).count(),
            1,
        )
