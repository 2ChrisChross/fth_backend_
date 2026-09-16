from decimal import Decimal, InvalidOperation

from django.contrib.auth.hashers import make_password
from django.utils.crypto import get_random_string
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import Address, ElectronicDocument, Farm, PhoneNumber, User


def index(request):
    return Response({"message": "FTH API is running."})


@api_view(["POST"])
@permission_classes([AllowAny])
def register_user(request):
    data = request.data or {}

    required_fields = [
        "phonenumber",
        "username",
        "password",
        "firstname",
        "lastname",
        "region",
        "province",
        "municipality",
        "baranggay",
        "house_number",
        "street",
        "postal_code",
        "farm_size",
    ]

    missing_fields = [
        field for field in required_fields
        if field not in data or str(data.get(field, "")).strip() == ""
    ]
    if missing_fields:
        return Response(
            {"error": "Missing required fields", "missing_fields": missing_fields},
            status=400,
        )

    phone_number = str(data.get("phonenumber", "")).strip()
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    first_name = str(data.get("firstname", "")).strip()
    middle_name = str(data.get("middle_name") or data.get("midle_name") or data.get("middlename") or "").strip()
    last_name = str(data.get("lastname", "")).strip()

    farm_region = str(data.get("farm_region") or data.get("region", "")).strip()
    farm_province = str(data.get("farm_province") or data.get("province", "")).strip()
    farm_municipality = str(data.get("farm_municipality") or data.get("municipality", "")).strip()
    farm_barangay = str(data.get("farm_barangay") or data.get("baranggay", "")).strip()
    farm_house_number = str(data.get("farm_house_number") or data.get("house_number", "")).strip()
    farm_street = str(data.get("farm_street") or data.get("street", "")).strip()
    farm_postal_code = str(data.get("farm_postal_code") or data.get("postal_code", "")).strip()

    try:
        farm_size = Decimal(str(data.get("farm_size", "")))
    except (TypeError, InvalidOperation, ValueError):
        return Response({"error": "farm_size must be a valid number."}, status=400)

    document_urls = data.get("documents")
    if document_urls is None:
        document_urls = [
            data.get(f"document_{index}")
            for index in range(1, 5)
        ]

    if isinstance(document_urls, str):
        document_urls = [document_urls]

    document_urls = [str(url).strip() for url in document_urls if str(url).strip()]
    if len(document_urls) < 4:
        return Response({"error": "Please upload at least 4 document URLs."}, status=400)

    # Persist the user record.
    user = User.objects.create(
        password_hash=make_password(password),
        first_name=first_name,
        middle_name=middle_name or None,
        last_name=last_name,
        verification_code=get_random_string(
            8,
            allowed_chars="ABCDEFGHJKLMNPQRSTUVWXYZ23456789",
        ),
    )

    # Save the user profile address if the schema later includes a direct user-address FK.
    user_address = Address.objects.create(
        street_address=f"{house_number} {street}" if data.get("house_number") else street,
        barangay=data.get("baranggay") or data.get("barangay"),
        municipality_city=data.get("municipality") or data.get("municipality_city"),
        province=data.get("province"),
        country=data.get("country") or "Philippines",
        address_type="residence",
    )

    if hasattr(User, "address"):
        user.address = user_address
        user.save(update_fields=["address"])

    phone = PhoneNumber.objects.create(
        user=user,
        mobile_number=phone_number,
        phone_type="mobile",
        contact_status=1,
        is_verified=0,
    )

    farm_address = Address.objects.create(
        street_address=f"{farm_house_number} {farm_street}" if farm_house_number else farm_street,
        barangay=farm_barangay,
        municipality_city=farm_municipality,
        province=farm_province,
        country=data.get("farm_country") or "Philippines",
        address_type="farm",
    )

    farm = Farm.objects.create(
        user=user,
        address=farm_address,
        farm_size_hectares=farm_size,
    )

    for index, url in enumerate(document_urls[:4], start=1):
        file_extension = url.rsplit(".", 1)[-1].lower() if "." in url else ""
        ElectronicDocument.objects.create(
            user=user,
            doc_title=f"Registration document {index}",
            doc_type=1,
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
            "otp": user.verification_code,
            "document_count": len(document_urls[:4]),
        },
        status=201,
    )