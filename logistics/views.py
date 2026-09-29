from api.views import dashboard_entity_form, dashboard_users


from decimal import Decimal
from decimal import InvalidOperation

from django.contrib.auth.hashers import make_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.crypto import get_random_string
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from api.models import PhoneNumber, User
from api.registration import (
    create_address,
    create_registration_documents,
    normalize_address_payload,
    normalize_registration_documents,
    resolve_enum_order_id,
)
from api.views import _log_audit_change, _serialize_model, dashboard_users, database_ready_for_dashboard
from .models import LogisticsBusiness, Vehicle


def dashboard(request):
    return dashboard_users(request, section_override="logistics")


def create(request):
    dashboard_url = reverse("logistics:dashboard")
    if not database_ready_for_dashboard():
        return render(
            request,
            "api/entity_form.html",
            {
                "section": "logistics",
                "dashboard_url": dashboard_url,
                "users": [],
                "db_error": "The database tables for this app have not been created yet. Run your migrations or connect the correct database.",
            },
        )

    users = User.objects.order_by("first_name", "last_name", "user_id")
    if request.method == "POST":
        owner_id = request.POST.get("user_id")
        owner = User.objects.filter(user_id=owner_id).first() if owner_id else None
        truck_model = (request.POST.get("truck_model") or "").strip()
        plate_number = (request.POST.get("plate_number") or "").strip()
        max_weight = request.POST.get("max_weight_capacity_kg") or ""
        max_volume = request.POST.get("max_volume_capacity_m3") or ""
        current_health_status = request.POST.get("current_health_status", 0)

        if not owner or not truck_model or not plate_number:
            return render(
                request,
                "api/entity_form.html",
                {
                    "section": "logistics",
                    "dashboard_url": dashboard_url,
                    "users": users,
                    "error": "You must assign an owner and provide a vehicle model and plate number.",
                },
            )

        vehicle = Vehicle.objects.create(
            user=owner,
            truck_model=truck_model,
            plate_number=plate_number,
            max_weight_capacity_kg=Decimal(str(max_weight)) if str(max_weight).strip() else None,
            max_volume_capacity_m3=Decimal(str(max_volume)) if str(max_volume).strip() else None,
            current_health_status=int(current_health_status) if str(current_health_status).isdigit() else 0,
        )
        _log_audit_change(
            user=owner,
            action_type="CREATE",
            target_table="VEHICLES",
            target_id=vehicle.vehicle_id,
            old_values={},
            new_values=_serialize_model(vehicle),
            request=request,
        )
        return redirect(dashboard_url)

    return render(
        request,
        "api/entity_form.html",
        {"section": "logistics", "dashboard_url": dashboard_url, "users": users},
    )


