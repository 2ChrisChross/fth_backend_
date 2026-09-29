from django.urls import path

from . import views


app_name = "logistics"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("create/", views.create, name="create"),
]