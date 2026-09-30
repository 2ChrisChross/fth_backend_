from decimal import Decimal

from django.contrib.auth.hashers import make_password
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.crypto import get_random_string

from farmers.models import Farm
from shared.audit import _log_audit_change, _serialize_model
from shared.models import Address, PhoneNumber, User

from .services import dashboard_url, database_ready_for_dashboard


def dashboard_user_form(request, user_id=None):
    if not database_ready_for_dashboard():
        return render(
            request,
            "dashboard/farmer_form.html",
            {
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
                    "user": user,
                    "phone": phone,
                    "farm": farm,
                    "address": address,
                    "dashboard_url": dashboard_url("farmers"),
                    "error": "First name and last name are required.",
                },
            )

        if user is None:
            anchor_address = Address.objects.create(
                street_address=f"{house_number} {street}"
                if house_number or street
                else "",
                barangay=barangay,
                municipality_city=municipality,
                province=province,
                country="Philippines",
                gps_coordinates=region or "",
                address_type="residence",
            )
            user = User.objects.create(
                personal_address=anchor_address,
                first_name=first_name,
                middle_name=middle_name or None,
                last_name=last_name,
                password_hash=make_password("changeme123"),
                verification_code=get_random_string(
                    8, allowed_chars="ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
                ),
            )
            _log_audit_change(
                user=user,
                action_type="CREATE",
                target_table="USERS",
                target_id=user.user_id,
                old_values={},
                new_values=_serialize_model(user),
                request=request,
            )
        else:
            previous = _serialize_model(user)
            user.first_name = first_name
            user.middle_name = middle_name or None
            user.last_name = last_name
            user.save()
            _log_audit_change(
                user=user,
                action_type="UPDATE",
                target_table="USERS",
                target_id=user.user_id,
                old_values={
                    "first_name": previous.get("first_name"),
                    "middle_name": previous.get("middle_name"),
                    "last_name": previous.get("last_name"),
                },
                new_values={
                    "first_name": user.first_name,
                    "middle_name": user.middle_name,
                    "last_name": user.last_name,
                },
                request=request,
            )

        if phone is None:
            PhoneNumber.objects.create(
                user=user, mobile_number=phone_number or "", phone_type="mobile"
            )
        else:
            phone.mobile_number = phone_number or phone.mobile_number
            phone.save()

        if farm is None:
            address_obj = Address.objects.create(
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
            Farm.objects.create(
                user=user,
                address=address_obj,
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
                farm.address.save()
            farm.farm_size_hectares = (
                Decimal(str(farm_size)) if farm_size else farm.farm_size_hectares
            )
            farm.save()

        return redirect(dashboard_url("farmers"))

    return render(
        request,
        "dashboard/farmer_form.html",
        {
            "user": user,
            "phone": phone,
            "farm": farm,
            "address": address,
            "dashboard_url": dashboard_url("farmers"),
        },
    )


def dashboard_user_delete(request, user_id):
    if not database_ready_for_dashboard():
        return render(
            request,
            "dashboard/farmer_delete_confirm.html",
            {
                "user": None,
                "db_error": (
                    "The database tables for this app have not been created yet. "
                    "Run your migrations or connect the correct database."
                ),
            },
        )

    user = get_object_or_404(User, user_id=user_id)
    if request.method == "POST":
        previous = _serialize_model(user)
        user.delete()
        _log_audit_change(
            user=user,
            action_type="DELETE",
            target_table="USERS",
            target_id=user_id,
            old_values=previous,
            new_values={},
            request=request,
        )
        return redirect(dashboard_url("farmers"))
    return render(request, "dashboard/farmer_delete_confirm.html", {"user": user})
