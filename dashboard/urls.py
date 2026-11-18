from django.urls import include, path

from .account_views import account_code_request_detail, account_code_requests
from .farmer_views import farmer_detail
from .simulator import (
    simulator_farmer_api,
    simulator_farmer_detail,
    simulator_farmers,
    simulator_map_asset,
    simulator_map_glyph,
    simulator_map_lookup,
    simulator_map_tile,
    simulator_page,
    simulator_register,
)
from .verification_views import verification_requests
from .views import (
    DashboardLoginView,
    businesses_dashboard,
    dashboard_audit_logs,
    dashboard_logout,
    dashboard_reports,
    dashboard_user_delete,
    dashboard_users,
    farmer_code_request_detail,
    farmer_code_requests,
    farmer_delete,
    farmers_dashboard,
    logistics_dashboard,
)

farmer_urlpatterns = [
    path("", farmers_dashboard, name="dashboard"),
    path("<int:user_id>/", farmer_detail, name="detail"),
    path("delete/<int:user_id>/", farmer_delete, name="delete"),
]

business_urlpatterns = [
    path("", businesses_dashboard, name="dashboard"),
]

logistics_urlpatterns = [
    path("", logistics_dashboard, name="dashboard"),
]

urlpatterns = [
    path("dashboard/login/", DashboardLoginView.as_view(), name="dashboard_login"),
    path("dashboard/logout/", dashboard_logout, name="dashboard_logout"),
    path("dashboard/local-test/<str:section>/", simulator_page, name="local_simulator"),
    path(
        "dashboard/local-map/assets/<str:asset>",
        simulator_map_asset,
        name="local_map_asset",
    ),
    path(
        "dashboard/local-map/glyphs/<str:fontstack>/<str:glyph_range>",
        simulator_map_glyph,
        name="local_map_glyph",
    ),
    path(
        "dashboard/local-map/tiles/<int:zoom>/<int:x>/<int:y>.pbf",
        simulator_map_tile,
        name="local_map_tile",
    ),
    path("dashboard/local-map/lookup/", simulator_map_lookup, name="local_map_lookup"),
    path(
        "dashboard/local-test-farmers/",
        simulator_farmers,
        name="local_simulator_farmers",
    ),
    path(
        "dashboard/local-test/farmers/<int:farmer_id>/api/<path:action>",
        simulator_farmer_api,
        name="local_simulator_farmer_api",
    ),
    path(
        "dashboard/local-test/farmers/<int:farmer_id>/",
        simulator_farmer_detail,
        name="local_simulator_farmer_detail",
    ),
    path(
        "dashboard/verification-requests/",
        verification_requests,
        name="dashboard_verification_requests",
    ),
    path(
        "dashboard/local-test/<str:section>/register/",
        simulator_register,
        name="local_simulator_register",
    ),
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
    path(
        "dashboard/account-code-requests/<str:kind>/",
        account_code_requests,
        name="dashboard_account_code_requests",
    ),
    path(
        "dashboard/account-code-requests/<str:kind>/<int:request_id>/",
        account_code_request_detail,
        name="dashboard_account_code_request_detail",
    ),
    path("dashboard/", dashboard_users, name="dashboard_users"),
    path("dashboard/audit-logs/", dashboard_audit_logs, name="dashboard_audit_logs"),
    path("dashboard/reports/", dashboard_reports, name="dashboard_reports"),
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
