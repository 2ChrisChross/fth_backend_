from rest_framework import serializers


class AddressInputSerializer(serializers.Serializer):
    street_address = serializers.CharField(max_length=255)
    barangay = serializers.CharField(max_length=255)
    municipality_city = serializers.CharField(max_length=255)
    province = serializers.CharField(max_length=255)
    postal_code = serializers.CharField(max_length=20)
    country = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default="Philippines"
    )
    gps_coordinates = serializers.CharField(
        max_length=255, required=False, allow_blank=True
    )


class RegistrationDocumentInputSerializer(serializers.Serializer):
    type = serializers.CharField(max_length=100)
    url = serializers.CharField(max_length=500)

    def validate_type(self, value):
        return value.strip().lower().replace(" ", "_")

    def validate_url(self, value):
        return value.strip()
