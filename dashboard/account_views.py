from urllib.parse import urlsplit

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import DatabaseError, connection
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from businesses.models import BulkBuyer
from logistics.models import LogisticsCompany, Vehicle
from shared.code_workflows import (
    AccountWorkflowConflict,
    AccountWorkflowValidationError,
    issue_account_code,
    manually_verify_account,
    mark_account_code_mailed,
    review_account_code_request,
)
from shared.models import AccountCodeRequest, AuditLog, EmailAddress, PhoneNumber

from .permissions import (
    dashboard_navigation,
    dashboard_permission_required,
    has_dashboard_permission,
)
from .services import DASHBOARD_PAGE_SIZE

KINDS = {"businesses": "Bulk Buyer", "logistics": "Logistics"}
AUDIT_ACTION_LABELS = {
    "CODE_REQUEST_APPROVED": "Request approved",
    "CODE_REQUEST_REJECTED": "Request rejected",
    "CODE_ISSUED": "Code issued",
    "CODE_MAILED": "Mailing recorded",
    "CODE_EXPIRED": "Code expired",
    "ACCOUNT_MANUALLY_VERIFIED": "Account manually verified",
}


def _kind_label(kind):
    from django.http import Http404

    if kind not in KINDS:
        raise Http404
    return KINDS[kind]


def _table_ready():
    try:
        tables = {name.casefold() for name in connection.introspection.table_names()}
        return AccountCodeRequest._meta.db_table.casefold() in tables
    except DatabaseError:
        return False


def _document_link(value):
    value = (value or "").strip()
    if not value or "\\" in value or any(ord(char) < 32 for char in value):
        return ""
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""
    if parsed.scheme.lower() in ("http", "https") and parsed.netloc:
        return value
    return ""


@never_cache
@require_http_methods(["GET", "POST"])
@dashboard_permission_required("farmers.view_farmer_code_requests")
def account_code_requests(request, kind):
    label = _kind_label(kind)
    can_review = has_dashboard_permission(
        request.user, "farmers.review_farmer_code_requests"
    )
    can_issue = has_dashboard_permission(request.user, "farmers.issue_farmer_codes")
    can_view_detail = can_review and has_dashboard_permission(
        request.user, "farmers.view_farmer_applications"
    )
    context = {
        "kind": kind,
        "kind_label": label,
        "section": "code_requests",
        "sections": dashboard_navigation(request.user),
        "statuses": AccountCodeRequest.Status.choices,
        "selected_status": "all",
        "can_review": can_review,
        "can_issue": can_issue,
        "can_view_detail": can_view_detail,
    }
    if not _table_ready():
        context["db_error"] = "The account code-request table is not available yet."
        return render(request, "dashboard/account_code_requests.html", context)

    if request.method == "POST":
        from .verification_views import return_to_unified_queue

        action = request.POST.get("action")
        if action in ("approve", "reject"):
            allowed = can_review
        elif action in ("issue", "mark_mailed"):
            allowed = can_issue
        else:
            raise PermissionDenied
        if not allowed:
            raise PermissionDenied
        request_id = request.POST.get("request_id", "")
        if not request_id.isdigit():
            messages.error(request, "Code request not found.")
            return return_to_unified_queue(request) or redirect(
                "dashboard_account_code_requests", kind=kind
            )
        code_request = get_object_or_404(
            AccountCodeRequest, request_id=int(request_id), kind=kind
        )
        try:
            if action in ("approve", "reject"):
                code_request = review_account_code_request(
                    code_request.request_id,
                    request.user,
                    action,
                    (request.POST.get("reason") or "").strip(),
                    request=request,
                )
                messages.success(request, f"Request {code_request.status}.")
            elif action == "issue":
                code_request, code, expires_at = issue_account_code(
                    code_request.request_id, request.user, request=request
                )
                request.session["issued_account_code"] = {
                    "kind": kind,
                    "request_id": code_request.request_id,
                    "code": code,
                    "expires_at": expires_at.isoformat(),
                }
                messages.success(
                    request, "Code issued. Copy and mail it now; it is shown once."
                )
            else:
                mark_account_code_mailed(
                    code_request.request_id, request.user, request=request
                )
                messages.success(request, "Mailing recorded.")
        except AccountCodeRequest.DoesNotExist:
            messages.error(request, "Code request not found.")
        except (AccountWorkflowValidationError, AccountWorkflowConflict) as exc:
            messages.error(request, str(exc))
        return return_to_unified_queue(request) or redirect(
            "dashboard_account_code_requests", kind=kind
        )

    selected_status = request.GET.get("status", "all")
    if (
        selected_status != "all"
        and selected_status not in AccountCodeRequest.Status.values
    ):
        context["error"] = "Select a valid status filter."
        return render(request, "dashboard/account_code_requests.html", context)
    code_requests = (
        AccountCodeRequest.objects.filter(kind=kind)
        .select_related("user")
        .prefetch_related(
            Prefetch(
                "user__phone_numbers", queryset=PhoneNumber.objects.order_by("phone_id")
            )
        )
        .order_by("requested_at", "request_id")
    )
    if selected_status != "all":
        code_requests = code_requests.filter(status=selected_status)
    page_obj = Paginator(code_requests, DASHBOARD_PAGE_SIZE).get_page(
        request.GET.get("page")
    )
    for item in page_obj.object_list:
        phone = next(iter(item.user.phone_numbers.all()), None)
        item.phone_number = phone.mobile_number if phone else None
    issued_code = request.session.get("issued_account_code")
    if issued_code and issued_code.get("kind") == kind:
        request.session.pop("issued_account_code")
        if not can_issue:
            issued_code = None
    else:
        issued_code = None
    context.update(
        code_requests=page_obj.object_list,
        page_obj=page_obj,
        selected_status=selected_status,
        issued_code=issued_code,
    )
    return render(request, "dashboard/account_code_requests.html", context)


