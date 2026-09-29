from django.urls import path

from . import views


app_name = "farmers"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("create/", views.create, name="create"),
    path("edit/<int:user_id>/", views.edit, name="edit"),
    path("delete/<int:user_id>/", views.delete, name="delete"),
]