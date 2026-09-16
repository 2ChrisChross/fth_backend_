from decimal import Decimal, InvalidOperation

from django.contrib.auth.hashers import make_password
from django.db import connection
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.crypto import get_random_string
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import Address, ElectronicDocument, EnumeratedValue, Farm, PhoneNumber, User


def _resolve_enum_order_id(enum_type, raw_value):
    if raw_value is None:
        return None

    value = str(raw_value).strip()
    if value == "":
        return None

    if value.isdigit():
        return int(value)

    candidates = ["order_id", "ordering"]
    with connection.cursor() as cursor:
        for column in candidates:
            try:
                cursor.execute(
                    (
                        f'SELECT {column} FROM "enumerated_values" WHERE LOWER(type) = LOWER(%s) '
                        f'AND LOWER(value) = LOWER(%s) LIMIT 1'
                    ),
                    [str(enum_type), value],
                )
                row = cursor.fetchone()
                if row:
                    return row[0]
            except Exception:
                continue

    try:
        enum = EnumeratedValue.objects.filter(type__iexact=str(enum_type), value__iexact=value).first()
        if enum is not None:
            if hasattr(enum, "order_id") and enum.order_id is not None:
                return enum.order_id
            if hasattr(enum, "ordering") and enum.ordering is not None:
                return enum.ordering
        return None
    except Exception:
        return None


def index(request):
    return Response({"message": "FTH API is running."})


def database_ready_for_dashboard():
    required_tables = {"users", "phone_numbers", "farms", "addresses", "electronic_documents"}
    try:
        existing_tables = {name.lower() for name in connection.introspection.table_names()}
        return required_tables.issubset(existing_tables)
    except Exception:
        return False