@never_cache
@require_http_methods(["GET", "POST"])
@dashboard_permission_required("farmers.view_farmer_code_requests")
def account_code_request_detail(request, kind, request_id):
    label = _kind_label(kind)
    if not (
        has_dashboard_permission(request.user, "farmers.review_farmer_code_requests")
        and has_dashboard_permission(request.user, "farmers.view_farmer_applications")
    ):
        raise PermissionDenied
    code_request = get_object_or_404(
        AccountCodeRequest.objects.select_related("user", "user__personal_address"),
        request_id=request_id,
        kind=kind,
    )
    can_manually_verify = has_dashboard_permission(
        request.user, "farmers.manually_verify_farmer"
    )
    if request.method == "POST":
        if (
            not can_manually_verify
            or request.POST.get("action", "manual_verify") != "manual_verify"
        ):
            raise PermissionDenied
        reason = (request.POST.get("reason") or "").strip()
        try:
            if not reason:
                raise AccountWorkflowValidationError("A reason is required.")
            manually_verify_account(request_id, request.user, reason, request=request)
            messages.success(request, "Account manually verified.")
        except AccountCodeRequest.DoesNotExist:
            messages.error(request, "Code request not found.")
        except (AccountWorkflowValidationError, AccountWorkflowConflict) as exc:
            messages.error(request, str(exc))
        return redirect(
            "dashboard_account_code_request_detail", kind=kind, request_id=request_id
        )

    account = code_request.user
    organization = None
    vehicle = None
    if kind == "businesses":
        organization = (
            BulkBuyer.objects.filter(user=account, date_time_deleted__isnull=True)
            .select_related("address")
            .order_by("business_id")
            .first()
        )
    else:
        organization = (
            LogisticsCompany.objects.filter(
                user=account, date_time_deleted__isnull=True
            )
            .select_related("address")
            .first()
        )
        if organization:
            vehicle = (
                Vehicle.objects.filter(
                    user=account,
                    logistics_business=organization,
                    deleted_at__isnull=True,
                )
                .order_by("vehicle_id")
                .first()
            )
    audit_events = list(
        AuditLog.objects.filter(
            target_table="ACCOUNT_CODE_REQUESTS", target_id=request_id
        )
        .order_by("-created_at", "-log_id")
        .values("created_at", "action_type", "staff_user__username")
    )
    for event in audit_events:
        event["label"] = AUDIT_ACTION_LABELS.get(event["action_type"], "Staff activity")
    documents = code_request.user.electronic_documents.filter(
        date_time_deleted__isnull=True
    )
    for document in documents:
        document.safe_file_url = _document_link(document.file_url)
    return render(
        request,
        "dashboard/account_code_request_detail.html",
        {
            "kind": kind,
            "kind_label": label,
            "section": "code_requests",
            "sections": dashboard_navigation(request.user),
            "code_request": code_request,
            "account": account,
            "phone": account.phone_numbers.order_by("phone_id").first(),
            "email": (
                EmailAddress.objects.filter(user=account, deleted_at__isnull=True)
                .order_by("email_id")
                .first()
            ),
            "organization": organization,
            "vehicle": vehicle,
            "audit_events": audit_events,
            "can_manually_verify": can_manually_verify,
            "documents": documents,
        },
    )
