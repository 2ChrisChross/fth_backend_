from api.views import dashboard_entity_form, dashboard_users


from django.contrib.auth.hashers import make_password
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.utils.crypto import get_random_string
from django.utils import timezone
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
from .models import Business
from api.views import _log_audit_change, _serialize_model, dashboard_users, database_ready_for_dashboard


def dashboard(request):
    return dashboard_users(request, section_override="businesses")


def create(request):
    dashboard_url = reverse("businesses:dashboard")
    if not database_ready_for_dashboard():
        return render(
            request,
            "api/entity_form.html",
            {
                "section": "businesses",
                "dashboard_url": dashboard_url,
                "users": [],
                "db_error": "The database tables for this app have not been created yet. Run your migrations or connect the correct database.",
            },
        )

    users = User.objects.order_by("first_name", "last_name", "user_id")
    if request.method == "POST":
        owner_id = request.POST.get("user_id")
        owner = User.objects.filter(user_id=owner_id).first() if owner_id else None
        business_name = (request.POST.get("business_name") or "").strip()
        registration_number = (request.POST.get("registration_number") or "").strip()
        business_type = request.POST.get("business_type")
        is_verified = request.POST.get("is_verified", 0)

        if not owner or not business_name:
            return render(
                request,
                "api/entity_form.html",
                {
                    "section": "businesses",
                    "dashboard_url": dashboard_url,
                    "users": users,
                    "error": "An owner and business name are required.",
                },
            )

        business = Business.objects.create(
            user=owner,
            business_name=business_name,
            business_type=int(business_type) if business_type and str(business_type).isdigit() else None,
            registration_number=registration_number or None,
            is_verified=int(is_verified) if str(is_verified).isdigit() else 0,
            date_time_created=timezone.now(),
        )
        _log_audit_change(
            user=owner,
            action_type="CREATE",
            target_table="BUSINESSES",
            target_id=business.business_id,
            old_values={},
            new_values=_serialize_model(business),
            request=request,
        )
        return redirect(dashboard_url)

    return render(
        request,
        "api/entity_form.html",
        {"section": "businesses", "dashboard_url": dashboard_url, "users": users},
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
        "business_name",
    )
    if any(not str(data.get(field) or "").strip() for field in required_fields):
        return Response(status=400)
    if str(data.get("role") or "").strip() != "Bulk_Buyer":
        return Response(status=400)

    personal_address_data = normalize_address_payload(data.get("personal_address"))
    business_address_data = normalize_address_payload(data.get("business_address"))
    required_documents = ("birth_certificate", "business_utility_bill", "business_permit", "national_id")
    documents = normalize_registration_documents(data.get("documents"), required_documents)
    date_of_birth = parse_date(str(data.get("date_of_birth")))
    role_id = resolve_enum_order_id("role", "Bulk_Buyer")
    if not personal_address_data or not business_address_data or not documents or not date_of_birth or role_id is None:
        return Response(status=400)

    username = str(data.get("username")).strip()
    if User.objects.filter(username=username).exists():
        return Response(status=409)

    try:
        with transaction.atomic():
            personal_address = create_address(personal_address_data, "residence")
            business_address = create_address(business_address_data, "business")
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
            business = Business.objects.create(
                user=user,
                address=business_address,
                business_name=str(data.get("business_name")).strip(),
                is_verified=0,
                date_time_created=timezone.now(),
            )
            create_registration_documents(user, documents)
            _log_audit_change(
                user=user,
                action_type="CREATE",
                target_table="BUSINESSES",
                target_id=business.business_id,
                old_values={},
                new_values=_serialize_model(business),
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
    role_id = resolve_enum_order_id("role", "Bulk_Buyer")
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