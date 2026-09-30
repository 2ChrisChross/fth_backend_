from decimal import Decimal, InvalidOperation

from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings

from shared.models import User

from .tokens import FarmerRefreshToken


class FarmerProfileSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(read_only=True)
    username = serializers.CharField(max_length=150, required=False)
    first_name = serializers.CharField(max_length=255, required=False)
    middle_name = serializers.CharField(
        max_length=255, required=False, allow_blank=True, allow_null=True
    )
    last_name = serializers.CharField(max_length=255, required=False)
    phone_number = serializers.SerializerMethodField()
    farm = serializers.SerializerMethodField()
    new_password = serializers.CharField(
        write_only=True, required=False, trim_whitespace=False
    )

    def get_phone_number(self, user):
        phone = user.phone_numbers.order_by("phone_id").first()
        return phone.mobile_number if phone else None

    def get_farm(self, user):
        farm = user.farms.filter(deleted_at__isnull=True).order_by("farm_id").first()
        if farm is None:
            return None
        address = farm.address
        return {
            "farm_id": farm.farm_id,
            "farm_size_hectares": farm.farm_size_hectares,
            "address": (
                {
                    "street_address": address.street_address,
                    "barangay": address.barangay,
                    "municipality_city": address.municipality_city,
                    "province": address.province,
                    "postal_code": address.postal_code,
                    "country": address.country,
                    "gps_coordinates": address.gps_coordinates,
                }
                if address
                else None
            ),
        }

    def validate_username(self, value):
        if (
            User.objects.filter(username=value)
            .exclude(user_id=self.instance.user_id)
            .exists()
        ):
            raise serializers.ValidationError("This username is already in use.")
        return value

    def validate_new_password(self, value):
        validate_password(value, user=self.instance)
        return value

    def update(self, instance, validated_data):
        new_password = validated_data.pop("new_password", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        update_fields = list(validated_data)
        if new_password:
            instance.password_hash = make_password(new_password)
            update_fields.append("password_hash")
        if update_fields:
            instance.save(update_fields=update_fields)
        return instance


class FarmerLoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True)


class FarmerCodeRequestSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=255)
    first_name = serializers.CharField(max_length=255)
    last_name = serializers.CharField(max_length=255)
    purpose = serializers.ChoiceField(choices=("verification", "recovery"))


class FarmerCodeRecoverySerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=255)
    verification_code = serializers.CharField(max_length=8, write_only=True)


class FarmerTokenRefreshSerializer(TokenRefreshSerializer):
    token_class = FarmerRefreshToken

    def validate(self, attrs):
        from .authentication import get_active_farmer

        try:
            refresh = self.token_class(attrs["refresh"])
            user_id = refresh[api_settings.USER_ID_CLAIM]
        except (KeyError, TokenError, TypeError) as exc:
            raise InvalidToken("Token is invalid.") from exc

        if get_active_farmer(user_id) is None:
            raise InvalidToken("Token is not for an active farmer account.")
        return super().validate(attrs)


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
