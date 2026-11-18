from decimal import Decimal

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from businesses.commerce import order_data
from logistics.models import DeliveryAssignment
from shared.models import Address, Order

from .authentication import FarmerJWTAuthentication
from .models import Crop, CropCalendar, CropType, Farm, MarketplaceListing


class FarmerView(APIView):
    authentication_classes = [FarmerJWTAuthentication]
    permission_classes = [IsAuthenticated]


class FarmAddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = Address
        fields = (
            "street_address",
            "barangay",
            "municipality_city",
            "province",
            "postal_code",
            "country",
            "gps_coordinates",
        )
        extra_kwargs = {
            "street_address": {
                "required": True,
                "allow_blank": False,
                "allow_null": False,
            },
            "barangay": {"required": True, "allow_blank": False, "allow_null": False},
            "municipality_city": {
                "required": True,
                "allow_blank": False,
                "allow_null": False,
            },
            "province": {"required": True, "allow_blank": False, "allow_null": False},
            "postal_code": {
                "required": True,
                "allow_blank": False,
                "allow_null": False,
            },
        }


class FarmSerializer(serializers.ModelSerializer):
    address = FarmAddressSerializer()
    farm_size_hectares = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal("0")
    )

    class Meta:
        model = Farm
        fields = ("farm_id", "farm_size_hectares", "address")
        read_only_fields = ("farm_id",)

    @transaction.atomic
    def create(self, validated_data):
        address = Address.objects.create(
            **validated_data.pop("address"), address_type="farm"
        )
        return Farm.objects.create(
            user=self.context["request"].user, address=address, **validated_data
        )

    @transaction.atomic
    def update(self, instance, validated_data):
        address_data = validated_data.pop("address", None)
        if address_data is not None:
            old_address = instance.address
            fields = FarmAddressSerializer.Meta.fields
            values = {
                field: getattr(old_address, field)
                for field in fields
                if old_address is not None
            }
            values.update(address_data)
            instance.address = Address.objects.create(**values, address_type="farm")
        if "farm_size_hectares" in validated_data:
            instance.farm_size_hectares = validated_data["farm_size_hectares"]
        instance.save()
        return instance


class CropListingInput(serializers.Serializer):
    farm_id = serializers.IntegerField(min_value=1, required=False)
    crop_type_id = serializers.IntegerField(min_value=1, required=False)
    crop_id = serializers.IntegerField(min_value=1, required=False)
    batch_number = serializers.CharField(
        max_length=255, required=False, allow_blank=True
    )
    title = serializers.CharField(max_length=255)
    available_stock_kg = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0"), required=False
    )
    price_per_kg = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0")
    )
    is_active = serializers.BooleanField()

    def validate(self, attrs):
        if "crop_id" in attrs:
            if "farm_id" in attrs or "crop_type_id" in attrs:
                raise serializers.ValidationError(
                    "Choose an existing crop or a farm and crop type, not both."
                )
            if "available_stock_kg" in attrs:
                raise serializers.ValidationError(
                    "Update existing crop stock separately after creating the listing."
                )
        elif "farm_id" not in attrs or "crop_type_id" not in attrs:
            raise serializers.ValidationError(
                "Provide an existing crop ID, or both a farm ID and crop type ID."
            )
        elif "available_stock_kg" not in attrs:
            raise serializers.ValidationError(
                {"available_stock_kg": "Enter available stock for the new crop."}
            )
        return attrs


class CropListingUpdate(serializers.Serializer):
    batch_number = serializers.CharField(
        max_length=255, required=False, allow_blank=True
    )
    title = serializers.CharField(max_length=255, required=False)
    available_stock_kg = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0"), required=False
    )
    price_per_kg = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0"), required=False
    )
    is_active = serializers.BooleanField(required=False)


def farmer_listing_data(listing):
    crop = listing.crop
    return {
        "listing_id": listing.pk,
        "farm_id": crop.farm_id,
        "crop_id": crop.pk,
        "crop_type_id": crop.crop_type_id,
        "crop_name": crop.crop_type.crop_name if crop.crop_type else None,
        "batch_number": crop.batch_number,
        "title": listing.listing_title,
        "available_stock_kg": crop.available_stock_kg,
        "price_per_kg": listing.listing_price_per_kg,
        "is_active": listing.is_active == 1,
        "calendar_id": listing.calendar_id,
    }


def owned_listings(user):
    return MarketplaceListing.objects.filter(
        crop__farm__user=user,
        crop__farm__deleted_at__isnull=True,
        crop__deleted_at__isnull=True,
    )


class FarmsView(FarmerView):
    def get(self, request):
        farms = (
            Farm.objects.filter(user=request.user, deleted_at__isnull=True)
            .select_related("address")
            .order_by("farm_id")
        )
        return Response(FarmSerializer(farms, many=True).data)

    def post(self, request):
        serializer = FarmSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=201)


