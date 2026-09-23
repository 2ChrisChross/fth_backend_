import json
from decimal import Decimal, InvalidOperation

from django.contrib.auth.hashers import make_password
from django.db import connection
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.crypto import get_random_string
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import Address, AuditLog, Business, DeliveryTrip, ElectronicDocument, EnumeratedValue, Farm, PhoneNumber, User, Vehicle


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
    required_tables = {"users", "phone_numbers", "farms", "addresses", "electronic_documents", "vehicles", "businesses", "audit_logs"}
    try:
        existing_tables = {name.lower() for name in connection.introspection.table_names()}
        return required_tables.issubset(existing_tables)
    except Exception:
        return False


def _serialize_model(instance):
    if instance is None:
        return {}
    payload = {}
    for field in instance._meta.fields:
        value = getattr(instance, field.name)
        if hasattr(value, "isoformat"):
            payload[field.name] = value.isoformat()
        else:
            payload[field.name] = value
    return payload


def _log_audit_change(user, action_type, target_table, target_id, old_values=None, new_values=None, request=None):
    try:
        ip_address = ""
        if request is not None:
            forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
            if forwarded_for:
                ip_address = forwarded_for.split(",")[0].strip()
            else:
                ip_address = request.META.get("REMOTE_ADDR", "")

        AuditLog.objects.create(
            user=user,
            action_type=action_type,
            target_table=target_table,
            target_id=target_id,
            old_values=json.dumps(old_values, default=str) if old_values is not None else None,
            new_values=json.dumps(new_values, default=str) if new_values is not None else None,
            ip_address=ip_address,
            created_at=timezone.now(),
        )
    except Exception:
        pass


