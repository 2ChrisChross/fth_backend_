from django.urls import path

from farmers.views import register_user, verify_user_code

urlpatterns = [
    path("register/", register_user, name="register_user"),
    path("verify-code/", verify_user_code, name="verify_user_code"),
]
