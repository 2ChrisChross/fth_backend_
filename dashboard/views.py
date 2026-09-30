from django.shortcuts import redirect, render

from businesses.models import BulkBuyer
from logistics.models import Vehicle
from shared.audit import _log_audit_change, _serialize_model
from shared.models import AuditLog, User

from .bulk_buyer_views import business_create
from .farmer_views import dashboard_user_delete, dashboard_user_form
from .services import (
    DASHBOARD_SECTIONS,
    build_dashboard_rows,
    database_ready_for_dashboard,
)
from .services import (
    dashboard_url as _dashboard_url,
)
from .vehicle_views import logistics_create


def dashboard_reports(request):
    if not database_ready_for_dashboard():
        return render(
            request,
            "dashboard/reports.html",
            {
                "section": "reports",
                "sections": DASHBOARD_SECTIONS,
                "summary": {},
                "recent_logs": [],
                "db_error": (
                    "The database tables for this app have not been created yet. "
                    "Run your migrations or connect the correct database."
                ),
            },
        )

    farmers_count = User.objects.count()
    logistics_count = Vehicle.objects.count()
    bulk_buyers_count = BulkBuyer.objects.count()

    verified_farmers = User.objects.filter(is_verified__in=[1, True, "1"]).count()
    pending_farmers = User.objects.filter(is_verified__in=[0, None]).count()
    rejected_farmers = User.objects.filter(is_verified=2).count()

    approved_bulk_buyers = BulkBuyer.objects.filter(
        is_verified__in=[1, True, "1"]
    ).count()
    pending_bulk_buyers = BulkBuyer.objects.filter(is_verified__in=[0, None]).count()
    rejected_bulk_buyers = BulkBuyer.objects.filter(is_verified=2).count()

    healthy_logistics = Vehicle.objects.filter(current_health_status=1).count()
    pending_logistics = Vehicle.objects.filter(
        current_health_status__in=[0, None]
    ).count()
    maintenance_logistics = Vehicle.objects.filter(current_health_status=2).count()
    disabled_logistics = Vehicle.objects.filter(current_health_status=3).count()

    recent_logs = AuditLog.objects.select_related("user").order_by("-created_at")[:8]
    summary = {
        "farmers": farmers_count,
        "logistics": logistics_count,
        "bulk_buyers": bulk_buyers_count,
        "verified_farmers": verified_farmers,
        "pending_farmers": pending_farmers,
        "rejected_farmers": rejected_farmers,
        "approved_bulk_buyers": approved_bulk_buyers,
        "pending_bulk_buyers": pending_bulk_buyers,
        "rejected_bulk_buyers": rejected_bulk_buyers,
        "healthy_logistics": healthy_logistics,
        "pending_logistics": pending_logistics,
        "maintenance_logistics": maintenance_logistics,
        "disabled_logistics": disabled_logistics,
    }

    return render(
        request,
        "dashboard/reports.html",
        {
            "section": "reports",
            "summary": summary,
            "recent_logs": recent_logs,
            "sections": DASHBOARD_SECTIONS,
        },
    )


def dashboard_users(request, section_override=None):
    query = (request.GET.get("q") or "").strip()
    sort_field = request.GET.get("sort_field", "last_name")
    sort_dir = request.GET.get("sort_dir", "asc")
    status_filter = request.GET.get("status_filter", "all")
    section = (
        section_override
        or (
            request.POST.get("section") or request.GET.get("section") or "reports"
        ).strip()
        or "reports"
    )

    if section == "reports" and request.method == "GET":
        return dashboard_reports(request)
    if section == "audit_logs" and section_override is None and request.method == "GET":
        return redirect("dashboard_audit_logs")

    if request.method == "POST":
        target_id = request.POST.get("target_id")
        stage = request.POST.get("stage")
        if target_id and stage is not None:
            try:
                stage_value = int(stage)
            except TypeError, ValueError:
                stage_value = None

            if stage_value is not None and section == "farmers":
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
            elif stage_value is not None and section == "logistics":
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
                        old_values={
                            "current_health_status": previous.get(
                                "current_health_status"
                            )
                        },
                        new_values={
                            "current_health_status": vehicle.current_health_status
                        },
                        request=request,
                    )
            elif stage_value is not None and section == "businesses":
                bulk_buyer = BulkBuyer.objects.filter(business_id=target_id).first()
                if bulk_buyer is not None:
                    previous = _serialize_model(bulk_buyer)
                    bulk_buyer.is_verified = stage_value
                    bulk_buyer.save(update_fields=["is_verified"])
                    _log_audit_change(
                        user=bulk_buyer.user,
                        action_type="UPDATE_STATUS",
                        target_table="BULK_BUYERS",
                        target_id=bulk_buyer.business_id,
                        old_values={"is_verified": previous.get("is_verified")},
                        new_values={"is_verified": bulk_buyer.is_verified},
                        request=request,
                    )

        destination = _dashboard_url(section)
        separator = "&" if "?" in destination else "?"
        return redirect(
            f"{destination}{separator}q={query}&sort_field={sort_field}&sort_dir={sort_dir}&status_filter={status_filter}"
        )

    section_title = (
        "Bulk Buyers" if section == "businesses" else section.replace("_", " ").title()
    )
    context = {
        "rows": [],
        "query": query,
        "sort_field": sort_field,
        "sort_dir": sort_dir,
        "status_filter": status_filter,
        "section": section,
        "section_title": section_title,
        "dashboard_url": _dashboard_url(section),
        "sections": DASHBOARD_SECTIONS,
    }
    if not database_ready_for_dashboard():
        context["db_error"] = (
            "The database tables for this app have not been created yet. "
            "Run your migrations or connect the project to the correct database."
        )
    else:
        context["rows"] = build_dashboard_rows(
            section, query, sort_field, sort_dir, status_filter
        )
    return render(request, "dashboard/records.html", context)


def dashboard_audit_logs(request):
    return dashboard_users(request, section_override="audit_logs")


def dashboard_entity_form(request, section="farmers"):
    if section == "businesses":
        return business_create(request)
    if section == "logistics":
        return logistics_create(request)
    return redirect(_dashboard_url("farmers"))


def farmers_dashboard(request):
    return dashboard_users(request, section_override="farmers")


def farmer_create(request):
    return dashboard_user_form(request)


def farmer_edit(request, user_id):
    return dashboard_user_form(request, user_id=user_id)


def farmer_delete(request, user_id):
    return dashboard_user_delete(request, user_id)


def businesses_dashboard(request):
    return dashboard_users(request, section_override="businesses")


def logistics_dashboard(request):
    return dashboard_users(request, section_override="logistics")
