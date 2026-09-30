from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render

from farmers.models import Farm, FarmerCodeRequest
from farmers.registration import create_farmer_registration
from farmers.serializers import FarmerRegistrationSerializer
from farmers.workflows import (
    FarmerWorkflowConflict,
    FarmerWorkflowValidationError,
    manually_verify_farmer,
)
from shared.audit import log_staff_audit_change
from shared.models import Address, ElectronicDocument, PhoneNumber, User

from .permissions import (
    dashboard_navigation,
    dashboard_permission_required,
    has_dashboard_permission,
)
from .services import dashboard_url, database_ready_for_dashboard


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


@transaction.atomic
def _save_farmer_dashboard_form(
    request,
    user,
    phone,
    farm,
    first_name,
    middle_name,
    last_name,
    phone_number,
    farm_size,
    street,
    barangay,
    municipality,
    province,
    region,
    house_number,
):
    old_values = _farmer_audit_values(user, phone, farm)
    user.first_name = first_name
    user.middle_name = middle_name or None
    user.last_name = last_name
    user.save(update_fields=["first_name", "middle_name", "last_name"])

    if phone is None:
        phone = PhoneNumber.objects.create(
            user=user, mobile_number=phone_number or "", phone_type="mobile"
        )
    else:
        phone.mobile_number = phone_number or phone.mobile_number
        phone.save(update_fields=["mobile_number"])

    if farm is None:
        address = Address.objects.create(
            street_address=f"{house_number} {street}"
            if house_number or street
            else "",
            barangay=barangay,
            municipality_city=municipality,
            province=province,
            country="Philippines",
            gps_coordinates=region or "",
            address_type="farm",
        )
        farm = Farm.objects.create(
            user=user,
            address=address,
            farm_size_hectares=Decimal(str(farm_size)) if farm_size else None,
        )
    else:
        if farm.address:
            farm.address.street_address = (
                f"{house_number} {street}" if house_number or street else ""
            )
            farm.address.barangay = barangay
            farm.address.municipality_city = municipality
            farm.address.province = province
            farm.address.gps_coordinates = region or farm.address.gps_coordinates
            farm.address.save(
                update_fields=[
                    "street_address",
                    "barangay",
                    "municipality_city",
                    "province",
                    "gps_coordinates",
                ]
            )
        farm.farm_size_hectares = (
            Decimal(str(farm_size)) if farm_size else farm.farm_size_hectares
        )
        farm.save(update_fields=["farm_size_hectares"])

    log_staff_audit_change(
        staff_user=request.user,
        user=user,
        action_type="UPDATE",
        target_table="USERS",
        target_id=user.user_id,
        old_values=old_values,
        new_values=_farmer_audit_values(user, phone, farm),
        request=request,
    )
    return user


def _create_farmer_from_dashboard(request):
    registration_data = request.POST.dict()
    registration_data["role"] = "Farmer"
    registration_data["documents"] = [
        request.POST.get(f"document_{index}", "") for index in range(1, 5)
    ]
    registration_data["document_types"] = [
        request.POST.get(f"document_type_{index}", "")
        for index in range(1, 5)
    ]
    serializer = FarmerRegistrationSerializer(data=registration_data)
    if not serializer.is_valid():
        registration_values = request.POST.dict()
        registration_values.pop("password", None)
        registration_documents = [
            {
                "url": request.POST.get(f"document_{index}", ""),
                "type": request.POST.get(f"document_type_{index}", ""),
            }
            for index in range(1, 5)
        ]
        return render(
            request,
            "dashboard/farmer_form.html",
            {
                "section": "farmers",
                "sections": dashboard_navigation(request.user),
                "registration_mode": True,
                "registration_values": registration_values,
                "registration_documents": registration_documents,
                "registration_errors": serializer.errors,
                "dashboard_url": dashboard_url("farmers"),
            },
        )

    create_farmer_registration(
        serializer.validated_data,
        request,
        staff_user=request.user,
    )
    return redirect(dashboard_url("farmers"))


