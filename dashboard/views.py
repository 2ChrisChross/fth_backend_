from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from businesses.models import BulkBuyer
from farmers.models import FarmerCodeRequest
from farmers.workflows import (
    FarmerWorkflowConflict,
    FarmerWorkflowValidationError,
    issue_farmer_code,
    manually_verify_farmer,
    mark_farmer_code_mailed,
    review_farmer_code_request,
)
from logistics.models import Vehicle
from shared.models import AuditLog, PhoneNumber, User

from .bulk_buyer_views import business_create
from .farmer_views import dashboard_user_delete, dashboard_user_form
from .forms import DashboardAuthenticationForm
from .permissions import (
    dashboard_navigation,
    dashboard_permission_required,
    has_dashboard_permission,
)
from .services import (
    DASHBOARD_PAGE_SIZE,
    build_dashboard_rows,
    database_ready_for_dashboard,
)
from .services import dashboard_url as _dashboard_url
from .vehicle_views import logistics_create
from .workflows import (
    DashboardWorkflowNotFound,
    DashboardWorkflowValidationError,
    update_dashboard_status,
)


class DashboardLoginView(LoginView):
    template_name = "dashboard/login.html"
    authentication_form = DashboardAuthenticationForm


@require_POST
@login_required(login_url="dashboard_login")
def dashboard_logout(request):
    logout(request)
    return redirect("dashboard_login")


@never_cache
@dashboard_permission_required("farmers.view_farmer_code_requests")
def farmer_code_requests(request):
    if not database_ready_for_dashboard():
        return render(
            request,
            "dashboard/farmer_code_requests.html",
            {
                "code_requests": [],
                "page_obj": None,
                "statuses": FarmerCodeRequest.Status.choices,
                "selected_status": "all",
                "section": "code_requests",
                "sections": dashboard_navigation(request.user),
                "can_review": has_dashboard_permission(
                    request.user, "farmers.review_farmer_code_requests"
                ),
                "can_issue": has_dashboard_permission(
                    request.user, "farmers.issue_farmer_codes"
                ),
                "db_error": "The farmer code-request table is not available yet.",
            },
        )

    selected_status = request.GET.get("status", "all")
    if (
        selected_status != "all"
        and selected_status not in FarmerCodeRequest.Status.values
    ):
        return render(
            request,
            "dashboard/farmer_code_requests.html",
            {
                "code_requests": [],
                "statuses": FarmerCodeRequest.Status.choices,
                "selected_status": "all",
                "farmer_id": request.GET.get("farmer_id", ""),
                "section": "code_requests",
                "sections": dashboard_navigation(request.user),
                "error": "Select a valid status filter.",
                "can_review": has_dashboard_permission(
                    request.user, "farmers.review_farmer_code_requests"
                ),
                "can_issue": has_dashboard_permission(
                    request.user, "farmers.issue_farmer_codes"
                ),
            },
        )

    if request.method == "POST":
        request_id = request.POST.get("request_id")
        action = request.POST.get("action")
        reason = (request.POST.get("reason") or "").strip()
        if action in ("approve", "reject"):
            permission = "farmers.review_farmer_code_requests"
        elif action in ("issue", "mark_mailed"):
            permission = "farmers.issue_farmer_codes"
        else:
            raise PermissionDenied
        if not has_dashboard_permission(request.user, permission):
            raise PermissionDenied
        try:
            if action in ("approve", "reject"):
                code_request = review_farmer_code_request(
                    request_id, request.user, action, reason
                )
                messages.success(request, f"Request {code_request.status}.")
            elif action == "issue":
                code_request, code, expires_at = issue_farmer_code(
                    request_id, request.user
                )
                request.session["issued_farmer_code"] = {
                    "request_id": code_request.request_id,
                    "code": code,
                    "expires_at": expires_at.isoformat(),
                }
                messages.success(
                    request, "Code issued. Copy and mail it now; it is shown once."
                )
            else:
                code_request = mark_farmer_code_mailed(request_id, request.user)
                messages.success(request, "Mailing recorded.")
        except FarmerCodeRequest.DoesNotExist:
            messages.error(request, "Code request not found.")
        except FarmerWorkflowValidationError as exc:
            messages.error(request, str(exc))
        except FarmerWorkflowConflict as exc:
            messages.error(request, str(exc))
        return redirect("dashboard_code_requests")

    code_requests = FarmerCodeRequest.objects.select_related("user").order_by(
        "requested_at"
    ).prefetch_related(
        Prefetch(
            "user__phone_numbers",
            queryset=PhoneNumber.objects.order_by("phone_id"),
        )
    )
    if selected_status != "all":
        code_requests = code_requests.filter(status=selected_status)
    farmer_id = request.GET.get("farmer_id", "").strip()
    if farmer_id:
        if not farmer_id.isdigit():
            messages.error(request, "Enter a valid farmer ID.")
            farmer_id = ""
        else:
            code_requests = code_requests.filter(user_id=int(farmer_id))
    issued_code = request.session.pop("issued_farmer_code", None)
    page_obj = Paginator(code_requests, DASHBOARD_PAGE_SIZE).get_page(
        request.GET.get("page")
    )
    code_requests = list(page_obj.object_list)
    for code_request in code_requests:
        phone = next(iter(code_request.user.phone_numbers.all()), None)
        code_request.phone_number = phone.mobile_number if phone else None

    return render(
        request,
        "dashboard/farmer_code_requests.html",
        {
            "code_requests": code_requests,
            "page_obj": page_obj,
            "statuses": FarmerCodeRequest.Status.choices,
            "selected_status": selected_status,
            "farmer_id": farmer_id,
            "issued_code": issued_code,
            "section": "code_requests",
            "sections": dashboard_navigation(request.user),
            "can_review": has_dashboard_permission(
                request.user, "farmers.review_farmer_code_requests"
            ),
            "can_issue": has_dashboard_permission(
                request.user, "farmers.issue_farmer_codes"
            ),
        },
    )


