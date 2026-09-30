from django.contrib.auth.hashers import make_password
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.crypto import get_random_string
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from shared.audit import _log_audit_change, _serialize_model
from shared.models import PhoneNumber, User
from shared.registration import (
    create_address,
    create_registration_documents,
    resolve_enum_order_id,
)

from .models import LogisticsCompany, Vehicle
from .serializers import LogisticsRegistrationSerializer


@api_view(["POST"])
@permission_classes([AllowAny])
def register(request):
    request_data = request.data if isinstance(request.data, dict) else {}
    serializer = LogisticsRegistrationSerializer(data=request_data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=400)

    data = serializer.validated_data
    role_id = resolve_enum_order_id("role", "Logistics_Manager")
    if role_id is None:
        return Response({"role": ["This role is not configured."]}, status=400)

    vehicle_data = data["vehicle"]
    body_type_id = resolve_enum_order_id("body_type", vehicle_data["body_type"])
    if body_type_id is None:
        return Response(
            {"vehicle": {"body_type": ["Select a valid body type."]}},
            status=400,
        )

    username = data["username"]
    if User.objects.filter(username=username).exists():
        return Response({"username": ["This username is already in use."]}, status=409)

    try:
        with transaction.atomic():
            personal_address = create_address(data["personal_address"], "residence")
            company_address = create_address(
                data["company_address"], "logistics_business"
            )
            user = User.objects.create(
                username=username,
                password_hash=make_password(data["password"]),
                date_of_birth=data["date_of_birth"],
                personal_address=personal_address,
                role=role_id,
                is_verified=0,
                first_name=data["first_name"],
                middle_name=data.get("middle_name") or None,
                last_name=data["last_name"],
                verification_code=get_random_string(
                    8, allowed_chars="ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
                ),
            )
            PhoneNumber.objects.create(
                user=user,
                mobile_number=data["phone_number"],
                phone_type="mobile",
                contact_status=1,
                is_verified=0,
            )
            logistics_company = LogisticsCompany.objects.create(
                user=user,
                address=company_address,
                business_name=data["company_name"],
                contact_phone=data["company_phone"],
                contact_email=data["company_email"],
                is_verified=0,
                date_time_created=timezone.now(),
            )
            vehicle = Vehicle.objects.create(
                user=user,
                logistics_business=logistics_company,
                truck_model=vehicle_data["model"],
                plate_number=vehicle_data["plate_number"],
                max_weight_capacity_kg=vehicle_data["max_weight_capacity_kg"],
                max_volume_capacity_m3=vehicle_data["max_volume_capacity_m3"],
                body_type=body_type_id,
                is_refrigerated=int(vehicle_data["is_refrigerated"]),
                current_health_status=0,
            )
            create_registration_documents(
                user,
                data["documents"],
                vehicle=lambda document_type: (
                    vehicle if document_type == "vehicle_photo" else None
                ),
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
        return Response(
            {"non_field_errors": ["Registration conflicts with an existing record."]},
            status=409,
        )

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

    users = User.objects.filter(
        role=role_id, phone_numbers__mobile_number=phone_number
    ).order_by("-user_id")
    for user in users:
        if (
            user.verification_code
            and user.verification_code.strip() == verification_code
        ):
            if user.is_verified != 1:
                user.is_verified = 1
                user.save(update_fields=["is_verified"])
            return Response({"valid": True}, status=200)
    return Response({"valid": False}, status=200)
