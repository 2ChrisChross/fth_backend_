from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import RequestFactory, SimpleTestCase
from django.urls import Resolver404, resolve, reverse

from .services import build_dashboard_rows, database_ready_for_dashboard
from .views import dashboard_users


class DashboardSidebarTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_database_uses_postgresql(self):
        self.assertEqual(
            settings.DATABASES["default"]["ENGINE"], "django.db.backends.postgresql"
        )

    @patch("dashboard.views.database_ready_for_dashboard", return_value=False)
    def test_dashboard_home_opens_reports_first(self, mock_db):
        response = self.client.get("/dashboard/")

        self.assertTemplateUsed(response, "dashboard/reports.html")
        self.assertContains(response, "Reports")
        self.assertContains(response, "Farmers")

    @patch("dashboard.views.database_ready_for_dashboard", return_value=False)
    def test_farmers_tab_uses_farmer_create_label(self, mock_db):
        response = dashboard_users(
            self.factory.get("/dashboard/"), section_override="farmers"
        )

        self.assertContains(response, "Add New Farmer")
        self.assertNotContains(response, "Add New User")

    @patch("dashboard.services.connection.introspection.table_names")
    def test_dashboard_database_readiness_uses_current_model_table_names(
        self, table_names
    ):
        table_names.return_value = [
            "USERS",
            "PHONE_NUMBERS",
            "FARMS",
            "ADDRESSES",
            "ELECTRONIC_DOCUMENTS",
            "VEHICLES",
            "BULK_BUYERS",
            "AUDIT_LOGS",
        ]

        self.assertTrue(database_ready_for_dashboard())

    @patch("dashboard.views.database_ready_for_dashboard", return_value=False)
    def test_dashboard_renders_sidebar_sections(self, mock_db):
        request = self.factory.get("/dashboard/", {"section": "logistics"})
        response = dashboard_users(request)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Farmers")
        self.assertContains(response, "Logistics")
        self.assertContains(response, "Bulk Buyers")
        self.assertContains(response, "Audit Logs")

    @patch("dashboard.views.database_ready_for_dashboard", return_value=False)
    def test_dashboard_create_actions_stay_with_their_entity(self, mock_db):
        request = self.factory.get("/dashboard/", {"section": "businesses"})
        response = dashboard_users(request)

        self.assertContains(response, "Add New Bulk Buyer")
        self.assertNotContains(response, "Add New Vehicle")

    @patch("dashboard.views.database_ready_for_dashboard", return_value=False)
    def test_audit_logs_link_targets_audit_section_from_each_entity_tab(self, mock_db):
        for section in ("farmers", "logistics", "businesses"):
            with self.subTest(section=section):
                response = dashboard_users(
                    self.factory.get("/dashboard/"), section_override=section
                )
                self.assertContains(
                    response, 'href="/dashboard/audit-logs/">Audit Logs</a>'
                )

    @patch("dashboard.views.database_ready_for_dashboard", return_value=False)
    def test_audit_logs_has_its_own_route_and_legacy_url_redirects(self, mock_db):
        self.assertEqual(reverse("dashboard_audit_logs"), "/dashboard/audit-logs/")
        self.assertEqual(
            resolve(reverse("dashboard_audit_logs")).func.__name__,
            "dashboard_audit_logs",
        )

        response = self.client.get("/dashboard/?section=audit_logs")

        self.assertRedirects(
            response, "/dashboard/audit-logs/", fetch_redirect_response=False
        )


class DashboardAppRouteTests(SimpleTestCase):
    def test_dashboard_and_admin_routes_stay_outside_api_prefix(self):
        self.assertEqual(reverse("dashboard_users"), "/dashboard/")
        self.assertEqual(resolve("/admin/").url_name, "index")

        for path in ("/api/dashboard/", "/register/"):
            with self.subTest(path=path), self.assertRaises(Resolver404):
                resolve(path)

    def test_dashboard_routes_belong_to_their_apps(self):
        expected_views = {
            "farmers:dashboard": "dashboard.views",
            "businesses:dashboard": "dashboard.views",
            "logistics:dashboard": "dashboard.views",
        }

        for route_name, module_name in expected_views.items():
            with self.subTest(route_name=route_name):
                self.assertEqual(
                    resolve(reverse(route_name)).func.__module__, module_name
                )


class DashboardRowBuilderTests(SimpleTestCase):
    def test_bulk_buyer_section_builds_bulk_buyer_rows(self):
        bulk_buyer = SimpleNamespace(
            business_id=7,
            business_name="Market",
            user=None,
            date_time_created=True,
            registration_number="REG-7",
            is_verified=1,
        )
        queryset = MagicMock()
        queryset.order_by.return_value = queryset
        queryset.__iter__.return_value = iter([bulk_buyer])

        with patch(
            "dashboard.services.BulkBuyer.objects.select_related",
            return_value=queryset,
        ):
            rows = build_dashboard_rows("businesses", "")

        self.assertEqual(rows[0]["entity"], bulk_buyer)
        self.assertEqual(rows[0]["name"], "Market")
        self.assertEqual(rows[0]["registration_number"], "REG-7")

    def test_logistics_section_builds_vehicle_rows(self):
        vehicle = SimpleNamespace(
            vehicle_id=3,
            user=None,
            plate_number="ABC123",
            truck_model="Truck",
            current_health_status=2,
        )
        queryset = MagicMock()
        queryset.order_by.return_value = queryset
        queryset.__iter__.return_value = iter([vehicle])
        audit_lookup = MagicMock()
        audit_values = audit_lookup.order_by.return_value.values_list.return_value
        audit_values.first.return_value = None

        with (
            patch(
                "dashboard.services.Vehicle.objects.select_related",
                return_value=queryset,
            ),
            patch(
                "dashboard.services.AuditLog.objects.filter", return_value=audit_lookup
            ),
        ):
            rows = build_dashboard_rows("logistics", "")

        self.assertEqual(rows[0]["entity"], vehicle)
        self.assertEqual(rows[0]["plate_number"], "ABC123")
        self.assertEqual(rows[0]["status_label"], "Maintenance")