@api_view(["POST"])
@permission_classes([AllowAny])
def register(request):
    data = request.data if isinstance(request.data, dict) else {}
    required_fields = (
        "username",
        "password",
        "first_name",
        "last_name",
        "date_of_birth",
        "phone_number",
        "company_name",
        "company_phone",
        "company_email",
    )
    if any(not str(data.get(field) or "").strip() for field in required_fields):
        return Response(status=400)
    if str(data.get("role") or "").strip() != "Logistics_Manager":
        return Response(status=400)

    personal_address_data = normalize_address_payload(data.get("personal_address"))
    company_address_data = normalize_address_payload(data.get("company_address"))
    required_documents = (
        "ltfrb_franchise_for_trucking",
        "vehicle_photo",
        "vehicle_driver_license",
        "national_id",
        "official_receipt",
        "certificate_of_registration",
        "nbi_clearance",
    )
    documents = normalize_registration_documents(data.get("documents"), required_documents)
    date_of_birth = parse_date(str(data.get("date_of_birth")))
    role_id = resolve_enum_order_id("role", "Logistics_Manager")
    vehicle_data = data.get("vehicle") if isinstance(data.get("vehicle"), dict) else {}
    required_vehicle_fields = (
        "model",
        "plate_number",
        "max_weight_capacity_kg",
        "max_volume_capacity_m3",
        "body_type",
        "is_refrigerated",
    )
    if any(vehicle_data.get(field) in (None, "") for field in required_vehicle_fields):
        return Response(status=400)

    try:
        max_weight = Decimal(str(vehicle_data["max_weight_capacity_kg"]))
        max_volume = Decimal(str(vehicle_data["max_volume_capacity_m3"]))
    except (InvalidOperation, TypeError, ValueError):
        return Response(status=400)

    body_type_id = resolve_enum_order_id("body_type", vehicle_data["body_type"])
    is_refrigerated = vehicle_data["is_refrigerated"]
    if (
        not personal_address_data
        or not company_address_data
        or not documents
        or not date_of_birth
        or role_id is None
        or body_type_id is None
        or not isinstance(is_refrigerated, bool)
        or max_weight < 0
        or max_volume < 0
    ):
        return Response(status=400)

    try:
        validate_email(str(data.get("company_email")).strip())
    except ValidationError:
        return Response(status=400)

    username = str(data.get("username")).strip()
    if User.objects.filter(username=username).exists():
        return Response(status=409)

    try:
        with transaction.atomic():
            personal_address = create_address(personal_address_data, "residence")
            company_address = create_address(company_address_data, "logistics_business")
            user = User.objects.create(
                username=username,
                password_hash=make_password(str(data.get("password"))),
                date_of_birth=date_of_birth,
                personal_address=personal_address,
                role=role_id,
                is_verified=0,
                first_name=str(data.get("first_name")).strip(),
                middle_name=str(data.get("middle_name") or "").strip() or None,
                last_name=str(data.get("last_name")).strip(),
                verification_code=get_random_string(8, allowed_chars="ABCDEFGHJKLMNPQRSTUVWXYZ23456789"),
            )
            PhoneNumber.objects.create(
                user=user,
                mobile_number=str(data.get("phone_number")).strip(),
                phone_type="mobile",
                contact_status=1,
                is_verified=0,
            )
            logistics_business = LogisticsBusiness.objects.create(
                user=user,
                address=company_address,
                business_name=str(data.get("company_name")).strip(),
                contact_phone=str(data.get("company_phone")).strip(),
                contact_email=str(data.get("company_email")).strip(),
                is_verified=0,
                date_time_created=timezone.now(),
            )
            vehicle = Vehicle.objects.create(
                user=user,
                logistics_business=logistics_business,
                truck_model=str(vehicle_data["model"]).strip(),
                plate_number=str(vehicle_data["plate_number"]).strip(),
                max_weight_capacity_kg=max_weight,
                max_volume_capacity_m3=max_volume,
                body_type=body_type_id,
                is_refrigerated=int(is_refrigerated),
                current_health_status=0,
            )
            create_registration_documents(
                user,
                documents,
                vehicle=lambda document_type: vehicle if document_type == "vehicle_photo" else None,
            )
            _log_audit_change(
                user=user,
                action_type="CREATE",
                target_table="VEHICLES",
                target_id=vehicle.vehicle_id,
                old_values={},
                new_values=_serialize_model(vehicle),
                request=request,
            )
    except IntegrityError:
        return Response(status=409)

    return Response(status=201)


@api_view(["POST"])
@permission_classes([AllowAny])
def verify_code(request):
    data = request.data if isinstance(request.data, dict) else {}
    phone_number = str(data.get("phone_number") or "").strip()
    verification_code = str(data.get("verification_code") or "").strip()
    role_id = resolve_enum_order_id("role", "Logistics_Manager")
    if not phone_number or not verification_code or role_id is None:
        return Response({"valid": False}, status=200)

    users = User.objects.filter(role=role_id, phone_numbers__mobile_number=phone_number).order_by("-user_id")
    for user in users:
        if user.verification_code and user.verification_code.strip() == verification_code:
            if user.is_verified != 1:
                user.is_verified = 1
                user.save(update_fields=["is_verified"])
            return Response({"valid": True}, status=200)
    return Response({"valid": False}, status=200)