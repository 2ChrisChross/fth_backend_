from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from businesses.models import BulkBuyer
from shared.audit import _serialize_model, log_staff_audit_change
from shared.models import User

from .permissions import dashboard_navigation, dashboard_permission_required
from .services import database_ready_for_dashboard


@dashboard_permission_required("farmers.manage_dashboard_records")
def business_create(request):
    dashboard_url = reverse("businesses:dashboard")
    if not database_ready_for_dashboard():
        return render(
            request,
            "dashboard/bulk_buyer_vehicle_form.html",
            {
                "section": "businesses",
                "sections": dashboard_navigation(request.user),
                "dashboard_url": dashboard_url,
                "users": [],
                "db_error": (
                    "The database tables for this app have not been created yet. "
                    "Run your migrations or connect the correct database."
                ),
            },
        )

    users = User.objects.order_by("first_name", "last_name", "user_id")
    if request.method == "POST":
        owner_id = request.POST.get("user_id")
        owner = User.objects.filter(user_id=owner_id).first() if owner_id else None
        business_name = (request.POST.get("business_name") or "").strip()
        registration_number = (request.POST.get("registration_number") or "").strip()
        business_type = request.POST.get("business_type")
        is_verified = request.POST.get("is_verified", 0)

        if not owner or not business_name:
            return render(
                request,
                "dashboard/bulk_buyer_vehicle_form.html",
                {
                    "section": "businesses",
                    "sections": dashboard_navigation(request.user),
                    "dashboard_url": dashboard_url,
                    "users": users,
                    "error": "An owner and business name are required.",
                },
            )

        with transaction.atomic():
            bulk_buyer = BulkBuyer.objects.create(
                user=owner,
                business_name=business_name,
                business_type=int(business_type)
                if business_type and str(business_type).isdigit()
                else None,
                registration_number=registration_number or None,
                is_verified=int(is_verified) if str(is_verified).isdigit() else 0,
                date_time_created=timezone.now(),
            )
            log_staff_audit_change(
                staff_user=request.user,
                user=owner,
                action_type="CREATE",
                target_table="BULK_BUYERS",
                target_id=bulk_buyer.business_id,
                old_values={},
                new_values=_serialize_model(bulk_buyer),
                request=request,
            )
        return redirect(dashboard_url)

    return render(
        request,
        "dashboard/bulk_buyer_vehicle_form.html",
        {
            "section": "businesses",
            "sections": dashboard_navigation(request.user),
            "dashboard_url": dashboard_url,
            "users": users,
        },
    )
