from django.core.paginator import Paginator
from django.db import connection
from django.db.models import OuterRef, Prefetch, Q, Subquery
from django.urls import reverse

from businesses.models import BulkBuyer
from farmers.models import Farm, FarmerCodeRequest
from logistics.models import Vehicle
from shared.models import (
    Address,
    AuditLog,
    ElectronicDocument,
    PhoneNumber,
    User,
)

DASHBOARD_PAGE_SIZE = 50

DASHBOARD_SECTIONS = [
    {"key": "reports", "label": "Reports"},
    {"key": "farmers", "label": "Farmers"},
    {"key": "code_requests", "label": "Farmer Code Requests"},
    {"key": "logistics", "label": "Logistics"},
    {"key": "businesses", "label": "Bulk Buyers"},
    {"key": "audit_logs", "label": "Audit Logs"},
]


def database_ready_for_dashboard():
    required_models = (
        User,
        FarmerCodeRequest,
        PhoneNumber,
        Farm,
        Address,
        ElectronicDocument,
        Vehicle,
        BulkBuyer,
        AuditLog,
    )
    required_tables = {model._meta.db_table.casefold() for model in required_models}
    try:
        existing_tables = {
            name.casefold() for name in connection.introspection.table_names()
        }
        return required_tables.issubset(existing_tables)
    except Exception:
        return False


def dashboard_url(section):
    route_names = {
        "farmers": "farmers:dashboard",
        "businesses": "businesses:dashboard",
        "logistics": "logistics:dashboard",
    }
    if section == "audit_logs":
        return reverse("dashboard_audit_logs")
    return reverse(route_names.get(section, "farmers:dashboard"))


def format_person_name(first_name=None, middle_name=None, last_name=None):
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


def _paginate_queryset(queryset, page_number, page_size):
    if page_number is None:
        return queryset, None
    page_obj = Paginator(queryset, page_size).get_page(page_number)
    return page_obj.object_list, page_obj


def _page_result(rows, page_obj):
    return (rows, page_obj) if page_obj is not None else rows


