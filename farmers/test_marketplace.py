import os
from decimal import Decimal
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import Group
from django.test import Client, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from farmers.models import Crop, CropCalendar, CropOperatingExpense, CropType, Farm
from logistics.models import LogisticsCompany, Vehicle
from shared.models import Address, User
from shared.registration import resolve_enum_order_id

RUN_DATABASE_TESTS = os.environ.get("FTH_DATABASE_TESTS") == "1"


@skipUnless(RUN_DATABASE_TESTS, "Requires a preinitialized PostgreSQL test database")
class FarmerMarketplaceTests(TestCase):
    databases = {"default"} if RUN_DATABASE_TESTS else set()

    @classmethod
    def setUpTestData(cls):
        cls.password = "TestPassword!482"
        roles = {
            role: resolve_enum_order_id("role", role)
            for role in ("Farmer", "Bulk_Buyer", "Logistics_Manager")
        }
        cls.farmer = User.objects.create(
            username="market_farmer",
            password_hash=make_password(cls.password),
            role=roles["Farmer"],
            is_verified=1,
        )
        cls.other = User.objects.create(
            username="other_farmer",
            password_hash=make_password(cls.password),
            role=roles["Farmer"],
            is_verified=1,
        )
        cls.pending = User.objects.create(
            username="pending_farmer",
            password_hash=make_password(cls.password),
            role=roles["Farmer"],
            is_verified=0,
        )
        cls.buyer = User.objects.create(
            username="market_buyer",
            password_hash=make_password(cls.password),
            role=roles["Bulk_Buyer"],
            is_verified=1,
        )
        cls.manager = User.objects.create(
            username="market_manager",
            password_hash=make_password(cls.password),
            role=roles["Logistics_Manager"],
            is_verified=1,
        )
        cls.address = Address.objects.create(
            street_address="Old address", country="Philippines", address_type="farm"
        )
        cls.farm = Farm.objects.create(
            user=cls.farmer, address=cls.address, farm_size_hectares=Decimal("3")
        )
        cls.other_farm = Farm.objects.create(user=cls.other, address=cls.address)
        cls.crop_type = CropType.objects.create(crop_name="Test tomato")
        cls.old_crop = Crop.objects.create(farm=cls.farm, crop_type=cls.crop_type)
        cls.old_calendar = CropCalendar.objects.create(
            crop=cls.old_crop, pickup_address=cls.address
        )

    def login(self, section, user):
        client = APIClient()
        response = client.post(
            f"/api/{section}/login/",
            {"username": user.username, "password": self.password},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
        return client

    def listing_payload(self):
        return {
            "farm_id": self.farm.pk,
            "crop_type_id": self.crop_type.pk,
            "batch_number": "TEST-1",
            "title": "Tomatoes",
            "available_stock_kg": "20.00",
            "price_per_kg": "4.00",
            "is_active": True,
        }

    def test_farms_are_owner_scoped_and_address_changes_preserve_pickup(self):
        farmer = self.login("farmers", self.farmer)
        other = self.login("farmers", self.other)
        self.assertEqual(
            [farm["farm_id"] for farm in farmer.get("/api/farmers/farms/").data],
            [self.farm.pk],
        )
        url = f"/api/farmers/farms/{self.farm.pk}/"
        self.assertEqual(
            other.patch(url, {"farm_size_hectares": "8"}, format="json").status_code,
            404,
        )
        response = farmer.patch(
            url,
            {"farm_size_hectares": "4.5", "address": {"street_address": "New"}},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.farm.refresh_from_db()
        self.other_farm.refresh_from_db()
        self.old_calendar.refresh_from_db()
        self.assertNotEqual(self.farm.address_id, self.address.pk)
        self.assertEqual(self.farm.address.street_address, "New")
        self.assertEqual(self.other_farm.address_id, self.address.pk)
        self.assertEqual(self.old_calendar.pickup_address_id, self.address.pk)
        self.assertEqual(
            farmer.patch(url, {"farm_size_hectares": "-1"}, format="json").status_code,
            400,
        )
        response = farmer.post(
            "/api/farmers/farms/",
            {
                "farm_size_hectares": "1.25",
                "address": {
                    "street_address": "New Road",
                    "barangay": "Test",
                    "municipality_city": "Test City",
                    "province": "Test",
                    "postal_code": "1000",
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            Farm.objects.get(pk=response.data["farm_id"]).user, self.farmer
        )

    def test_listings_orders_and_stock_are_scoped_to_the_owner(self):
        farmer = self.login("farmers", self.farmer)
        other = self.login("farmers", self.other)
        buyer = self.login("businesses", self.buyer)
        payload = self.listing_payload()
        self.assertEqual(
            other.post("/api/farmers/listings/", payload, format="json").status_code,
            404,
        )
        response = farmer.post("/api/farmers/listings/", payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        listing_id = response.data["listing_id"]
        listing_url = f"/api/farmers/listings/{listing_id}/"
        self.assertEqual(
            other.patch(listing_url, {"is_active": False}, format="json").status_code,
            404,
        )
        self.assertEqual(other.get("/api/farmers/listings/").data, [])
        self.assertEqual(buyer.get("/api/farmers/listings/").status_code, 401)
        self.assertEqual(
            farmer.patch(
                listing_url, {"price_per_kg": "-1"}, format="json"
            ).status_code,
            400,
        )
        order = buyer.post(
            "/api/businesses/orders/",
            {"listing_id": listing_id, "quantity_kg": "3"},
            format="json",
        )
        self.assertEqual(order.status_code, 201, order.data)
        orders = farmer.get("/api/farmers/orders/").data
        self.assertEqual(orders[0]["order_id"], order.data["order_id"])
        self.assertEqual(orders[0]["reservation_status"], "reserved")
        self.assertEqual(other.get("/api/farmers/orders/").data, [])
        response = farmer.patch(
            listing_url, {"available_stock_kg": "10", "is_active": False}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data["is_active"])
        visible_ids = [
            item["listing_id"] for item in buyer.get("/api/businesses/listings/").data
        ]
        self.assertNotIn(listing_id, visible_ids)
        cancelled = buyer.post(
            f"/api/businesses/orders/{order.data['order_id']}/cancel/", format="json"
        )
        self.assertEqual(cancelled.status_code, 200, cancelled.data)
        self.assertEqual(
            farmer.get("/api/farmers/orders/").data[0]["reservation_status"],
            "cancelled",
        )
        self.assertEqual(
            Crop.objects.get(pk=response.data["crop_id"]).available_stock_kg,
            Decimal("13"),
        )

    def test_farm_add_rejects_ids_and_update_requires_an_owned_active_farm(self):
        farmer = self.login("farmers", self.farmer)
        url = "/api/farmers/farms/"
        response = farmer.post(url, {"farm_id": self.farm.pk}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("already has", str(response.data))
        response = farmer.post(url, {"farm_id": self.other_farm.pk}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("assigned automatically", str(response.data))
        address = {
            "street_address": "Same address",
            "barangay": "Test",
            "municipality_city": "Test City",
            "province": "Test",
            "postal_code": "1000",
        }
        for _ in range(2):
            response = farmer.post(
                url, {"farm_size_hectares": "1", "address": address}, format="json"
            )
            self.assertEqual(response.status_code, 201, response.data)
        response = farmer.patch(
            f"{url}{self.other_farm.pk}/", {"farm_size_hectares": "4"}, format="json"
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn("not found", str(response.data).lower())
        self.farm.deleted_at = timezone.now()
        self.farm.save(update_fields=["deleted_at"])
        self.assertEqual(
            farmer.post(url, {"farm_id": self.farm.pk}, format="json").status_code, 400
        )
        self.assertEqual(
            farmer.patch(
                f"{url}{self.farm.pk}/", {"farm_size_hectares": "4"}, format="json"
            ).status_code,
            404,
        )

    def test_crop_expenses_are_crop_owned_validated_and_shared(self):
        farmer = self.login("farmers", self.farmer)
        other = self.login("farmers", self.other)
        url = f"/api/farmers/crops/{self.old_crop.pk}/expenses/"
        for data in (
            {"tag": "", "amount": "5"},
            {"tag": "Seed", "amount": "-1"},
            {"tag": "Seed", "amount": "1.234"},
            {"tag": "Seed"},
        ):
            self.assertEqual(farmer.post(url, data, format="json").status_code, 400)
        self.assertEqual(other.get(url).status_code, 404)
        self.assertEqual(
            other.post(url, {"tag": "Seed", "amount": "1"}, format="json").status_code,
            404,
        )
        for tag, amount in (("Seed", "10.00"), ("Fuel", "20.50"), ("Seed", "2.00")):
            response = farmer.post(url, {"tag": tag, "amount": amount}, format="json")
            self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            [(entry["tag"], entry["amount"]) for entry in farmer.get(url).data],
            [("Seed", "10.00"), ("Fuel", "20.50"), ("Seed", "2.00")],
        )
        payload = {
            "crop_id": self.old_crop.pk,
            "title": "First",
            "price_per_kg": "4",
            "is_active": True,
        }
        first = farmer.post("/api/farmers/listings/", payload, format="json")
        second = farmer.post("/api/farmers/listings/", payload, format="json")
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(first.data["crop_id"], second.data["crop_id"])
        self.assertEqual(
            CropOperatingExpense.objects.filter(crop=self.old_crop).count(), 3
        )
        self.old_crop.deleted_at = timezone.now()
        self.old_crop.save(update_fields=["deleted_at"])
        self.assertEqual(farmer.get(url).status_code, 404)
        self.assertEqual(
            farmer.post(url, {"tag": "Seed", "amount": "1"}, format="json").status_code,
            404,
        )

    def test_existing_crop_without_type_cannot_be_listed(self):
        farmer = self.login("farmers", self.farmer)
        self.old_crop.crop_type = None
        self.old_crop.save(update_fields=["crop_type"])
        response = farmer.post(
            "/api/farmers/listings/",
            {
                "crop_id": self.old_crop.pk,
                "title": "Invalid",
                "price_per_kg": "4",
                "is_active": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("crop type", str(response.data))

    def test_existing_crop_can_be_listed_using_its_calendar(self):
        farmer = self.login("farmers", self.farmer)
        other = self.login("farmers", self.other)
        crops = farmer.get("/api/farmers/crops/").data
        self.assertEqual([crop["crop_id"] for crop in crops], [self.old_crop.pk])
        payload = self.listing_payload()
        del payload["farm_id"]
        del payload["crop_type_id"]
        del payload["available_stock_kg"]
        payload["crop_id"] = self.old_crop.pk
        self.assertEqual(
            other.post("/api/farmers/listings/", payload, format="json").status_code,
            404,
        )
        response = farmer.post("/api/farmers/listings/", payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["crop_id"], self.old_crop.pk)
        self.assertEqual(response.data["calendar_id"], self.old_calendar.pk)
        self.old_crop.refresh_from_db()
        self.assertIsNone(self.old_crop.available_stock_kg)
        payload["available_stock_kg"] = "20"
        self.assertEqual(
            farmer.post("/api/farmers/listings/", payload, format="json").status_code,
            400,
        )
        del payload["available_stock_kg"]
        payload["farm_id"] = self.farm.pk
        self.assertEqual(
            farmer.post("/api/farmers/listings/", payload, format="json").status_code,
            400,
        )

    def test_farmer_order_shows_delivery_progress(self):
        farmer = self.login("farmers", self.farmer)
        buyer = self.login("businesses", self.buyer)
        manager = self.login("logistics", self.manager)
        from businesses.models import BulkBuyer

        BulkBuyer.objects.create(
            user=self.buyer, address=self.address, business_name="Test"
        )
        company = LogisticsCompany.objects.create(
            user=self.manager, business_name="Test"
        )
        vehicle = Vehicle.objects.create(
            user=self.manager,
            logistics_business=company,
            plate_number="TEST-1",
            max_weight_capacity_kg=Decimal("100"),
            max_volume_capacity_m3=Decimal("10"),
            body_type=1,
        )
        listing = farmer.post(
            "/api/farmers/listings/", self.listing_payload(), format="json"
        )
        self.assertEqual(listing.status_code, 201, listing.data)
        order = buyer.post(
            "/api/businesses/orders/",
            {
                "listing_id": listing.data["listing_id"],
                "quantity_kg": "3",
                "delivery_company_id": company.pk,
            },
            format="json",
        )
        self.assertEqual(order.status_code, 201, order.data)
        self.assertEqual(
            farmer.get("/api/farmers/orders/").data[0]["delivery_status"],
            "awaiting_trip",
        )
        trip = manager.post(
            "/api/logistics/trips/",
            {"vehicle_id": vehicle.pk, "order_ids": [order.data["order_id"]]},
            format="json",
        )
        self.assertEqual(trip.status_code, 201, trip.data)
        url = f"/api/logistics/trips/{trip.data['trip_id']}/"
        self.assertEqual(
            farmer.get("/api/farmers/orders/").data[0]["delivery_status"], "planned"
        )
        self.assertEqual(
            manager.patch(url, {"trip_status": 2}, format="json").status_code, 200
        )
        self.assertEqual(
            farmer.get("/api/farmers/orders/").data[0]["delivery_status"], "in_transit"
        )
        self.assertEqual(
            manager.patch(url, {"trip_status": 3}, format="json").status_code, 200
        )
        result = farmer.get("/api/farmers/orders/").data[0]
        self.assertEqual(result["delivery_status"], "completed")
        self.assertEqual(result["reservation_status"], "delivered")

    def test_verified_senders_and_recipient_scoped_inbox(self):
        farmer = self.login("farmers", self.farmer)
        other = self.login("farmers", self.other)
        buyer = self.login("businesses", self.buyer)
        manager = self.login("logistics", self.manager)
        payload = {"farmer_id": self.farmer.pk, "body": "Hello farmer"}
        self.assertEqual(
            farmer.post(
                "/api/businesses/farmer-messages/", payload, format="json"
            ).status_code,
            401,
        )
        self.assertEqual(
            buyer.post(
                "/api/businesses/farmer-messages/",
                {"farmer_id": self.pending.pk, "body": "Hello"},
                format="json",
            ).status_code,
            404,
        )
        self.assertEqual(
            buyer.post(
                "/api/businesses/farmer-messages/",
                {"farmer_id": self.farmer.pk, "body": "  "},
                format="json",
            ).status_code,
            400,
        )
        self.assertEqual(
            buyer.post(
                "/api/businesses/farmer-messages/", payload, format="json"
            ).status_code,
            201,
        )
        self.assertEqual(
            manager.post(
                "/api/logistics/farmer-messages/", payload, format="json"
            ).status_code,
            201,
        )
        messages = farmer.get("/api/farmers/messages/").data
        self.assertEqual(
            {message["sender_kind"] for message in messages},
            {"businesses", "logistics"},
        )
        self.assertEqual(other.get("/api/farmers/messages/").data, [])
        self.buyer.is_verified = 0
        self.buyer.save(update_fields=["is_verified"])
        self.assertEqual(
            buyer.post(
                "/api/businesses/farmer-messages/", payload, format="json"
            ).status_code,
            401,
        )

    @override_settings(DEBUG=True, ENABLE_LOCAL_SIMULATOR=True)
    def test_simulator_farmer_list_requires_staff_and_paginates(self):
        staff = get_user_model().objects.create_superuser(
            username="simulator_staff", password=self.password
        )
        self.client.force_login(staff)
        for index in range(25):
            User.objects.create(username=f"list_farmer_{index}", role=self.farmer.role)
        response = self.client.get(
            "/dashboard/local-test-farmers/", REMOTE_ADDR="127.0.0.1"
        )
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(len(result["farmers"]), 25)
        self.assertTrue(result["has_next"])
        self.assertNotIn("password_hash", result["farmers"][0])
        response = self.client.get(
            "/dashboard/local-test-farmers/?page=2", REMOTE_ADDR="127.0.0.1"
        )
        self.assertGreater(len(response.json()["farmers"]), 0)
        self.assertEqual(
            self.client.get(
                "/dashboard/local-test-farmers/", REMOTE_ADDR="192.0.2.1"
            ).status_code,
            404,
        )

    @override_settings(DEBUG=True, ENABLE_LOCAL_SIMULATOR=True)
    def test_local_farmer_operations_are_scoped_and_public_api_stays_protected(self):
        staff = get_user_model().objects.create_superuser(
            username="simulator_editor", password=self.password
        )
        self.client.force_login(staff)
        base = f"/dashboard/local-test/farmers/{self.farmer.pk}/api/"
        pending = f"/dashboard/local-test/farmers/{self.pending.pk}/api/"
        detail = f"/dashboard/local-test/farmers/{self.pending.pk}/"
        self.assertEqual(self.client.get(detail).status_code, 200)
        self.assertContains(self.client.get(detail), self.pending.username)
        self.assertEqual(
            self.client.get(
                f"/dashboard/local-test/farmers/{self.buyer.pk}/"
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(detail, HTTP_X_FORWARDED_FOR="192.0.2.1").status_code,
            404,
        )

        response = self.client.patch(
            base + "me/", {"first_name": "Edited"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.first_name, "Edited")
        response = self.client.patch(
            pending + "me/", {"first_name": "Pending"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(APIClient().get("/api/farmers/me/").status_code, 401)
        self.assertEqual(
            APIClient().patch(
                "/api/farmers/me/", {"first_name": "Blocked"}, format="json"
            ).status_code,
            401,
        )
        self.assertEqual(
            APIClient().post(
                "/api/farmers/login/",
                {"username": self.pending.username, "password": self.password},
                format="json",
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.patch(
                base + f"farms/{self.other_farm.pk}/",
                {"farm_size_hectares": "4"},
                content_type="application/json",
            ).status_code,
            404,
        )
        response = self.client.post(
            base + "listings/", self.listing_payload(), content_type="application/json"
        )
        self.assertEqual(response.status_code, 201, response.content)
        listing_id = response.json()["listing_id"]
        expense_url = base + f"crops/{response.json()['crop_id']}/expenses/"
        expense = self.client.post(
            expense_url,
            {"tag": "Fuel", "amount": "5.00"},
            content_type="application/json",
        )
        self.assertEqual(expense.status_code, 201, expense.content)
        self.assertEqual(self.client.get(expense_url).json()[0]["tag"], "Fuel")
        self.assertEqual(
            self.client.get(pending + f"crops/{self.old_crop.pk}/expenses/").status_code,
            404,
        )
        duplicate = self.client.post(
            base + "farms/", {"farm_id": self.farm.pk}, content_type="application/json"
        )
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("already has", str(duplicate.content))
        response = self.client.patch(
            base + f"listings/{listing_id}/",
            {"price_per_kg": "-1"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400, response.content)
        for action in (
            "farms/", "crop-types/", "crops/", "listings/", "orders/", "messages/"
        ):
            self.assertEqual(self.client.get(base + action).status_code, 200, action)
        self.assertEqual(self.client.post(base + "login/").status_code, 404)
        self.assertEqual(self.client.delete(base + "me/").status_code, 405)
        self.assertEqual(
            self.client.get(
                base + "me/", REMOTE_ADDR="127.0.0.1",
                HTTP_X_FORWARDED_FOR="192.0.2.1",
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                f"/dashboard/local-test/farmers/{self.buyer.pk}/api/me/"
            ).status_code,
            404,
        )
        self.pending.deleted_at = timezone.now()
        self.pending.save(update_fields=["deleted_at"])
        self.assertEqual(self.client.get(pending + "me/").status_code, 404)
        self.assertEqual(self.client.get(detail).status_code, 404)

    @override_settings(DEBUG=True, ENABLE_LOCAL_SIMULATOR=True)
    def test_local_farmer_edits_require_csrf_and_staff_permission(self):
        staff = get_user_model().objects.create_superuser(
            username="simulator_csrf", password=self.password
        )
        client = Client(enforce_csrf_checks=True)
        client.force_login(staff)
        url = f"/dashboard/local-test/farmers/{self.farmer.pk}/api/me/"
        expense_url = (
            f"/dashboard/local-test/farmers/{self.farmer.pk}/api/"
            f"crops/{self.old_crop.pk}/expenses/"
        )
        self.assertEqual(
            client.post(
                expense_url,
                {"tag": "Fuel", "amount": "5"},
                content_type="application/json",
            ).status_code,
            403,
        )
        self.assertEqual(
            client.patch(
                url, {"first_name": "Blocked"}, content_type="application/json"
            ).status_code,
            403,
        )
        page = client.get("/dashboard/local-test/farmers/")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(
            client.patch(
                url, {"first_name": "Allowed"}, content_type="application/json",
                HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
            ).status_code,
            200,
        )
        client.logout()
        self.assertEqual(client.get(url).status_code, 404)
        detail = f"/dashboard/local-test/farmers/{self.farmer.pk}/"
        self.assertEqual(client.get(detail).status_code, 404)
        ordinary_user = get_user_model().objects.create_user(
            username="simulator_nonstaff", password=self.password
        )
        client.force_login(ordinary_user)
        self.assertEqual(client.get(url).status_code, 404)
        self.assertEqual(client.get(detail).status_code, 404)
        with override_settings(ENABLE_LOCAL_SIMULATOR=False):
            client.force_login(staff)
            self.assertEqual(client.get(url).status_code, 404)

    @override_settings(
        DEBUG=False, ENABLE_LOCAL_SIMULATOR=False, ENABLE_LIVE_SIMULATOR=True
    )
    def test_live_simulator_requires_management_permission_and_csrf(self):
        client = Client(enforce_csrf_checks=True)
        url = f"/dashboard/local-test/farmers/{self.farmer.pk}/api/me/"
        proxy = {"REMOTE_ADDR": "192.0.2.1", "HTTP_X_FORWARDED_FOR": "198.51.100.1"}
        self.assertEqual(client.get(url, **proxy).status_code, 404)

        reviewer = get_user_model().objects.create_user(
            username="live_reviewer", is_staff=True
        )
        reviewer.groups.add(Group.objects.get(name="Reviewer"))
        client.force_login(reviewer)
        self.assertEqual(client.get(url, **proxy).status_code, 404)

        manager = get_user_model().objects.create_user(
            username="live_manager", is_staff=True
        )
        manager.groups.add(Group.objects.get(name="Support editor"))
        client.force_login(manager)
        self.assertEqual(
            client.patch(
                url, {"first_name": "Blocked"}, content_type="application/json", **proxy
            ).status_code,
            403,
        )
        page = client.get("/dashboard/local-test/farmers/", **proxy)
        self.assertContains(page, "Live database warning.")
        with self.assertLogs("dashboard.simulator", level="WARNING") as logs:
            response = client.patch(
                url, {"first_name": "Live edit"}, content_type="application/json",
                HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value, **proxy,
            )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn(
            f"staff_id={manager.pk} farmer_id={self.farmer.pk}", logs.output[0]
        )
        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.first_name, "Live edit")
        self.assertEqual(APIClient().get("/api/farmers/me/").status_code, 401)
        with override_settings(ENABLE_LIVE_SIMULATOR=False):
            self.assertEqual(client.get(url, **proxy).status_code, 404)
