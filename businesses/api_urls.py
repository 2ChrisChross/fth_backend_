from django.urls import path

from shared.account_api import (
    BuyerAuthentication,
    CodeRequestView,
    LoginView,
    LogoutView,
    ProfileView,
    RefreshView,
)
from shared.farmer_messages import SendFarmerMessageView

from .commerce import DeliveryCompaniesView, ListingsView, OrderCancelView, OrdersView
from .views import register, verify_code

app_name = "businesses_api"

urlpatterns = [
    path("register/", register, name="register"),
    path("verify-code/", verify_code, name="verify_code"),
    path(
        "code-requests/",
        CodeRequestView.as_view(kind="businesses"),
        name="code_request",
    ),
    path("login/", LoginView.as_view(role="Bulk_Buyer"), name="login"),
    path(
        "token/refresh/", RefreshView.as_view(role="Bulk_Buyer"), name="token_refresh"
    ),
    path(
        "logout/",
        LogoutView.as_view(authentication_classes=[BuyerAuthentication]),
        name="logout",
    ),
    path(
        "me/",
        ProfileView.as_view(
            authentication_classes=[BuyerAuthentication], role="Bulk_Buyer"
        ),
        name="me",
    ),
    path("listings/", ListingsView.as_view(), name="listings"),
    path(
        "delivery-companies/",
        DeliveryCompaniesView.as_view(),
        name="delivery_companies",
    ),
    path("orders/", OrdersView.as_view(), name="orders"),
    path(
        "farmer-messages/",
        SendFarmerMessageView.as_view(
            authentication_classes=[BuyerAuthentication], sender_kind="businesses"
        ),
        name="farmer_messages",
    ),
    path(
        "orders/<int:order_id>/cancel/", OrderCancelView.as_view(), name="cancel_order"
    ),
]
