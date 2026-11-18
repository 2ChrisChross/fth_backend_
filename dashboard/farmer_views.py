from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from farmers.models import Crop, Farm, FarmerCodeRequest, FarmerDocumentRequest
from farmers.workflows import (
    FarmerWorkflowConflict,
    FarmerWorkflowValidationError,
    document_type_choices,
    manually_verify_farmer,
    request_farmer_documents,
    revoke_farmer_document_request,
)
from shared.audit import log_staff_audit_change
from shared.models import (
    ElectronicDocument,
)

from .filters import DashboardFilterForm, apply_farm_filters
from .permissions import (
    dashboard_navigation,
    dashboard_permission_required,
    has_dashboard_permission,
)
from .services import (
    calendar_status_labels,
    dashboard_url,
    database_ready_for_dashboard,
    farm_crops_with_stage,
    farmer_users,
)


def _farmer_audit_values(user, phone, farm):
    address = farm.address if farm and farm.address else None
    return {
        "first_name": user.first_name,
        "middle_name": user.middle_name,
        "last_name": user.last_name,
        "phone_number": phone.mobile_number if phone else None,
        "farm_size_hectares": farm.farm_size_hectares if farm else None,
        "farm_address": {
            "street_address": address.street_address,
            "barangay": address.barangay,
            "municipality_city": address.municipality_city,
            "province": address.province,
            "gps_coordinates": address.gps_coordinates,
        }
        if address
        else None,
    }


