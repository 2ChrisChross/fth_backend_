import json
from decimal import Decimal

from django.contrib.auth.hashers import make_password
from django.db import connection
from django.db.models import F, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import get_random_string
from rest_framework.response import Response

from businesses.models import Business
from logistics.models import Vehicle

from .models import Address, AuditLog, DeliveryTrip, ElectronicDocument, Farm, PhoneNumber, User


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


def _format_person_name(first_name=None, middle_name=None, last_name=None):
    first = (first_name or "").strip()
    middle = (middle_name or "").strip()
    last = (last_name or "").strip()

    if last and first:
        return f"{last}, {first}{' ' + middle if middle else ''}"
    if last:
        return last
    if first:
        return first + (f" {middle}" if middle else "")
    if middle:
        return middle
    return "-"


def _dashboard_url(section):
    route_names = {
        "farmers": "farmers:dashboard",
        "businesses": "businesses:dashboard",
        "logistics": "logistics:dashboard",
    }
    if section == "audit_logs":
        return f"{reverse('dashboard_users')}?section=audit_logs"
    return reverse(route_names.get(section, "farmers:dashboard"))


def _dashboard_stage_rows(section, query, sort_field=None, sort_dir="asc", status_filter="all"):
    sort_field = sort_field or "last_name"
    sort_dir = "asc" if sort_dir not in {"asc", "desc"} else sort_dir
    status_filter = status_filter or "all"
    descending = sort_dir == "desc"

    def order_value(*fields):
        ordered = []
        for field in fields:
            ordered.append(f"-{field}" if descending else field)
        return ordered

    if section == "farmers":
        users = User.objects.all()
        if sort_field == "verification":
            users = users.order_by(*order_value("is_verified", "last_name", "first_name", "middle_name", "user_id"))
        elif sort_field == "farm_size":
            users = users.order_by(*order_value("farms__farm_size_hectares", "last_name", "first_name", "middle_name", "user_id"))
        elif sort_field == "newest":
            users = users.order_by(*order_value("user_id"))
        else:
            users = users.order_by(*order_value("last_name", "first_name", "middle_name", "user_id"))

        if status_filter == "pending":
            users = users.filter(is_verified__in=[0, None])
        elif status_filter == "verified":
            users = users.filter(is_verified__in=[1, True, "1"])
        elif status_filter == "rejected":
            users = users.filter(is_verified=2)

        if query:
            users = users.filter(
                Q(first_name__icontains=query)
                | Q(middle_name__icontains=query)
                | Q(last_name__icontains=query)
                | Q(phone_numbers__mobile_number__icontains=query)
                | Q(farms__address__municipality_city__icontains=query)
                | Q(farms__address__barangay__icontains=query)
            ).distinct()

        rows = []
        for user in users:
            phone = user.phone_numbers.first()
            farm = user.farms.first()
            address = farm.address if farm and farm.address else None
            documents = user.electronic_documents.all()[:4]
            creation_date = AuditLog.objects.filter(target_table="USERS", target_id=user.user_id, action_type="CREATE").order_by("created_at").values_list("created_at", flat=True).first()
            rows.append(
                {
                    "id": user.user_id,
                    "entity": user,
                    "name": _format_person_name(user.first_name, user.middle_name, user.last_name),
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
                    "created_at": creation_date,
                }
            )
        return rows

    if section == "logistics":
        vehicles = Vehicle.objects.select_related("user")
        if sort_field == "status":
            vehicles = vehicles.order_by(*order_value("current_health_status", "user__last_name", "user__first_name", "vehicle_id"))
        elif sort_field == "capacity":
            vehicles = vehicles.order_by(*order_value("max_weight_capacity_kg", "user__last_name", "user__first_name", "vehicle_id"))
        elif sort_field == "plate_number":
            vehicles = vehicles.order_by(*order_value("plate_number", "user__last_name", "user__first_name", "vehicle_id"))
        else:
            vehicles = vehicles.order_by(*order_value("user__last_name", "user__first_name", "user__middle_name", "vehicle_id"))

        if status_filter == "pending":
            vehicles = vehicles.filter(current_health_status__in=[0, None])
        elif status_filter == "healthy":
            vehicles = vehicles.filter(current_health_status=1)
        elif status_filter == "maintenance":
            vehicles = vehicles.filter(current_health_status=2)
        elif status_filter == "disabled":
            vehicles = vehicles.filter(current_health_status=3)

        if query:
            vehicles = vehicles.filter(
                Q(plate_number__icontains=query)
                | Q(truck_model__icontains=query)
                | Q(user__first_name__icontains=query)
                | Q(user__last_name__icontains=query)
            )
        rows = []
        for vehicle in vehicles:
            owner_name = vehicle.user if vehicle.user else None
            name = _format_person_name(
                getattr(owner_name, "first_name", None),
                getattr(owner_name, "middle_name", None),
                getattr(owner_name, "last_name", None),
            ) if owner_name else "Unassigned"
            creation_date = AuditLog.objects.filter(target_table="VEHICLES", target_id=vehicle.vehicle_id, action_type="CREATE").order_by("created_at").values_list("created_at", flat=True).first()
            rows.append(
                {
                    "id": vehicle.vehicle_id,
                    "entity": vehicle,
                    "name": name,
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
                    "created_at": creation_date,
                }
            )
        return rows

    if section == "businesses":
        businesses = Business.objects.select_related("user")
        if sort_field == "status":
            businesses = businesses.order_by(*order_value("is_verified", "business_name", "user__last_name"))
        elif sort_field == "owner":
            businesses = businesses.order_by(*order_value("user__last_name", "user__first_name", "business_name"))
        else:
            businesses = businesses.order_by(*order_value("business_name", "user__last_name", "user__first_name"))

        if status_filter == "pending":
            businesses = businesses.filter(is_verified__in=[0, None])
        elif status_filter == "approved":
            businesses = businesses.filter(is_verified__in=[1, True, "1"])
        elif status_filter == "rejected":
            businesses = businesses.filter(is_verified=2)

        if query:
            businesses = businesses.filter(
                Q(business_name__icontains=query)
                | Q(registration_number__icontains=query)
                | Q(user__first_name__icontains=query)
                | Q(user__last_name__icontains=query)
            )
        rows = []
        for business in businesses:
            owner_name = business.user
            creation_date = business.date_time_created or AuditLog.objects.filter(target_table="BUSINESSES", target_id=business.business_id, action_type="CREATE").order_by("created_at").values_list("created_at", flat=True).first()
            rows.append(
                {
                    "id": business.business_id,
                    "entity": business,
                    "name": business.business_name or "-",
                    "owner": _format_person_name(
                        getattr(owner_name, "first_name", None),
                        getattr(owner_name, "middle_name", None),
                        getattr(owner_name, "last_name", None),
                    ) if owner_name else "-",
                    "registration_number": business.registration_number or "-",
                    "status_value": 1 if business.is_verified in (1, True, "1") else 0,
                    "status_label": "Approved" if business.is_verified in (1, True, "1") else "Pending",
                    "status_options": [
                        (0, "Pending"),
                        (1, "Approved"),
                        (2, "Rejected"),
                    ],
                    "created_at": creation_date,
                }
            )
        return rows

    audit_logs = AuditLog.objects.select_related("user")
    if sort_field == "action":
        audit_logs = audit_logs.order_by(*order_value("action_type", "created_at"))
    elif sort_field == "user":
        audit_logs = audit_logs.order_by(*order_value("user__last_name", "user__first_name", "created_at"))
    else:
        audit_logs = audit_logs.order_by(*order_value("created_at"))

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
                "name": _format_person_name(
                    getattr(log.user, "first_name", None),
                    getattr(log.user, "middle_name", None),
                    getattr(log.user, "last_name", None),
                ) if log.user else "System",
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
    rejected_farmers = User.objects.filter(is_verified=2).count()

    approved_businesses = Business.objects.filter(is_verified__in=[1, True, "1"]).count()
    pending_businesses = Business.objects.filter(is_verified__in=[0, None]).count()
    rejected_businesses = Business.objects.filter(is_verified=2).count()

    healthy_logistics = Vehicle.objects.filter(current_health_status=1).count()
    pending_logistics = Vehicle.objects.filter(current_health_status__in=[0, None]).count()
    maintenance_logistics = Vehicle.objects.filter(current_health_status=2).count()
    disabled_logistics = Vehicle.objects.filter(current_health_status=3).count()

    recent_logs = AuditLog.objects.select_related("user").order_by("-created_at")[:8]

    summary = {
        "farmers": farmers_count,
        "logistics": logistics_count,
        "businesses": businesses_count,
        "verified_farmers": verified_farmers,
        "pending_farmers": pending_farmers,
        "rejected_farmers": rejected_farmers,
        "approved_businesses": approved_businesses,
        "pending_businesses": pending_businesses,
        "rejected_businesses": rejected_businesses,
        "healthy_logistics": healthy_logistics,
        "pending_logistics": pending_logistics,
        "maintenance_logistics": maintenance_logistics,
        "disabled_logistics": disabled_logistics,
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


def dashboard_users(request, section_override=None):
    query = (request.GET.get("q") or "").strip()
    sort_field = request.GET.get("sort_field", "last_name")
    sort_dir = request.GET.get("sort_dir", "asc")
    status_filter = request.GET.get("status_filter", "all")
    section = section_override or (request.POST.get("section") or request.GET.get("section") or "farmers").strip() or "farmers"
    legacy_sort = request.GET.get("sort")
    if legacy_sort and not sort_field:
        sort_field = legacy_sort

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
        dashboard_url = _dashboard_url(section)
        separator = "&" if "?" in dashboard_url else "?"
        return redirect(
            f"{dashboard_url}{separator}q={query}&sort_field={sort_field}&sort_dir={sort_dir}&status_filter={status_filter}"
        )

    sidebar_sections = [
        {"key": "farmers", "label": "Farmers"},
        {"key": "logistics", "label": "Logistics"},
        {"key": "businesses", "label": "Businesses"},
        {"key": "reports", "label": "Reports"},
        {"key": "audit_logs", "label": "Audit Logs"},
    ]

    if not database_ready_for_dashboard():
        return render(
            request,
            "api/dashboard.html",
            {
                "rows": [],
                "query": query,
                "sort_field": sort_field,
                "sort_dir": sort_dir,
                "status_filter": status_filter,
                "section": section,
                "dashboard_url": _dashboard_url(section),
                "sections": sidebar_sections,
                "db_error": """The database tables for this app have not been created yet. 
                Run your migrations or connect the project to the correct database.""",
            },
        )

    dashboard_rows = _dashboard_stage_rows(section, query, sort_field, sort_dir, status_filter)

    return render(
        request,
        "api/dashboard.html",
        {
            "rows": dashboard_rows,
            "query": query,
            "sort_field": sort_field,
            "sort_dir": sort_dir,
            "status_filter": status_filter,
            "section": section,
            "dashboard_url": _dashboard_url(section),
            "sections": sidebar_sections,
        },
    )

def dashboard_entity_form(request, section="farmers"):
    if section == "businesses":
        from businesses.views import create
    elif section == "logistics":
        from logistics.views import create
    else:
        return redirect(_dashboard_url("farmers"))

    return create(request)


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
                "dashboard_url": _dashboard_url("farmers"),
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
                    "phone": phone,
                    "farm": farm,
                    "address": address,
                    "dashboard_url": _dashboard_url("farmers"),
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

        return redirect(_dashboard_url("farmers"))

    return render(
        request,
        "api/user_form.html",
        {
            "user": user,
            "phone": phone,
            "farm": farm,
            "address": address,
            "dashboard_url": _dashboard_url("farmers"),
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
        return redirect(_dashboard_url("farmers"))
    return render(request, "api/user_delete_confirm.html", {"user": user})