def dashboard_users(request):
    query = (request.GET.get("q") or "").strip()
    sort = request.GET.get("sort", "name")

    if not database_ready_for_dashboard():
        return render(
            request,
            "api/dashboard.html",
            {
                "rows": [],
                "query": query,
                "sort": sort,
                "db_error": "The database tables for this app have not been created yet. Run your migrations or connect the project to the correct database.",
            },
        )

    users = User.objects.all().order_by("first_name", "last_name", "user_id")

    if query:
        users = users.filter(
            Q(first_name__icontains=query)
            | Q(middle_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(phone_numbers__mobile_number__icontains=query)
            | Q(farms__address__municipality_city__icontains=query)
            | Q(farms__address__barangay__icontains=query)
        ).distinct()

    if sort == "az":
        users = users.order_by("first_name", "last_name", "user_id")
    elif sort == "za":
        users = users.order_by("-first_name", "-last_name", "-user_id")
    elif sort == "newest":
        users = users.order_by("-user_id")

    dashboard_rows = []
    for user in users:
        phone = user.phone_numbers.first()
        farm = user.farms.first()
        address = farm.address if farm and farm.address else None
        documents = user.electronic_documents.all()[:4]

        dashboard_rows.append(
            {
                "user": user,
                "full_name": " ".join(
                    part for part in [user.first_name, user.middle_name, user.last_name] if part
                ),
                "phone_number": phone.mobile_number if phone else "-",
                "farm_size": farm.farm_size_hectares if farm else "-",
                "verification_code": user.verification_code or "-",
                "address": (
                    ", ".join(
                        part
                        for part in [
                            address.street_address if address else None,
                            address.barangay if address else None,
                            address.municipality_city if address else None,
                            address.province if address else None,
                        ]
                        if part
                    )
                    or "-"
                ),
                "documents": documents,
            }
        )

    return render(
        request,
        "api/dashboard.html",
        {
            "rows": dashboard_rows,
            "query": query,
            "sort": sort,
        },
    )


def dashboard_user_form(request, user_id=None):
    if not database_ready_for_dashboard():
        return render(
            request,
            "api/user_form.html",
            {
                "user": None,
                "phone": None,
                "farm": None,
                "address": None,
                "db_error": "The database tables for this app have not been created yet. Run your migrations or connect the correct database.",
            },
        )

    user = get_object_or_404(User, user_id=user_id) if user_id else None
    phone = user.phone_numbers.first() if user else None
    farm = user.farms.first() if user else None
    address = farm.address if farm else None

    if request.method == "POST":
        first_name = (request.POST.get("first_name") or "").strip()
        middle_name = (request.POST.get("middle_name") or "").strip()
        last_name = (request.POST.get("last_name") or "").strip()
        phone_number = (request.POST.get("phone_number") or "").strip()
        farm_size = (request.POST.get("farm_size") or "").strip()
        street = (request.POST.get("street") or "").strip()
        barangay = (request.POST.get("barangay") or "").strip()
        municipality = (request.POST.get("municipality") or "").strip()
        province = (request.POST.get("province") or "").strip()
        region = (request.POST.get("region") or "").strip()
        house_number = (request.POST.get("house_number") or "").strip()

        if not first_name or not last_name:
            return render(
                request,
                "api/user_form.html",
                {
                    "user": user,
                    "error": "First name and last name are required.",
                },
            )

        if user is None:
            anchor_address = Address.objects.create(
                street_address=f"{house_number} {street}" if house_number or street else "",
                barangay=barangay,
                municipality_city=municipality,
                province=province,
                country="Philippines",
                gps_coordinates=region or "",
                address_type="residence",
            )
            user = User.objects.create(
                user_id=anchor_address.address_id,
                first_name=first_name,
                middle_name=middle_name or None,
                last_name=last_name,
                password_hash=make_password("changeme123"),
                verification_code=get_random_string(8, allowed_chars="ABCDEFGHJKLMNPQRSTUVWXYZ23456789"),
            )
        else:
            user.first_name = first_name
            user.middle_name = middle_name or None
            user.last_name = last_name
            user.save()

        if phone is None:
            phone = PhoneNumber.objects.create(user=user, mobile_number=phone_number or "", phone_type="mobile")
        else:
            phone.mobile_number = phone_number or phone.mobile_number
            phone.save()

        if farm is None:
            address_obj = Address.objects.create(
                street_address=f"{house_number} {street}" if house_number or street else "",
                barangay=barangay,
                municipality_city=municipality,
                province=province,
                country="Philippines",
                gps_coordinates=region or "",
                address_type="farm",
            )
            farm = Farm.objects.create(
                user=user,
                address=address_obj,
                farm_size_hectares=Decimal(str(farm_size)) if farm_size else None,
            )
        else:
            if farm.address:
                farm.address.street_address = f"{house_number} {street}" if house_number or street else ""
                farm.address.barangay = barangay
                farm.address.municipality_city = municipality
                farm.address.province = province
                farm.address.gps_coordinates = region or farm.address.gps_coordinates
                farm.address.save()
            farm.farm_size_hectares = Decimal(str(farm_size)) if farm_size else farm.farm_size_hectares
            farm.save()

        return redirect("dashboard_users")

    return render(
        request,
        "api/user_form.html",
        {
            "user": user,
            "phone": phone,
            "farm": farm,
            "address": address,
        },
    )


def dashboard_user_delete(request, user_id):
    if not database_ready_for_dashboard():
        return render(
            request,
            "api/user_delete_confirm.html",
            {
                "user": None,
                "db_error": "The database tables for this app have not been created yet. Run your migrations or connect the correct database.",
            },
        )

    user = get_object_or_404(User, user_id=user_id)
    if request.method == "POST":
        user.delete()
        return redirect("dashboard_users")
    return render(request, "api/user_delete_confirm.html", {"user": user})


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

    preferred_language = _resolve_enum_order_id("language", data.get("language") or data.get("preferred_language"))
    role_order_id = _resolve_enum_order_id("role", data.get("role"))
    onboarding_status_id = _resolve_enum_order_id(
        "onboarding_status",
        data.get("onboarding_status") or "Profile_Created",
    )
    payment_method_id = _resolve_enum_order_id("payment_method", data.get("payment_method") or data.get("preferred_payment_method"))

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
        document_urls = [data.get(f"document_{index}") for index in range(1, 5)]

    if isinstance(document_urls, str):
        document_urls = [document_urls]

    document_urls = [str(url).strip() for url in document_urls if str(url).strip()]
    if len(document_urls) < 4:
        return Response({"error": "Please upload at least 4 document URLs."}, status=400)

    document_type_names = data.get("document_types")
    if document_type_names is None and data.get("document_type") is not None:
        document_type_names = data.get("document_type")
    if document_type_names is None:
        document_type_names = ["Utility Bills", "Valid_ID", "Owner_Address", "Farm_Ownership"]
    if isinstance(document_type_names, str):
        document_type_names = [document_type_names]
    document_type_names = [str(item).strip() for item in document_type_names if str(item).strip()]

    user_address = Address.objects.create(
        street_address=f"{data.get('house_number', '')} {data.get('street', '')}" if data.get("house_number") else data.get("street") or "",
        barangay=data.get("baranggay") or data.get("barangay"),
        municipality_city=data.get("municipality") or data.get("municipality_city"),
        province=data.get("province"),
        country=data.get("country") or "Philippines",
        gps_coordinates=farm_region or data.get("region") or "",
        address_type="residence",
    )

    user = User.objects.create(
        user_id=user_address.address_id,
        password_hash=make_password(password),
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

    farm_address = Address.objects.create(
        street_address=f"{farm_house_number} {farm_street}" if farm_house_number else farm_street,
        barangay=farm_barangay,
        municipality_city=farm_municipality,
        province=farm_province,
        country=data.get("farm_country") or "Philippines",
        gps_coordinates=farm_region or "",
        address_type="farm",
    )

    farm = Farm.objects.create(
        user=user,
        address=farm_address,
        farm_size_hectares=farm_size,
    )

    document_type_order_ids = []
    for index, url in enumerate(document_urls[:4], start=1):
        file_extension = url.rsplit(".", 1)[-1].lower() if "." in url else ""
        doc_type_name = document_type_names[index - 1] if index - 1 < len(document_type_names) else "Utility Bills"
        doc_type_order_id = _resolve_enum_order_id("document_type", doc_type_name) or 1
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
            "otp": user.verification_code,
            "language_order_id": preferred_language,
            "role_order_id": role_order_id,
            "onboarding_status_order_id": onboarding_status_id,
            "payment_method_order_id": payment_method_id,
            "document_type_order_ids": document_type_order_ids,
            "document_count": len(document_urls[:4]),
        },
        status=201,
    )