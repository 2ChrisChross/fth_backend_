from django.contrib.auth.hashers import make_password
from django.utils.crypto import get_random_string
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from farmers.models import Farm
from shared.models import ElectronicDocument, PhoneNumber, User
from shared.registration import (
    create_address,
    resolve_enum_order_id,
)

from .serializers import FarmerRegistrationSerializer


@api_view(["POST"])
@permission_classes([AllowAny])
def verify_user_code(request):
    data = request.data or {}
    phone_number = str(
        data.get("phone_number") or data.get("phonenumber") or ""
    ).strip()
    verification_code = str(data.get("verification_code") or "").strip()

    if phone_number == "" or verification_code == "":
        return Response(
            {
                "valid": False,
                "error": "phone_number and verification_code are required.",
            },
            status=400,
        )

    users = User.objects.filter(phone_numbers__mobile_number=phone_number).order_by(
        "-user_id"
    )
    if not users.exists():
        return Response({"valid": False}, status=200)

    for user in users:
        if (
            user.verification_code is not None
            and user.verification_code.strip() == verification_code
        ):
            if user.is_verified != 1:
                user.is_verified = 1
                user.save(update_fields=["is_verified"])
            return Response({"valid": True}, status=200)

    return Response({"valid": False}, status=200)


@api_view(["POST"])
@permission_classes([AllowAny])
def register_user(request):
    request_data = request.data if isinstance(request.data, dict) else {}
    serializer = FarmerRegistrationSerializer(data=request_data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=400)

    data = serializer.validated_data
    phone_number = data["phonenumber"]
    username = data["username"]
    password = data["password"]
    first_name = data["firstname"]
    middle_name = (
        data.get("middle_name")
        or data.get("midle_name")
        or data.get("middlename")
        or ""
    )
    last_name = data["lastname"]

    preferred_language = resolve_enum_order_id(
        "language", data.get("language") or data.get("preferred_language")
    )
    role_order_id = resolve_enum_order_id("role", "Farmer")
    onboarding_status_id = resolve_enum_order_id(
        "onboarding_status",
        data.get("onboarding_status") or "Profile_Created",
    )
    payment_method_id = resolve_enum_order_id(
        "payment_method",
        data.get("payment_method") or data.get("preferred_payment_method"),
    )

    farm_region = data["farm_region"]
    farm_province = data["farm_province"]
    farm_municipality = data["farm_municipality"]
    farm_barangay = data["farm_barangay"]
    farm_house_number = data["farm_house_number"]
    farm_street = data["farm_street"]
    farm_postal_code = data["farm_postal_code"]
    farm_size = data["farm_size"]
    document_urls = data["document_urls"]
    document_type_names = data["document_type_names"]

    user_address = create_address(
        {
            "street_address": f"{data.get('house_number', '')} {data.get('street', '')}"
            if data.get("house_number")
            else data.get("street") or "",
            "barangay": data.get("baranggay") or data.get("barangay") or "",
            "municipality_city": data.get("municipality")
            or data.get("municipality_city")
            or "",
            "province": data.get("province") or "",
            "postal_code": data.get("postal_code") or "",
            "country": data.get("country") or "Philippines",
            "gps_coordinates": farm_region or data.get("region") or "",
        },
        "residence",
    )

    user = User.objects.create(
        username=username,
        password_hash=make_password(password),
        personal_address=user_address,
        preferred_language=preferred_language,
        role=role_order_id,
        onboarding_status=onboarding_status_id,
        preferred_payment_method=payment_method_id,
        first_name=first_name,
        middle_name=middle_name or None,
        last_name=last_name,
        verification_code=get_random_string(
            8,
            allowed_chars="ABCDEFGHJKLMNPQRSTUVWXYZ23456789",
        ),
    )

    phone = PhoneNumber.objects.create(
        user=user,
        mobile_number=phone_number,
        phone_type="mobile",
        contact_status=1,
        is_verified=0,
    )

    farm_address = create_address(
        {
            "street_address": f"{farm_house_number} {farm_street}"
            if farm_house_number
            else farm_street,
            "barangay": farm_barangay,
            "municipality_city": farm_municipality,
            "province": farm_province,
            "postal_code": farm_postal_code,
            "country": data.get("farm_country") or "Philippines",
            "gps_coordinates": farm_region,
        },
        "farm",
    )

    farm = Farm.objects.create(
        user=user,
        address=farm_address,
        farm_size_hectares=farm_size,
    )

    document_type_order_ids = []
    for index, url in enumerate(document_urls[:4], start=1):
        file_extension = url.rsplit(".", 1)[-1].lower() if "." in url else ""
        doc_type_name = (
            document_type_names[index - 1]
            if index - 1 < len(document_type_names)
            else "Utility Bills"
        )
        doc_type_order_id = resolve_enum_order_id("document_type", doc_type_name) or 1
        document_type_order_ids.append(doc_type_order_id)
        ElectronicDocument.objects.create(
            user=user,
            doc_title=f"Registration document {index}",
            doc_type=doc_type_order_id,
            file_url=url,
            file_extension=file_extension,
            verification_status=0,
        )

    return Response(
        {
            "message": "Registration successful.",
            "user_id": user.user_id,
            "username": username,
            "phone_id": phone.phone_id,
            "farm_id": farm.farm_id,
            "language_order_id": preferred_language,
            "role_order_id": role_order_id,
            "onboarding_status_order_id": onboarding_status_id,
            "payment_method_order_id": payment_method_id,
            "document_type_order_ids": document_type_order_ids,
            "document_count": len(document_urls[:4]),
        },
        status=201,
    )
