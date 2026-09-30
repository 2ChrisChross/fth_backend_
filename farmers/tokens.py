from django.utils import timezone
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken, Token
from rest_framework_simplejwt.utils import datetime_from_epoch

from .models import FarmerRevokedRefreshToken


class FarmerRefreshToken(RefreshToken):
    @classmethod
    def for_user(cls, user):
        return Token.for_user.__func__(cls, user)

    def check_blacklist(self):
        jti = self.payload["jti"]
        if FarmerRevokedRefreshToken.objects.filter(jti=jti).exists():
            raise TokenError("Token is blacklisted")

    def verify(self):
        self.check_blacklist()
        super().verify()

    def blacklist(self):
        jti = self.payload["jti"]
        user_id = self.payload.get("user_id")
        FarmerRevokedRefreshToken.objects.filter(
            expires_at__lte=timezone.now()
        ).delete()
        user = None
        if user_id is not None:
            from shared.models import User

            user = User.objects.filter(user_id=user_id).first()
        record, _ = FarmerRevokedRefreshToken.objects.get_or_create(
            jti=jti,
            defaults={
                "user": user,
                "expires_at": datetime_from_epoch(self.payload["exp"]),
            },
        )
        return record

    def outstand(self):
        return None