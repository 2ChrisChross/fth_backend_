from rest_framework.permissions import BasePermission

from dashboard.permissions import has_dashboard_permission


class FarmerStaffPermission(BasePermission):
    permission = None

    def has_permission(self, request, view):
        return has_dashboard_permission(request.user, self.permission)


class CanViewFarmerApplications(FarmerStaffPermission):
    permission = "farmers.view_farmer_applications"


class CanViewFarmerCodeRequests(FarmerStaffPermission):
    permission = "farmers.view_farmer_code_requests"


class CanReviewFarmerCodeRequests(FarmerStaffPermission):
    permission = "farmers.review_farmer_code_requests"


class CanIssueFarmerCodes(FarmerStaffPermission):
    permission = "farmers.issue_farmer_codes"


class CanManuallyVerifyFarmer(FarmerStaffPermission):
    permission = "farmers.manually_verify_farmer"