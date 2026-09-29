from django.urls import path

from . import views


app_name = "businesses"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("create/", views.create, name="create"),
]