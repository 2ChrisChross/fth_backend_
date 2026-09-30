from django.urls import include, path

from .farmer_views import farmer_detail
from .views import (
    DashboardLoginView,
    business_create,
    businesses_dashboard,
    dashboard_audit_logs,
    dashboard_entity_form,
    dashboard_logout,
    dashboard_reports,
    dashboard_user_delete,
    dashboard_user_form,
    dashboard_users,
    farmer_code_request_detail,
    farmer_code_requests,
    farmer_create,
    farmer_delete,
    farmer_edit,
    farmers_dashboard,
    logistics_create,
    logistics_dashboard,
)

farmer_urlpatterns = [
    path("", farmers_dashboard, name="dashboard"),
    path("create/", farmer_create, name="create"),
    path("<int:user_id>/", farmer_detail, name="detail"),
    path("edit/<int:user_id>/", farmer_edit, name="edit"),
    path("delete/<int:user_id>/", farmer_delete, name="delete"),
]

business_urlpatterns = [
    path("", businesses_dashboard, name="dashboard"),
    path("create/", business_create, name="create"),
]

logistics_urlpatterns = [
    path("", logistics_dashboard, name="dashboard"),
    path("create/", logistics_create, name="create"),
]

urlpatterns = [
    path("dashboard/login/", DashboardLoginView.as_view(), name="dashboard_login"),
    path("dashboard/logout/", dashboard_logout, name="dashboard_logout"),
    path(
        "dashboard/farmer-code-requests/",
        farmer_code_requests,
        name="dashboard_code_requests",
    ),
    path(
        "dashboard/farmer-code-requests/<int:request_id>/",
        farmer_code_request_detail,
        name="dashboard_code_request_detail",
    ),
    path("dashboard/", dashboard_users, name="dashboard_users"),
    path("dashboard/audit-logs/", dashboard_audit_logs, name="dashboard_audit_logs"),
    path("dashboard/reports/", dashboard_reports, name="dashboard_reports"),
    path("dashboard/create/", dashboard_user_form, name="dashboard_user_create"),
    path(
        "dashboard/create/<str:section>/",
        dashboard_entity_form,
        name="dashboard_entity_create",
    ),
    path(
        "dashboard/edit/<int:user_id>/", dashboard_user_form, name="dashboard_user_edit"
    ),
    path(
        "dashboard/delete/<int:user_id>/",
        dashboard_user_delete,
        name="dashboard_user_delete",
    ),
    path(
        "dashboard/farmers/",
        include((farmer_urlpatterns, "farmers"), namespace="farmers"),
    ),
    path(
        "dashboard/businesses/",
        include((business_urlpatterns, "businesses"), namespace="businesses"),
    ),
    path(
        "dashboard/logistics/",
        include((logistics_urlpatterns, "logistics"), namespace="logistics"),
    ),
]
