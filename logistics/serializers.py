from rest_framework import serializers

from shared.serializers import (
    AddressInputSerializer,
    RegistrationDocumentInputSerializer,
)


class StrictBooleanField(serializers.BooleanField):
    default_error_messages = {
        "invalid": "Must be a JSON boolean.",
    }

    def to_internal_value(self, data):
        if not isinstance(data, bool):
            self.fail("invalid")
        return data


class LogisticsVehicleInputSerializer(serializers.Serializer):
    model = serializers.CharField(max_length=255)
    plate_number = serializers.CharField(max_length=255)
    max_weight_capacity_kg = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=0
    )
    max_volume_capacity_m3 = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=0
    )
    body_type = serializers.CharField(max_length=255)
    is_refrigerated = StrictBooleanField()


class LogisticsRegistrationSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True)
    first_name = serializers.CharField(max_length=255)
    middle_name = serializers.CharField(
        max_length=255, required=False, allow_blank=True
    )
    last_name = serializers.CharField(max_length=255)
    date_of_birth = serializers.DateField()
    phone_number = serializers.CharField(max_length=255)
    company_name = serializers.CharField(max_length=255)
    company_phone = serializers.CharField(max_length=255)
    company_email = serializers.EmailField(max_length=255)
    role = serializers.CharField(required=False, allow_blank=True)
    personal_address = AddressInputSerializer()
    company_address = AddressInputSerializer()
    vehicle = LogisticsVehicleInputSerializer()
    documents = RegistrationDocumentInputSerializer(many=True)

    def validate_role(self, value):
        if value != "Logistics_Manager":
            raise serializers.ValidationError("Must be Logistics_Manager.")
        return value

    def validate_documents(self, documents):
        required_types = {
            "ltfrb_franchise_for_trucking",
            "vehicle_photo",
            "vehicle_driver_license",
            "national_id",
            "official_receipt",
            "certificate_of_registration",
            "nbi_clearance",
        }
        supplied_types = {document["type"] for document in documents}
        if not required_types.issubset(supplied_types):
            raise serializers.ValidationError(
                "Provide all required document types and URLs."
            )
        return documents

    def validate(self, attrs):
        if attrs.get("role") != "Logistics_Manager":
            raise serializers.ValidationError({"role": ["Must be Logistics_Manager."]})
        return attrs
