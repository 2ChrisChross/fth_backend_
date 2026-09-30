from django.contrib.auth.hashers import check_password
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.views import TokenRefreshView

from farmers.models import FarmerCodeRequest
from farmers.permissions import (
    CanIssueFarmerCodes,
    CanManuallyVerifyFarmer,
    CanReviewFarmerCodeRequests,
    CanViewFarmerApplications,
    CanViewFarmerCodeRequests,
)
from farmers.registration import create_farmer_registration
from farmers.tokens import FarmerRefreshToken
from farmers.workflows import (
    OPEN_CODE_REQUEST_STATUSES,
    FarmerWorkflowConflict,
    FarmerWorkflowValidationError,
    issue_farmer_code,
    manually_verify_farmer,
    mark_farmer_code_mailed,
    review_farmer_code_request,
)
from shared.models import PhoneNumber, User
from shared.registration import resolve_enum_order_id

from .authentication import FarmerJWTAuthentication
from .serializers import (
    FarmerCodeRecoverySerializer,
    FarmerCodeRequestSerializer,
    FarmerLoginSerializer,
    FarmerProfileSerializer,
    FarmerRegistrationSerializer,
    FarmerTokenRefreshSerializer,
)


class FarmerTokenRefreshView(TokenRefreshView):
    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = FarmerTokenRefreshSerializer


