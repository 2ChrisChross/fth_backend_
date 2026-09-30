from rest_framework import serializers

from shared.serializers import (
    AddressInputSerializer,
    RegistrationDocumentInputSerializer,
)


class BulkBuyerRegistrationSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True)
    first_name = serializers.CharField(max_length=255)
    middle_name = serializers.CharField(
        max_length=255, required=False, allow_blank=True
    )
    last_name = serializers.CharField(max_length=255)
    date_of_birth = serializers.DateField()
    phone_number = serializers.CharField(max_length=255)
    business_name = serializers.CharField(max_length=255)
    role = serializers.CharField(required=False, allow_blank=True)
    personal_address = AddressInputSerializer()
    business_address = AddressInputSerializer()
    documents = RegistrationDocumentInputSerializer(many=True)

    def validate_role(self, value):
        if value != "Bulk_Buyer":
            raise serializers.ValidationError("Must be Bulk_Buyer.")
        return value

    def validate_documents(self, documents):
        required_types = {
            "birth_certificate",
            "business_utility_bill",
            "business_permit",
            "national_id",
        }
        supplied_types = {document["type"] for document in documents}
        if not required_types.issubset(supplied_types):
            raise serializers.ValidationError(
                "Provide all required document types and URLs."
            )
        return documents

    def validate(self, attrs):
        if attrs.get("role") != "Bulk_Buyer":
            raise serializers.ValidationError({"role": ["Must be Bulk_Buyer."]})
        return attrs
