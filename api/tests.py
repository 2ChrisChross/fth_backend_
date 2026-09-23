from unittest.mock import patch

from django.conf import settings
from django.core.exceptions import FieldDoesNotExist
from django.test import RequestFactory, SimpleTestCase

from .models import Farm, User
from .views import dashboard_users


class SchemaRegressionTests(SimpleTestCase):
    def test_user_model_does_not_define_address_relation(self):
        with self.assertRaises(FieldDoesNotExist):
            User._meta.get_field("address")

        self.assertIsNotNone(Farm._meta.get_field("address"))


class DashboardSidebarTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_default_database_url_is_configured(self):
        self.assertIn("farmtohome_db", settings.DATABASE_URL)
        self.assertIn("dpg-dah5ghh42hec73esq7eg-a", settings.DATABASE_URL)

    @patch("api.views.database_ready_for_dashboard", return_value=False)
    def test_dashboard_renders_sidebar_sections(self, mock_db):
        request = self.factory.get("/dashboard/", {"section": "logistics"})

        response = dashboard_users(request)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Farmers")
        self.assertContains(response, "Logistics")
        self.assertContains(response, "Businesses")
        self.assertContains(response, "Audit Logs")
