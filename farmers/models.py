from django.conf import settings
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


class FarmerCodeRequest(models.Model):
    class Purpose(models.TextChoices):
        VERIFICATION = "verification", "Account verification"
        RECOVERY = "recovery", "Account recovery"

    class Status(models.TextChoices):
        PENDING_REVIEW = "pending_review", "Pending review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        CODE_ISSUED = "code_issued", "Code issued"
        MAILED = "mailed", "Mailed"
        COMPLETED = "completed", "Completed"
        EXPIRED = "expired", "Expired"

    request_id = models.AutoField(primary_key=True)
    user = models.ForeignKey(
        "api.User",
        on_delete=models.CASCADE,
        related_name="farmer_code_requests",
    )
    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING_REVIEW,
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_farmer_code_requests",
    )
    review_reason = models.TextField(blank=True)
    code_issued_at = models.DateTimeField(null=True, blank=True)
    code_expires_at = models.DateTimeField(null=True, blank=True)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="issued_farmer_codes",
    )
    mailed_at = models.DateTimeField(null=True, blank=True)
    mailed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mailed_farmer_codes",
    )

    class Meta:
        managed = True
        db_table = "FARMER_CODE_REQUESTS"
        ordering = ["requested_at"]
        permissions = [
            (
                "view_farmer_applications",
                "Can view farmer applications and documents",
            ),
            ("view_farmer_code_requests", "Can view farmer code requests"),
            (
                "review_farmer_code_requests",
                "Can approve or reject farmer code requests",
            ),
            (
                "issue_farmer_codes",
                "Can issue farmer verification or recovery codes",
            ),
            ("manually_verify_farmer", "Can manually verify farmer accounts"),
            ("view_dashboard_reports", "Can view dashboard reports"),
            ("view_dashboard_audit_logs", "Can view dashboard audit logs"),
            ("manage_dashboard_records", "Can create and edit dashboard records"),
        ]


class FarmerRevokedRefreshToken(models.Model):
    token_id = models.AutoField(primary_key=True)
    user = models.ForeignKey(
        "api.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="revoked_refresh_tokens",
    )
    jti = models.CharField(max_length=255, unique=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = True
        db_table = "FARMER_REVOKED_REFRESH_TOKENS"


class FarmerAdminAuditEvent(models.Model):
    class Action(models.TextChoices):
        APPROVED = "approved", "Approved request"
        REJECTED = "rejected", "Rejected request"
        CODE_ISSUED = "code_issued", "Code issued"
        CODE_MAILED = "code_mailed", "Code mailed"
        MANUALLY_VERIFIED = "manually_verified", "Manually verified"

    event_id = models.AutoField(primary_key=True)
    user = models.ForeignKey(
        "api.User",
        on_delete=models.CASCADE,
        related_name="farmer_admin_events",
    )
    code_request = models.ForeignKey(
        FarmerCodeRequest,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="admin_events",
    )
    staff_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="farmer_admin_events",
    )
    action = models.CharField(max_length=30, choices=Action.choices)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = True
        db_table = "FARMER_ADMIN_AUDIT_EVENTS"
        ordering = ["-created_at"]
