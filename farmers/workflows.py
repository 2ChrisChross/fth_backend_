from datetime import timedelta

from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import get_random_string

from shared.models import PhoneNumber, User
from shared.registration import resolve_enum_order_id

from .models import FarmerAdminAuditEvent, FarmerCodeRequest

CODE_LIFETIME = timedelta(days=14)
OPEN_CODE_REQUEST_STATUSES = (
    FarmerCodeRequest.Status.PENDING_REVIEW,
    FarmerCodeRequest.Status.APPROVED,
    FarmerCodeRequest.Status.CODE_ISSUED,
    FarmerCodeRequest.Status.MAILED,
)


class FarmerWorkflowConflict(Exception):
    pass


class FarmerWorkflowValidationError(Exception):
    pass


def review_farmer_code_request(request_id, staff_user, decision, reason=""):
    if decision not in ("approve", "reject"):
        raise FarmerWorkflowValidationError("Choose approve or reject.")
    if decision == "reject" and not reason:
        raise FarmerWorkflowValidationError(
            "A reason is required when rejecting a request."
        )

    with transaction.atomic():
        code_request = FarmerCodeRequest.objects.select_for_update().select_related(
            "user"
        ).get(request_id=request_id)
        if code_request.status != FarmerCodeRequest.Status.PENDING_REVIEW:
            raise FarmerWorkflowConflict("Only pending requests can be reviewed.")
        code_request.status = (
            FarmerCodeRequest.Status.APPROVED
            if decision == "approve"
            else FarmerCodeRequest.Status.REJECTED
        )
        code_request.reviewed_at = timezone.now()
        code_request.reviewed_by = staff_user
        code_request.review_reason = reason
        code_request.save(
            update_fields=[
                "status",
                "reviewed_at",
                "reviewed_by",
                "review_reason",
            ]
        )
        FarmerAdminAuditEvent.objects.create(
            user=code_request.user,
            code_request=code_request,
            staff_user=staff_user,
            action=(
                FarmerAdminAuditEvent.Action.APPROVED
                if decision == "approve"
                else FarmerAdminAuditEvent.Action.REJECTED
            ),
            reason=reason,
        )
    return code_request


def issue_farmer_code(request_id, staff_user):
    with transaction.atomic():
        code_request = FarmerCodeRequest.objects.select_for_update().select_related(
            "user"
        ).get(request_id=request_id)
        if code_request.status != FarmerCodeRequest.Status.APPROVED:
            raise FarmerWorkflowConflict("Only approved requests can receive a code.")
        farmer = code_request.user
        farmer_role_id = resolve_enum_order_id("role", "Farmer")
        if farmer_role_id is None or farmer.role != farmer_role_id or (
            code_request.purpose == FarmerCodeRequest.Purpose.VERIFICATION
            and farmer.is_verified == 1
        ) or (
            code_request.purpose == FarmerCodeRequest.Purpose.RECOVERY
            and farmer.is_verified != 1
        ):
            raise FarmerWorkflowConflict(
                "The farmer account is not eligible for this code."
            )

        code = get_random_string(
            8,
            allowed_chars="ABCDEFGHJKLMNPQRSTUVWXYZ23456789",
        )
        issued_at = timezone.now()
        expires_at = issued_at + CODE_LIFETIME
        farmer.verification_code = make_password(code)
        farmer.verification_code_purpose = code_request.purpose
        farmer.verification_code_expires_at = expires_at
        farmer.save(
            update_fields=[
                "verification_code",
                "verification_code_purpose",
                "verification_code_expires_at",
            ]
        )
        code_request.status = FarmerCodeRequest.Status.CODE_ISSUED
        code_request.code_issued_at = issued_at
        code_request.code_expires_at = expires_at
        code_request.issued_by = staff_user
        code_request.mailed_at = None
        code_request.mailed_by = None
        code_request.save(
            update_fields=[
                "status",
                "code_issued_at",
                "code_expires_at",
                "issued_by",
                "mailed_at",
                "mailed_by",
            ]
        )
        FarmerAdminAuditEvent.objects.create(
            user=farmer,
            code_request=code_request,
            staff_user=staff_user,
            action=FarmerAdminAuditEvent.Action.CODE_ISSUED,
        )
    return code_request, code, expires_at


def mark_farmer_code_mailed(request_id, staff_user):
    code_expired = False
    with transaction.atomic():
        code_request = FarmerCodeRequest.objects.select_for_update().select_related(
            "user"
        ).get(request_id=request_id)
        if code_request.status != FarmerCodeRequest.Status.CODE_ISSUED:
            raise FarmerWorkflowConflict("Only issued codes can be marked as mailed.")
        if (
            not code_request.code_expires_at
            or code_request.code_expires_at <= timezone.now()
        ):
            code_request.status = FarmerCodeRequest.Status.EXPIRED
            code_request.save(update_fields=["status"])
            code_expired = True
        else:
            code_request.status = FarmerCodeRequest.Status.MAILED
            code_request.mailed_at = timezone.now()
            code_request.mailed_by = staff_user
            code_request.save(update_fields=["status", "mailed_at", "mailed_by"])
            FarmerAdminAuditEvent.objects.create(
                user=code_request.user,
                code_request=code_request,
                staff_user=staff_user,
                action=FarmerAdminAuditEvent.Action.CODE_MAILED,
            )
    if code_expired:
        raise FarmerWorkflowConflict("The code has expired; issue a new code request.")
    return code_request


def manually_verify_farmer(user_id, staff_user, reason):
    reason = reason.strip()
    if not reason:
        raise FarmerWorkflowValidationError(
            "A reason is required for manual verification."
        )

    with transaction.atomic():
        farmer = User.objects.select_for_update().get(
            user_id=user_id,
            deleted_at__isnull=True,
        )
        farmer_role_id = resolve_enum_order_id("role", "Farmer")
        if farmer_role_id is None or farmer.role != farmer_role_id:
            raise FarmerWorkflowConflict(
                "Only farmer accounts can be manually verified."
            )
        if farmer.is_verified == 1:
            raise FarmerWorkflowConflict("The farmer is already verified.")
        farmer.is_verified = 1
        farmer.verification_code = None
        farmer.verification_code_purpose = None
        farmer.verification_code_expires_at = None
        farmer.save(
            update_fields=[
                "is_verified",
                "verification_code",
                "verification_code_purpose",
                "verification_code_expires_at",
            ]
        )
        PhoneNumber.objects.filter(user=farmer).update(is_verified=1)
        FarmerCodeRequest.objects.filter(
            user=farmer,
            purpose=FarmerCodeRequest.Purpose.VERIFICATION,
            status__in=OPEN_CODE_REQUEST_STATUSES,
        ).update(
            status=FarmerCodeRequest.Status.COMPLETED,
            reviewed_at=timezone.now(),
            reviewed_by=staff_user,
            review_reason=reason,
        )
        FarmerAdminAuditEvent.objects.create(
            user=farmer,
            staff_user=staff_user,
            action=FarmerAdminAuditEvent.Action.MANUALLY_VERIFIED,
            reason=reason,
        )
    return farmer