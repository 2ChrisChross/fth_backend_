from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password
from django.db import IntegrityError, transaction
from django.utils.crypto import constant_time_compare, salted_hmac
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.settings import api_settings

from farmers.tokens import FarmerRefreshToken
from shared.code_workflows import request_new_account_code
from shared.models import User
from shared.registration import resolve_enum_order_id


def active_user(user_id, role):
    role_id = resolve_enum_order_id("role", role)
    if role_id is None:
        return None
    return User.objects.filter(
        user_id=user_id, role=role_id, is_verified=1, deleted_at__isnull=True
    ).first()


def password_version(user):
    return salted_hmac(
        "shared.account_api.password", user.password_hash or ""
    ).hexdigest()


def token_matches_password(token, user):
    version = token.get("password_version")
    return isinstance(version, str) and constant_time_compare(
        version, password_version(user)
    )


class RoleAuthentication(JWTAuthentication):
    role = None

    def get_user(self, validated_token):
        try:
            user_id = validated_token[api_settings.USER_ID_CLAIM]
        except KeyError as exc:
            raise AuthenticationFailed("Token has no user identifier.") from exc
        user = active_user(user_id, self.role)
        if user is None or not token_matches_password(validated_token, user):
            raise AuthenticationFailed(
                "Token is not for an active account of this role."
            )
        return user


class BuyerAuthentication(RoleAuthentication):
    role = "Bulk_Buyer"


class LogisticsAuthentication(RoleAuthentication):
    role = "Logistics_Manager"


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, trim_whitespace=False)


class CodeRequestView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    kind = None

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        request_new_account_code(
            serializer.validated_data["username"],
            serializer.validated_data["password"],
            self.kind,
        )
        return Response(
            {"detail": "If the account is eligible, the request will be reviewed."},
            status=202,
        )


class RefreshInputSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class ProfileSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(read_only=True)
    username = serializers.CharField(max_length=150, required=False)
    first_name = serializers.CharField(max_length=255, required=False)
    middle_name = serializers.CharField(
        max_length=255, required=False, allow_blank=True, allow_null=True
    )
    last_name = serializers.CharField(max_length=255, required=False)
    phone_number = serializers.SerializerMethodField()
    organization = serializers.SerializerMethodField()
    new_password = serializers.CharField(
        write_only=True, required=False, trim_whitespace=False
    )

    def get_phone_number(self, user):
        phone = user.phone_numbers.order_by("phone_id").first()
        return phone.mobile_number if phone else None

    def get_organization(self, user):
        if self.context["role"] == "Bulk_Buyer":
            buyer = (
                user.businesses.filter(date_time_deleted__isnull=True)
                .order_by("business_id")
                .first()
            )
            return (
                {"business_id": buyer.pk, "business_name": buyer.business_name}
                if buyer
                else None
            )
        from logistics.models import LogisticsCompany

        company = LogisticsCompany.objects.filter(
            user=user, date_time_deleted__isnull=True
        ).first()
        return (
            {
                "company_id": company.pk,
                "business_name": company.business_name,
                "contact_phone": company.contact_phone,
                "contact_email": company.contact_email,
            }
            if company
            else None
        )

    def validate_username(self, value):
        if User.objects.filter(username=value).exclude(pk=self.instance.pk).exists():
            raise serializers.ValidationError("This username is already in use.")
        return value

    def validate_new_password(self, value):
        validate_password(value, user=self.instance)
        return value

    def update(self, instance, validated_data):
        password = validated_data.pop("new_password", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        fields = list(validated_data)
        if password:
            instance.password_hash = make_password(password)
            fields.append("password_hash")
        if fields:
            instance.save(update_fields=fields)
        return instance


class LoginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    role = None

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = User.objects.filter(
            username=serializer.validated_data["username"], deleted_at__isnull=True
        ).first()
        if user is None or not check_password(
            serializer.validated_data["password"], user.password_hash or ""
        ):
            return Response({"detail": "Invalid username or password."}, status=401)
        role_id = resolve_enum_order_id("role", self.role)
        if user.is_verified != 1 or role_id is None or user.role != role_id:
            return Response({"detail": "This account cannot log in here."}, status=403)
        refresh = FarmerRefreshToken.for_user(user)
        refresh["password_version"] = password_version(user)
        return Response({"access": str(refresh.access_token), "refresh": str(refresh)})


class RefreshView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    role = None

    def post(self, request):
        serializer = RefreshInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = serializer.validated_data["refresh"]
        try:
            refresh = FarmerRefreshToken(token)
            user_id = refresh[api_settings.USER_ID_CLAIM]
            with transaction.atomic():
                role_id = resolve_enum_order_id("role", self.role)
                user = (
                    User.objects.select_for_update()
                    .filter(
                        user_id=user_id,
                        role=role_id,
                        is_verified=1,
                        deleted_at__isnull=True,
                    )
                    .first()
                    if role_id is not None
                    else None
                )
                if user is None or not token_matches_password(refresh, user):
                    raise TokenError("Inactive account")
                refresh = FarmerRefreshToken(token)
                refresh.blacklist()
                refresh.set_jti()
                refresh.set_exp()
                refresh.set_iat()
                return Response(
                    {"access": str(refresh.access_token), "refresh": str(refresh)}
                )
        except KeyError, TokenError, TypeError, ValueError:
            return Response(
                {"detail": "A valid refresh token is required."}, status=401
            )


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = RefreshInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        raw_token = serializer.validated_data["refresh"]
        try:
            with transaction.atomic():
                User.objects.select_for_update().get(pk=request.user.pk)
                token = FarmerRefreshToken(raw_token)
                if str(token[api_settings.USER_ID_CLAIM]) != str(request.user.pk):
                    return Response(
                        {"detail": "Token belongs to another account."}, status=403
                    )
                token.blacklist()
        except KeyError, TokenError, TypeError, ValueError:
            return Response(
                {"detail": "A valid refresh token is required."}, status=400
            )
        return Response(status=204)


class ProfileView(APIView):
    permission_classes = [IsAuthenticated]
    role = None

    def get(self, request):
        return Response(
            ProfileSerializer(request.user, context={"role": self.role}).data
        )

    def patch(self, request):
        serializer = ProfileSerializer(
            request.user, data=request.data, partial=True, context={"role": self.role}
        )
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                serializer.save()
        except IntegrityError:
            username = serializer.validated_data.get("username")
            if (
                username
                and User.objects.filter(username=username)
                .exclude(pk=request.user.pk)
                .exists()
            ):
                return Response(
                    {"username": ["This username is already in use."]}, status=409
                )
            raise
        return Response(
            ProfileSerializer(request.user, context={"role": self.role}).data
        )
