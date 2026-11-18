from django.conf import settings
from django.db import models


class Province(models.Model):
    code = models.CharField(max_length=10, primary_key=True)
    name = models.CharField(max_length=255)

    class Meta:
        db_table = "PROVINCES"


class Municipality(models.Model):
    code = models.CharField(max_length=10, primary_key=True)
    name = models.CharField(max_length=255)
    province = models.ForeignKey(
        Province, on_delete=models.PROTECT, related_name="municipalities"
    )
    independent = models.BooleanField(default=False)

    class Meta:
        db_table = "MUNICIPALITIES"


class Barangay(models.Model):
    code = models.CharField(max_length=10, primary_key=True)
    name = models.CharField(max_length=255)
    municipality = models.ForeignKey(
        Municipality, on_delete=models.PROTECT, related_name="barangays"
    )

    class Meta:
        db_table = "BARANGAYS"


class Address(models.Model):
    address_id = models.AutoField(primary_key=True)
    street_address = models.CharField(max_length=255, null=True, blank=True)
    barangay = models.CharField(max_length=255, null=True, blank=True)
    municipality_city = models.CharField(max_length=255, null=True, blank=True)
    province = models.CharField(max_length=255, null=True, blank=True)
    postal_code = models.CharField(max_length=20, null=True, blank=True)
    country = models.CharField(max_length=255, default="Philippines", blank=True)
    gps_coordinates = models.CharField(max_length=255, null=True, blank=True)
    address_type = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        managed = True
        db_table = "ADDRESSES"


class EnumeratedValue(models.Model):
    enum_id = models.AutoField(primary_key=True)
    enumerated_value_id = models.BigIntegerField(null=True, blank=True)
    type = models.CharField(max_length=100)
    value = models.CharField(max_length=100)
    ordering = models.IntegerField(default=0)

    class Meta:
        managed = True
        db_table = "ENUMERATED_VALUES"
        constraints = [
            models.UniqueConstraint(
                fields=["type", "value"], name="uq_enumerated_value"
            )
        ]


class User(models.Model):
    user_id = models.AutoField(primary_key=True)
    username = models.CharField(max_length=150, null=True, blank=True, unique=True)
    password_hash = models.CharField(max_length=255, null=True, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    personal_address = models.ForeignKey(
        "Address",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="users",
    )
    preferred_language = models.BigIntegerField(null=True, blank=True)
    role = models.BigIntegerField(null=True, blank=True)
    onboarding_status = models.BigIntegerField(null=True, blank=True)
    is_verified = models.SmallIntegerField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    first_name = models.CharField(max_length=255, null=True, blank=True)
    middle_name = models.CharField(max_length=255, null=True, blank=True)
    last_name = models.CharField(max_length=255, null=True, blank=True)
    average_rating = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    preferred_payment_method = models.BigIntegerField(null=True, blank=True)
    total_earnings = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    verification_code = models.CharField(max_length=128, null=True, blank=True)
    verification_code_purpose = models.CharField(max_length=20, null=True, blank=True)
    verification_code_expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "USERS"

    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False


class AccountCodeRequest(models.Model):
    class Kind(models.TextChoices):
        BUSINESSES = "businesses", "Bulk buyer"
        LOGISTICS = "logistics", "Logistics"

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
        User, on_delete=models.CASCADE, related_name="account_code_requests"
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING_REVIEW
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_account_code_requests",
    )
    review_reason = models.TextField(blank=True)
    code_issued_at = models.DateTimeField(null=True, blank=True)
    code_expires_at = models.DateTimeField(null=True, blank=True)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="issued_account_codes",
    )
    mailed_at = models.DateTimeField(null=True, blank=True)
    mailed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mailed_account_codes",
    )

    class Meta:
        db_table = "ACCOUNT_CODE_REQUESTS"
        ordering = ["requested_at", "request_id"]


class FarmerMessage(models.Model):
    class SenderKind(models.TextChoices):
        BUYER = "businesses", "Bulk buyer"
        LOGISTICS = "logistics", "Logistics"

    recipient = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="farmer_messages"
    )
    sender = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="sent_farmer_messages"
    )
    sender_kind = models.CharField(max_length=20, choices=SenderKind.choices)
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "FARMER_MESSAGES"
        ordering = ["-created_at", "-id"]


class PhoneNumber(models.Model):
    phone_id = models.AutoField(primary_key=True)
    user = models.ForeignKey(
        "User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="phone_numbers",
    )
    mobile_number = models.CharField(max_length=255, null=True, blank=True)
    phone_type = models.CharField(max_length=255, null=True, blank=True)
    contact_status = models.BigIntegerField(null=True, blank=True)
    is_verified = models.BigIntegerField(null=True, blank=True)
    start_date = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)
    last_tested_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "PHONE_NUMBERS"


class EmailAddress(models.Model):
    email_id = models.AutoField(primary_key=True)
    user = models.ForeignKey(
        "User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="email_addresses",
    )
    email_address = models.CharField(max_length=255, null=True, blank=True)
    email_type = models.BigIntegerField(null=True, blank=True)
    is_verified = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "EMAIL_ADDRESSES"


class ElectronicDocument(models.Model):
    doc_id = models.AutoField(primary_key=True)
    user = models.ForeignKey(
        "User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="electronic_documents",
    )
    vehicle = models.ForeignKey(
        "logistics.Vehicle",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents",
    )
    doc_title = models.CharField(max_length=255, null=True, blank=True)
    doc_type = models.BigIntegerField(null=True, blank=True)
    file_url = models.CharField(max_length=500, null=True, blank=True)
    file_extension = models.CharField(max_length=50, null=True, blank=True)
    verification_status = models.BigIntegerField(null=True, blank=True)
    rejection_reason = models.TextField(null=True, blank=True)
    expiration_date = models.DateField(null=True, blank=True)
    date_time_deleted = models.DateTimeField(null=True, blank=True)
    date_time_uploaded = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "ELECTRONIC_DOCUMENTS"


class AuditLog(models.Model):
    log_id = models.AutoField(primary_key=True)
    user = models.ForeignKey(
        "User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    staff_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="staff_audit_logs",
    )
    action_type = models.CharField(max_length=255, null=True, blank=True)
    target_table = models.CharField(max_length=255, null=True, blank=True)
    target_id = models.IntegerField(null=True, blank=True)
    old_values = models.TextField(null=True, blank=True)
    new_values = models.TextField(null=True, blank=True)
    ip_address = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "AUDIT_LOGS"


class Order(models.Model):
    order_id = models.AutoField(primary_key=True)
    buyer = models.ForeignKey(
        "User", on_delete=models.SET_NULL, null=True, blank=True, related_name="orders"
    )
    order_type = models.BigIntegerField(null=True, blank=True)
    total_payment = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    delivery_date = models.DateField(null=True, blank=True)
    order_status = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "ORDERS"


class OrderItem(models.Model):
    order_item_id = models.AutoField(primary_key=True)
    order = models.ForeignKey(
        "Order", on_delete=models.SET_NULL, null=True, blank=True, related_name="items"
    )
    calendar = models.ForeignKey(
        "farmers.CropCalendar",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="order_items",
    )
    quantity_ordered_kg = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    price_at_purchase = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )

    class Meta:
        managed = True
        db_table = "ORDER_ITEMS"


class OrderStatusHistory(models.Model):
    history_id = models.AutoField(primary_key=True)
    order = models.ForeignKey(
        "Order",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="status_history",
    )
    status_changed_to = models.BigIntegerField(null=True, blank=True)
    updated_by_role = models.CharField(max_length=255, null=True, blank=True)
    changed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "ORDER_STATUS_HISTORY"
