import ipaddress
import json
import logging
import re
import sqlite3
import zipfile
from contextlib import closing

from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from businesses.views import register as register_buyer
from farmers.marketplace import (
    CropsView,
    CropTypesView,
    FarmDetailView,
    FarmerListingDetailView,
    FarmerListingsView,
    FarmerOrdersView,
    FarmsView,
    ListingExpensesView,
)
from farmers.views import farmer_profile
from farmers.views import register_user as register_farmer
from logistics.views import register as register_logistics
from shared.farmer_messages import FarmerInboxView
from shared.models import User
from shared.registration import resolve_enum_order_id

from .permissions import dashboard_navigation, has_dashboard_permission
from .region3 import locate_point, parse_coordinates, validate_address

logger = logging.getLogger(__name__)


@never_cache
@require_GET
def simulator_map_asset(request, asset):
    check_simulator(request, "farmers")
    assets = {
        "maplibre-gl.js": "application/javascript",
        "maplibre-gl.css": "text/css",
    }
    if asset not in assets:
        raise Http404
    path = settings.BASE_DIR / "node_modules" / "maplibre-gl" / "dist" / asset
    if not path.is_file():
        return JsonResponse(
            {"detail": "Map assets missing. Run npm install."}, status=503
        )
    return HttpResponse(path.read_bytes(), content_type=assets[asset])


@never_cache
@require_GET
def simulator_map_glyph(request, fontstack, glyph_range):
    check_simulator(request, "farmers")
    if fontstack != "Open Sans Regular":
        raise Http404
    match = re.fullmatch(r"([0-9]+)-([0-9]+)\.pbf", glyph_range)
    if (
        not match
        or int(match[1]) % 256
        or int(match[2]) != int(match[1]) + 255
        or int(match[1]) > 65280
    ):
        raise Http404
    path = (
        settings.BASE_DIR
        / "dashboard"
        / "static"
        / "dashboard"
        / "region3_font_glyphs.zip"
    )
    try:
        with zipfile.ZipFile(path) as archive:
            data = archive.read(glyph_range)
    except OSError, zipfile.BadZipFile, KeyError:
        return JsonResponse(
            {"detail": "Local map fonts are missing or invalid."}, status=503
        )
    return HttpResponse(data, content_type="application/x-protobuf")


@never_cache
@require_GET
def simulator_map_tile(request, zoom, x, y):
    check_simulator(request, "farmers")
    if zoom > 14 or x >= 2**zoom or y >= 2**zoom:
        raise Http404
    path = settings.BASE_DIR / "local_map_data" / "philippines.mbtiles"
    if not path.is_file():
        return JsonResponse(
            {"detail": "Local map data missing. See README for setup."}, status=503
        )
    try:
        with closing(
            sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        ) as db:
            row = db.execute(
                "SELECT tile_data FROM tiles "
                "WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                (zoom, x, 2**zoom - 1 - y),
            ).fetchone()
    except sqlite3.Error:
        return JsonResponse({"detail": "Local map data cannot be read."}, status=503)
    if not row:
        return HttpResponse(status=204)
    response = HttpResponse(row[0], content_type="application/x-protobuf")
    response["Content-Encoding"] = "gzip"
    return response


@never_cache
@require_POST
def simulator_map_lookup(request):
    check_simulator(request, "farmers")
    try:
        payload = json.loads(request.body)
        if not isinstance(payload, dict):
            raise ValueError
        latitude, longitude = parse_coordinates(
            payload.get("latitude"), payload.get("longitude")
        )
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return JsonResponse(
            {"detail": "Provide valid latitude and longitude."}, status=400
        )
    return JsonResponse(locate_point(latitude, longitude))


def simulator_allowed(request):
    if settings.ENABLE_LIVE_SIMULATOR:
        return has_dashboard_permission(
            request.user, "farmers.manage_dashboard_records"
        )
    if not settings.DEBUG or not settings.ENABLE_LOCAL_SIMULATOR:
        return False
    if settings.DATABASES["default"].get("HOST") not in (
        "localhost",
        "127.0.0.1",
        "::1",
    ):
        return False
    if request.META.get("HTTP_X_FORWARDED_FOR"):
        return False
    try:
        loopback = ipaddress.ip_address(
            request.META.get("REMOTE_ADDR") or ""
        ).is_loopback
    except ValueError:
        return False
    return loopback and has_dashboard_permission(
        request.user, "farmers.manage_dashboard_records"
    )


def check_simulator(request, section):
    if section not in ("farmers", "businesses", "logistics") or not (
        simulator_allowed(request)
    ):
        raise Http404


@never_cache
@require_GET
def simulator_page(request, section):
    check_simulator(request, section)
    return render(
        request,
        "dashboard/simulator.html",
        {
            "section": section,
            "section_title": {
                "farmers": "Farmers",
                "businesses": "Bulk Buyers",
                "logistics": "Logistics",
            }[section],
            "sections": dashboard_navigation(request.user),
            "live_simulator": settings.ENABLE_LIVE_SIMULATOR,
        },
    )


@never_cache
@require_GET
def simulator_farmer_detail(request, farmer_id):
    check_simulator(request, "farmers")
    role_id = resolve_enum_order_id("role", "Farmer")
    if role_id is None:
        return JsonResponse({"detail": "Farmer role is not configured."}, status=503)
    farmer = get_object_or_404(
        User, user_id=farmer_id, role=role_id, deleted_at__isnull=True
    )
    return render(
        request,
        "dashboard/simulator.html",
        {
            "section": "farmers",
            "section_title": "Farmers",
            "sections": dashboard_navigation(request.user),
            "selected_farmer": farmer,
            "live_simulator": settings.ENABLE_LIVE_SIMULATOR,
        },
    )


