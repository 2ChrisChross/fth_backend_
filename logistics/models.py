from django.db import models


class LogisticsBusiness(models.Model):
    logistics_business_id = models.AutoField(primary_key=True)
    user = models.OneToOneField('api.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='logistics_business')
    address = models.ForeignKey('api.Address', on_delete=models.SET_NULL, null=True, blank=True, related_name='logistics_businesses')
    business_name = models.CharField(max_length=255)
    contact_phone = models.CharField(max_length=255)
    contact_email = models.CharField(max_length=255)
    is_verified = models.SmallIntegerField(default=0)
    date_time_created = models.DateTimeField(null=True, blank=True)
    date_time_deleted = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'LOGISTICS_BUSINESSES'


class Vehicle(models.Model):
    vehicle_id = models.AutoField(primary_key=True)
    user = models.ForeignKey('api.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='vehicles')
    logistics_business = models.ForeignKey('LogisticsBusiness', on_delete=models.SET_NULL, null=True, blank=True, related_name='vehicles')
    truck_model = models.CharField(max_length=255, null=True, blank=True)
    plate_number = models.CharField(max_length=255, null=True, blank=True)
    max_weight_capacity_kg = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    max_volume_capacity_m3 = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    body_type = models.BigIntegerField(null=True, blank=True)
    is_refrigerated = models.SmallIntegerField(default=0)
    is_air_conditioned = models.SmallIntegerField(null=True, blank=True)
    fuel_consumption_liters_per_100km = models.SmallIntegerField(null=True, blank=True)
    total_distance_meters = models.BigIntegerField(null=True, blank=True)
    current_health_status = models.BigIntegerField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'VEHICLES'