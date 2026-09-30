from django import forms
from django.contrib.auth.forms import AuthenticationForm


class DashboardAuthenticationForm(AuthenticationForm):
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.is_staff:
            raise forms.ValidationError(
                "This account does not have access to the admin dashboard.",
                code="staff_required",
            )