@api_view(["POST"])
@permission_classes([AllowAny])
def login_user(request):
    serializer = FarmerLoginSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    credentials = serializer.validated_data
    user = User.objects.filter(
        username=credentials["username"], deleted_at__isnull=True
    ).first()
    if user is None or not check_password(
        credentials["password"], user.password_hash or ""
    ):
        return Response(
            {"detail": "Invalid username or password."},
            status=status.HTTP_401_UNAUTHORIZED,
        )
    if user.is_verified != 1:
        return Response(
            {"detail": "Account verification is required before login."},
            status=status.HTTP_403_FORBIDDEN,
        )
    farmer_role_id = resolve_enum_order_id("role", "Farmer")
    if farmer_role_id is None or user.role != farmer_role_id:
        return Response(
            {"detail": "This account cannot use farmer login."},
            status=status.HTTP_403_FORBIDDEN,
        )
    refresh = FarmerRefreshToken.for_user(user)
    return Response(
        {"access": str(refresh.access_token), "refresh": str(refresh)},
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@authentication_classes([FarmerJWTAuthentication])
@permission_classes([IsAuthenticated])
def logout_user(request):
    try:
        refresh = FarmerRefreshToken(str(request.data.get("refresh") or ""))
        token_user_id = refresh["user_id"]
    except (KeyError, TokenError, TypeError):
        return Response(
            {"detail": "A valid refresh token is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if str(token_user_id) != str(request.user.user_id):
        return Response(
            {"detail": "Refresh token does not belong to the authenticated farmer."},
            status=status.HTTP_403_FORBIDDEN,
        )
    refresh.blacklist()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET", "PATCH"])
@authentication_classes([FarmerJWTAuthentication])
@permission_classes([IsAuthenticated])
def farmer_profile(request):
    if request.method == "GET":
        return Response(FarmerProfileSerializer(request.user).data)
    serializer = FarmerProfileSerializer(
        request.user,
        data=request.data,
        partial=True,
        context={"request": request},
    )
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(FarmerProfileSerializer(request.user).data)


@api_view(["POST"])
@permission_classes([AllowAny])
def request_farmer_code(request):
    serializer = FarmerCodeRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    user = (
        User.objects.filter(
            phone_numbers__mobile_number=data["phone_number"],
            first_name__iexact=data["first_name"],
            last_name__iexact=data["last_name"],
            deleted_at__isnull=True,
        )
        .order_by("-user_id")
        .first()
    )
    purpose = data["purpose"]
    farmer_role_id = resolve_enum_order_id("role", "Farmer")
    eligible = (
        user is not None
        and farmer_role_id is not None
        and user.role == farmer_role_id
        and (
            (
                purpose == FarmerCodeRequest.Purpose.VERIFICATION
                and user.is_verified != 1
            )
            or (
                purpose == FarmerCodeRequest.Purpose.RECOVERY
                and user.is_verified == 1
            )
        )
    )
    if eligible:
        open_requests = FarmerCodeRequest.objects.filter(
            user=user,
            purpose=purpose,
            status__in=OPEN_CODE_REQUEST_STATUSES,
        )
        if (
            user.verification_code_expires_at
            and user.verification_code_expires_at <= timezone.now()
        ):
            open_requests.filter(
                status__in=(
                    FarmerCodeRequest.Status.CODE_ISSUED,
                    FarmerCodeRequest.Status.MAILED,
                )
            ).update(status=FarmerCodeRequest.Status.EXPIRED)
            user.verification_code = None
            user.verification_code_purpose = None
            user.verification_code_expires_at = None
            user.save(
                update_fields=[
                    "verification_code",
                    "verification_code_purpose",
                    "verification_code_expires_at",
                ]
            )
        outstanding_codes = open_requests.filter(
            status__in=(
                FarmerCodeRequest.Status.CODE_ISSUED,
                FarmerCodeRequest.Status.MAILED,
            )
        )
        if outstanding_codes.exists():
            outstanding_codes.update(status=FarmerCodeRequest.Status.EXPIRED)
            user.verification_code = None
            user.verification_code_purpose = None
            user.verification_code_expires_at = None
            user.save(
                update_fields=[
                    "verification_code",
                    "verification_code_purpose",
                    "verification_code_expires_at",
                ]
            )
        if not open_requests.exists():
            FarmerCodeRequest.objects.create(user=user, purpose=purpose)
    return Response(
        {"detail": "If the account is eligible, the request will be reviewed."},
        status=status.HTTP_202_ACCEPTED,
    )


@api_view(["POST"])
@permission_classes([AllowAny])
def verify_user_code(request):
    serializer = FarmerCodeRecoverySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    users = User.objects.filter(
        phone_numbers__mobile_number=data["phone_number"],
        deleted_at__isnull=True,
    ).filter(Q(is_verified=0) | Q(is_verified__isnull=True)).order_by("-user_id")
    now = timezone.now()
    for user in users:
        if (
            user.verification_code_purpose
            != FarmerCodeRequest.Purpose.VERIFICATION
            or user.verification_code_expires_at is None
            or user.verification_code_expires_at <= now
            or not check_password(
                data["verification_code"], user.verification_code or ""
            )
        ):
            continue
        code_request = FarmerCodeRequest.objects.filter(
            user=user,
            purpose=FarmerCodeRequest.Purpose.VERIFICATION,
            status=FarmerCodeRequest.Status.MAILED,
        ).order_by("-code_issued_at").first()
        if code_request is None:
            continue
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=user.pk)
            if user.is_verified == 1 or not check_password(
                data["verification_code"], user.verification_code or ""
            ):
                continue
            user.is_verified = 1
            user.verification_code = None
            user.verification_code_purpose = None
            user.verification_code_expires_at = None
            user.save(
                update_fields=[
                    "is_verified",
                    "verification_code",
                    "verification_code_purpose",
                    "verification_code_expires_at",
                ]
            )
            code_request.status = FarmerCodeRequest.Status.COMPLETED
            code_request.save(update_fields=["status"])
            PhoneNumber.objects.filter(user=user).update(is_verified=1)
        return Response({"valid": True}, status=status.HTTP_200_OK)
    return Response({"valid": False}, status=status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([AllowAny])
def recover_farmer_account(request):
    serializer = FarmerCodeRecoverySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    now = timezone.now()
    farmer_role_id = resolve_enum_order_id("role", "Farmer")
    if farmer_role_id is None:
        return Response(
            {"detail": "The recovery code is invalid or expired."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    users = User.objects.filter(
        phone_numbers__mobile_number=data["phone_number"],
        is_verified=1,
        role=farmer_role_id,
        deleted_at__isnull=True,
    ).order_by("-user_id")
    for user in users:
        if (
            user.verification_code_purpose != FarmerCodeRequest.Purpose.RECOVERY
            or user.verification_code_expires_at is None
            or user.verification_code_expires_at <= now
            or not check_password(
                data["verification_code"], user.verification_code or ""
            )
        ):
            continue
        code_request = FarmerCodeRequest.objects.filter(
            user=user,
            purpose=FarmerCodeRequest.Purpose.RECOVERY,
            status=FarmerCodeRequest.Status.MAILED,
        ).order_by("-code_issued_at").first()
        if code_request is None:
            continue
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=user.pk)
            if not check_password(
                data["verification_code"], user.verification_code or ""
            ):
                continue
            user.verification_code = None
            user.verification_code_purpose = None
            user.verification_code_expires_at = None
            user.save(
                update_fields=[
                    "verification_code",
                    "verification_code_purpose",
                    "verification_code_expires_at",
                ]
            )
            code_request.status = FarmerCodeRequest.Status.COMPLETED
            code_request.save(update_fields=["status"])
        refresh = FarmerRefreshToken.for_user(user)
        return Response(
            {"access": str(refresh.access_token), "refresh": str(refresh)},
            status=status.HTTP_200_OK,
        )
    return Response(
        {"detail": "The recovery code is invalid or expired."},
        status=status.HTTP_400_BAD_REQUEST,
    )


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([CanViewFarmerCodeRequests])
def admin_code_requests(request):
    requests = FarmerCodeRequest.objects.select_related("user").order_by(
        "requested_at"
    )
    request_status = request.query_params.get("status")
    if request_status:
        if request_status not in FarmerCodeRequest.Status.values:
            return Response(
                {"status": ["Select a valid request status."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        requests = requests.filter(status=request_status)
    results = []
    for code_request in requests:
        farmer = code_request.user
        phone = farmer.phone_numbers.order_by("phone_id").first()
        results.append(
            {
                "request_id": code_request.request_id,
                "purpose": code_request.purpose,
                "status": code_request.status,
                "requested_at": code_request.requested_at,
                "reviewed_at": code_request.reviewed_at,
                "review_reason": code_request.review_reason,
                "code_issued_at": code_request.code_issued_at,
                "code_expires_at": code_request.code_expires_at,
                "mailed_at": code_request.mailed_at,
                "farmer": {
                    "user_id": farmer.user_id,
                    "username": farmer.username,
                    "first_name": farmer.first_name,
                    "last_name": farmer.last_name,
                    "phone_number": phone.mobile_number if phone else None,
                },
            }
        )
    return Response(results)


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([CanViewFarmerApplications])
def admin_code_request_detail(request, request_id):
    code_request = get_object_or_404(
        FarmerCodeRequest.objects.select_related(
            "user", "reviewed_by", "issued_by", "mailed_by"
        ),
        request_id=request_id,
    )
    farmer = code_request.user
    phone = farmer.phone_numbers.order_by("phone_id").first()
    return Response(
        {
            "request_id": code_request.request_id,
            "purpose": code_request.purpose,
            "status": code_request.status,
            "requested_at": code_request.requested_at,
            "reviewed_at": code_request.reviewed_at,
            "reviewed_by": code_request.reviewed_by_id,
            "review_reason": code_request.review_reason,
            "code_issued_at": code_request.code_issued_at,
            "code_expires_at": code_request.code_expires_at,
            "issued_by": code_request.issued_by_id,
            "mailed_at": code_request.mailed_at,
            "mailed_by": code_request.mailed_by_id,
            "farmer": {
                "user_id": farmer.user_id,
                "username": farmer.username,
                "first_name": farmer.first_name,
                "middle_name": farmer.middle_name,
                "last_name": farmer.last_name,
                "phone_number": phone.mobile_number if phone else None,
                "is_verified": farmer.is_verified == 1,
                "documents": list(
                    farmer.electronic_documents.filter(
                        date_time_deleted__isnull=True
                    ).values(
                        "doc_id",
                        "doc_title",
                        "file_url",
                        "verification_status",
                    )
                ),
            },
            "audit_events": list(
                code_request.admin_events.values(
                    "action",
                    "reason",
                    "created_at",
                    "staff_user_id",
                )
            ),
        }
    )


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([CanReviewFarmerCodeRequests])
def admin_review_code_request(request, request_id):
    decision = str(request.data.get("decision") or "").strip().lower()
    reason = str(request.data.get("reason") or "").strip()
    try:
        code_request = review_farmer_code_request(
            request_id, request.user, decision, reason
        )
    except FarmerCodeRequest.DoesNotExist:
        return Response(
            {"detail": "Request not found."}, status=status.HTTP_404_NOT_FOUND
        )
    except FarmerWorkflowValidationError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    except FarmerWorkflowConflict as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
    return Response({"request_id": request_id, "status": code_request.status})


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([CanIssueFarmerCodes])
def admin_issue_code(request, request_id):
    try:
        code_request, code, expires_at = issue_farmer_code(request_id, request.user)
    except FarmerCodeRequest.DoesNotExist:
        return Response(
            {"detail": "Request not found."}, status=status.HTTP_404_NOT_FOUND
        )
    except FarmerWorkflowConflict as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
    response = Response(
        {
            "request_id": request_id,
            "status": code_request.status,
            "code": code,
            "expires_at": expires_at,
        }
    )
    response["Cache-Control"] = "no-store"
    return response


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([CanIssueFarmerCodes])
def admin_mark_code_mailed(request, request_id):
    try:
        code_request = mark_farmer_code_mailed(request_id, request.user)
    except FarmerCodeRequest.DoesNotExist:
        return Response(
            {"detail": "Request not found."}, status=status.HTTP_404_NOT_FOUND
        )
    except FarmerWorkflowConflict as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
    return Response({"request_id": request_id, "status": code_request.status})


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([CanManuallyVerifyFarmer])
def admin_manually_verify_farmer(request, user_id):
    reason = str(request.data.get("reason") or "").strip()
    try:
        manually_verify_farmer(user_id, request.user, reason)
    except User.DoesNotExist:
        return Response(
            {"detail": "Farmer not found."}, status=status.HTTP_404_NOT_FOUND
        )
    except FarmerWorkflowValidationError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    except FarmerWorkflowConflict as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
    return Response({"user_id": user_id, "is_verified": True})


@api_view(["POST"])
@permission_classes([AllowAny])
def register_user(request):
    request_data = request.data if isinstance(request.data, dict) else {}
    serializer = FarmerRegistrationSerializer(data=request_data)
    serializer.is_valid(raise_exception=True)
    result = create_farmer_registration(serializer.validated_data, request)
    user = result["user"]
    phone = result["phone"]
    farm = result["farm"]
    code_request = result["code_request"]
    return Response(
        {
            "message": "Registration successful.",
            "user_id": user.user_id,
            "username": user.username,
            "phone_id": phone.phone_id,
            "farm_id": farm.farm_id,
            "code_request_id": code_request.request_id,
            "language_order_id": result["language_order_id"],
            "role_order_id": result["role_order_id"],
            "onboarding_status_order_id": result["onboarding_status_order_id"],
            "payment_method_order_id": result["payment_method_order_id"],
            "document_type_order_ids": result["document_type_order_ids"],
            "document_count": result["document_count"],
        },
        status=status.HTTP_201_CREATED,
    )