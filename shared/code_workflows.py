from datetime import timedelta

from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import constant_time_compare, get_random_string

from shared.audit import log_staff_audit_change
from shared.models import AccountCodeRequest, PhoneNumber, User
from shared.registration import resolve_enum_order_id

CODE_LIFETIME = timedelta(days=14)
ROLE_BY_KIND = {
    AccountCodeRequest.Kind.BUSINESSES: "Bulk_Buyer",
    AccountCodeRequest.Kind.LOGISTICS: "Logistics_Manager",
}


class AccountWorkflowValidationError(Exception):
    pass


class AccountWorkflowConflict(Exception):
    pass


def _snapshot(code_request):
    return {
        "kind": code_request.kind,
        "status": code_request.status,
        "review_reason": code_request.review_reason,
        "code_expires_at": code_request.code_expires_at,
    }


def _audit(code_request, staff_user, action, previous, request):
    log_staff_audit_change(
        staff_user=staff_user,
        user=code_request.user,
        action_type=action,
        target_table="ACCOUNT_CODE_REQUESTS",
        target_id=code_request.pk,
        old_values=previous,
        new_values=_snapshot(code_request),
        request=request,
    )


def review_account_code_request(
    request_id, staff_user, decision, reason="", request=None
):
    reason = (reason or "").strip()
    if decision not in ("approve", "reject"):
        raise AccountWorkflowValidationError("Choose approve or reject.")
    if decision == "reject" and not reason:
        raise AccountWorkflowValidationError(
            "A reason is required when rejecting a request."
        )
    with transaction.atomic():
        code_request = (
            AccountCodeRequest.objects.select_for_update(of=("self",))
            .select_related("user")
            .get(pk=request_id)
        )
        if code_request.status != AccountCodeRequest.Status.PENDING_REVIEW:
            raise AccountWorkflowConflict("Only pending requests can be reviewed.")
        previous = _snapshot(code_request)
        code_request.status = (
            AccountCodeRequest.Status.APPROVED
            if decision == "approve"
            else AccountCodeRequest.Status.REJECTED
        )
        code_request.reviewed_by = staff_user
        code_request.reviewed_at = timezone.now()
        code_request.review_reason = reason
        code_request.save(
            update_fields=["status", "reviewed_by", "reviewed_at", "review_reason"]
        )
        action = (
            "CODE_REQUEST_APPROVED"
            if decision == "approve"
            else "CODE_REQUEST_REJECTED"
        )
        _audit(code_request, staff_user, action, previous, request)
    return code_request


