from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from businesses.models import OrderReservation
from shared.account_api import LogisticsAuthentication
from shared.enums import enum_rows

from .models import (
    DeliveryAssignment,
    DeliveryTrip,
    LogisticsCompany,
    TripManifest,
    Vehicle,
)

PLANNED = 1
IN_TRANSIT = 2
COMPLETED = 3


class VehicleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vehicle
        fields = (
            "vehicle_id",
            "truck_model",
            "plate_number",
            "max_weight_capacity_kg",
            "max_volume_capacity_m3",
            "body_type",
            "is_refrigerated",
            "is_air_conditioned",
        )
        read_only_fields = ("vehicle_id",)
        extra_kwargs = {
            "truck_model": {
                "required": True,
                "allow_null": False,
                "allow_blank": False,
            },
            "plate_number": {
                "required": True,
                "allow_null": False,
                "allow_blank": False,
            },
            "max_weight_capacity_kg": {"required": True, "allow_null": False},
            "max_volume_capacity_m3": {"required": True, "allow_null": False},
            "body_type": {"required": True, "allow_null": False},
        }

    def validate_body_type(self, value):
        if value not in {ordering for ordering, _ in enum_rows("body_type")}:
            raise serializers.ValidationError("Select a configured body type.")
        return value

    def validate_max_weight_capacity_kg(self, value):
        if value <= 0:
            raise serializers.ValidationError("Capacity must be positive.")
        return value

    def validate_max_volume_capacity_m3(self, value):
        if value <= 0:
            raise serializers.ValidationError("Capacity must be positive.")
        return value

    def validate_is_refrigerated(self, value):
        if value not in (0, 1):
            raise serializers.ValidationError("Use 0 or 1.")
        return value

    def validate_is_air_conditioned(self, value):
        if value not in (None, 0, 1):
            raise serializers.ValidationError("Use 0, 1, or null.")
        return value


class TripInputSerializer(serializers.Serializer):
    vehicle_id = serializers.IntegerField(min_value=1)
    order_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), min_length=1, max_length=100
    )
    eta = serializers.DateTimeField(required=False, allow_null=True)

    def validate_order_ids(self, value):
        if len(set(value)) != len(value):
            raise serializers.ValidationError("Order IDs must be unique.")
        return value


class TripStatusSerializer(serializers.Serializer):
    trip_status = serializers.ChoiceField(choices=(IN_TRANSIT, COMPLETED))


def company_for(user):
    return get_object_or_404(
        LogisticsCompany, user=user, date_time_deleted__isnull=True
    )


def trip_data(trip):
    return {
        "trip_id": trip.pk,
        "vehicle_id": trip.vehicle_id,
        "driver_id": trip.driver_id,
        "trip_status": trip.trip_status,
        "eta": trip.eta,
        "weight_utilization_pct": trip.weight_utilization_pct,
        "order_ids": list(
            trip.manifests.order_by("dropoff_sequence").values_list(
                "order_id", flat=True
            )
        ),
    }


def address_data(address):
    if address is None:
        return None
    return {
        "street_address": address.street_address,
        "barangay": address.barangay,
        "municipality_city": address.municipality_city,
        "province": address.province,
        "postal_code": address.postal_code,
        "country": address.country,
        "gps_coordinates": address.gps_coordinates,
    }


class LogisticsView(APIView):
    authentication_classes = [LogisticsAuthentication]
    permission_classes = [IsAuthenticated]


class VehiclesView(LogisticsView):
    def get(self, request):
        company = company_for(request.user)
        vehicles = Vehicle.objects.filter(
            logistics_business=company, deleted_at__isnull=True
        ).order_by("vehicle_id")
        return Response(VehicleSerializer(vehicles, many=True).data)

    def post(self, request):
        company = company_for(request.user)
        serializer = VehicleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vehicle = serializer.save(user=request.user, logistics_business=company)
        return Response(VehicleSerializer(vehicle).data, status=201)