def build_dashboard_rows(
    section,
    query,
    sort_field=None,
    sort_dir="asc",
    status_filter="all",
    page_number=None,
    page_size=DASHBOARD_PAGE_SIZE,
):
    sort_field = sort_field or "last_name"
    sort_dir = sort_dir if sort_dir in {"asc", "desc"} else "asc"
    status_filter = status_filter or "all"
    descending = sort_dir == "desc"

    def order_value(*fields):
        return [f"-{field}" if descending else field for field in fields]

    if section == "farmers":
        creation_date_query = (
            AuditLog.objects.filter(
                target_table="USERS",
                target_id=OuterRef("user_id"),
                action_type="CREATE",
            )
            .order_by("created_at")
            .values("created_at")[:1]
        )
        users = (
            User.objects.annotate(
                dashboard_created_at=Subquery(creation_date_query)
            )
            .select_related("personal_address")
            .prefetch_related(
                Prefetch(
                    "phone_numbers",
                    queryset=PhoneNumber.objects.order_by("phone_id"),
                ),
                Prefetch(
                    "farms",
                    queryset=Farm.objects.select_related("address").order_by(
                        "farm_id"
                    ),
                ),
            )
        )
        if sort_field == "verification":
            users = users.order_by(
                *order_value(
                    "is_verified", "last_name", "first_name", "middle_name", "user_id"
                )
            )
        elif sort_field == "farm_size":
            users = users.order_by(
                *order_value(
                    "farms__farm_size_hectares",
                    "last_name",
                    "first_name",
                    "middle_name",
                    "user_id",
                )
            )
        elif sort_field == "newest":
            users = users.order_by(*order_value("user_id"))
        else:
            users = users.order_by(
                *order_value("last_name", "first_name", "middle_name", "user_id")
            )

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

        users, page_obj = _paginate_queryset(users, page_number, page_size)
        rows = []
        for user in users:
            phone = next(iter(user.phone_numbers.all()), None)
            farm = next(iter(user.farms.all()), None)
            address = farm.address if farm and farm.address else None
            rows.append(
                {
                    "id": user.user_id,
                    "entity": user,
                    "name": format_person_name(
                        user.first_name, user.middle_name, user.last_name
                    ),
                    "phone": phone.mobile_number if phone else "-",
                    "farm_size": farm.farm_size_hectares if farm else "-",
                    "location": ", ".join(
                        part
                        for part in [
                            address.street_address if address else None,
                            address.barangay if address else None,
                            address.municipality_city if address else None,
                            address.province if address else None,
                        ]
                        if part
                    )
                    or "-",
                    "status_value": 1 if user.is_verified in (1, True, "1") else 0,
                    "status_label": "Verified"
                    if user.is_verified in (1, True, "1")
                    else "Pending",
                    "status_options": [
                        (0, "Pending"),
                        (1, "Verified"),
                        (2, "Rejected"),
                    ],
                    "created_at": user.dashboard_created_at,
                }
            )
        return _page_result(rows, page_obj)

    if section == "logistics":
        creation_date_query = (
            AuditLog.objects.filter(
                target_table="VEHICLES",
                target_id=OuterRef("vehicle_id"),
                action_type="CREATE",
            )
            .order_by("created_at")
            .values("created_at")[:1]
        )
        vehicles = Vehicle.objects.select_related("user").annotate(
            dashboard_created_at=Subquery(creation_date_query)
        )
        if sort_field == "status":
            vehicles = vehicles.order_by(
                *order_value(
                    "current_health_status",
                    "user__last_name",
                    "user__first_name",
                    "vehicle_id",
                )
            )
        elif sort_field == "capacity":
            vehicles = vehicles.order_by(
                *order_value(
                    "max_weight_capacity_kg",
                    "user__last_name",
                    "user__first_name",
                    "vehicle_id",
                )
            )
        elif sort_field == "plate_number":
            vehicles = vehicles.order_by(
                *order_value(
                    "plate_number", "user__last_name", "user__first_name", "vehicle_id"
                )
            )
        else:
            vehicles = vehicles.order_by(
                *order_value(
                    "user__last_name",
                    "user__first_name",
                    "user__middle_name",
                    "vehicle_id",
                )
            )

        status_filters = {
            "pending": {"current_health_status__in": [0, None]},
            "healthy": {"current_health_status": 1},
            "maintenance": {"current_health_status": 2},
            "disabled": {"current_health_status": 3},
        }
        if status_filter in status_filters:
            vehicles = vehicles.filter(**status_filters[status_filter])
        if query:
            vehicles = vehicles.filter(
                Q(plate_number__icontains=query)
                | Q(truck_model__icontains=query)
                | Q(user__first_name__icontains=query)
                | Q(user__last_name__icontains=query)
            )

        vehicles, page_obj = _paginate_queryset(vehicles, page_number, page_size)
        rows = []
        for vehicle in vehicles:
            owner = vehicle.user
            name = (
                format_person_name(
                    getattr(owner, "first_name", None),
                    getattr(owner, "middle_name", None),
                    getattr(owner, "last_name", None),
                )
                if owner
                else "Unassigned"
            )
            status_value = int(vehicle.current_health_status or 0)
            rows.append(
                {
                    "id": vehicle.vehicle_id,
                    "entity": vehicle,
                    "name": name,
                    "plate_number": vehicle.plate_number or "-",
                    "model": vehicle.truck_model or "-",
                    "status_value": status_value,
                    "status_label": {
                        0: "Pending",
                        1: "Healthy",
                        2: "Maintenance",
                        3: "Disabled",
                    }.get(status_value, "Pending"),
                    "status_options": [
                        (0, "Pending"),
                        (1, "Healthy"),
                        (2, "Maintenance"),
                        (3, "Disabled"),
                    ],
                    "created_at": vehicle.dashboard_created_at,
                }
            )
        return _page_result(rows, page_obj)

    if section == "businesses":
        creation_date_query = (
            AuditLog.objects.filter(
                target_table__in=["BULK_BUYERS", "BUSINESSES"],
                target_id=OuterRef("business_id"),
                action_type="CREATE",
            )
            .order_by("created_at")
            .values("created_at")[:1]
        )
        bulk_buyers = BulkBuyer.objects.select_related("user").annotate(
            dashboard_created_at=Subquery(creation_date_query)
        )
        if sort_field == "status":
            bulk_buyers = bulk_buyers.order_by(
                *order_value("is_verified", "business_name", "user__last_name")
            )
        elif sort_field == "owner":
            bulk_buyers = bulk_buyers.order_by(
                *order_value("user__last_name", "user__first_name", "business_name")
            )
        else:
            bulk_buyers = bulk_buyers.order_by(
                *order_value("business_name", "user__last_name", "user__first_name")
            )

        status_filters = {
            "pending": {"is_verified__in": [0, None]},
            "approved": {"is_verified__in": [1, True, "1"]},
            "rejected": {"is_verified": 2},
        }
        if status_filter in status_filters:
            bulk_buyers = bulk_buyers.filter(**status_filters[status_filter])
        if query:
            bulk_buyers = bulk_buyers.filter(
                Q(business_name__icontains=query)
                | Q(registration_number__icontains=query)
                | Q(user__first_name__icontains=query)
                | Q(user__last_name__icontains=query)
            )

        bulk_buyers, page_obj = _paginate_queryset(
            bulk_buyers, page_number, page_size
        )
        rows = []
        for bulk_buyer in bulk_buyers:
            owner = bulk_buyer.user
            creation_date = (
                bulk_buyer.date_time_created or bulk_buyer.dashboard_created_at
            )
            rows.append(
                {
                    "id": bulk_buyer.business_id,
                    "entity": bulk_buyer,
                    "name": bulk_buyer.business_name or "-",
                    "owner": format_person_name(
                        getattr(owner, "first_name", None),
                        getattr(owner, "middle_name", None),
                        getattr(owner, "last_name", None),
                    )
                    if owner
                    else "-",
                    "registration_number": bulk_buyer.registration_number or "-",
                    "status_value": 1
                    if bulk_buyer.is_verified in (1, True, "1")
                    else 0,
                    "status_label": "Approved"
                    if bulk_buyer.is_verified in (1, True, "1")
                    else "Pending",
                    "status_options": [
                        (0, "Pending"),
                        (1, "Approved"),
                        (2, "Rejected"),
                    ],
                    "created_at": creation_date,
                }
            )
        return _page_result(rows, page_obj)

    audit_logs = AuditLog.objects.select_related("user", "staff_user")
    if sort_field == "action":
        audit_logs = audit_logs.order_by(*order_value("action_type", "created_at"))
    elif sort_field == "user":
        audit_logs = audit_logs.order_by(
            *order_value("user__last_name", "user__first_name", "created_at")
        )
    else:
        audit_logs = audit_logs.order_by(*order_value("created_at"))
    if query:
        audit_logs = audit_logs.filter(
            Q(action_type__icontains=query)
            | Q(target_table__icontains=query)
            | Q(user__first_name__icontains=query)
            | Q(user__last_name__icontains=query)
        )

    audit_logs, page_obj = _paginate_queryset(audit_logs, page_number, page_size)
    rows = [
        {
            "id": log.log_id,
            "entity": log,
            "name": (
                log.staff_user.get_username()
                if log.staff_user
                else format_person_name(
                    getattr(log.user, "first_name", None),
                    getattr(log.user, "middle_name", None),
                    getattr(log.user, "last_name", None),
                )
                if log.user
                else "System"
            ),
            "action": log.action_type or "-",
            "target": log.target_table or "-",
            "status_label": "Recorded",
            "status_value": 1,
            "status_options": [(1, "Recorded")],
            "created_at": log.created_at,
        }
        for log in audit_logs
    ]
    return _page_result(rows, page_obj)
