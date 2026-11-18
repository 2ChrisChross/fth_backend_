from django.core.paginator import Paginator
from django.db.models import CharField, F, Prefetch, Value
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from farmers.models import FarmerCodeRequest
from shared.models import AccountCodeRequest, PhoneNumber

from .account_views import _table_ready
from .permissions import (
    dashboard_navigation,
    dashboard_permission_required,
    has_dashboard_permission,
)
from .services import DASHBOARD_PAGE_SIZE, database_ready_for_dashboard

REQUEST_TYPES = {"all", "farmers", "businesses", "logistics"}


def return_to_unified_queue(request):
    if request.GET.get("queue") != "unified":
        return None
    params = request.GET.copy()
    params.pop("queue", None)
    for key in list(params):
        if key not in {"type", "status", "farmer_id", "page"}:
            params.pop(key)
    url = reverse("dashboard_verification_requests")
    return redirect(f"{url}?{params.urlencode()}" if params else url)


@never_cache
@require_GET
@dashboard_permission_required("farmers.view_farmer_code_requests")
def verification_requests(request):
    selected_type = request.GET.get(
        "type", "farmers" if request.GET.get("farmer_id") else "all"
    )
    selected_status = request.GET.get("status", "all")
    farmer_id = request.GET.get("farmer_id", "").strip()
    if selected_type != "farmers":
        farmer_id = ""
    can_review = has_dashboard_permission(
        request.user, "farmers.review_farmer_code_requests"
    )
    can_issue = has_dashboard_permission(request.user, "farmers.issue_farmer_codes")
    can_view_applications = has_dashboard_permission(
        request.user, "farmers.view_farmer_applications"
    )
    context = {
        "section": "code_requests",
        "sections": dashboard_navigation(request.user),
        "selected_type": selected_type,
        "selected_status": selected_status,
        "farmer_id": farmer_id,
        "statuses": FarmerCodeRequest.Status.choices,
        "can_review": can_review,
        "can_issue": can_issue,
        "can_view_farmer_detail": can_view_applications,
        "can_view_account_detail": can_review and can_view_applications,
    }
    if not database_ready_for_dashboard() or not _table_ready():
        context["error"] = (
            "Verification request tables are not available. Run migrations."
        )
        return render(request, "dashboard/verification_requests.html", context)
    if selected_type not in REQUEST_TYPES:
        context["error"] = "Select a valid request type."
        return render(
            request, "dashboard/verification_requests.html", context, status=400
        )
    if (
        selected_status != "all"
        and selected_status not in FarmerCodeRequest.Status.values
    ):
        context["error"] = "Select a valid status filter."
        return render(
            request, "dashboard/verification_requests.html", context, status=400
        )
    if farmer_id and not farmer_id.isdigit():
        context["error"] = "Select a valid farmer ID."
        return render(
            request, "dashboard/verification_requests.html", context, status=400
        )

    farmers = FarmerCodeRequest.objects.all()
    accounts = AccountCodeRequest.objects.all()
    if selected_status != "all":
        farmers = farmers.filter(status=selected_status)
        accounts = accounts.filter(status=selected_status)
    if farmer_id:
        farmers = farmers.filter(user_id=int(farmer_id))
    if selected_type in ("businesses", "logistics"):
        accounts = accounts.filter(kind=selected_type)

    farmer_rows = (
        farmers.order_by()
        .annotate(queue_kind=Value("farmers", output_field=CharField()))
        .values("request_id", "requested_at", "queue_kind")
    )
    account_rows = (
        accounts.order_by()
        .annotate(queue_kind=F("kind"))
        .values("request_id", "requested_at", "queue_kind")
    )
    if selected_type == "farmers":
        rows = farmer_rows
    elif selected_type == "all":
        rows = farmer_rows.union(account_rows)
    else:
        rows = account_rows
    page_obj = Paginator(
        rows.order_by("requested_at", "queue_kind", "request_id"), DASHBOARD_PAGE_SIZE
    ).get_page(request.GET.get("page"))
    page_rows = list(page_obj.object_list)
    phones = Prefetch(
        "user__phone_numbers", queryset=PhoneNumber.objects.order_by("phone_id")
    )
    farmer_ids = [
        row["request_id"] for row in page_rows if row["queue_kind"] == "farmers"
    ]
    account_ids = [
        row["request_id"] for row in page_rows if row["queue_kind"] != "farmers"
    ]
    farmer_items = (
        FarmerCodeRequest.objects.select_related("user")
        .prefetch_related(phones)
        .in_bulk(farmer_ids)
    )
    account_items = (
        AccountCodeRequest.objects.select_related("user")
        .prefetch_related(phones)
        .in_bulk(account_ids)
    )
    items = []
    for row in page_rows:
        kind = row["queue_kind"]
        item = (farmer_items if kind == "farmers" else account_items).get(
            row["request_id"]
        )
        if item is None:
            continue
        item.queue_kind = kind
        phone = next(iter(item.user.phone_numbers.all()), None)
        item.phone_number = phone.mobile_number if phone else None
        items.append(item)

    farmer_code = request.session.pop("issued_farmer_code", None)
    account_code = request.session.pop("issued_account_code", None)
    issued_codes = []
    if farmer_code:
        issued_codes.append({**farmer_code, "kind": "farmers"})
    if account_code:
        issued_codes.append(account_code)
    context.update(
        code_requests=items,
        page_obj=page_obj,
        issued_codes=[code for code in issued_codes if code] if can_issue else [],
    )
    return render(request, "dashboard/verification_requests.html", context)
