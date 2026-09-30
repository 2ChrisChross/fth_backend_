from decimal import Decimal

from django.shortcuts import redirect, render
from django.urls import reverse

from logistics.models import Vehicle
from shared.audit import _log_audit_change, _serialize_model
from shared.models import User

from .services import database_ready_for_dashboard


def logistics_create(request):
    dashboard_url = reverse("logistics:dashboard")
    if not database_ready_for_dashboard():
        return render(
            request,
            "dashboard/bulk_buyer_vehicle_form.html",
            {
                "section": "logistics",
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
        truck_model = (request.POST.get("truck_model") or "").strip()
        plate_number = (request.POST.get("plate_number") or "").strip()
        max_weight = request.POST.get("max_weight_capacity_kg") or ""
        max_volume = request.POST.get("max_volume_capacity_m3") or ""
        current_health_status = request.POST.get("current_health_status", 0)

        if not owner or not truck_model or not plate_number:
            return render(
                request,
                "dashboard/bulk_buyer_vehicle_form.html",
                {
                    "section": "logistics",
                    "dashboard_url": dashboard_url,
                    "users": users,
                    "error": (
                        "You must assign an owner and provide a vehicle model "
                        "and plate number."
                    ),
                },
            )

        vehicle = Vehicle.objects.create(
            user=owner,
            truck_model=truck_model,
            plate_number=plate_number,
            max_weight_capacity_kg=Decimal(str(max_weight))
            if str(max_weight).strip()
            else None,
            max_volume_capacity_m3=Decimal(str(max_volume))
            if str(max_volume).strip()
            else None,
            current_health_status=int(current_health_status)
            if str(current_health_status).isdigit()
            else 0,
        )
        _log_audit_change(
            user=owner,
            action_type="CREATE",
            target_table="VEHICLES",
            target_id=vehicle.vehicle_id,
            old_values={},
            new_values=_serialize_model(vehicle),
            request=request,
        )
        return redirect(dashboard_url)

    return render(
        request,
        "dashboard/bulk_buyer_vehicle_form.html",
        {
            "section": "logistics",
            "dashboard_url": dashboard_url,
            "users": users,
        },
    )
