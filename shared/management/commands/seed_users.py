from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.test import Client

from businesses.models import BulkBuyer
from farmers.models import (
    Crop,
    CropCalendar,
    Farm,
    FarmerAdminAuditEvent,
    FarmerCodeRequest,
    FarmerRevokedRefreshToken,
)
from logistics.models import LogisticsCompany, Vehicle, VehicleStatusHistory
from shared.models import (
    Address,
    AuditLog,
    ElectronicDocument,
    EmailAddress,
    PhoneNumber,
    User,
)

LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "::1"}
TEST_USERNAME_PREFIXES = ("test_farmer", "test_buyer", "test_logistics")
DOC_BASE = "https://example.com/docs"


def _address(prefix, number):
    return {
        "street_address": f"{number} {prefix} Street",
        "barangay": "Poblacion",
        "municipality_city": "Davao City",
        "province": "Davao del Sur",
        "postal_code": "8000",
        "country": "Philippines",
        "gps_coordinates": "Region XI",
    }


def farmer_payload(index, password):
    return {
        "role": "Farmer",
        "username": f"test_farmer{index}",
        "password": password,
        "firstname": "Farmer",
        "lastname": f"Test{index}",
        "phonenumber": f"+63917000{index:04d}",
        "region": "Region XI",
        "province": "Davao del Sur",
        "municipality": "Davao City",
        "baranggay": "Poblacion",
        "house_number": str(index),
        "street": "Home Street",
        "postal_code": "8000",
        "farm_size": "2.50",
        "farm_region": "Region XI",
        "farm_province": "Davao del Sur",
        "farm_municipality": "Davao City",
        "farm_barangay": "Poblacion",
        "farm_house_number": str(index),
        "farm_street": "Farm Road",
        "farm_postal_code": "8000",
        "language": "English",
        "documents": [f"{DOC_BASE}/farmer{index}_{n}.jpg" for n in range(1, 5)],
    }


def buyer_payload(index, password):
    types = (
        "birth_certificate",
        "business_utility_bill",
        "business_permit",
        "national_id",
    )
    return {
        "role": "Bulk_Buyer",
        "username": f"test_buyer{index}",
        "password": password,
        "first_name": "Buyer",
        "last_name": f"Test{index}",
        "date_of_birth": "1990-01-15",
        "phone_number": f"+63918000{index:04d}",
        "business_name": f"Test Trading {index}",
        "personal_address": _address("Home", index),
        "business_address": _address("Market", index),
        "documents": [
            {"type": doc_type, "url": f"{DOC_BASE}/buyer{index}_{doc_type}.jpg"}
            for doc_type in types
        ],
    }


def logistics_payload(index, password):
    types = (
        "ltfrb_franchise_for_trucking",
        "vehicle_photo",
        "vehicle_driver_license",
        "national_id",
        "official_receipt",
        "certificate_of_registration",
        "nbi_clearance",
    )
    return {
        "role": "Logistics_Manager",
        "username": f"test_logistics{index}",
        "password": password,
        "first_name": "Logistics",
        "last_name": f"Test{index}",
        "date_of_birth": "1988-06-20",
        "phone_number": f"+63919000{index:04d}",
        "company_name": f"Test Haulers {index}",
        "company_phone": f"+63822000{index:04d}",
        "company_email": f"haulers{index}@example.com",
        "personal_address": _address("Home", index),
        "company_address": _address("Depot", index),
        "vehicle": {
            "model": "Isuzu Elf",
            "plate_number": f"TST {1000 + index}",
            "max_weight_capacity_kg": "3000.00",
            "max_volume_capacity_m3": "15.00",
            "body_type": "Other",
            "is_refrigerated": False,
        },
        "documents": [
            {"type": doc_type, "url": f"{DOC_BASE}/logistics{index}_{doc_type}.jpg"}
            for doc_type in types
        ],
    }


SEEDS = (
    ("farmers", "/api/farmers/register/", farmer_payload),
    ("buyers", "/api/businesses/register/", buyer_payload),
    ("logistics", "/api/logistics/register/", logistics_payload),
)


