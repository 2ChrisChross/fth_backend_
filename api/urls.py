from django.urls import path

from .views import (
    dashboard_user_delete,
    dashboard_user_form,
    dashboard_users,
    register_user,
)

urlpatterns = [
    path("register/", register_user, name="register_user"),
    path("dashboard/", dashboard_users, name="dashboard_users"),
    path("dashboard/create/", dashboard_user_form, name="dashboard_user_create"),
    path("dashboard/edit/<int:user_id>/", dashboard_user_form, name="dashboard_user_edit"),
    path("dashboard/delete/<int:user_id>/", dashboard_user_delete, name="dashboard_user_delete"),
]
