from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.settings import api_settings

from shared.models import User
from shared.registration import resolve_enum_order_id


def get_active_farmer(user_id):
    user = User.objects.filter(
        user_id=user_id,
        is_verified=1,
        deleted_at__isnull=True,
    ).first()
    farmer_role_id = resolve_enum_order_id("role", "Farmer")
    if user is None or farmer_role_id is None or user.role != farmer_role_id:
        return None
    return user


class FarmerJWTAuthentication(JWTAuthentication):
    def get_user(self, validated_token):
        try:
            user_id = validated_token[api_settings.USER_ID_CLAIM]
        except KeyError as exc:
            raise AuthenticationFailed("Token has no farmer identifier.") from exc

        user = get_active_farmer(user_id)
        if user is None:
            raise AuthenticationFailed(
                "This token is not for an active farmer account."
            )
        return user