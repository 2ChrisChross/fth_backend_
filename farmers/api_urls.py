from django.urls import path

from .views import (
    FarmerTokenRefreshView,
    admin_code_request_detail,
    admin_code_requests,
    admin_issue_code,
    admin_manually_verify_farmer,
    admin_mark_code_mailed,
    admin_review_code_request,
    farmer_profile,
    login_user,
    logout_user,
    recover_farmer_account,
    register_user,
    request_farmer_code,
    verify_user_code,
)

app_name = "farmers_api"

urlpatterns = [
    path("register/", register_user, name="register"),
    path("verify-code/", verify_user_code, name="verify_code"),
    path("login/", login_user, name="login"),
    path("token/refresh/", FarmerTokenRefreshView.as_view(), name="token_refresh"),
    path("logout/", logout_user, name="logout"),
    path("me/", farmer_profile, name="me"),
    path("code-requests/", request_farmer_code, name="code_request"),
    path("recover/", recover_farmer_account, name="recover"),
    path("admin/code-requests/", admin_code_requests, name="admin_code_requests"),
    path(
        "admin/code-requests/<int:request_id>/",
        admin_code_request_detail,
        name="admin_code_request_detail",
    ),
    path(
        "admin/code-requests/<int:request_id>/review/",
        admin_review_code_request,
        name="admin_review_code_request",
    ),
    path(
        "admin/code-requests/<int:request_id>/issue-code/",
        admin_issue_code,
        name="admin_issue_code",
    ),
    path(
        "admin/code-requests/<int:request_id>/mark-mailed/",
        admin_mark_code_mailed,
        name="admin_mark_code_mailed",
    ),
    path(
        "admin/farmers/<int:user_id>/verify/",
        admin_manually_verify_farmer,
        name="admin_manually_verify_farmer",
    ),
]
