from django.apps import apps
from django.contrib import admin

from .models import User


class ApiUserAdmin(admin.ModelAdmin):
    exclude = ("password_hash", "verification_code")
    list_display = (
        "user_id",
        "username",
        "first_name",
        "last_name",
        "role",
        "is_verified",
    )
    search_fields = ("username", "first_name", "last_name")


for app_label in ("api", "farmers", "businesses", "logistics"):
    for model in apps.get_app_config(app_label).get_models():
        admin.site.register(model, ApiUserAdmin if model is User else admin.ModelAdmin)