def _dashboard_stage_rows(section, query, sort):
    if section == "farmers":
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

        rows = []
        for user in users:
            phone = user.phone_numbers.first()
            farm = user.farms.first()
            address = farm.address if farm and farm.address else None
            documents = user.electronic_documents.all()[:4]
            rows.append(
                {
                    "id": user.user_id,
                    "entity": user,
                    "name": " ".join(part for part in [user.first_name, user.middle_name, user.last_name] if part),
                    "phone": phone.mobile_number if phone else "-",
                    "farm_size": farm.farm_size_hectares if farm else "-",
                    "verification_code": user.verification_code or "-",
                    "location": (
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
                    "status_value": 1 if user.is_verified in (1, True, "1") else 0,
                    "status_label": "Verified" if user.is_verified in (1, True, "1") else "Pending",
                    "status_options": [
                        (0, "Pending"),
                        (1, "Verified"),
                        (2, "Rejected"),
                    ],
                }
            )
        return rows

    if section == "logistics":
        vehicles = Vehicle.objects.select_related("user").order_by("vehicle_id")
        if query:
            vehicles = vehicles.filter(
                Q(plate_number__icontains=query)
                | Q(truck_model__icontains=query)
                | Q(user__first_name__icontains=query)
                | Q(user__last_name__icontains=query)
            )
        rows = []
        for vehicle in vehicles:
            rows.append(
                {
                    "id": vehicle.vehicle_id,
                    "entity": vehicle,
                    "name": vehicle.user.get_full_name() if hasattr(vehicle.user, "get_full_name") else (vehicle.user.first_name if vehicle.user else "Unassigned"),
                    "plate_number": vehicle.plate_number or "-",
                    "model": vehicle.truck_model or "-",
                    "status_value": int(vehicle.current_health_status or 0),
                    "status_label": {0: "Pending", 1: "Healthy", 2: "Maintenance", 3: "Disabled"}.get(vehicle.current_health_status or 0, "Pending"),
                    "status_options": [
                        (0, "Pending"),
                        (1, "Healthy"),
                        (2, "Maintenance"),
                        (3, "Disabled"),
                    ],
                }
            )
        return rows

    if section == "businesses":
        businesses = Business.objects.select_related("user").order_by("business_name")
        if query:
            businesses = businesses.filter(
                Q(business_name__icontains=query)
                | Q(registration_number__icontains=query)
                | Q(user__first_name__icontains=query)
                | Q(user__last_name__icontains=query)
            )
        rows = []
        for business in businesses:
            rows.append(
                {
                    "id": business.business_id,
                    "entity": business,
                    "name": business.business_name or "-",
                    "owner": business.user.first_name + " " + (business.user.last_name or "") if business.user else "-",
                    "registration_number": business.registration_number or "-",
                    "status_value": 1 if business.is_verified in (1, True, "1") else 0,
                    "status_label": "Approved" if business.is_verified in (1, True, "1") else "Pending",
                    "status_options": [
                        (0, "Pending"),
                        (1, "Approved"),
                        (2, "Rejected"),
                    ],
                }
            )
        return rows

    audit_logs = AuditLog.objects.select_related("user").order_by("-created_at")[:100]
    if query:
        audit_logs = audit_logs.filter(
            Q(action_type__icontains=query)
            | Q(target_table__icontains=query)
            | Q(user__first_name__icontains=query)
            | Q(user__last_name__icontains=query)
        )
    rows = []
    for log in audit_logs:
        rows.append(
            {
                "id": log.log_id,
                "entity": log,
                "name": log.user.first_name + " " + (log.user.last_name or "") if log.user else "System",
                "action": log.action_type or "-",
                "target": log.target_table or "-",
                "status_label": "Recorded",
                "status_value": 1,
                "status_options": [(1, "Recorded")],
                "created_at": log.created_at,
            }
        )
    return rows


def dashboard_reports(request):
    if not database_ready_for_dashboard():
        return render(
            request,
            "api/reports.html",
            {
                "summary": {},
                "recent_logs": [],
                "db_error": "The database tables for this app have not been created yet. Run your migrations or connect the correct database.",
            },
        )

    farmers_count = User.objects.count()
    logistics_count = Vehicle.objects.count()
    businesses_count = Business.objects.count()
    verified_farmers = User.objects.filter(is_verified__in=[1, True, "1"]).count()
    pending_farmers = User.objects.filter(is_verified__in=[0, None]).count()
    approved_businesses = Business.objects.filter(is_verified__in=[1, True, "1"]).count()
    recent_logs = AuditLog.objects.select_related("user").order_by("-created_at")[:8]

    summary = {
        "farmers": farmers_count,
        "logistics": logistics_count,
        "businesses": businesses_count,
        "verified_farmers": verified_farmers,
        "pending_farmers": pending_farmers,
        "approved_businesses": approved_businesses,
    }

    return render(
        request,
        "api/reports.html",
        {
            "summary": summary,
            "recent_logs": recent_logs,
            "sections": [
                {"key": "farmers", "label": "Farmers"},
                {"key": "logistics", "label": "Logistics"},
                {"key": "businesses", "label": "Businesses"},
                {"key": "reports", "label": "Reports"},
                {"key": "audit_logs", "label": "Audit Logs"},
            ],
        },
    )


def dashboard_users(request):
    query = (request.GET.get("q") or "").strip()
    sort = request.GET.get("sort", "name")
    section = (request.POST.get("section") or request.GET.get("section") or "farmers").strip() or "farmers"

    if request.method == "POST":
        target_id = request.POST.get("target_id")
        stage = request.POST.get("stage")
        if target_id and stage is not None:
            try:
                stage_value = int(stage)
            except (TypeError, ValueError):
                stage_value = None

            if stage_value is not None:
                if section == "farmers":
                    user = User.objects.filter(user_id=target_id).first()
                    if user is not None:
                        previous = _serialize_model(user)
                        user.is_verified = stage_value
                        user.save(update_fields=["is_verified"])
                        _log_audit_change(
                            user=user,
                            action_type="UPDATE_STATUS",
                            target_table="USERS",
                            target_id=user.user_id,
                            old_values={"is_verified": previous.get("is_verified")},
                            new_values={"is_verified": user.is_verified},
                            request=request,
                        )
                elif section == "logistics":
                    vehicle = Vehicle.objects.filter(vehicle_id=target_id).first()
                    if vehicle is not None:
                        previous = _serialize_model(vehicle)
                        vehicle.current_health_status = stage_value
                        vehicle.save(update_fields=["current_health_status"])
                        _log_audit_change(
                            user=vehicle.user,
                            action_type="UPDATE_STATUS",
                            target_table="VEHICLES",
                            target_id=vehicle.vehicle_id,
                            old_values={"current_health_status": previous.get("current_health_status")},
                            new_values={"current_health_status": vehicle.current_health_status},
                            request=request,
                        )
                elif section == "businesses":
                    business = Business.objects.filter(business_id=target_id).first()
                    if business is not None:
                        previous = _serialize_model(business)
                        business.is_verified = stage_value
                        business.save(update_fields=["is_verified"])
                        _log_audit_change(
                            user=business.user,
                            action_type="UPDATE_STATUS",
                            target_table="BUSINESSES",
                            target_id=business.business_id,
                            old_values={"is_verified": previous.get("is_verified")},
                            new_values={"is_verified": business.is_verified},
                            request=request,
                        )
        return redirect(f"/dashboard/?section={section}&q={query}")

    if not database_ready_for_dashboard():
        return render(
            request,
            "api/dashboard.html",
            {
                "rows": [],
                "query": query,
                "sort": sort,
                "section": section,
                "db_error": """The database tables for this app have not been created yet. 
                Run your migrations or connect the project to the correct database.""",
            },
        )

    dashboard_rows = _dashboard_stage_rows(section, query, sort)
    sidebar_sections = [
        {"key": "farmers", "label": "Farmers"},
        {"key": "logistics", "label": "Logistics"},
        {"key": "businesses", "label": "Businesses"},
        {"key": "reports", "label": "Reports"},
        {"key": "audit_logs", "label": "Audit Logs"},
    ]

    return render(
        request,
        "api/dashboard.html",
        {
            "rows": dashboard_rows,
            "query": query,
            "sort": sort,
            "section": section,
            "sections": sidebar_sections,
        },
    )


def dashboard_entity_form(request, section="farmers"):
    if section not in {"businesses", "logistics"}:
        return redirect("dashboard_users")

    if not database_ready_for_dashboard():
        return render(
            request,
            "api/entity_form.html",
            {
                "section": section,
                "users": [],
                "db_error": """The database tables for this app have not been created yet. 
                Run your migrations or connect the correct database.""",
            },
        )

    users = User.objects.order_by("first_name", "last_name", "user_id")

    if request.method == "POST":
        owner_id = request.POST.get("user_id")
        owner = User.objects.filter(user_id=owner_id).first() if owner_id else None

        if section == "businesses":
            business_name = (request.POST.get("business_name") or "").strip()
            registration_number = (request.POST.get("registration_number") or "").strip()
            business_type = request.POST.get("business_type")
            is_verified = request.POST.get("is_verified", 0)

            if not owner or not business_name:
                return render(
                    request,
                    "api/entity_form.html",
                    {"section": section, "users": users, "error": "An owner and business name are required."},
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

        elif section == "logistics":
            truck_model = (request.POST.get("truck_model") or "").strip()
            plate_number = (request.POST.get("plate_number") or "").strip()
            max_weight = request.POST.get("max_weight_capacity_kg") or ""
            max_volume = request.POST.get("max_volume_capacity_m3") or ""
            current_health_status = request.POST.get("current_health_status", 0)

            if not owner or not truck_model or not plate_number:
                return render(
                    request,
                    "api/entity_form.html",
                    {"section": section, "users": users, "error": "You must assign an owner and provide a vehicle model and plate number."},
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

        return redirect(f"/dashboard/?section={section}")

    return render(
        request,
        "api/entity_form.html",
        {
            "section": section,
            "users": users,
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
                "db_error": """The database tables for this app have not been created yet. 
                Run your migrations or connect the correct database.""",
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
            _log_audit_change(
                user=user,
                action_type="CREATE",
                target_table="USERS",
                target_id=user.user_id,
                old_values={},
                new_values=_serialize_model(user),
                request=request,
            )
        else:
            previous = _serialize_model(user)
            user.first_name = first_name
            user.middle_name = middle_name or None
            user.last_name = last_name
            user.save()
            _log_audit_change(
                user=user,
                action_type="UPDATE",
                target_table="USERS",
                target_id=user.user_id,
                old_values={"first_name": previous.get("first_name"), "middle_name": previous.get("middle_name"), "last_name": previous.get("last_name")},
                new_values={"first_name": user.first_name, "middle_name": user.middle_name, "last_name": user.last_name},
                request=request,
            )

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
                "db_error": """The database tables for this app have not been created yet. 
                Run your migrations or connect the correct database.""",
            },
        )

    user = get_object_or_404(User, user_id=user_id)
    if request.method == "POST":
        previous = _serialize_model(user)
        user.delete()
        _log_audit_change(
            user=user,
            action_type="DELETE",
            target_table="USERS",
            target_id=user_id,
            old_values=previous,
            new_values={},
            request=request,
        )
        return redirect("dashboard_users")
    return render(request, "api/user_delete_confirm.html", {"user": user})


@api_view(["POST"])
@permission_classes([AllowAny])
def verify_user_code(request):
    data = request.data or {}
    phone_number = str(data.get("phone_number") or data.get("phonenumber") or "").strip()
    verification_code = str(data.get("verification_code") or "").strip()

    if phone_number == "" or verification_code == "":
        return Response({"valid": False, "error": "phone_number and verification_code are required."}, status=400)

    users = User.objects.filter(phone_numbers__mobile_number=phone_number).order_by("-user_id")
    if not users.exists():
        return Response({"valid": False}, status=200)

    for user in users:
        if user.verification_code is not None and user.verification_code.strip() == verification_code:
            return Response({"valid": True}, status=200)

    return Response({"valid": False}, status=200)


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
        "farm_region",
        "farm_province",
        "farm_municipality",
        "farm_barangay",
        "farm_house_number",
        "farm_street",
        "farm_postal_code",
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