class VehicleDetailView(LogisticsView):
    def patch(self, request, vehicle_id):
        company = company_for(request.user)
        with transaction.atomic():
            vehicle = get_object_or_404(
                Vehicle.objects.select_for_update(),
                pk=vehicle_id,
                logistics_business=company,
                deleted_at__isnull=True,
            )
            if vehicle.delivery_trips.filter(
                trip_status__in=(PLANNED, IN_TRANSIT)
            ).exists():
                return Response({"detail": "Vehicle has an active trip."}, status=409)
            serializer = VehicleSerializer(vehicle, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
        return Response(serializer.data)

    def delete(self, request, vehicle_id):
        company = company_for(request.user)
        with transaction.atomic():
            vehicle = get_object_or_404(
                Vehicle.objects.select_for_update(),
                pk=vehicle_id,
                logistics_business=company,
                deleted_at__isnull=True,
            )
            if vehicle.delivery_trips.filter(
                trip_status__in=(PLANNED, IN_TRANSIT)
            ).exists():
                return Response({"detail": "Vehicle has an active trip."}, status=409)
            vehicle.deleted_at = timezone.now()
            vehicle.save(update_fields=["deleted_at"])
        return Response(status=204)


class DeliveriesView(LogisticsView):
    def get(self, request):
        company = company_for(request.user)
        assignments = (
            DeliveryAssignment.objects.filter(
                company=company,
                order__deleted_at__isnull=True,
                order__reservation__status__in=(
                    OrderReservation.Status.RESERVED,
                    OrderReservation.Status.DELIVERED,
                ),
            )
            .select_related(
                "order",
                "order__reservation__pickup_address",
                "order__reservation__destination_address",
            )
            .order_by("id")
        )
        return Response(
            [
                {
                    "order_id": assignment.order_id,
                    "trip_id": assignment.trip_id,
                    "delivery_date": assignment.order.delivery_date,
                    "reservation_status": assignment.order.reservation.status,
                    "pickup_address": address_data(
                        assignment.order.reservation.pickup_address
                    ),
                    "destination_address": address_data(
                        assignment.order.reservation.destination_address
                    ),
                    "quantity_kg": assignment.order.items.aggregate(
                        total=Sum("quantity_ordered_kg")
                    )["total"],
                }
                for assignment in assignments
            ]
        )


class TripsView(LogisticsView):
    def get(self, request):
        company = company_for(request.user)
        trips = (
            DeliveryTrip.objects.filter(assignments__company=company)
            .distinct()
            .order_by("-trip_id")
        )
        return Response([trip_data(trip) for trip in trips])

    def post(self, request):
        company = company_for(request.user)
        serializer = TripInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        with transaction.atomic():
            vehicle = get_object_or_404(
                Vehicle.objects.select_for_update(),
                pk=data["vehicle_id"],
                logistics_business=company,
                deleted_at__isnull=True,
            )
            if vehicle.delivery_trips.filter(
                trip_status__in=(PLANNED, IN_TRANSIT)
            ).exists():
                return Response({"detail": "Vehicle has an active trip."}, status=409)
            assignments = list(
                DeliveryAssignment.objects.select_for_update(of=("self",))
                .filter(
                    company=company,
                    order_id__in=data["order_ids"],
                    order__reservation__status=OrderReservation.Status.RESERVED,
                )
                .select_related("order", "order__reservation")
                .order_by("order_id")
            )
            if len(assignments) != len(data["order_ids"]) or any(
                assignment.trip_id is not None
                or assignment.order.deleted_at is not None
                for assignment in assignments
            ):
                raise ValidationError(
                    {"order_ids": ["Orders are not available to this company."]}
                )
            if OrderReservation.objects.filter(
                order_id__in=data["order_ids"],
                status=OrderReservation.Status.RESERVED,
            ).count() != len(data["order_ids"]):
                raise ValidationError(
                    {"order_ids": ["Orders are not available to this company."]}
                )
            quantity = sum(
                (
                    assignment.order.items.aggregate(total=Sum("quantity_ordered_kg"))[
                        "total"
                    ]
                    or Decimal("0")
                )
                for assignment in assignments
            )
            if (
                not vehicle.max_weight_capacity_kg
                or quantity > vehicle.max_weight_capacity_kg
            ):
                raise ValidationError(
                    {"order_ids": ["Orders exceed vehicle weight capacity."]}
                )
            trip = DeliveryTrip.objects.create(
                driver=request.user,
                vehicle=vehicle,
                trip_status=PLANNED,
                eta=data.get("eta"),
                weight_utilization_pct=(
                    quantity / vehicle.max_weight_capacity_kg * 100
                ).quantize(Decimal("0.01")),
            )
            by_order = {assignment.order_id: assignment for assignment in assignments}
            for sequence, order_id in enumerate(data["order_ids"], start=1):
                assignment = by_order[order_id]
                assignment.trip = trip
                assignment.save(update_fields=["trip"])
                TripManifest.objects.create(
                    trip=trip, order=assignment.order, dropoff_sequence=sequence
                )
        return Response(trip_data(trip), status=201)


class TripDetailView(LogisticsView):
    def patch(self, request, trip_id):
        company = company_for(request.user)
        serializer = TripStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_status = int(serializer.validated_data["trip_status"])
        with transaction.atomic():
            trip = get_object_or_404(
                DeliveryTrip.objects.select_for_update(),
                pk=trip_id,
                pk__in=DeliveryAssignment.objects.filter(company=company).values(
                    "trip_id"
                ),
            )
            if (trip.trip_status, new_status) not in (
                (PLANNED, IN_TRANSIT),
                (IN_TRANSIT, COMPLETED),
            ):
                return Response(
                    {"detail": "Invalid trip status transition."}, status=409
                )
            trip.trip_status = new_status
            trip.save(update_fields=["trip_status"])
            if new_status == COMPLETED:
                OrderReservation.objects.filter(
                    order__delivery_assignment__trip=trip
                ).update(status=OrderReservation.Status.DELIVERED)
        return Response(trip_data(trip))
