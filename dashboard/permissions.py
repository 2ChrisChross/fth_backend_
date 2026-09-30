from functools import wraps

from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied

NAVIGATION_ITEMS = (
    ("reports", "Reports", "farmers.view_dashboard_reports"),
    (
        "farmers",
        "Farmers",
        (
            "farmers.view_farmer_applications",
            "farmers.manage_dashboard_records",
        ),
    ),
    (
        "code_requests",
        "Farmer Code Requests",
        "farmers.view_farmer_code_requests",
    ),
    ("logistics", "Logistics", "farmers.manage_dashboard_records"),
    ("businesses", "Bulk Buyers", "farmers.manage_dashboard_records"),
    ("audit_logs", "Audit Logs", "farmers.view_dashboard_audit_logs"),
)


def has_dashboard_permission(user, permission):
    if not user.is_authenticated or not user.is_active or not user.is_staff:
        return False
    if user.is_superuser or not user.groups.exists():
        return True
    permissions = (permission,) if isinstance(permission, str) else permission
    return any(user.has_perm(required) for required in permissions)


def dashboard_navigation(user):
    return [
        {"key": key, "label": label}
        for key, label, permission in NAVIGATION_ITEMS
        if has_dashboard_permission(user, permission)
    ]


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