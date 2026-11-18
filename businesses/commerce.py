from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from farmers.models import Crop, MarketplaceListing
from logistics.models import DeliveryAssignment, LogisticsCompany
from shared.account_api import BuyerAuthentication
from shared.models import Order, OrderItem
from shared.registration import resolve_enum_order_id

from .models import OrderReservation


class OrderInputSerializer(serializers.Serializer):
    listing_id = serializers.IntegerField(min_value=1)
    quantity_kg = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0.01")
    )
    delivery_date = serializers.DateField(required=False, allow_null=True)
    delivery_company_id = serializers.IntegerField(
        min_value=1, required=False, allow_null=True
    )

    def validate_delivery_date(self, value):
        if value is not None and value < timezone.localdate():
            raise serializers.ValidationError("Delivery date cannot be in the past.")
        return value


def available_listings():
    return (
        MarketplaceListing.objects.filter(
            is_active=1,
            crop__deleted_at__isnull=True,
            crop__farm__isnull=False,
            crop__farm__deleted_at__isnull=True,
            crop__available_stock_kg__gt=0,
            listing_price_per_kg__gte=0,
            calendar__isnull=False,
            calendar__crop_id=F("crop_id"),
        )
        .filter(
            Q(crop__expires_at__isnull=True) | Q(crop__expires_at__gt=timezone.now())
        )
        .select_related("crop", "crop__crop_type", "calendar")
    )


def listing_data(listing):
    return {
        "listing_id": listing.listing_id,
        "title": listing.listing_title,
        "crop_name": listing.crop.crop_type.crop_name
        if listing.crop.crop_type
        else None,
        "calendar_id": listing.calendar_id,
        "price_per_kg": listing.listing_price_per_kg,
        "available_stock_kg": listing.crop.available_stock_kg,
    }


def order_data(order):
    assignment = DeliveryAssignment.objects.filter(order=order).first()
    return {
        "order_id": order.order_id,
        "total_payment": order.total_payment,
        "delivery_date": order.delivery_date,
        "order_status": order.order_status,
        "reservation_status": order.reservation.status,
        "created_at": order.created_at,
        "delivery_company_id": assignment.company_id if assignment else None,
        "trip_id": assignment.trip_id if assignment else None,
        "items": [
            {
                "calendar_id": item.calendar_id,
                "quantity_kg": item.quantity_ordered_kg,
                "price_per_kg": item.price_at_purchase,
            }
            for item in order.items.all()
        ],
    }


class BuyerView(APIView):
    authentication_classes = [BuyerAuthentication]
    permission_classes = [IsAuthenticated]


class ListingsView(BuyerView):
    def get(self, request):
        listings = available_listings().order_by("listing_id")
        return Response([listing_data(listing) for listing in listings])


class DeliveryCompaniesView(BuyerView):
    def get(self, request):
        role_id = resolve_enum_order_id("role", "Logistics_Manager")
        if role_id is None:
            return Response({"detail": "Logistics role is not configured."}, status=503)
        companies = LogisticsCompany.objects.filter(
            date_time_deleted__isnull=True,
            user__deleted_at__isnull=True,
            user__is_verified=1,
            user__role=role_id,
        ).order_by("logistics_business_id")
        return Response(
            [
                {"company_id": company.pk, "business_name": company.business_name}
                for company in companies
            ]
        )


