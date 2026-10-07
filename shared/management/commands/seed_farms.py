from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from farmers.models import Crop, CropCalendar, CropType, Farm, MarketplaceListing
from dashboard.services import crop_calendar_stage, stage_has_stock
from shared.models import Address, EnumeratedValue, User

from .seed_users import LOCAL_HOSTS

SEED_STREET_PREFIX = "Seed Farm"
FARM_SIZES = ("1.50", "3.25", "5.00", "7.75", "10.00")
BARANGAYS = ("Toril", "Calinan", "Marilog", "Baguio District", "Paquibato")
CROP_PRICES = ("45.00", "60.00", "85.50", "120.00")
CROP_STOCKS = ("150.00", "320.50", "500.00", "850.00")


def _farmer_role_id():
    return (
        EnumeratedValue.objects.filter(type__iexact="role", value__iexact="Farmer")
        .values_list("ordering", flat=True)
        .first()
    )


def _seeded_farms(user):
    return Farm.objects.filter(
        user=user, address__street_address__startswith=SEED_STREET_PREFIX
    )


# Days from today that land preparation starts; spreads crops across every stage.
CALENDAR_START_OFFSETS = (-5, -20, -45, -65, -73, 10)


def _status_order(stage):
    """Stored calendar_status for a stage name, or None if not in the enum table."""
    return (
        EnumeratedValue.objects.filter(
            type__iexact="calendar_status",
            value__iexact=stage.replace(" ", "_"),
        )
        .values_list("ordering", flat=True)
        .first()
    )


def _add_calendar(crop, index):
    start = timezone.localdate() + timedelta(days=CALENDAR_START_OFFSETS[index % len(CALENDAR_START_OFFSETS)])
    day = timedelta(days=1)
    prep_end = start + 13 * day
    plant_start = prep_end + day
    plant_end = plant_start + 13 * day
    harvest_start = plant_end + 31 * day
    harvest_end = harvest_start + 13 * day
    calendar = CropCalendar(
        crop=crop,
        land_preparation_start=start,
        land_preparation_end=prep_end,
        planting_start=plant_start,
        planting_end=plant_end,
        harvesting_start=harvest_start,
        harvesting_end=harvest_end,
        packing_duration_days=3,
        expected_quantity_kg=crop.available_stock_kg,
        delivery_date=harvest_end + 4 * day,
    )
    calendar.calendar_status = _status_order(crop_calendar_stage(calendar))
    calendar.save()
    if not stage_has_stock(crop_calendar_stage(calendar)):
        crop.available_stock_kg = None
        crop.save(update_fields=["available_stock_kg"])
    return calendar


def _backfill_calendars():
    seeded = Crop.objects.filter(batch_number__startswith="SEED-")
    count = 0
    for crop in list(seeded.filter(calendars__isnull=True).order_by("crop_id")):
        _add_calendar(crop, count)
        count += 1
    for calendar in CropCalendar.objects.filter(
        crop__in=seeded, calendar_status__isnull=True
    ):
        calendar.calendar_status = _status_order(crop_calendar_stage(calendar))
        if calendar.calendar_status is not None:
            calendar.save(update_fields=["calendar_status"])
            count += 1
    return count


@transaction.atomic
def delete_seeded_farms():
    """Delete only the extra farms created by this command, with their crops."""
    farms = Farm.objects.filter(
        user__username__startswith="test_farmer",
        address__street_address__startswith=SEED_STREET_PREFIX,
    )
    address_ids = list(farms.values_list("address", flat=True))
    crops = Crop.objects.filter(farm__in=farms)
    calendars = CropCalendar.objects.filter(crop__in=crops)
    MarketplaceListing.objects.filter(
        Q(crop__in=crops) | Q(calendar__in=calendars)
    ).delete()
    calendars.delete()
    crops.delete()
    count = farms.count()
    farms.delete()
    Address.objects.filter(pk__in=address_ids).delete()
    return count


def _create_farm(user, number, crop_types, crops_per_farm):
    address = Address.objects.create(
        street_address=f"{SEED_STREET_PREFIX} {number} Road",
        barangay=BARANGAYS[(number - 1) % len(BARANGAYS)],
        municipality_city="Davao City",
        province="Davao del Sur",
        postal_code="8000",
        country="Philippines",
        gps_coordinates="Region XI",
        address_type="farm",
    )
    farm = Farm.objects.create(
        user=user,
        address=address,
        farm_size_hectares=Decimal(FARM_SIZES[(number - 1) % len(FARM_SIZES)]),
    )

    now = timezone.now()
    for offset in range(crops_per_farm):
        crop_type = crop_types[(farm.farm_id + offset) % len(crop_types)]
        crop = Crop.objects.create(
            farm=farm,
            crop_type=crop_type,
            batch_number=f"SEED-{farm.farm_id}-{offset + 1}",
            available_stock_kg=Decimal(CROP_STOCKS[(number + offset) % len(CROP_STOCKS)]),
            price_per_kg=Decimal(CROP_PRICES[(number + offset) % len(CROP_PRICES)]),
            harvested_at=now - timedelta(days=2 + offset),
            expires_at=now
            + timedelta(days=max(crop_type.base_shelf_life_days or 7, 1)),
        )
        _add_calendar(crop, farm.farm_id + offset)
    return farm


class Command(BaseCommand):
    help = (
        "Add extra farms (with crops) to the seeded test_farmer* users. "
        "Run seed_users first. Local databases only."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--farms",
            type=int,
            default=2,
            help="Extra farms each seeded farmer should have (default 2).",
        )
        parser.add_argument(
            "--crops",
            type=int,
            default=2,
            help="Crops to add to each new farm (default 2).",
        )

        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete the previously seeded extra farms, then seed again.",
        )
        parser.add_argument(
            "--reset-only",
            action="store_true",
            help="Delete the previously seeded extra farms and stop.",
        )

    def handle(self, *args, **options):
        host = settings.DATABASES["default"].get("HOST", "")
        if host not in LOCAL_HOSTS:
            raise CommandError(
                f"Refusing to seed non-local database host '{host}'. "
                "Unset DATABASE_URL and use your local PostgreSQL."
            )
        if options["farms"] < 0 or options["crops"] < 0:
            raise CommandError("--farms and --crops cannot be negative.")

        if options["reset"] or options["reset_only"]:
            removed = delete_seeded_farms()
            self.stdout.write(f"Removed {removed} seeded farms.")
            if options["reset_only"]:
                return

        role_id = _farmer_role_id()
        farmers = list(
            User.objects.filter(
                username__startswith="test_farmer", role=role_id
            ).order_by("user_id")
            if role_id is not None
            else []
        )
        if not farmers:
            raise CommandError(
                "No seeded farmers found. Load the enum seed SQL and run "
                "'manage.py seed_users' first."
            )

        crop_types = list(CropType.objects.order_by("crop_type_id"))
        if options["crops"] and not crop_types:
            raise CommandError(
                "No crop types found. Run database_migrations/"
                "20260930_local_dev_seed.sql first, or pass --crops 0."
            )

        created = existing = 0
        with transaction.atomic():
            for user in farmers:
                have = _seeded_farms(user).count()
                existing += min(have, options["farms"])
                for number in range(have + 1, options["farms"] + 1):
                    _create_farm(user, number, crop_types, options["crops"])
                    created += 1
            backfilled = _backfill_calendars()

        self.stdout.write(
            self.style.SUCCESS(
                f"farms: {created} created, {existing} already existed "
                f"across {len(farmers)} farmers; "
                f"{backfilled} crop calendars added"
            )
        )
