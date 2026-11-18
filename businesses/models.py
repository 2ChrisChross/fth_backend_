from django.db import models


class BulkBuyer(models.Model):
    business_id = models.AutoField(primary_key=True)
    user = models.ForeignKey(
        "api.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="businesses",
    )
    address = models.ForeignKey(
        "api.Address",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="businesses",
    )
    business_name = models.CharField(max_length=255, null=True, blank=True)
    business_type = models.BigIntegerField(null=True, blank=True)
    registration_number = models.CharField(max_length=255, null=True, blank=True)
    is_verified = models.SmallIntegerField(null=True, blank=True)
    date_time_created = models.DateTimeField(null=True, blank=True)
    date_time_deleted = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "BULK_BUYERS"
        verbose_name = "bulk buyer"
        verbose_name_plural = "bulk buyers"


class OrderReservation(models.Model):
    class Status(models.TextChoices):
        RESERVED = "reserved", "Reserved"
        CANCELLED = "cancelled", "Cancelled"
        DELIVERED = "delivered", "Delivered"

    order = models.OneToOneField(
        "api.Order", on_delete=models.CASCADE, related_name="reservation"
    )
    crop = models.ForeignKey("farmers.Crop", on_delete=models.PROTECT)
    pickup_address = models.ForeignKey(
        "api.Address", on_delete=models.PROTECT, null=True, related_name="+"
    )
    destination_address = models.ForeignKey(
        "api.Address", on_delete=models.PROTECT, null=True, related_name="+"
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.RESERVED
    )
