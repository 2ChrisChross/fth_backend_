from django.urls import path

from .views import register, verify_code


app_name = "logistics_api"

urlpatterns = [
    path("register/", register, name="register"),
    path("verify-code/", verify_code, name="verify_code"),
]