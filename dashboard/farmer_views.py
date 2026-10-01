from urllib.parse import urlsplit

from django.contrib import messages
from django.contrib.auth.hashers import make_password
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render

from farmers.models import Farm, FarmerCodeRequest
from farmers.registration import create_farmer_registration
from farmers.serializers import (
    FarmerDashboardRegistrationSerializer,
    FarmerDashboardUpdateSerializer,
)
from farmers.workflows import (
    FarmerWorkflowConflict,
    FarmerWorkflowValidationError,
    manually_verify_farmer,
)
from shared.audit import log_staff_audit_change
from shared.models import (
    ElectronicDocument,
    EnumeratedValue,
    PhoneNumber,
    User,
)
from shared.registration import create_address, resolve_enum_order_id

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


def _save_farmer_address(address, data, prefix, address_type):
    if prefix == "farm_":
        house_number = data["farm_house_number"]
        street = data["farm_street"]
        fields = {
            "street_address": f"{house_number} {street}".strip()
            if house_number
            else street,
            "barangay": data["farm_barangay"],
            "municipality_city": data["farm_municipality"],
            "province": data["farm_province"],
            "postal_code": data["farm_postal_code"],
            "country": data.get("farm_country") or "Philippines",
            "gps_coordinates": data["farm_region"],
        }
    else:
        house_number = data["house_number"]
        street = data["street"]
        fields = {
            "street_address": f"{house_number} {street}".strip()
            if house_number
            else street,
            "barangay": data["baranggay"],
            "municipality_city": data["municipality"],
            "province": data["province"],
            "postal_code": data["postal_code"],
            "country": data.get("country") or "Philippines",
            "gps_coordinates": data["region"],
        }

    if address is None:
        return create_address(fields, address_type)

    for field, value in fields.items():
        setattr(address, field, value)
    address.save(update_fields=list(fields))
    return address


def _existing_registration_values(user, phone, farm):
    personal_address = user.personal_address
    farm_address = farm.address if farm else None

    def address_value(address, field):
        return getattr(address, field, "") if address else ""

    return {
        "phonenumber": phone.mobile_number if phone else "",
        "username": user.username or "",
        "firstname": user.first_name or "",
        "middle_name": user.middle_name or "",
        "lastname": user.last_name or "",
        "region": address_value(personal_address, "gps_coordinates"),
        "province": address_value(personal_address, "province"),
        "municipality": address_value(personal_address, "municipality_city"),
        "baranggay": address_value(personal_address, "barangay"),
        "house_number": "",
        "street": address_value(personal_address, "street_address"),
        "postal_code": address_value(personal_address, "postal_code"),
        "country": address_value(personal_address, "country") or "Philippines",
        "farm_size": farm.farm_size_hectares if farm else "",
        "farm_region": address_value(farm_address, "gps_coordinates"),
        "farm_province": address_value(farm_address, "province"),
        "farm_municipality": address_value(farm_address, "municipality_city"),
        "farm_barangay": address_value(farm_address, "barangay"),
        "farm_house_number": "",
        "farm_street": address_value(farm_address, "street_address"),
        "farm_postal_code": address_value(farm_address, "postal_code"),
        "farm_country": address_value(farm_address, "country") or "Philippines",
        "language": user.preferred_language or "",
        "payment_method": user.preferred_payment_method or "",
    }


def _existing_registration_documents(user):
    defaults = ("Utility Bills", "Valid_ID", "Owner_Address", "Farm_Ownership")
    try:
        document_types = {
            item.ordering: item.value
            for item in EnumeratedValue.objects.filter(type__iexact="document_type")
        }
    except Exception:
        document_types = {}

    documents = list(user.electronic_documents.order_by("doc_id")[:4])
    return [
        {
            "url": documents[index].file_url or "" if index < len(documents) else "",
            "type": document_types.get(
                documents[index].doc_type, defaults[index]
            )
            if index < len(documents)
            else defaults[index],
        }
        for index in range(4)
    ]