@never_cache
@require_GET
def simulator_farmers(request):
    check_simulator(request, "farmers")
    role_id = resolve_enum_order_id("role", "Farmer")
    if role_id is None:
        return JsonResponse({"detail": "Farmer role is not configured."}, status=503)
    farmers = User.objects.filter(role=role_id, deleted_at__isnull=True)
    search = request.GET.get("q", "").strip()
    if search:
        farmers = farmers.filter(
            Q(username__icontains=search)
            | Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
        )
    page = Paginator(farmers.order_by("user_id"), 25).get_page(request.GET.get("page"))
    return JsonResponse(
        {
            "farmers": [
                {
                    "user_id": farmer.user_id,
                    "username": farmer.username,
                    "first_name": farmer.first_name,
                    "last_name": farmer.last_name,
                    "is_verified": farmer.is_verified == 1,
                }
                for farmer in page.object_list
            ],
            "page": page.number,
            "pages": page.paginator.num_pages,
            "has_previous": page.has_previous(),
            "has_next": page.has_next(),
        }
    )


class LocalFarmerAuthentication(BaseAuthentication):
    def authenticate(self, request):
        check_simulator(request._request, "farmers")
        farmer = getattr(request._request, "_simulator_farmer", None)
        if farmer is None:
            raise AuthenticationFailed("No local farmer selected.")
        return farmer, None


@never_cache
@require_http_methods(["GET", "POST", "PATCH"])
def simulator_farmer_api(request, farmer_id, action):
    check_simulator(request, "farmers")
    role_id = resolve_enum_order_id("role", "Farmer")
    if role_id is None:
        return JsonResponse({"detail": "Farmer role is not configured."}, status=503)
    farmer = get_object_or_404(
        User, user_id=farmer_id, role=role_id, deleted_at__isnull=True
    )
    views = {
        "me/": farmer_profile.cls,
        "farms/": FarmsView,
        "crop-types/": CropTypesView,
        "crops/": CropsView,
        "listings/": FarmerListingsView,
        "orders/": FarmerOrdersView,
        "messages/": FarmerInboxView,
    }
    view = views.get(action)
    kwargs = {}
    if view is None:
        expense_match = re.fullmatch(r"listings/([1-9][0-9]*)/expenses/", action)
        if expense_match:
            view = ListingExpensesView
            kwargs["listing_id"] = int(expense_match.group(1))
    if view is None:
        match = re.fullmatch(r"(farms|listings)/([1-9][0-9]*)/", action)
        if not match:
            raise Http404
        if match.group(1) == "farms":
            view = FarmDetailView
            kwargs["farm_id"] = int(match.group(2))
        else:
            view = FarmerListingDetailView
            kwargs["listing_id"] = int(match.group(2))
    if request.method in ("POST", "PATCH") and (
        action == "farms/" or re.fullmatch(r"farms/[1-9][0-9]*/", action)
    ):
        try:
            payload = json.loads(request.body)
        except UnicodeDecodeError, json.JSONDecodeError:
            return JsonResponse({"detail": "Provide a JSON object."}, status=400)
        if not isinstance(payload, dict):
            return JsonResponse({"detail": "Provide a JSON object."}, status=400)
        if (
            request.method == "POST" and "farm_id" not in payload
        ) or "address" in payload:
            error = validate_address(payload.get("address"))
            if error:
                return JsonResponse({"address": [error]}, status=400)
    request._simulator_farmer = farmer
    if settings.ENABLE_LIVE_SIMULATOR:
        logger.warning(
            "Live simulator farmer access: "
            "staff_id=%s farmer_id=%s method=%s action=%s",
            request.user.pk,
            farmer_id,
            request.method,
            action,
        )
    return view.as_view(authentication_classes=[LocalFarmerAuthentication])(
        request, **kwargs
    )


@never_cache
@require_POST
def simulator_register(request, section):
    check_simulator(request, section)
    try:
        payload = json.loads(request.body)
    except UnicodeDecodeError, json.JSONDecodeError:
        return JsonResponse({"detail": "Provide a JSON object."}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"detail": "Provide a JSON object."}, status=400)
    if section == "farmers":
        addresses = {
            "personal_address": {
                "street_address": payload.get("street"),
                "barangay": payload.get("baranggay"),
                "municipality_city": payload.get("municipality"),
                "province": payload.get("province"),
                "postal_code": payload.get("postal_code"),
                "country": payload.get("country"),
                "gps_coordinates": payload.get("personal_gps_coordinates"),
            },
            "farm_address": {
                "street_address": payload.get("farm_street"),
                "barangay": payload.get("farm_barangay"),
                "municipality_city": payload.get("farm_municipality"),
                "province": payload.get("farm_province"),
                "postal_code": payload.get("farm_postal_code"),
                "country": payload.get("farm_country"),
                "gps_coordinates": payload.get("farm_gps_coordinates"),
            },
        }
    else:
        organization = (
            "business_address" if section == "businesses" else "company_address"
        )
        addresses = {
            "personal_address": payload.get("personal_address"),
            organization: payload.get(organization),
        }
    errors = {
        name: [error]
        for name, address in addresses.items()
        if (error := validate_address(address))
    }
    if errors:
        return JsonResponse(errors, status=400)
    view = {
        "farmers": register_farmer,
        "businesses": register_buyer,
        "logistics": register_logistics,
    }[section]
    response = view(request)
    if response.status_code != 201:
        return JsonResponse(response.data, status=response.status_code, safe=False)
    if section == "farmers":
        return JsonResponse(response.data, status=201)
    return JsonResponse(
        {"detail": "Account created. A staff member must review the request."},
        status=201,
    )
