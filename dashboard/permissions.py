from functools import wraps

from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError

NAVIGATION_ITEMS = (
    (
        "farmers",
        "Farmers",
        (
            "farmers.view_farmer_applications",
            "farmers.manage_dashboard_records",
        ),
    ),
    ("logistics", "Logistics", "farmers.manage_dashboard_records"),
    ("businesses", "Bulk Buyers", "farmers.manage_dashboard_records"),
    ("reports", "Reports", "farmers.view_dashboard_reports"),
    (
        "code_requests",
        "Verification Requests",
        "farmers.view_farmer_code_requests",
    ),
    ("audit_logs", "Audit Logs", "farmers.view_dashboard_audit_logs"),
)

USER_SECTIONS = {"farmers", "logistics", "businesses"}


def has_dashboard_permission(user, permission):
    if not user.is_authenticated or not user.is_active or not user.is_staff:
        return False
    if user.is_superuser or not user.groups.exists():
        return True
    permissions = (permission,) if isinstance(permission, str) else permission
    return any(user.has_perm(required) for required in permissions)


def pending_code_request_farmer_count():
    from farmers.models import FarmerCodeRequest

    try:
        return (
            FarmerCodeRequest.objects.filter(
                status=FarmerCodeRequest.Status.PENDING_REVIEW
            )
            .values("user_id")
            .distinct()
            .count()
        )
    except DatabaseError:
        return 0


def pending_account_request_count():
    from shared.models import AccountCodeRequest

    try:
        return (
            AccountCodeRequest.objects.filter(
                status=AccountCodeRequest.Status.PENDING_REVIEW
            )
            .values("user_id")
            .distinct()
            .count()
        )
    except DatabaseError:
        return 0


def dashboard_navigation(user):
    items = [
        {
            "key": key,
            "label": label,
            "group": "users" if key in USER_SECTIONS else "features",
        }
        for key, label, permission in NAVIGATION_ITEMS
        if has_dashboard_permission(user, permission)
    ]
    for item in items:
        if item["key"] == "code_requests":
            item["badge"] = (
                pending_code_request_farmer_count() + pending_account_request_count()
            )
    return items


def dashboard_permission_required(permission):
    def decorate(view):
        @staff_member_required(login_url="dashboard_login")
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not has_dashboard_permission(request.user, permission):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapped

    return decorate
