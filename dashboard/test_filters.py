from datetime import datetime
from datetime import timezone as datetime_timezone
from html import unescape
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from businesses.models import BulkBuyer
from farmers.models import Crop, CropType, Farm, FarmerCodeRequest
from logistics.models import Vehicle
from shared.models import AccountCodeRequest, Address, AuditLog, PhoneNumber, User


class DashboardFilterTests(TestCase):
    def setUp(self):
        staff = get_user_model().objects.create_user(
            username="filter_staff", password="unused", is_staff=True
        )
        self.client.force_login(staff)
        self.farmer = User.objects.create(
            first_name="Filtered", last_name="Farmer", role=1, is_verified=1
        )
        self.address = Address.objects.create(
            province="Pampanga", municipality_city="Arayat", barangay="San Juan"
        )
        self.other_address = Address.objects.create(
            province="Bulacan", municipality_city="Malolos", barangay="San Juan"
        )
        self.rice = CropType.objects.create(crop_name="Rice")
        self.farm = Farm.objects.create(
            user=self.farmer, address=self.address, farm_size_hectares=2
        )
        Crop.objects.create(farm=self.farm, crop_type=self.rice)
        self.created = datetime(2024, 5, 10, 12, tzinfo=datetime_timezone.utc)
        AuditLog.objects.create(
            target_table="USERS",
            target_id=self.farmer.pk,
            action_type="CREATE",
            created_at=self.created,
        )

    def test_farmer_filters_match_one_active_farm_and_combine_with_dates_status(self):
        another = Farm.objects.create(
            user=self.farmer, address=self.other_address, farm_size_hectares=12
        )
        Crop.objects.create(farm=another, crop_type=self.rice)
        url = reverse("farmers:dashboard")
        params = {
            "province": "pampanga",
            "municipality": "arayat",
            "crop": "rice",
            "farm_size": "1_to_10",
            "status_filter": "verified",
            "date_from": "2024-05-10",
            "date_to": "2024-05-10",
        }
        response = self.client.get(url, params)
        self.assertEqual(
            [row["id"] for row in response.context["rows"]], [self.farmer.pk]
        )
        self.assertContains(response, 'name="province" value="pampanga"')
        params["farm_size"] = "10_plus"
        self.assertEqual(self.client.get(url, params).context["rows"], [])
        self.farm.deleted_at = timezone.now()
        self.farm.save(update_fields=["deleted_at"])
        params["farm_size"] = "1_to_10"
        self.assertEqual(self.client.get(url, params).context["rows"], [])

    def test_farm_detail_filters_active_crop_and_location_without_duplicates(self):
        Crop.objects.create(farm=self.farm, crop_type=self.rice)
        archived_crop = Crop.objects.create(
            farm=self.farm,
            crop_type=CropType.objects.create(crop_name="Corn"),
            deleted_at=timezone.now(),
        )
        url = reverse("farmers:detail", args=[self.farmer.pk])
        response = self.client.get(
            url,
            {
                "view": "farms",
                "province": "pampanga",
                "crop": "rice",
                "farm_size": "1_to_10",
            },
        )
        self.assertEqual(
            [farm.pk for farm in response.context["farms"]], [self.farm.pk]
        )
        response = self.client.get(url, {"view": "farms", "crop": "corn"})
        self.assertEqual(response.context["farms"], [])
        self.assertIsNotNone(archived_crop.deleted_at)

    def test_farm_pagination_preserves_location_and_crop(self):
        Farm.objects.bulk_create(
            [Farm(user=self.farmer, address=self.address) for _ in range(20)]
        )
        response = self.client.get(
            reverse("farmers:detail", args=[self.farmer.pk]),
            {
                "view": "farms",
                "province": "Pampanga",
                "farm_status": "active",
            },
        )
        self.assertEqual(response.context["page_obj"].paginator.count, 21)
        self.assertIn(
            "province=Pampanga&amp;farm_status=active&amp;page=2",
            response.content.decode(),
        )

    def test_buyers_and_vehicles_combine_filters_and_keep_them_after_status_action(
        self,
    ):
        buyer = BulkBuyer.objects.create(
            business_name="Buyer",
            address=self.address,
            is_verified=0,
            date_time_created=self.created,
        )
        BulkBuyer.objects.create(
            business_name="Other",
            address=self.other_address,
            is_verified=0,
            date_time_created=self.created,
        )
        buyer_url = reverse("businesses:dashboard")
        query = "?province=Pampanga&date_from=2024-05-10&status_filter=pending&page=1"
        response = self.client.get(buyer_url + query)
        self.assertEqual([row["id"] for row in response.context["rows"]], [buyer.pk])
        response = self.client.post(
            buyer_url + query,
            {"section": "businesses", "target_id": buyer.pk, "stage": "1"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            parse_qs(urlsplit(response.url).query)["province"], ["Pampanga"]
        )
        vehicle = Vehicle.objects.create(
            plate_number="MATCH",
            body_type=1,
            is_refrigerated=1,
            max_weight_capacity_kg=1000,
        )
        Vehicle.objects.create(
            plate_number="OTHER",
            body_type=1,
            is_refrigerated=0,
            max_weight_capacity_kg=1000,
        )
        AuditLog.objects.create(
            target_table="VEHICLES",
            target_id=vehicle.pk,
            action_type="CREATE",
            created_at=self.created,
        )
        response = self.client.get(
            reverse("logistics:dashboard"),
            {
                "body_type": "1",
                "refrigerated": "1",
                "min_capacity": "1000",
                "max_capacity": "1000",
                "date_to": "2024-05-10",
            },
        )
        self.assertEqual([row["id"] for row in response.context["rows"]], [vehicle.pk])

    def test_optional_column_values_appear_for_each_record_type(self):
        PhoneNumber.objects.create(user=self.farmer, mobile_number="09123456789")
        farmer = self.client.get(reverse("farmers:dashboard"))
        self.assertContains(farmer, 'data-column="phone" hidden>09123456789')
        self.assertContains(farmer, 'data-column="farm_size" hidden>2.00')
        self.assertContains(
            farmer, 'data-column="location" hidden>San Juan, Arayat, Pampanga'
        )

        Vehicle.objects.create(
            plate_number="CAPACITY",
            max_weight_capacity_kg=0,
            max_volume_capacity_m3=5,
            is_refrigerated=1,
        )
        logistics = self.client.get(reverse("logistics:dashboard"))
        self.assertContains(logistics, 'data-column="weight" hidden>0.00')
        self.assertContains(logistics, 'data-column="volume" hidden>5.00')
        self.assertContains(logistics, 'data-column="refrigerated" hidden>Yes')

        BulkBuyer.objects.create(business_name="Buyer", address=self.address)
        buyers = self.client.get(reverse("businesses:dashboard"))
        self.assertContains(
            buyers, 'data-column="address" hidden>San Juan, Arayat, Pampanga'
        )

    def test_audit_filters_and_pagination_preserve_query(self):
        for _ in range(2):
            AuditLog.objects.create(
                action_type="UPDATE_STATUS",
                target_table="BULK_BUYERS",
                created_at=self.created,
            )
        with patch("dashboard.views.DASHBOARD_PAGE_SIZE", 1):
            response = self.client.get(
                reverse("dashboard_audit_logs"),
                {
                    "action_type": "update",
                    "target_type": "buyers",
                    "date_from": "2024-05-10",
                    "date_to": "2024-05-10",
                },
            )
        self.assertEqual(response.context["page_obj"].paginator.count, 2)
        self.assertContains(response, "action_type=update")
        self.assertContains(response, "target_type=buyers")
        self.assertContains(response, "page=2")

    def test_invalid_ranges_and_choices_are_visible(self):
        for route, params in (
            ("farmers:dashboard", {"date_from": "2024-06-01", "date_to": "2024-05-01"}),
            ("logistics:dashboard", {"min_capacity": "10", "max_capacity": "5"}),
            ("logistics:dashboard", {"body_type": "not-a-type"}),
        ):
            with self.subTest(route=route, params=params):
                response = self.client.get(reverse(route), params)
                self.assertEqual(response.status_code, 400)
                self.assertContains(
                    response, "Correct the filter errors", status_code=400
                )

    def test_pending_includes_unknown_status_and_rejected_labels_are_correct(self):
        unknown = User.objects.create(first_name="Unknown", role=1, is_verified=None)
        rejected = User.objects.create(first_name="Rejected", role=1, is_verified=2)
        buyer = BulkBuyer.objects.create(
            business_name="Unknown buyer", is_verified=None
        )
        rejected_buyer = BulkBuyer.objects.create(
            business_name="Rejected buyer", is_verified=2
        )
        vehicle = Vehicle.objects.create(
            plate_number="UNKNOWN", current_health_status=None
        )
        for route, expected in (
            ("farmers:dashboard", unknown.pk),
            ("businesses:dashboard", buyer.pk),
            ("logistics:dashboard", vehicle.pk),
        ):
            response = self.client.get(reverse(route), {"status_filter": "pending"})
            self.assertIn(expected, [row["id"] for row in response.context["rows"]])
        for route, expected in (
            ("farmers:dashboard", rejected.pk),
            ("businesses:dashboard", rejected_buyer.pk),
        ):
            response = self.client.get(reverse(route), {"status_filter": "rejected"})
            self.assertEqual(
                [(row["id"], row["status_label"]) for row in response.context["rows"]],
                [(expected, "Rejected")],
            )

    def test_verification_purpose_dates_and_action_return_preserve_filters(self):
        recovery = FarmerCodeRequest.objects.create(
            user=self.farmer, purpose=FarmerCodeRequest.Purpose.RECOVERY
        )
        buyer = AccountCodeRequest.objects.create(user=self.farmer, kind="businesses")
        url = reverse("dashboard_verification_requests")
        today = timezone.localdate().isoformat()
        params = {"purpose": "recovery", "date_from": today, "date_to": today}
        response = self.client.get(url, params)
        self.assertEqual(
            [item.pk for item in response.context["code_requests"]], [recovery.pk]
        )
        self.assertContains(response, "purpose=recovery")
        query = "?queue=unified&purpose=recovery&date_from=" + today + "&page=1"
        response = self.client.post(
            reverse("dashboard_code_requests") + query,
            {"request_id": recovery.pk, "action": "approve"},
        )
        self.assertEqual(
            parse_qs(urlsplit(response.url).query)["purpose"], ["recovery"]
        )
        response = self.client.get(url, {"purpose": "verification"})
        self.assertEqual(
            [(item.queue_kind, item.pk) for item in response.context["code_requests"]],
            [("businesses", buyer.pk)],
        )
        self.assertEqual(self.client.get(url, {"purpose": "invalid"}).status_code, 400)

    def test_verification_pagination_and_form_action_preserve_filters(self):
        for _ in range(2):
            FarmerCodeRequest.objects.create(
                user=self.farmer, purpose=FarmerCodeRequest.Purpose.RECOVERY
            )
        today = timezone.localdate().isoformat()
        with patch("dashboard.verification_views.DASHBOARD_PAGE_SIZE", 1):
            response = self.client.get(
                reverse("dashboard_verification_requests"),
                {
                    "type": "farmers",
                    "purpose": "recovery",
                    "date_from": today,
                },
            )
        html = unescape(response.content.decode())
        self.assertEqual(response.context["page_obj"].paginator.count, 2)
        self.assertIn(f"purpose=recovery&date_from={today}&page=2", html)
        self.assertIn(f"purpose=recovery&date_from={today}&page=1&queue=unified", html)
        self.assertIn(reverse("dashboard_code_requests") + "?", html)