@dashboard_permission_required("farmers.view_farmer_applications")
def farmer_code_request_detail(request, request_id):
    code_request = get_object_or_404(
        FarmerCodeRequest.objects.select_related("user"),
        request_id=request_id,
    )
    if request.method == "POST":
        if not has_dashboard_permission(
            request.user, "farmers.manually_verify_farmer"
        ):
            raise PermissionDenied
        try:
            manually_verify_farmer(
                code_request.user_id,
                request.user,
                request.POST.get("reason", ""),
            )
            messages.success(request, "Farmer manually verified.")
        except FarmerWorkflowValidationError as exc:
            messages.error(request, str(exc))
        except FarmerWorkflowConflict as exc:
            messages.error(request, str(exc))
        return redirect("dashboard_code_request_detail", request_id=request_id)

    phone = code_request.user.phone_numbers.order_by("phone_id").first()
    return render(
        request,
        "dashboard/farmer_code_request_detail.html",
        {
            "code_request": code_request,
            "section": "code_requests",
            "sections": dashboard_navigation(request.user),
            "farmer": code_request.user,
            "phone": phone,
            "documents": code_request.user.electronic_documents.filter(
                date_time_deleted__isnull=True
            ),
            "audit_events": code_request.admin_events.select_related("staff_user"),
            "can_manually_verify": has_dashboard_permission(
                request.user, "farmers.manually_verify_farmer"
            ),
        },
    )


@dashboard_permission_required("farmers.view_dashboard_reports")
def dashboard_reports(request):
    if not database_ready_for_dashboard():
        return render(
            request,
            "dashboard/reports.html",
            {
                "section": "reports",
                "sections": dashboard_navigation(request.user),
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

    recent_logs = AuditLog.objects.select_related("user", "staff_user").order_by(
        "-created_at"
    )[:8]
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
            "sections": dashboard_navigation(request.user),
            "summary": summary,
            "recent_logs": recent_logs,
        },
    )


@staff_member_required(login_url="dashboard_login")
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

    required_permissions = {
        "reports": "farmers.view_dashboard_reports",
        "farmers": (
            "farmers.view_farmer_applications",
            "farmers.manage_dashboard_records",
        ),
        "businesses": "farmers.manage_dashboard_records",
        "logistics": "farmers.manage_dashboard_records",
        "audit_logs": "farmers.view_dashboard_audit_logs",
    }
    if not has_dashboard_permission(
        request.user,
        required_permissions.get(section, "farmers.manage_dashboard_records"),
    ):
        raise PermissionDenied

    if section == "reports" and request.method == "GET":
        return dashboard_reports(request)
    if section == "audit_logs" and section_override is None and request.method == "GET":
        return redirect("dashboard_audit_logs")

    if request.method == "POST":
        target_id = request.POST.get("target_id")
        stage = request.POST.get("stage")
        if target_id and stage is not None:
            if section not in ("businesses", "logistics"):
                raise PermissionDenied
            try:
                update_dashboard_status(
                    section,
                    target_id,
                    stage,
                    request.user,
                    request,
                )
            except DashboardWorkflowValidationError as exc:
                messages.error(request, str(exc))
            except DashboardWorkflowNotFound as exc:
                messages.error(request, str(exc))

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
        "page_obj": None,
        "query": query,
        "sort_field": sort_field,
        "sort_dir": sort_dir,
        "status_filter": status_filter,
        "section": section,
        "section_title": section_title,
        "dashboard_url": _dashboard_url(section),
        "sections": dashboard_navigation(request.user),
    }
    if not database_ready_for_dashboard():
        context["db_error"] = (
            "The database tables for this app have not been created yet. "
            "Run your migrations or connect the project to the correct database."
        )
    else:
        context["rows"], context["page_obj"] = build_dashboard_rows(
            section,
            query,
            sort_field,
            sort_dir,
            status_filter,
            page_number=request.GET.get("page", 1),
            page_size=DASHBOARD_PAGE_SIZE,
        )
    return render(request, "dashboard/records.html", context)


@dashboard_permission_required("farmers.view_dashboard_audit_logs")
def dashboard_audit_logs(request):
    return dashboard_users(request, section_override="audit_logs")


@dashboard_permission_required("farmers.manage_dashboard_records")
def dashboard_entity_form(request, section="farmers"):
    if section == "businesses":
        return business_create(request)
    if section == "logistics":
        return logistics_create(request)
    return redirect(_dashboard_url("farmers"))


@dashboard_permission_required(
    (
        "farmers.view_farmer_applications",
        "farmers.manage_dashboard_records",
    )
)
def farmers_dashboard(request):
    return dashboard_users(request, section_override="farmers")


@dashboard_permission_required("farmers.manage_dashboard_records")
def farmer_create(request):
    return dashboard_user_form(request)


@dashboard_permission_required("farmers.manage_dashboard_records")
def farmer_edit(request, user_id):
    return dashboard_user_form(request, user_id=user_id)


@dashboard_permission_required("farmers.manage_dashboard_records")
def farmer_delete(request, user_id):
    return dashboard_user_delete(request, user_id)


@dashboard_permission_required("farmers.manage_dashboard_records")
def businesses_dashboard(request):
    return dashboard_users(request, section_override="businesses")


@dashboard_permission_required("farmers.manage_dashboard_records")
def logistics_dashboard(request):
    return dashboard_users(request, section_override="logistics")
