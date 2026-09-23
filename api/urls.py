from django.urls import path

from .views import (
    dashboard_entity_form,
    dashboard_reports,
    dashboard_user_delete,
    dashboard_user_form,
    dashboard_users,
    register_user,
    verify_user_code,
)

urlpatterns = [
    path("register/", register_user, name="register_user"),
    path("verify-code/", verify_user_code, name="verify_user_code"),
    path("dashboard/", dashboard_users, name="dashboard_users"),
    path("dashboard/reports/", dashboard_reports, name="dashboard_reports"),
    path("dashboard/create/", dashboard_user_form, name="dashboard_user_create"),
    path("dashboard/create/<str:section>/", dashboard_entity_form, name="dashboard_entity_create"),
    path("dashboard/edit/<int:user_id>/", dashboard_user_form, name="dashboard_user_edit"),
    path("dashboard/delete/<int:user_id>/", dashboard_user_delete, name="dashboard_user_delete"),
]
