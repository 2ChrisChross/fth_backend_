from django.db import models


class Address(models.Model):
    address_id = models.AutoField(primary_key=True)
    street_address = models.CharField(max_length=255, null=True, blank=True)
    barangay = models.CharField(max_length=255, null=True, blank=True)
    municipality_city = models.CharField(max_length=255, null=True, blank=True)
    province = models.CharField(max_length=255, null=True, blank=True)
    country = models.CharField(max_length=255, default='Philippines', blank=True)
    gps_coordinates = models.CharField(max_length=255, null=True, blank=True)
    address_type = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'ADDRESSES'


class EnumeratedValue(models.Model):
    enum_id = models.AutoField(primary_key=True)
    enumerated_value_id = models.BigIntegerField(null=True, blank=True)
    type = models.CharField(max_length=100)
    value = models.CharField(max_length=100)
    ordering = models.IntegerField(default=0)

    class Meta:
        managed = False
        db_table = 'ENUMERATED_VALUES'
        constraints = [
            models.UniqueConstraint(fields=['type', 'value'], name='uq_enumerated_value')
        ]


class User(models.Model):
    user_id = models.AutoField(primary_key=True)
    password_hash = models.CharField(max_length=255, null=True, blank=True)
    preferred_language = models.BigIntegerField(null=True, blank=True)
    role = models.BigIntegerField(null=True, blank=True)
    onboarding_status = models.BigIntegerField(null=True, blank=True)
    is_verified = models.SmallIntegerField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    first_name = models.CharField(max_length=255, null=True, blank=True)
    middle_name = models.CharField(max_length=255, null=True, blank=True)
    last_name = models.CharField(max_length=255, null=True, blank=True)
    average_rating = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    preferred_payment_method = models.BigIntegerField(null=True, blank=True)
    total_earnings = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    verification_code = models.CharField(max_length=8, null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'USERS'


class PhoneNumber(models.Model):
    phone_id = models.AutoField(primary_key=True)
    user = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, related_name='phone_numbers')
    mobile_number = models.CharField(max_length=255, null=True, blank=True)
    phone_type = models.CharField(max_length=255, null=True, blank=True)
    contact_status = models.BigIntegerField(null=True, blank=True)
    is_verified = models.BigIntegerField(null=True, blank=True)
    start_date = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)
    last_tested_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'PHONE_NUMBERS'


class EmailAddress(models.Model):
    email_id = models.AutoField(primary_key=True)
    user = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, related_name='email_addresses')
    email_address = models.CharField(max_length=255, null=True, blank=True)
    email_type = models.BigIntegerField(null=True, blank=True)
    is_verified = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'EMAIL_ADDRESSES'


class Business(models.Model):
    business_id = models.AutoField(primary_key=True)
    user = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, related_name='businesses')
    business_name = models.CharField(max_length=255, null=True, blank=True)
    business_type = models.BigIntegerField(null=True, blank=True)
    registration_number = models.CharField(max_length=255, null=True, blank=True)
    is_verified = models.SmallIntegerField(null=True, blank=True)
    date_time_created = models.DateTimeField(null=True, blank=True)
    date_time_deleted = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'BUSINESSES'


class ElectronicDocument(models.Model):
    doc_id = models.AutoField(primary_key=True)
    user = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, related_name='electronic_documents')
    vehicle = models.ForeignKey('Vehicle', on_delete=models.SET_NULL, null=True, blank=True, related_name='documents')
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
        managed = False
        db_table = 'ELECTRONIC_DOCUMENTS'


class AuditLog(models.Model):
    log_id = models.AutoField(primary_key=True)
    user = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_logs')
    action_type = models.CharField(max_length=255, null=True, blank=True)
    target_table = models.CharField(max_length=255, null=True, blank=True)
    target_id = models.IntegerField(null=True, blank=True)
    old_values = models.TextField(null=True, blank=True)
    new_values = models.TextField(null=True, blank=True)
    ip_address = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'AUDIT_LOGS'


class Farm(models.Model):
    farm_id = models.AutoField(primary_key=True)
    user = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, related_name='farms')
    address = models.ForeignKey('Address', on_delete=models.SET_NULL, null=True, blank=True, related_name='farms')
    farm_size_hectares = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'FARMS'


class Vehicle(models.Model):
    vehicle_id = models.AutoField(primary_key=True)
    user = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, related_name='vehicles')
    truck_model = models.CharField(max_length=255, null=True, blank=True)
    plate_number = models.CharField(max_length=255, null=True, blank=True)
    max_weight_capacity_kg = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    max_volume_capacity_m3 = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    body_type = models.BigIntegerField(null=True, blank=True)
    is_air_conditioned = models.SmallIntegerField(null=True, blank=True)
    fuel_consumption_liters_per_100km = models.SmallIntegerField(null=True, blank=True)
    total_distance_meters = models.BigIntegerField(null=True, blank=True)
    current_health_status = models.BigIntegerField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'VEHICLES'


class CropType(models.Model):
    crop_type_id = models.AutoField(primary_key=True)
    crop_name = models.CharField(max_length=255, null=True, blank=True)
    category = models.CharField(max_length=255, null=True, blank=True)
    base_shelf_life_days = models.SmallIntegerField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'CROP_TYPES'