@transaction.atomic
def _save_farmer_dashboard_form(
    request,
    user,
    phone,
    farm,
    data,
):
    old_values = _farmer_audit_values(user, phone, farm)
    user.personal_address = _save_farmer_address(
        user.personal_address, data, "", "residence"
    )
    user.username = data["username"]
    user.first_name = data["firstname"]
    user.middle_name = data.get("middle_name") or None
    user.last_name = data["lastname"]
    user.preferred_language = resolve_enum_order_id(
        "language", data.get("language") or None
    )
    user.preferred_payment_method = resolve_enum_order_id(
        "payment_method", data.get("payment_method") or None
    )
    user_fields = [
        "personal_address",
        "username",
        "first_name",
        "middle_name",
        "last_name",
        "preferred_language",
        "preferred_payment_method",
    ]
    if data.get("password"):
        user.password_hash = make_password(data["password"])
        user_fields.append("password_hash")
    user.save(update_fields=user_fields)

    if phone is None:
        phone = PhoneNumber.objects.create(
            user=user, mobile_number=data["phonenumber"], phone_type="mobile"
        )
    else:
        phone.mobile_number = data["phonenumber"]
        phone.save(update_fields=["mobile_number"])

    farm_address = _save_farmer_address(
        farm.address if farm else None, data, "farm_", "farm"
    )
    if farm is None:
        farm = Farm.objects.create(
            user=user,
            address=farm_address,
            farm_size_hectares=data["farm_size"],
        )
    else:
        farm.address = farm_address
        farm.farm_size_hectares = data["farm_size"]
        farm.save(update_fields=["address", "farm_size_hectares"])

    existing_documents = list(user.electronic_documents.order_by("doc_id")[:4])
    for index, (url, document_type) in enumerate(
        zip(data["document_urls"][:4], data["document_type_names"][:4])
    ):
        path = urlsplit(url).path
        file_extension = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        doc_type_id = resolve_enum_order_id("document_type", document_type) or 1
        if index < len(existing_documents):
            document = existing_documents[index]
            changed = document.file_url != url or document.doc_type != doc_type_id
            document.doc_title = document_type
            document.doc_type = doc_type_id
            document.file_url = url
            document.file_extension = file_extension
            if changed:
                document.verification_status = 0
            document.save(
                update_fields=[
                    "doc_title",
                    "doc_type",
                    "file_url",
                    "file_extension",
                    "verification_status",
                ]
            )
        else:
            ElectronicDocument.objects.create(
                user=user,
                doc_title=document_type,
                doc_type=doc_type_id,
                file_url=url,
                file_extension=file_extension,
                verification_status=0,
            )

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
    serializer = FarmerDashboardRegistrationSerializer(data=registration_data)
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

        registration_data = request.POST.dict()
        registration_data["role"] = "Farmer"
        registration_data["documents"] = [
            request.POST.get(f"document_{index}", "") for index in range(1, 5)
        ]
        registration_data["document_types"] = [
            request.POST.get(f"document_type_{index}", "")
            for index in range(1, 5)
        ]
        serializer = FarmerDashboardUpdateSerializer(
            user, data=registration_data
        )
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
                    "registration_mode": False,
                    "user": user,
                    "phone": phone,
                    "farm": farm,
                    "address": address,
                    "registration_values": registration_values,
                    "registration_documents": registration_documents,
                    "registration_errors": serializer.errors,
                    "dashboard_url": dashboard_url("farmers"),
                },
            )

        _save_farmer_dashboard_form(request, user, phone, farm, serializer.validated_data)

        return redirect(dashboard_url("farmers"))

    registration_mode = user is None
    if registration_mode:
        registration_values = {}
        registration_documents = [
            {"url": "", "type": document_type}
            for document_type in (
                "Utility Bills",
                "Valid_ID",
                "Owner_Address",
                "Farm_Ownership",
            )
        ]
    else:
        registration_values = _existing_registration_values(user, phone, farm)
        registration_documents = _existing_registration_documents(user)

    return render(
        request,
        "dashboard/farmer_form.html",
        {
            "section": "farmers",
            "sections": dashboard_navigation(request.user),
            "registration_mode": registration_mode,
            "registration_values": registration_values,
            "registration_documents": registration_documents,
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
