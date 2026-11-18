from django.urls import path

from shared.account_api import (
    CodeRequestView,
    LoginView,
    LogisticsAuthentication,
    LogoutView,
    ProfileView,
    RefreshView,
)
from shared.farmer_messages import SendFarmerMessageView

from .operations import (
    DeliveriesView,
    TripDetailView,
    TripsView,
    VehicleDetailView,
    VehiclesView,
)
from .views import register, verify_code

app_name = "logistics_api"

urlpatterns = [
    path("register/", register, name="register"),
    path("verify-code/", verify_code, name="verify_code"),
    path(
        "code-requests/", CodeRequestView.as_view(kind="logistics"), name="code_request"
    ),
    path("login/", LoginView.as_view(role="Logistics_Manager"), name="login"),
    path(
        "token/refresh/",
        RefreshView.as_view(role="Logistics_Manager"),
        name="token_refresh",
    ),
    path(
        "logout/",
        LogoutView.as_view(authentication_classes=[LogisticsAuthentication]),
        name="logout",
    ),
    path(
        "me/",
        ProfileView.as_view(
            authentication_classes=[LogisticsAuthentication], role="Logistics_Manager"
        ),
        name="me",
    ),
    path("vehicles/", VehiclesView.as_view(), name="vehicles"),
    path(
        "vehicles/<int:vehicle_id>/", VehicleDetailView.as_view(), name="vehicle_detail"
    ),
    path("deliveries/", DeliveriesView.as_view(), name="deliveries"),
    path(
        "farmer-messages/",
        SendFarmerMessageView.as_view(
            authentication_classes=[LogisticsAuthentication], sender_kind="logistics"
        ),
        name="farmer_messages",
    ),
    path("trips/", TripsView.as_view(), name="trips"),
    path("trips/<int:trip_id>/", TripDetailView.as_view(), name="trip_detail"),
]
