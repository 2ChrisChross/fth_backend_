from django.apps import AppConfig


class SharedConfig(AppConfig):
    name = "shared"
    # Keep the historical migration and content-type identity stable.
    label = "api"
    verbose_name = "Shared"