@dashboard_permission_required(
    ("farmers.view_farmer_applications", "farmers.manage_dashboard_records")
)
def farmer_detail(request, user_id):
    if not database_ready_for_dashboard():
        return render(
            request,
            "dashboard/farmer_detail.html",
            {
                "section": "farmers",
                "sections": dashboard_navigation(request.user),
                "active_view": "information",
                "db_error": "The farmer and farm tables are not available yet.",
            },
        )

    farmer = get_object_or_404(
        farmer_users().select_related("personal_address"),
        user_id=user_id,
        deleted_at__isnull=True,
    )
    active_view = request.GET.get("view", "information")
    if active_view not in ("information", "farms"):
        active_view = "information"

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "manual_verify" and has_dashboard_permission(
                request.user, "farmers.manually_verify_farmer"
            ):
                manually_verify_farmer(
                    farmer.user_id,
                    request.user,
                    request.POST.get("reason", ""),
                    request=request,
                )
                messages.success(request, "Farmer manually verified.")
            elif action == "request_documents" and has_dashboard_permission(
                request.user, "farmers.request_farmer_documents"
            ):
                created = request_farmer_documents(
                    farmer.user_id,
                    request.user,
                    request.POST.getlist("doc_types"),
                    request.POST.get("message", ""),
                    request=request,
                )
                messages.success(
                    request, f"Requested {len(created)} document(s) from the farmer."
                )
            elif action == "revoke_document_request" and has_dashboard_permission(
                request.user, "farmers.request_farmer_documents"
            ):
                doc_request = get_object_or_404(
                    FarmerDocumentRequest,
                    request_id=int(request.POST.get("request_id") or 0)
                    if str(request.POST.get("request_id") or "0").isdigit()
                    else 0,
                    user=farmer,
                )
                revoke_farmer_document_request(
                    doc_request.request_id,
                    request.user,
                    request.POST.get("reason", ""),
                    request=request,
                )
                messages.success(request, "Document request revoked.")
            else:
                raise PermissionDenied
        except (FarmerWorkflowValidationError, FarmerWorkflowConflict) as exc:
            messages.error(request, str(exc))
        return redirect(f"{request.path}?view=information")

    phone = farmer.phone_numbers.order_by("phone_id").first()
    can_view_applications = has_dashboard_permission(
        request.user, "farmers.view_farmer_applications"
    )
    documents = (
        ElectronicDocument.objects.filter(
            user=farmer,
            date_time_deleted__isnull=True,
        )
        if can_view_applications
        else []
    )
    code_requests = FarmerCodeRequest.objects.filter(user=farmer).order_by(
        "-requested_at"
    )[:6]
    farm_count = farmer.farms.count()
    type_choices = document_type_choices()
    type_labels = dict(type_choices)
    document_requests = list(
        FarmerDocumentRequest.objects.filter(user=farmer)
        .select_related("requested_by", "document")
        .order_by("-requested_at", "-request_id")[:30]
    )
    for doc_request in document_requests:
        doc_request.doc_label = type_labels.get(
            doc_request.doc_type, f"Document type {doc_request.doc_type}"
        )
    page_obj = None
    farms = []
    farm_status = request.GET.get("farm_status", "active")
    farm_size_filter = request.GET.get("farm_size", "all")
    farm_search = (request.GET.get("farm_search") or "").strip()
    farm_sort = request.GET.get("farm_sort", "newest")
    filter_form = DashboardFilterForm("farms", request.GET)
    filter_valid = active_view != "farms" or filter_form.is_valid()
    filter_params = request.GET.copy()
    filter_params.pop("page", None)

    if active_view == "farms" and filter_valid:
        farm_queryset = (
            Farm.objects.filter(user=farmer)
            .select_related("address")
            .annotate(
                active_crop_count=Count(
                    "crops",
                    filter=Q(crops__deleted_at__isnull=True),
                    distinct=True,
                )
            )
        )
        if farm_status == "active":
            farm_queryset = farm_queryset.filter(deleted_at__isnull=True)
        elif farm_status == "archived":
            farm_queryset = farm_queryset.filter(deleted_at__isnull=False)
        elif farm_status != "all":
            farm_status = "active"
            farm_queryset = farm_queryset.filter(deleted_at__isnull=True)

        if farm_size_filter == "under_1":
            farm_queryset = farm_queryset.filter(farm_size_hectares__lt=1)
        elif farm_size_filter == "1_to_10":
            farm_queryset = farm_queryset.filter(
                farm_size_hectares__gte=1,
                farm_size_hectares__lt=10,
            )
        elif farm_size_filter == "10_plus":
            farm_queryset = farm_queryset.filter(farm_size_hectares__gte=10)
        elif farm_size_filter != "all":
            farm_size_filter = "all"

        if farm_search:
            farm_queryset = farm_queryset.filter(
                Q(address__street_address__icontains=farm_search)
                | Q(address__barangay__icontains=farm_search)
                | Q(address__municipality_city__icontains=farm_search)
                | Q(address__province__icontains=farm_search)
                | Q(address__postal_code__icontains=farm_search)
            )

        farm_queryset = apply_farm_filters(farm_queryset, filter_form.cleaned_data)
        if farm_sort == "size_asc":
            farm_queryset = farm_queryset.order_by("farm_size_hectares", "farm_id")
        elif farm_sort == "size_desc":
            farm_queryset = farm_queryset.order_by("-farm_size_hectares", "farm_id")
        else:
            farm_sort = "newest"
            farm_queryset = farm_queryset.order_by("-farm_id")
        farm_queryset = farm_queryset.prefetch_related(
            Prefetch(
                "crops",
                queryset=Crop.objects.filter(deleted_at__isnull=True)
                .select_related("crop_type")
                .prefetch_related("calendars")
                .order_by("crop_id"),
                to_attr="active_crops",
            )
        )
        page_obj = Paginator(farm_queryset, 20).get_page(request.GET.get("page"))
        farms = list(page_obj.object_list)
        labels = calendar_status_labels()
        for farm in farms:
            farm.active_crops = farm_crops_with_stage(farm.active_crops, labels)

    return render(
        request,
        "dashboard/farmer_detail.html",
        {
            "section": "farmers",
            "sections": dashboard_navigation(request.user),
            "farmer": farmer,
            "phone": phone,
            "code_requests": code_requests,
            "farm_count": farm_count,
            "document_requests": document_requests,
            "document_type_choices": type_choices,
            "pending_document_count": sum(
                1 for item in document_requests if item.status == "pending"
            ),
            "can_request_documents": has_dashboard_permission(
                request.user, "farmers.request_farmer_documents"
            ),
            "active_view": active_view,
            "farms": farms,
            "page_obj": page_obj,
            "farm_status": farm_status,
            "farm_size_filter": farm_size_filter,
            "farm_search": farm_search,
            "farm_sort": farm_sort,
            "filter_form": filter_form,
            "filter_error": not filter_valid,
            "filter_query": filter_params.urlencode(),
            "personal_address": farmer.personal_address,
            "documents": documents,
            "can_view_applications": can_view_applications,
            "can_manage_records": has_dashboard_permission(
                request.user, "farmers.manage_dashboard_records"
            ),
            "can_view_code_requests": has_dashboard_permission(
                request.user, "farmers.view_farmer_code_requests"
            ),
            "can_manually_verify": has_dashboard_permission(
                request.user, "farmers.manually_verify_farmer"
            ),
        },
        status=400 if not filter_valid else 200,
    )


@require_POST
@dashboard_permission_required("farmers.manage_dashboard_records")
def dashboard_user_delete(request, user_id):
    if not database_ready_for_dashboard():
        messages.error(
            request,
            "The database tables for this app have not been created yet. "
            "Run your migrations or connect the correct database.",
        )
        return redirect(dashboard_url("farmers"))

    get_object_or_404(farmer_users(), user_id=user_id)
    with transaction.atomic():
        user = farmer_users().select_for_update().get(user_id=user_id)
        previous = _farmer_audit_values(
            user,
            user.phone_numbers.order_by("phone_id").first(),
            user.farms.select_related("address").order_by("farm_id").first(),
        )
        log_staff_audit_change(
            staff_user=request.user,
            user=user,
            action_type="DELETE",
            target_table="USERS",
            target_id=user_id,
            old_values=previous,
            new_values={},
            request=request,
        )
        user.delete()
    return redirect(dashboard_url("farmers"))