class OrdersView(BuyerView):
    def get(self, request):
        orders = (
            Order.objects.filter(
                buyer=request.user, deleted_at__isnull=True, reservation__isnull=False
            )
            .prefetch_related("items")
            .order_by("-order_id")
        )
        return Response([order_data(order) for order in orders])

    def post(self, request):
        serializer = OrderInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        with transaction.atomic():
            listing = (
                available_listings()
                .select_for_update(of=("self",))
                .filter(pk=data["listing_id"])
                .first()
            )
            if listing is None:
                raise ValidationError({"listing_id": ["Listing is not available."]})
            crop = Crop.objects.select_for_update().get(pk=listing.crop_id)
            if (
                listing.calendar.crop_id != crop.pk
                or crop.deleted_at is not None
                or crop.available_stock_kg is None
                or crop.available_stock_kg < data["quantity_kg"]
                or (crop.expires_at is not None and crop.expires_at <= timezone.now())
            ):
                raise ValidationError(
                    {"quantity_kg": ["Requested stock is unavailable."]}
                )
            total = data["quantity_kg"] * listing.listing_price_per_kg
            total = total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if total >= Decimal("10000000000"):
                raise ValidationError({"quantity_kg": ["Order total is too large."]})
            company = None
            destination = None
            if data.get("delivery_company_id") is not None:
                role_id = resolve_enum_order_id("role", "Logistics_Manager")
                if role_id is None:
                    return Response(
                        {"detail": "Logistics role is not configured."}, status=503
                    )
                company = LogisticsCompany.objects.filter(
                    pk=data["delivery_company_id"],
                    date_time_deleted__isnull=True,
                    user__deleted_at__isnull=True,
                    user__is_verified=1,
                    user__role=role_id,
                ).first()
                if company is None:
                    raise ValidationError(
                        {"delivery_company_id": ["Company is not available."]}
                    )
                business = (
                    request.user.businesses.filter(
                        date_time_deleted__isnull=True, address__isnull=False
                    )
                    .order_by("business_id")
                    .first()
                )
                if business is None or listing.calendar.pickup_address_id is None:
                    raise ValidationError(
                        {
                            "delivery_company_id": [
                                "Pickup and business addresses are required."
                            ]
                        }
                    )
                destination = business.address
            now = timezone.now()
            order = Order.objects.create(
                buyer=request.user,
                total_payment=total,
                delivery_date=data.get("delivery_date"),
                created_at=now,
                updated_at=now,
            )
            OrderItem.objects.create(
                order=order,
                calendar=listing.calendar,
                quantity_ordered_kg=data["quantity_kg"],
                price_at_purchase=listing.listing_price_per_kg,
            )
            OrderReservation.objects.create(
                order=order,
                crop=crop,
                pickup_address=listing.calendar.pickup_address,
                destination_address=destination,
            )
            crop.available_stock_kg -= data["quantity_kg"]
            crop.save(update_fields=["available_stock_kg"])
            if company is not None:
                DeliveryAssignment.objects.create(order=order, company=company)
        return Response(order_data(order), status=201)


class OrderCancelView(BuyerView):
    def post(self, request, order_id):
        with transaction.atomic():
            assignment = (
                DeliveryAssignment.objects.select_for_update()
                .filter(order_id=order_id, order__buyer=request.user)
                .first()
            )
            reservation = (
                OrderReservation.objects.select_for_update()
                .filter(order_id=order_id, order__buyer=request.user)
                .first()
            )
            if reservation is None:
                return Response({"detail": "Order not found."}, status=404)
            if reservation.status != OrderReservation.Status.RESERVED:
                return Response({"detail": "Order cannot be cancelled."}, status=409)
            if assignment is not None and assignment.trip_id is not None:
                return Response(
                    {"detail": "Order is already assigned to a trip."}, status=409
                )
            crop = Crop.objects.select_for_update().get(pk=reservation.crop_id)
            quantity = reservation.order.items.get().quantity_ordered_kg
            if crop.available_stock_kg is None or quantity is None:
                return Response(
                    {"detail": "Stock cannot be restored automatically."}, status=409
                )
            if crop.available_stock_kg + quantity >= Decimal("10000000000"):
                return Response(
                    {"detail": "Restored stock would exceed the allowed maximum."},
                    status=409,
                )
            crop.available_stock_kg += quantity
            crop.save(update_fields=["available_stock_kg"])
            reservation.status = OrderReservation.Status.CANCELLED
            reservation.save(update_fields=["status"])
            reservation.order.updated_at = timezone.now()
            reservation.order.save(update_fields=["updated_at"])
        return Response(order_data(reservation.order))
