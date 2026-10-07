from datetime import timedelta

from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import get_random_string

from shared.audit import _log_audit_change, log_staff_audit_change
from shared.enums import enum_rows
from shared.models import ElectronicDocument, PhoneNumber, User
from shared.registration import resolve_enum_order_id

from .models import FarmerAdminAuditEvent, FarmerCodeRequest, FarmerDocumentRequest

CODE_LIFETIME = timedelta(days=14)
OPEN_CODE_REQUEST_STATUSES = (
    FarmerCodeRequest.Status.PENDING_REVIEW,
    FarmerCodeRequest.Status.APPROVED,
    FarmerCodeRequest.Status.CODE_ISSUED,
    FarmerCodeRequest.Status.MAILED,
)

def _code_request_snapshot(code_request):
    return {
        "status": code_request.status,
        "purpose": code_request.purpose,
        "review_reason": code_request.review_reason,
        "code_expires_at": code_request.code_expires_at,
    }


def _log_code_request_action(
    staff_user, code_request, action, old, reason="", request=None
):
    new_values = _code_request_snapshot(code_request)
    if reason:
        new_values["reason"] = reason
    log_staff_audit_change(
        staff_user=staff_user,
        user=code_request.user,
        action_type=action,
        target_table="FARMER_CODE_REQUESTS",
        target_id=code_request.request_id,
        old_values=old,
        new_values=new_values,
        request=request,
    )

class FarmerWorkflowConflict(Exception):
    pass


class FarmerWorkflowValidationError(Exception):
    pass


def pending_document_requests(user):
    return FarmerDocumentRequest.objects.filter(
        user=user, status=FarmerDocumentRequest.Status.PENDING
    )


def ensure_no_pending_document_requests(farmer):
    if pending_document_requests(farmer).exists():
        raise FarmerWorkflowConflict(
            "The farmer has unanswered document requests. "
            "They must submit the documents or the requests must be revoked."
        )


FARMER_DOCUMENT_TYPES = (
    "Utility Bills",
    "Valid_ID",
    "Owner_Address",
    "Farm_Ownership",
    "Birth_Certificate",
    "National_Id",
    "Nbi_Clearance",
)


def document_type_choices():
    """(ordering, label) for the farmer registration document types."""
    return [
        (ordering, value.replace("_", " "))
        for ordering, value in enum_rows("document_type", FARMER_DOCUMENT_TYPES)
    ]


def _document_request_snapshot(doc_request):
    return {
        "status": doc_request.status,
        "doc_type": doc_request.doc_type,
        "message": doc_request.message,
    }


def request_farmer_documents(user_id, staff_user, doc_types, message, request=None):
    message = (message or "").strip()
    if not message:
        raise FarmerWorkflowValidationError(
            "A message explaining why the documents are needed is required."
        )
    try:
        doc_types = list(dict.fromkeys(int(value) for value in doc_types))
    except (TypeError, ValueError):
        raise FarmerWorkflowValidationError("Choose valid document types.")
    if not doc_types:
        raise FarmerWorkflowValidationError("Choose at least one document type.")
    valid = {ordering for ordering, _ in document_type_choices()}
    if any(value not in valid for value in doc_types):
        raise FarmerWorkflowValidationError("Choose valid document types.")

    with transaction.atomic():
        farmer = User.objects.select_for_update().get(
            user_id=user_id, deleted_at__isnull=True
        )
        farmer_role_id = resolve_enum_order_id("role", "Farmer")
        if farmer_role_id is None or farmer.role != farmer_role_id:
            raise FarmerWorkflowConflict(
                "Documents can only be requested from farmer accounts."
            )
        already = set(
            pending_document_requests(farmer).values_list("doc_type", flat=True)
        )
        created = []
        for doc_type in doc_types:
            if doc_type in already:
                continue
            doc_request = FarmerDocumentRequest.objects.create(
                user=farmer,
                doc_type=doc_type,
                message=message,
                requested_by=staff_user,
            )
            log_staff_audit_change(
                staff_user=staff_user,
                user=farmer,
                action_type="DOCUMENT_REQUESTED",
                target_table="FARMER_DOCUMENT_REQUESTS",
                target_id=doc_request.request_id,
                old_values={},
                new_values={**_document_request_snapshot(doc_request), "reason": message},
                request=request,
            )
            created.append(doc_request)
        if not created:
            raise FarmerWorkflowConflict(
                "Those documents have already been requested from this farmer."
            )
    return created


