from django.contrib.auth.hashers import make_password
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from shared.audit import _log_audit_change, _serialize_model
from shared.code_workflows import verify_account_code
from shared.models import AccountCodeRequest, PhoneNumber, User
from shared.registration import (
    create_address,
    create_registration_documents,
    resolve_enum_order_id,
)

from .models import BulkBuyer
from .serializers import BulkBuyerRegistrationSerializer


@api_view(["POST"])
@permission_classes([AllowAny])
def register(request):
    request_data = request.data if isinstance(request.data, dict) else {}
    serializer = BulkBuyerRegistrationSerializer(data=request_data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=400)

    data = serializer.validated_data
    role_id = resolve_enum_order_id("role", "Bulk_Buyer")
    if role_id is None:
        return Response({"role": ["This role is not configured."]}, status=400)

    username = data["username"]
    if User.objects.filter(username=username).exists():
        return Response({"username": ["This username is already in use."]}, status=409)

    try:
        with transaction.atomic():
            personal_address = create_address(data["personal_address"], "residence")
            business_address = create_address(data["business_address"], "business")
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
            )
            PhoneNumber.objects.create(
                user=user,
                mobile_number=data["phone_number"],
                phone_type="mobile",
                contact_status=1,
                is_verified=0,
            )
            bulk_buyer = BulkBuyer.objects.create(
                user=user,
                address=business_address,
                business_name=data["business_name"],
                is_verified=0,
                date_time_created=timezone.now(),
            )
            create_registration_documents(user, data["documents"])
            AccountCodeRequest.objects.create(user=user, kind="businesses")
            _log_audit_change(
                user=user,
                action_type="CREATE",
                target_table="BULK_BUYERS",
                target_id=bulk_buyer.business_id,
                old_values={},
                new_values=_serialize_model(bulk_buyer),
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
    return Response(
        {"valid": verify_account_code(phone_number, verification_code, "businesses")},
        status=200,
    )