@dashboard_permission_required("farmers.manage_dashboard_records")
def dashboard_user_form(request, user_id=None):
    if not database_ready_for_dashboard():
        return render(
            request,
            "dashboard/farmer_form.html",
            {
                "section": "farmers",
                "sections": dashboard_navigation(request.user),
                "registration_mode": True,
                "user": None,
                "phone": None,
                "farm": None,
                "address": None,
                "dashboard_url": dashboard_url("farmers"),
                "db_error": (
                    "The database tables for this app have not been created yet. "
                    "Run your migrations or connect the correct database."
                ),
            },
        )

    user = get_object_or_404(User, user_id=user_id) if user_id else None
    phone = user.phone_numbers.first() if user else None
    farm = user.farms.first() if user else None
    address = farm.address if farm else None

    if request.method == "POST":
        if user is None:
            return _create_farmer_from_dashboard(request)

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
                "dashboard/farmer_form.html",
                {
                    "section": "farmers",
                    "sections": dashboard_navigation(request.user),
                    "registration_mode": False,
                    "user": user,
                    "phone": phone,
                    "farm": farm,
                    "address": address,
                    "dashboard_url": dashboard_url("farmers"),
                    "error": "First name and last name are required.",
                },
            )

        user = _save_farmer_dashboard_form(
            request,
            user,
            phone,
            farm,
            first_name,
            middle_name,
            last_name,
            phone_number,
            farm_size,
            street,
            barangay,
            municipality,
            province,
            region,
            house_number,
        )

        return redirect(dashboard_url("farmers"))

    return render(
        request,
        "dashboard/farmer_form.html",
        {
            "section": "farmers",
            "sections": dashboard_navigation(request.user),
            "registration_mode": user is None,
            "registration_documents": [
                {"url": "", "type": document_type}
                for document_type in (
                    "Utility Bills",
                    "Valid_ID",
                    "Owner_Address",
                    "Farm_Ownership",
                )
            ]
            if user is None
            else [],
            "user": user,
            "phone": phone,
            "farm": farm,
            "address": address,
            "dashboard_url": dashboard_url("farmers"),
        },
    )


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
        User.objects.select_related("personal_address"),
        user_id=user_id,
        deleted_at__isnull=True,
    )
    active_view = request.GET.get("view", "information")
    if active_view not in ("information", "farms"):
        active_view = "information"

    if request.method == "POST":
        if request.POST.get("action") != "manual_verify" or not (
            has_dashboard_permission(
                request.user, "farmers.manually_verify_farmer"
            )
        ):
            raise PermissionDenied
        try:
            manually_verify_farmer(
                farmer.user_id,
                request.user,
                request.POST.get("reason", ""),
            )
            messages.success(request, "Farmer manually verified.")
        except FarmerWorkflowValidationError as exc:
            messages.error(request, str(exc))
        except FarmerWorkflowConflict as exc:
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
    page_obj = None
    farms = []
    farm_status = request.GET.get("farm_status", "active")
    farm_size_filter = request.GET.get("farm_size", "all")
    farm_search = (request.GET.get("farm_search") or "").strip()
    farm_sort = request.GET.get("farm_sort", "newest")

    if active_view == "farms":
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

        if farm_sort == "size_asc":
            farm_queryset = farm_queryset.order_by("farm_size_hectares", "farm_id")
        elif farm_sort == "size_desc":
            farm_queryset = farm_queryset.order_by("-farm_size_hectares", "farm_id")
        else:
            farm_sort = "newest"
            farm_queryset = farm_queryset.order_by("-farm_id")
        page_obj = Paginator(farm_queryset, 20).get_page(request.GET.get("page"))
        farms = page_obj.object_list

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
            "active_view": active_view,
            "farms": farms,
            "page_obj": page_obj,
            "farm_status": farm_status,
            "farm_size_filter": farm_size_filter,
            "farm_search": farm_search,
            "farm_sort": farm_sort,
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
    )


@dashboard_permission_required("farmers.manage_dashboard_records")
def dashboard_user_delete(request, user_id):
    if not database_ready_for_dashboard():
        return render(
            request,
            "dashboard/farmer_delete_confirm.html",
            {
                "section": "farmers",
                "sections": dashboard_navigation(request.user),
                "user": None,
                "db_error": (
                    "The database tables for this app have not been created yet. "
                    "Run your migrations or connect the correct database."
                ),
            },
        )

    user = get_object_or_404(User, user_id=user_id)
    if request.method == "POST":
        with transaction.atomic():
            user = User.objects.select_for_update().get(user_id=user_id)
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
    return render(
        request,
        "dashboard/farmer_delete_confirm.html",
        {
            "section": "farmers",
            "sections": dashboard_navigation(request.user),
            "user": user,
        },
    )