class FarmDetailView(FarmerView):
    @transaction.atomic
    def patch(self, request, farm_id):
        farm = get_object_or_404(
            Farm.objects.select_for_update(),
            pk=farm_id,
            user=request.user,
            deleted_at__isnull=True,
        )
        serializer = FarmSerializer(farm, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class CropTypesView(FarmerView):
    def get(self, request):
        return Response(
            list(
                CropType.objects.order_by("crop_name", "crop_type_id").values(
                    "crop_type_id", "crop_name"
                )
            )
        )


class CropsView(FarmerView):
    def get(self, request):
        crops = (
            Crop.objects.filter(
                farm__user=request.user,
                farm__deleted_at__isnull=True,
                deleted_at__isnull=True,
            )
            .select_related("crop_type")
            .order_by("crop_id")
        )
        return Response(
            [
                {
                    "crop_id": crop.pk,
                    "farm_id": crop.farm_id,
                    "crop_type_id": crop.crop_type_id,
                    "crop_name": crop.crop_type.crop_name if crop.crop_type else None,
                    "batch_number": crop.batch_number,
                    "available_stock_kg": crop.available_stock_kg,
                    "price_per_kg": crop.price_per_kg,
                }
                for crop in crops
            ]
        )


class FarmerListingsView(FarmerView):
    def get(self, request):
        listings = (
            owned_listings(request.user)
            .select_related("crop", "crop__crop_type")
            .order_by("listing_id")
        )
        return Response([farmer_listing_data(listing) for listing in listings])

    @transaction.atomic
    def post(self, request):
        serializer = CropListingInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if "crop_id" in data:
            crop = get_object_or_404(
                Crop.objects.select_for_update(of=("self",)).select_related("farm"),
                pk=data["crop_id"],
                farm__user=request.user,
                farm__deleted_at__isnull=True,
                deleted_at__isnull=True,
            )
            if "batch_number" in data:
                crop.batch_number = data["batch_number"]
                crop.save(update_fields=["batch_number"])
            calendar = crop.calendars.order_by("-calendar_id").first()
            if calendar is None:
                calendar = CropCalendar.objects.create(
                    crop=crop, pickup_address=crop.farm.address
                )
        else:
            farm = get_object_or_404(
                Farm.objects.select_for_update(),
                pk=data["farm_id"],
                user=request.user,
                deleted_at__isnull=True,
            )
            crop_type = get_object_or_404(CropType, pk=data["crop_type_id"])
            crop = Crop.objects.create(
                farm=farm,
                crop_type=crop_type,
                batch_number=data.get("batch_number", ""),
                available_stock_kg=data["available_stock_kg"],
                price_per_kg=data["price_per_kg"],
            )
            calendar = CropCalendar.objects.create(
                crop=crop, pickup_address=farm.address
            )
        listing = MarketplaceListing.objects.create(
            crop=crop,
            calendar=calendar,
            listing_title=data["title"],
            listing_price_per_kg=data["price_per_kg"],
            is_active=int(data["is_active"]),
            created_at=timezone.now(),
        )
        return Response(farmer_listing_data(listing), status=201)


class FarmerListingDetailView(FarmerView):
    @transaction.atomic
    def patch(self, request, listing_id):
        listing = get_object_or_404(
            owned_listings(request.user).select_for_update(of=("self",)),
            pk=listing_id,
        )
        crop = Crop.objects.select_for_update().get(pk=listing.crop_id)
        serializer = CropListingUpdate(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if "batch_number" in data:
            crop.batch_number = data["batch_number"]
        if "available_stock_kg" in data:
            crop.available_stock_kg = data["available_stock_kg"]
        if "price_per_kg" in data:
            crop.price_per_kg = data["price_per_kg"]
            listing.listing_price_per_kg = data["price_per_kg"]
        if "title" in data:
            listing.listing_title = data["title"]
        if "is_active" in data:
            listing.is_active = int(data["is_active"])
        crop.save()
        listing.save()
        listing.crop = crop
        return Response(farmer_listing_data(listing))


class FarmerOrdersView(FarmerView):
    def get(self, request):
        orders = (
            Order.objects.filter(
                reservation__crop__farm__user=request.user,
                deleted_at__isnull=True,
                reservation__isnull=False,
            )
            .select_related("reservation", "reservation__crop")
            .prefetch_related("items")
            .order_by("-order_id")
        )
        results = []
        for order in orders:
            assignment = (
                DeliveryAssignment.objects.filter(order=order)
                .select_related("trip")
                .first()
            )
            delivery_status = "not_assigned"
            if assignment:
                delivery_status = "awaiting_trip"
                if assignment.trip:
                    delivery_status = {
                        1: "planned",
                        2: "in_transit",
                        3: "completed",
                    }.get(assignment.trip.trip_status, "unknown")
            results.append(
                {
                    **order_data(order),
                    "crop_id": order.reservation.crop_id,
                    "buyer_id": order.buyer_id,
                    "delivery_status": delivery_status,
                }
            )
        return Response(results)