def issue_account_code(request_id, staff_user, request=None):
    with transaction.atomic():
        user_id = AccountCodeRequest.objects.values_list("user_id", flat=True).get(
            pk=request_id
        )
        user = User.objects.select_for_update().get(pk=user_id)
        code_request = (
            AccountCodeRequest.objects.select_for_update(of=("self",))
            .select_related("user")
            .get(pk=request_id)
        )
        if code_request.status != AccountCodeRequest.Status.APPROVED:
            raise AccountWorkflowConflict("Only approved requests can receive a code.")
        role_id = resolve_enum_order_id("role", ROLE_BY_KIND[code_request.kind])
        if (
            role_id is None
            or user.role != role_id
            or user.is_verified == 1
            or user.deleted_at
        ):
            raise AccountWorkflowConflict("The account is not eligible for this code.")
        previous = _snapshot(code_request)
        code = get_random_string(8, allowed_chars="ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
        issued_at = timezone.now()
        expires_at = issued_at + CODE_LIFETIME
        user.verification_code = make_password(code)
        user.verification_code_purpose = "verification"
        user.verification_code_expires_at = expires_at
        user.save(
            update_fields=[
                "verification_code",
                "verification_code_purpose",
                "verification_code_expires_at",
            ]
        )
        code_request.status = AccountCodeRequest.Status.CODE_ISSUED
        code_request.code_issued_at = issued_at
        code_request.code_expires_at = expires_at
        code_request.issued_by = staff_user
        code_request.save(
            update_fields=["status", "code_issued_at", "code_expires_at", "issued_by"]
        )
        _audit(code_request, staff_user, "CODE_ISSUED", previous, request)
    return code_request, code, expires_at


def mark_account_code_mailed(request_id, staff_user, request=None):
    expired = False
    with transaction.atomic():
        code_request = (
            AccountCodeRequest.objects.select_for_update(of=("self",))
            .select_related("user")
            .get(pk=request_id)
        )
        if code_request.status != AccountCodeRequest.Status.CODE_ISSUED:
            raise AccountWorkflowConflict("Only issued codes can be marked as mailed.")
        previous = _snapshot(code_request)
        if (
            not code_request.code_expires_at
            or code_request.code_expires_at <= timezone.now()
        ):
            code_request.status = AccountCodeRequest.Status.EXPIRED
            code_request.save(update_fields=["status"])
            _audit(code_request, staff_user, "CODE_EXPIRED", previous, request)
            expired = True
        else:
            code_request.status = AccountCodeRequest.Status.MAILED
            code_request.mailed_at = timezone.now()
            code_request.mailed_by = staff_user
            code_request.save(update_fields=["status", "mailed_at", "mailed_by"])
            _audit(code_request, staff_user, "CODE_MAILED", previous, request)
    if expired:
        raise AccountWorkflowConflict("The code has expired; request a new code.")
    return code_request


def manually_verify_account(request_id, staff_user, reason, request=None):
    reason = (reason or "").strip()
    if not reason:
        raise AccountWorkflowValidationError(
            "A reason is required for manual verification."
        )
    with transaction.atomic():
        user_id = AccountCodeRequest.objects.values_list("user_id", flat=True).get(
            pk=request_id
        )
        user = User.objects.select_for_update().get(pk=user_id)
        code_request = (
            AccountCodeRequest.objects.select_for_update(of=("self",))
            .select_related("user")
            .get(pk=request_id)
        )
        role_id = resolve_enum_order_id("role", ROLE_BY_KIND[code_request.kind])
        if role_id is None or user.role != role_id or user.deleted_at:
            raise AccountWorkflowConflict(
                "The account is not eligible for verification."
            )
        if user.is_verified == 1:
            raise AccountWorkflowConflict("The account is already verified.")
        previous = _snapshot(code_request)
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
        PhoneNumber.objects.filter(user=user).update(is_verified=1)
        AccountCodeRequest.objects.filter(
            user=user,
            kind=code_request.kind,
            status__in=[
                AccountCodeRequest.Status.PENDING_REVIEW,
                AccountCodeRequest.Status.APPROVED,
                AccountCodeRequest.Status.CODE_ISSUED,
                AccountCodeRequest.Status.MAILED,
            ],
        ).update(
            status=AccountCodeRequest.Status.COMPLETED,
            reviewed_at=timezone.now(),
            reviewed_by=staff_user,
            review_reason=reason,
        )
        code_request.refresh_from_db()
        log_staff_audit_change(
            staff_user=staff_user,
            user=user,
            action_type="ACCOUNT_MANUALLY_VERIFIED",
            target_table="ACCOUNT_CODE_REQUESTS",
            target_id=code_request.pk,
            old_values=previous,
            new_values={**_snapshot(code_request), "reason": reason, "is_verified": 1},
            request=request,
        )
    return user


def verify_account_code(phone_number, code, kind):
    role_id = resolve_enum_order_id("role", ROLE_BY_KIND[kind])
    if not phone_number or not code or role_id is None:
        return False
    user_ids = (
        User.objects.filter(role=role_id, phone_numbers__mobile_number=phone_number)
        .order_by("-user_id")
        .values_list("user_id", flat=True)
    )
    for user_id in user_ids:
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=user_id)
            requests = AccountCodeRequest.objects.filter(user=user)
            if not requests.exists():
                # Accounts created before the review workflow keep their original code.
                if user.verification_code and constant_time_compare(
                    user.verification_code.strip(), code
                ):
                    if user.is_verified != 1:
                        user.is_verified = 1
                        user.save(update_fields=["is_verified"])
                    return True
                continue
            code_request = (
                requests.select_for_update()
                .filter(kind=kind, status=AccountCodeRequest.Status.MAILED)
                .order_by("-code_issued_at")
                .first()
            )
            now = timezone.now()
            if (
                user.deleted_at is not None
                or user.is_verified == 1
                or code_request is None
                or not code_request.code_expires_at
                or code_request.code_expires_at <= now
                or user.verification_code_purpose != "verification"
                or not user.verification_code_expires_at
                or user.verification_code_expires_at <= now
                or not check_password(code, user.verification_code or "")
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
            code_request.status = AccountCodeRequest.Status.COMPLETED
            code_request.save(update_fields=["status"])
            PhoneNumber.objects.filter(user=user).update(is_verified=1)
            return True
    return False


def request_new_account_code(username, password, kind):
    role_id = resolve_enum_order_id("role", ROLE_BY_KIND[kind])
    if role_id is None:
        return
    with transaction.atomic():
        user = (
            User.objects.select_for_update()
            .filter(username=username, role=role_id, deleted_at__isnull=True)
            .first()
        )
        if (
            user is None
            or user.is_verified == 1
            or not check_password(password, user.password_hash or "")
        ):
            return
        requests = AccountCodeRequest.objects.filter(user=user, kind=kind)
        if not requests.exists():
            return
        active = (
            requests.select_for_update()
            .filter(
                status__in=[
                    AccountCodeRequest.Status.PENDING_REVIEW,
                    AccountCodeRequest.Status.APPROVED,
                    AccountCodeRequest.Status.CODE_ISSUED,
                    AccountCodeRequest.Status.MAILED,
                ]
            )
            .first()
        )
        if active:
            if active.status in (
                AccountCodeRequest.Status.PENDING_REVIEW,
                AccountCodeRequest.Status.APPROVED,
            ) or (active.code_expires_at and active.code_expires_at > timezone.now()):
                return
            active.status = AccountCodeRequest.Status.EXPIRED
            active.save(update_fields=["status"])
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
        AccountCodeRequest.objects.create(user=user, kind=kind)
