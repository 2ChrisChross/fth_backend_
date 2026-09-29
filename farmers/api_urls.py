from django.urls import path

from .views import register_user, verify_user_code


app_name = "farmers_api"

urlpatterns = [
    path("register/", register_user, name="register"),
    path("verify-code/", verify_user_code, name="verify_code"),
]