class Crop(models.Model):
    crop_id = models.AutoField(primary_key=True)
    farm = models.ForeignKey('Farm', on_delete=models.SET_NULL, null=True, blank=True, related_name='crops')
    crop_type = models.ForeignKey('CropType', on_delete=models.SET_NULL, null=True, blank=True, related_name='crops')
    batch_number = models.CharField(max_length=255, null=True, blank=True)
    available_stock_kg = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    price_per_kg = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    crop_image_url = models.CharField(max_length=500, null=True, blank=True)
    harvested_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'CROPS'


class MarketplaceListing(models.Model):
    listing_id = models.AutoField(primary_key=True)
    crop = models.ForeignKey('Crop', on_delete=models.SET_NULL, null=True, blank=True, related_name='marketplace_listings')
    calendar = models.ForeignKey('CropCalendar', on_delete=models.SET_NULL, null=True, blank=True, related_name='marketplace_listings')
    listing_title = models.CharField(max_length=255, null=True, blank=True)
    listing_type = models.BigIntegerField(null=True, blank=True)
    listing_price_per_kg = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    is_active = models.SmallIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'MARKETPLACE_LISTINGS'


class CropCalendar(models.Model):
    calendar_id = models.AutoField(primary_key=True)
    crop = models.ForeignKey('Crop', on_delete=models.SET_NULL, null=True, blank=True, related_name='calendars')
    pickup_address = models.ForeignKey('Address', on_delete=models.SET_NULL, null=True, blank=True, related_name='crop_calendars')
    calendar_status = models.BigIntegerField(null=True, blank=True)
    land_preparation_start = models.DateField(null=True, blank=True)
    land_preparation_end = models.DateField(null=True, blank=True)
    planting_start = models.DateField(null=True, blank=True)
    planting_end = models.DateField(null=True, blank=True)
    harvesting_start = models.DateField(null=True, blank=True)
    harvesting_end = models.DateField(null=True, blank=True)
    packing_duration_days = models.SmallIntegerField(null=True, blank=True)
    expected_quantity_kg = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    actual_harvested_kg = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    preorder_lead_time_days = models.SmallIntegerField(null=True, blank=True)
    delivery_date = models.DateField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'CROP_CALENDARS'


class Order(models.Model):
    order_id = models.AutoField(primary_key=True)
    buyer = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, related_name='orders')
    order_type = models.BigIntegerField(null=True, blank=True)
    total_payment = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    delivery_date = models.DateField(null=True, blank=True)
    order_status = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'ORDERS'


class OrderItem(models.Model):
    order_item_id = models.AutoField(primary_key=True)
    order = models.ForeignKey('Order', on_delete=models.SET_NULL, null=True, blank=True, related_name='items')
    calendar = models.ForeignKey('CropCalendar', on_delete=models.SET_NULL, null=True, blank=True, related_name='order_items')
    quantity_ordered_kg = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    price_at_purchase = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'ORDER_ITEMS'


class OrderStatusHistory(models.Model):
    history_id = models.AutoField(primary_key=True)
    order = models.ForeignKey('Order', on_delete=models.SET_NULL, null=True, blank=True, related_name='status_history')
    status_changed_to = models.BigIntegerField(null=True, blank=True)
    updated_by_role = models.CharField(max_length=255, null=True, blank=True)
    changed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'ORDER_STATUS_HISTORY'


class DeliveryTrip(models.Model):
    trip_id = models.AutoField(primary_key=True)
    driver = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, related_name='delivery_trips')
    vehicle = models.ForeignKey('Vehicle', on_delete=models.SET_NULL, null=True, blank=True, related_name='delivery_trips')
    weight_utilization_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    volume_utilization_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    eta = models.DateTimeField(null=True, blank=True)
    current_delivery_target = models.CharField(max_length=255, null=True, blank=True)
    trip_status = models.BigIntegerField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'DELIVERY_TRIPS'


class TripManifest(models.Model):
    manifest_id = models.AutoField(primary_key=True)
    trip = models.ForeignKey('DeliveryTrip', on_delete=models.SET_NULL, null=True, blank=True, related_name='manifests')
    order = models.ForeignKey('Order', on_delete=models.SET_NULL, null=True, blank=True, related_name='trip_manifests')
    dropoff_sequence = models.SmallIntegerField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'TRIP_MANIFESTS'


class VehicleStatusHistory(models.Model):
    history_id = models.AutoField(primary_key=True)
    vehicle = models.ForeignKey('Vehicle', on_delete=models.SET_NULL, null=True, blank=True, related_name='status_history')
    trip = models.ForeignKey('DeliveryTrip', on_delete=models.SET_NULL, null=True, blank=True, related_name='vehicle_status_history')
    status_changed_to = models.BigIntegerField(null=True, blank=True)
    issue_type = models.CharField(max_length=255, null=True, blank=True)
    component_location = models.CharField(max_length=255, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    photo_url = models.CharField(max_length=500, null=True, blank=True)
    start_date = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'VEHICLE_STATUS_HISTORY'