def _test_users():
    query = Q()
    for prefix in TEST_USERNAME_PREFIXES:
        query |= Q(username__startswith=prefix)
    return User.objects.filter(query)


@transaction.atomic
def delete_test_users():
    """Delete seeded users and every row that points at them (most FKs are SET_NULL)."""
    users = _test_users()
    user_ids = list(users.values_list("pk", flat=True))
    if not user_ids:
        return 0

    farms = Farm.objects.filter(user__in=user_ids)
    buyers = BulkBuyer.objects.filter(user__in=user_ids)
    companies = LogisticsCompany.objects.filter(user__in=user_ids)
    vehicles = Vehicle.objects.filter(
        Q(user__in=user_ids) | Q(logistics_business__in=companies)
    )

    address_ids = set(
        users.exclude(personal_address=None).values_list("personal_address", flat=True)
    )
    for related in (farms, buyers, companies):
        address_ids.update(
            related.exclude(address=None).values_list("address", flat=True)
        )

    crops = Crop.objects.filter(farm__in=farms)
    CropCalendar.objects.filter(crop__in=crops).delete()
    crops.delete()
    ElectronicDocument.objects.filter(
        Q(user__in=user_ids) | Q(vehicle__in=vehicles)
    ).delete()
    VehicleStatusHistory.objects.filter(vehicle__in=vehicles).delete()
    PhoneNumber.objects.filter(user__in=user_ids).delete()
    EmailAddress.objects.filter(user__in=user_ids).delete()
    AuditLog.objects.filter(user__in=user_ids).delete()
    FarmerAdminAuditEvent.objects.filter(user__in=user_ids).delete()
    FarmerRevokedRefreshToken.objects.filter(user__in=user_ids).delete()
    FarmerCodeRequest.objects.filter(user__in=user_ids).delete()
    vehicles.delete()
    farms.delete()
    buyers.delete()
    companies.delete()
    users.delete()
    Address.objects.filter(pk__in=address_ids).delete()
    return len(user_ids)


class Command(BaseCommand):
    help = (
        "Create test farmers, bulk buyers and logistics companies through the "
        "registration API. Local databases only."
    )

    def add_arguments(self, parser):
        parser.add_argument("--farmers", type=int, default=3)
        parser.add_argument("--buyers", type=int, default=3)
        parser.add_argument("--logistics", type=int, default=3)
        parser.add_argument("--password", default="TestPass123!")
        parser.add_argument(
            "--reset",
            action="store_true",
            help=(
                "Delete previously seeded test_farmer*, test_buyer* and "
                "test_logistics* users and their related rows before seeding."
            ),
        )
        parser.add_argument(
            "--reset-only",
            action="store_true",
            help="Delete the seeded test users and stop without creating new ones.",
        )

    def handle(self, *args, **options):
        host = settings.DATABASES["default"].get("HOST", "")
        if host not in LOCAL_HOSTS:
            raise CommandError(
                f"Refusing to seed non-local database host '{host}'. "
                "Unset DATABASE_URL and use your local PostgreSQL."
            )

        if options["reset"] or options["reset_only"]:
            removed = delete_test_users()
            self.stdout.write(f"reset: {removed} test users removed")
            if options["reset_only"]:
                return

        client = Client(SERVER_NAME="localhost")
        for key, url, build in SEEDS:
            created = skipped = 0
            for index in range(1, options[key] + 1):
                payload = build(index, options["password"])
                if User.objects.filter(username=payload["username"]).exists():
                    skipped += 1
                    continue
                response = client.post(url, payload, content_type="application/json")
                if response.status_code != 201:
                    raise CommandError(
                        f"{payload['username']} failed "
                        f"({response.status_code}): {response.content.decode()}"
                    )
                created += 1
            self.stdout.write(f"{key}: {created} created, {skipped} already existed")
        self.stdout.write(
            self.style.SUCCESS(f"Done. Test password: {options['password']}")
        )
