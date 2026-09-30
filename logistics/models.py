from django.db import models


class LogisticsCompany(models.Model):
    logistics_business_id = models.AutoField(primary_key=True)
    user = models.OneToOneField(
        "api.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="logistics_business",
    )
    address = models.ForeignKey(
        "api.Address",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="logistics_businesses",
    )
    business_name = models.CharField(max_length=255)
    contact_phone = models.CharField(max_length=255)
    contact_email = models.CharField(max_length=255)
    is_verified = models.SmallIntegerField(default=0)
    date_time_created = models.DateTimeField(null=True, blank=True)
    date_time_deleted = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "LOGISTICS_COMPANIES"
        verbose_name = "logistics company"
        verbose_name_plural = "logistics companies"


class Vehicle(models.Model):
    vehicle_id = models.AutoField(primary_key=True)
    user = models.ForeignKey(
        "api.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="vehicles",
    )
    logistics_business = models.ForeignKey(
        "LogisticsCompany",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="vehicles",
    )
    truck_model = models.CharField(max_length=255, null=True, blank=True)
    plate_number = models.CharField(max_length=255, null=True, blank=True)
    max_weight_capacity_kg = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    max_volume_capacity_m3 = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    body_type = models.BigIntegerField(null=True, blank=True)
    is_refrigerated = models.SmallIntegerField(default=0)
    is_air_conditioned = models.SmallIntegerField(null=True, blank=True)
    fuel_consumption_liters_per_100km = models.SmallIntegerField(null=True, blank=True)
    total_distance_meters = models.BigIntegerField(null=True, blank=True)
    current_health_status = models.BigIntegerField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "VEHICLES"


class DeliveryTrip(models.Model):
    trip_id = models.AutoField(primary_key=True)
    driver = models.ForeignKey(
        "api.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="delivery_trips",
    )
    vehicle = models.ForeignKey(
        "Vehicle",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="delivery_trips",
    )
    weight_utilization_pct = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    volume_utilization_pct = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    eta = models.DateTimeField(null=True, blank=True)
    current_delivery_target = models.CharField(max_length=255, null=True, blank=True)
    trip_status = models.BigIntegerField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "DELIVERY_TRIPS"


class TripManifest(models.Model):
    manifest_id = models.AutoField(primary_key=True)
    trip = models.ForeignKey(
        "DeliveryTrip",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="manifests",
    )
    order = models.ForeignKey(
        "api.Order",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="trip_manifests",
    )
    dropoff_sequence = models.SmallIntegerField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "TRIP_MANIFESTS"


class VehicleStatusHistory(models.Model):
    history_id = models.AutoField(primary_key=True)
    vehicle = models.ForeignKey(
        "Vehicle",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="status_history",
    )
    trip = models.ForeignKey(
        "DeliveryTrip",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="vehicle_status_history",
    )
    status_changed_to = models.BigIntegerField(null=True, blank=True)
    issue_type = models.CharField(max_length=255, null=True, blank=True)
    component_location = models.CharField(max_length=255, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    photo_url = models.CharField(max_length=500, null=True, blank=True)
    start_date = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "VEHICLE_STATUS_HISTORY"
