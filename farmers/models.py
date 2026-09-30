from django.db import models


class Farm(models.Model):
    farm_id = models.AutoField(primary_key=True)
    user = models.ForeignKey(
        "api.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="farms",
    )
    address = models.ForeignKey(
        "api.Address",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="farms",
    )
    farm_size_hectares = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "FARMS"


class CropType(models.Model):
    crop_type_id = models.AutoField(primary_key=True)
    crop_name = models.CharField(max_length=255, null=True, blank=True)
    category = models.CharField(max_length=255, null=True, blank=True)
    base_shelf_life_days = models.SmallIntegerField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "CROP_TYPES"


class Crop(models.Model):
    crop_id = models.AutoField(primary_key=True)
    farm = models.ForeignKey(
        "Farm", on_delete=models.SET_NULL, null=True, blank=True, related_name="crops"
    )
    crop_type = models.ForeignKey(
        "CropType",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="crops",
    )
    batch_number = models.CharField(max_length=255, null=True, blank=True)
    available_stock_kg = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    price_per_kg = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    crop_image_url = models.CharField(max_length=500, null=True, blank=True)
    harvested_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "CROPS"


class CropCalendar(models.Model):
    calendar_id = models.AutoField(primary_key=True)
    crop = models.ForeignKey(
        "Crop",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="calendars",
    )
    pickup_address = models.ForeignKey(
        "api.Address",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="crop_calendars",
    )
    calendar_status = models.BigIntegerField(null=True, blank=True)
    land_preparation_start = models.DateField(null=True, blank=True)
    land_preparation_end = models.DateField(null=True, blank=True)
    planting_start = models.DateField(null=True, blank=True)
    planting_end = models.DateField(null=True, blank=True)
    harvesting_start = models.DateField(null=True, blank=True)
    harvesting_end = models.DateField(null=True, blank=True)
    packing_duration_days = models.SmallIntegerField(null=True, blank=True)
    expected_quantity_kg = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    actual_harvested_kg = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    preorder_lead_time_days = models.SmallIntegerField(null=True, blank=True)
    delivery_date = models.DateField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "CROP_CALENDARS"


class MarketplaceListing(models.Model):
    listing_id = models.AutoField(primary_key=True)
    crop = models.ForeignKey(
        "Crop",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="marketplace_listings",
    )
    calendar = models.ForeignKey(
        "CropCalendar",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="marketplace_listings",
    )
    listing_title = models.CharField(max_length=255, null=True, blank=True)
    listing_type = models.BigIntegerField(null=True, blank=True)
    listing_price_per_kg = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    is_active = models.SmallIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "MARKETPLACE_LISTINGS"
