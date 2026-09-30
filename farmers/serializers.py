from decimal import Decimal, InvalidOperation

from rest_framework import serializers


class FarmerRegistrationSerializer(serializers.Serializer):
    phonenumber = serializers.CharField(max_length=255)
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True)
    firstname = serializers.CharField(max_length=255)
    lastname = serializers.CharField(max_length=255)
    region = serializers.CharField(max_length=255)
    province = serializers.CharField(max_length=255)
    municipality = serializers.CharField(max_length=255)
    baranggay = serializers.CharField(max_length=255)
    house_number = serializers.CharField(max_length=255)
    street = serializers.CharField(max_length=255)
    postal_code = serializers.CharField(max_length=20)
    farm_size = serializers.CharField()
    farm_region = serializers.CharField(max_length=255)
    farm_province = serializers.CharField(max_length=255)
    farm_municipality = serializers.CharField(max_length=255)
    farm_barangay = serializers.CharField(max_length=255)
    farm_house_number = serializers.CharField(max_length=255)
    farm_street = serializers.CharField(max_length=255)
    farm_postal_code = serializers.CharField(max_length=20)
    role = serializers.CharField(required=False, allow_blank=True)
    middle_name = serializers.CharField(required=False, allow_blank=True)
    midle_name = serializers.CharField(required=False, allow_blank=True)
    middlename = serializers.CharField(required=False, allow_blank=True)
    language = serializers.CharField(required=False, allow_blank=True)
    preferred_language = serializers.CharField(required=False, allow_blank=True)
    onboarding_status = serializers.CharField(required=False, allow_blank=True)
    payment_method = serializers.CharField(required=False, allow_blank=True)
    preferred_payment_method = serializers.CharField(required=False, allow_blank=True)
    municipality_city = serializers.CharField(required=False, allow_blank=True)
    barangay = serializers.CharField(required=False, allow_blank=True)
    country = serializers.CharField(required=False, allow_blank=True)
    farm_country = serializers.CharField(required=False, allow_blank=True)
    documents = serializers.JSONField(required=False, allow_null=True)
    document_types = serializers.JSONField(required=False, allow_null=True)
    document_type = serializers.JSONField(required=False, allow_null=True)
    document_1 = serializers.CharField(required=False, allow_blank=True)
    document_2 = serializers.CharField(required=False, allow_blank=True)
    document_3 = serializers.CharField(required=False, allow_blank=True)
    document_4 = serializers.CharField(required=False, allow_blank=True)

    def validate_farm_size(self, value):
        try:
            farm_size = Decimal(value)
        except InvalidOperation, TypeError, ValueError:
            raise serializers.ValidationError("Enter a valid number.")
        if not farm_size.is_finite():
            raise serializers.ValidationError("Enter a valid number.")
        return farm_size

    def validate(self, attrs):
        if attrs.get("role") != "Farmer":
            raise serializers.ValidationError({"role": ["Must be Farmer."]})

        document_urls = attrs.get("documents")
        if document_urls is None:
            document_urls = [
                attrs.get(f"document_{index}") or "" for index in range(1, 5)
            ]
        if isinstance(document_urls, str):
            document_urls = [document_urls]
        if not isinstance(document_urls, list):
            raise serializers.ValidationError(
                {"documents": ["Provide a list of document URLs."]}
            )
        document_urls = [
            str(url).strip()
            for url in document_urls
            if url is not None and str(url).strip()
        ]
        if len(document_urls) < 4:
            raise serializers.ValidationError(
                {"documents": ["Provide at least four document URLs."]}
            )
        attrs["document_urls"] = document_urls

        document_type_names = attrs.get("document_types")
        if document_type_names is None and attrs.get("document_type") is not None:
            document_type_names = attrs["document_type"]
        if document_type_names is None:
            document_type_names = [
                "Utility Bills",
                "Valid_ID",
                "Owner_Address",
                "Farm_Ownership",
            ]
        if isinstance(document_type_names, str):
            document_type_names = [document_type_names]
        if not isinstance(document_type_names, list):
            raise serializers.ValidationError(
                {"document_types": ["Provide a list of document types."]}
            )
        attrs["document_type_names"] = [
            str(item).strip() for item in document_type_names if str(item).strip()
        ]
        return attrs