def revoke_farmer_document_request(request_id, staff_user, reason, request=None):
    reason = (reason or "").strip()
    if not reason:
        raise FarmerWorkflowValidationError("A reason is required to revoke a request.")
    with transaction.atomic():
        doc_request = FarmerDocumentRequest.objects.select_for_update().select_related(
            "user"
        ).get(request_id=request_id)
        if doc_request.status != FarmerDocumentRequest.Status.PENDING:
            raise FarmerWorkflowConflict("Only pending requests can be revoked.")
        old = _document_request_snapshot(doc_request)
        doc_request.status = FarmerDocumentRequest.Status.REVOKED
        doc_request.revoked_at = timezone.now()
        doc_request.revoked_by = staff_user
        doc_request.revoke_reason = reason
        doc_request.save(
            update_fields=["status", "revoked_at", "revoked_by", "revoke_reason"]
        )
        log_staff_audit_change(
            staff_user=staff_user,
            user=doc_request.user,
            action_type="DOCUMENT_REQUEST_REVOKED",
            target_table="FARMER_DOCUMENT_REQUESTS",
            target_id=doc_request.request_id,
            old_values=old,
            new_values={**_document_request_snapshot(doc_request), "reason": reason},
            request=request,
        )
    return doc_request


def submit_farmer_document(request_id, farmer, file_url, request=None):
    file_url = (file_url or "").strip()
    if not file_url.lower().startswith(("http://", "https://")):
        raise FarmerWorkflowValidationError("Provide a valid HTTP or HTTPS file URL.")
    with transaction.atomic():
        doc_request = FarmerDocumentRequest.objects.select_for_update().get(
            request_id=request_id, user=farmer
        )
        if doc_request.status != FarmerDocumentRequest.Status.PENDING:
            raise FarmerWorkflowConflict("This request is no longer pending.")
        old = _document_request_snapshot(doc_request)
        document = ElectronicDocument.objects.create(
            user=farmer,
            doc_title=f"Requested document {doc_request.request_id}",
            doc_type=doc_request.doc_type,
            file_url=file_url,
            date_time_uploaded=timezone.now(),
        )
        doc_request.status = FarmerDocumentRequest.Status.SUBMITTED
        doc_request.submitted_at = timezone.now()
        doc_request.document = document
        doc_request.save(update_fields=["status", "submitted_at", "document"])
        _log_audit_change(
            user=farmer,
            action_type="DOCUMENT_SUBMITTED",
            target_table="FARMER_DOCUMENT_REQUESTS",
            target_id=doc_request.request_id,
            old_values=old,
            new_values=_document_request_snapshot(doc_request),
            request=request,
        )
    return doc_request


def review_farmer_code_request(
    request_id, staff_user, decision, reason="", request=None
):
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
        old_values = _code_request_snapshot(code_request)
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
        _log_code_request_action(
            staff_user,
            code_request,
            "CODE_REQUEST_APPROVED" if decision == "approve" else "CODE_REQUEST_REJECTED",
            old_values,
            reason,
            request,
        )
    return code_request


def issue_farmer_code(request_id, staff_user, request=None):
    with transaction.atomic():
        code_request = FarmerCodeRequest.objects.select_for_update().select_related(
            "user"
        ).get(request_id=request_id)
        if code_request.status != FarmerCodeRequest.Status.APPROVED:
            raise FarmerWorkflowConflict("Only approved requests can receive a code.")
        farmer = code_request.user
        if code_request.purpose == FarmerCodeRequest.Purpose.VERIFICATION:
            ensure_no_pending_document_requests(farmer)
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

        old_values = _code_request_snapshot(code_request)
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
        _log_code_request_action(
            staff_user, code_request, "CODE_ISSUED", old_values, request=request
        )
    return code_request, code, expires_at


def mark_farmer_code_mailed(request_id, staff_user, request=None):
    code_expired = False
    with transaction.atomic():
        code_request = FarmerCodeRequest.objects.select_for_update().select_related(
            "user"
        ).get(request_id=request_id)
        if code_request.status != FarmerCodeRequest.Status.CODE_ISSUED:
            raise FarmerWorkflowConflict("Only issued codes can be marked as mailed.")
        old_values = _code_request_snapshot(code_request)
        if (
            not code_request.code_expires_at
            or code_request.code_expires_at <= timezone.now()
        ):
            code_request.status = FarmerCodeRequest.Status.EXPIRED
            code_request.save(update_fields=["status"])
            _log_code_request_action(
                staff_user, code_request, "CODE_EXPIRED", old_values, request=request
            )
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
            _log_code_request_action(
                staff_user, code_request, "CODE_MAILED", old_values, request=request
            )
    if code_expired:
        raise FarmerWorkflowConflict("The code has expired; issue a new code request.")
    return code_request


def manually_verify_farmer(user_id, staff_user, reason, request=None):
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
        ensure_no_pending_document_requests(farmer)
        old_values = {"is_verified": farmer.is_verified}
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
        log_staff_audit_change(
            staff_user=staff_user,
            user=farmer,
            action_type="FARMER_MANUALLY_VERIFIED",
            target_table="USERS",
            target_id=farmer.user_id,
            old_values=old_values,
            new_values={"is_verified": 1, "reason": reason},
            request=request,
        )
    return farmer