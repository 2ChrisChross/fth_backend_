import re
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.staticfiles.storage import staticfiles_storage
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.template.loader import get_template
from django.test import Client, RequestFactory, SimpleTestCase, override_settings
from django.urls import Resolver404, resolve, reverse

from .farmer_views import (
    farmer_detail,
)
from .forms import DashboardAuthenticationForm
from .permissions import (
    dashboard_navigation,
    has_dashboard_permission,
    pending_code_request_farmer_count,
)
from .services import (
    _paginate_queryset,
    build_dashboard_rows,
    audit_log_reason,
    database_ready_for_dashboard,
    farmer_users,
)
from .views import dashboard_users, farmer_code_requests, farmer_delete
from .workflows import DashboardWorkflowValidationError, update_dashboard_status


class DashboardStaticFilesTests(SimpleTestCase):
    def test_collected_dashboard_scripts_are_served_with_debug_disabled(self):
        with TemporaryDirectory() as static_root, override_settings(
            STATIC_ROOT=static_root, DEBUG=False, ALLOWED_HOSTS=["testserver"]
        ):
            call_command("collectstatic", interactive=False, verbosity=0)
            client = Client()
            for name in ("columns.js", "filters.js"):
                url = staticfiles_storage.url(f"dashboard/{name}")
                response = client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertIn("javascript", response["Content-Type"])
                self.assertTrue(b"".join(response.streaming_content))
                self.assertIn("max-age=", response["Cache-Control"])


class FarmerUsersScopeTests(SimpleTestCase):
    @patch("dashboard.services.User.objects.filter")
    @patch("dashboard.services.resolve_enum_order_id", return_value=1)
    def test_farmer_users_filters_by_farmer_role(self, _resolve, mock_filter):
        farmer_users()
        mock_filter.assert_called_once_with(role=1)

    @patch("dashboard.services.resolve_enum_order_id", return_value=None)
    def test_farmer_users_is_empty_when_role_not_configured(self, _resolve):
        with patch("dashboard.services.User.objects.none") as mock_none:
            farmer_users()
        mock_none.assert_called_once_with()


class DashboardSidebarTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        badge = patch(
            "dashboard.permissions.pending_code_request_farmer_count", return_value=0
        )
        badge.start()
        self.addCleanup(badge.stop)
        badge = patch(
            "dashboard.permissions.pending_account_request_count", return_value=0
        )
        badge.start()
        self.addCleanup(badge.stop)

    def staff_request(self, path, data=None):
        request = self.factory.get(path, data)
        request.user = SimpleNamespace(
            is_authenticated=True,
            is_active=True,
            is_staff=True,
            is_superuser=False,
            groups=MagicMock(),
            has_perm=MagicMock(return_value=False),
        )
        request.user.groups.exists.return_value = False
        return request

    def test_database_uses_postgresql(self):
        self.assertEqual(
            settings.DATABASES["default"]["ENGINE"], "django.db.backends.postgresql"
        )

    @patch("dashboard.views.database_ready_for_dashboard", return_value=False)
    def test_dashboard_home_opens_reports_first_for_staff(self, mock_db):
        response = dashboard_users(self.staff_request("/dashboard/"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Reports")
        self.assertContains(response, "Farmers")

    @patch("dashboard.views.database_ready_for_dashboard", return_value=False)
    def test_farmers_tab_has_no_add_user_button(self, mock_db):
        response = dashboard_users(
            self.staff_request("/dashboard/"), section_override="farmers"
        )

        self.assertNotContains(response, "Add New")

    def test_farmer_optional_columns_are_hidden_by_default(self):
        rendered = get_template("dashboard/records.html").render(
            {
                "section": "farmers",
                "section_title": "Farmers",
                "sections": [],
                "rows": [
                    SimpleNamespace(
                        name="Juan Dela Cruz",
                        entity=SimpleNamespace(user_id=12),
                        created_at=None,
                        status_label="Pending",
                    )
                ],
                "query": "",
                "sort_field": "last_name",
                "sort_dir": "asc",
                "status_filter": "all",
                "dashboard_url": "/dashboard/farmers/",
            }
        )

        for key in ("name", "created", "account", "actions"):
            self.assertIn(f'<th data-column="{key}">', rendered)
        for key in ("phone", "farm_size", "location"):
            self.assertIn(f'<th data-column="{key}" hidden>', rendered)
            self.assertIn(f'<td data-column="{key}" hidden>', rendered)
        self.assertNotIn("Farm size</option>", rendered)

    def test_text_filter_forms_keep_a_search_button(self):
        records = get_template("dashboard/records.html").render(
            {
                "section": "farmers",
                "section_title": "Farmers",
                "sections": [],
                "status_filter": "all",
                "sort_field": "last_name",
                "sort_dir": "asc",
                "dashboard_url": "/dashboard/farmers/",
            }
        )
        farms = get_template("dashboard/farmer_detail.html").render(
            {
                "sections": [],
                "farmer": SimpleNamespace(username="farmer", user_id=1),
                "active_view": "farms",
            }
        )
        for html in (records, farms):
            self.assertIn('type="submit">Search</button>', html)
            self.assertNotIn('type="submit">Filter</button>', html)
            self.assertNotIn('type="submit">Apply Filters</button>', html)

    def test_column_customization_is_available_for_empty_record_lists(self):
        for section in ("farmers", "logistics", "businesses"):
            with self.subTest(section=section):
                rendered = get_template("dashboard/records.html").render(
                    {
                        "section": section,
                        "section_title": section.title(),
                        "sections": [],
                        "rows": [],
                        "status_filter": "all",
                        "sort_field": "last_name",
                        "sort_dir": "asc",
                    }
                )
                self.assertIn(f'data-column-table="{section}"', rendered)
                self.assertIn("data-column-menu-button", rendered)
                self.assertIn("No " + section + " match your search.", rendered)

    @patch("dashboard.services.connection.introspection.table_names")
    def test_dashboard_database_readiness_uses_current_model_table_names(
        self, table_names
    ):
        table_names.return_value = [
            "USERS",
            "PHONE_NUMBERS",
            "FARMS",
            "FARMER_CODE_REQUESTS",
            "ADDRESSES",
            "ELECTRONIC_DOCUMENTS",
            "VEHICLES",
            "BULK_BUYERS",
            "AUDIT_LOGS",
        ]

        self.assertTrue(database_ready_for_dashboard())

    @patch("dashboard.views.database_ready_for_dashboard", return_value=False)
    def test_dashboard_renders_sidebar_sections(self, mock_db):
        request = self.staff_request("/dashboard/", {"section": "logistics"})
        response = dashboard_users(request)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Farmers")
        self.assertContains(response, "Verification Requests")
        self.assertContains(response, "Logistics")
        self.assertContains(response, "Bulk Buyers")
        self.assertContains(response, "Audit Logs")

    @patch("dashboard.views.database_ready_for_dashboard", return_value=False)
    def test_bulk_buyers_tab_has_no_add_user_button(self, mock_db):
        request = self.staff_request("/dashboard/", {"section": "businesses"})
        response = dashboard_users(request)

        self.assertNotContains(response, "Add New")

    @patch("dashboard.views.database_ready_for_dashboard", return_value=False)
    def test_logistics_tab_has_no_add_button(self, mock_db):
        request = self.staff_request("/dashboard/", {"section": "logistics"})
        response = dashboard_users(request)

        self.assertNotContains(response, "Add New")

    @patch("dashboard.farmer_views.database_ready_for_dashboard", return_value=False)
    def test_farmer_detail_view_renders_database_unavailable_state(self, mock_db):
        response = farmer_detail(self.staff_request("/dashboard/farmers/12/"), 12)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Farmer Information")
        self.assertContains(response, "farmer and farm tables are not available yet")

    @patch("dashboard.views.database_ready_for_dashboard", return_value=False)
    def test_audit_logs_link_targets_audit_section_from_each_entity_tab(self, mock_db):
        for section in ("farmers", "logistics", "businesses"):
            with self.subTest(section=section):
                response = dashboard_users(
                    self.staff_request("/dashboard/"), section_override=section
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

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith("/dashboard/login/?next="))

    def test_anonymous_dashboard_access_redirects_to_dedicated_login(self):
        for path in (
            "/dashboard/",
            "/dashboard/reports/",
            "/dashboard/audit-logs/",
            "/dashboard/farmer-code-requests/",
            "/dashboard/farmer-code-requests/1/",
            "/dashboard/farmers/",
            "/dashboard/farmers/12/",
            "/dashboard/businesses/",
            "/dashboard/logistics/",
            "/dashboard/farmers/delete/1/",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertRedirects(
                    response,
                    f"/dashboard/login/?next={path}",
                    fetch_redirect_response=False,
                )

    def test_dashboard_login_page_uses_django_authentication_form(self):
        response = self.client.get("/dashboard/login/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="username"')
        self.assertContains(response, 'name="password"')

    def test_shared_dashboard_base_renders_role_navigation_and_logout(self):
        rendered = get_template("dashboard/base.html").render(
            {
                "sections": [
                    {"key": "reports", "label": "Reports"},
                    {"key": "code_requests", "label": "Farmer Code Requests"},
                ],
                "section": "code_requests",
            }
        )

        self.assertIn("Farmer Code Requests", rendered)
        self.assertIn('action="/dashboard/logout/"', rendered)

    def test_sidebar_separates_user_records_from_features(self):
        user = self.staff_request("/dashboard/").user
        rendered = get_template("dashboard/base.html").render(
            {"sections": dashboard_navigation(user), "section": "logistics"}
        )
        user_section, feature_section = rendered.split("Dashboard features", 1)
        self.assertIn("User records", user_section)
        for label in ("Farmers", "Logistics", "Bulk Buyers"):
            self.assertIn(f">{label}</a>", user_section)
        for label in ("Reports", "Verification Requests", "Audit Logs"):
            self.assertIn(label, feature_section)
            self.assertNotIn(f">{label}</a>", user_section)
        self.assertIn('class="nav-link active" href="/dashboard/logistics/"', user_section)

    def test_sidebar_hides_empty_groups_for_restricted_staff(self):
        user = self.staff_request("/dashboard/").user
        user.groups.exists.return_value = True
        user.has_perm.side_effect = lambda permission: permission == (
            "farmers.view_dashboard_reports"
        )
        rendered = get_template("dashboard/base.html").render(
            {"sections": dashboard_navigation(user)}
        )
        self.assertIn("Dashboard features", rendered)
        self.assertNotIn("User records", rendered)
        self.assertNotIn("Bulk Buyers", rendered)

    def test_dashboard_templates_compile(self):
        for template_name in (
            "dashboard/login.html",
            "dashboard/records.html",
            "dashboard/reports.html",
            "dashboard/farmer_code_requests.html",
            "dashboard/farmer_code_request_detail.html",
            "dashboard/farmer_detail.html",
            "dashboard/_delete_dialog.html",
        ):
            with self.subTest(template=template_name):
                get_template(template_name)

    @patch("dashboard.views.database_ready_for_dashboard", return_value=False)
    def test_code_request_queue_renders_for_staff(self, mock_db):
        response = farmer_code_requests(
            self.staff_request("/dashboard/farmer-code-requests/")
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Farmer Code Requests")
        self.assertContains(
            response, "The farmer code-request table is not available yet."
        )

    def test_dashboard_login_rejects_non_staff_accounts(self):
        form = DashboardAuthenticationForm()
        non_staff_user = SimpleNamespace(is_active=True, is_staff=False)

        with self.assertRaises(ValidationError):
            form.confirm_login_allowed(non_staff_user)

    def test_dashboard_pages_include_post_logout_form(self):
        for path, view in (
            ("/dashboard/", dashboard_users),
        ):
            with self.subTest(path=path), patch(
                "dashboard.views.database_ready_for_dashboard", return_value=False
            ):
                response = view(self.staff_request(path))
                self.assertContains(response, 'method="post"')
                self.assertContains(response, 'action="/dashboard/logout/"')

    @patch("dashboard.views.farmer_users")
    def test_farmer_status_cannot_be_changed_through_generic_records_post(
        self, filter_users
    ):
        request = self.factory.post(
            "/dashboard/farmers/",
            {"section": "farmers", "target_id": "12", "stage": "1"},
        )
        request.user = self.staff_request("/dashboard/").user

        with self.assertRaises(PermissionDenied):
            dashboard_users(request, section_override="farmers")
        filter_users.assert_not_called()

    def test_dashboard_has_no_create_or_edit_routes(self):
        for path in (
            "/dashboard/create/",
            "/dashboard/create/businesses/",
            "/dashboard/edit/1/",
            "/dashboard/farmers/create/",
            "/dashboard/farmers/edit/1/",
            "/dashboard/businesses/create/",
            "/dashboard/logistics/create/",
        ):
            with self.subTest(path=path), self.assertRaises(Resolver404):
                resolve(path)

    def test_farmer_delete_route_only_accepts_post(self):
        request = self.staff_request("/dashboard/farmers/delete/12/")

        response = farmer_delete(request, 12)

        self.assertEqual(response.status_code, 405)

    @patch("dashboard.farmer_views.database_ready_for_dashboard", return_value=True)
    @patch("dashboard.farmer_views.log_staff_audit_change")
    @patch("dashboard.farmer_views.transaction.atomic")
    @patch("dashboard.farmer_views.get_object_or_404")
    @patch("dashboard.farmer_views.farmer_users")
    def test_farmer_delete_post_removes_only_farmer_scoped_user(
        self, scoped_users, get_404, atomic, audit, mock_db
    ):
        user = MagicMock()
        user.phone_numbers.order_by.return_value.first.return_value = None
        user.farms.select_related.return_value.order_by.return_value.first.return_value = None
        scoped_users.return_value.select_for_update.return_value.get.return_value = user
        request = self.factory.post("/dashboard/farmers/delete/12/")
        request.user = self.staff_request("/dashboard/").user

        response = farmer_delete(request, 12)

        self.assertEqual(response.status_code, 302)
        user.delete.assert_called_once_with()

    def test_delete_confirmation_is_a_popup_dialog(self):
        rendered = get_template("dashboard/_delete_dialog.html").render({})

        self.assertIn("<dialog", rendered)
        self.assertIn("showModal", rendered)

class AuditLogReasonTests(SimpleTestCase):
    def setUp(self):
        badge = patch(
            "dashboard.permissions.pending_code_request_farmer_count", return_value=0
        )
        badge.start()
        self.addCleanup(badge.stop)
        badge = patch(
            "dashboard.permissions.pending_account_request_count", return_value=0
        )
        badge.start()
        self.addCleanup(badge.stop)

    def test_reason_is_read_from_logged_values(self):
        log = SimpleNamespace(new_values='{"status": 2, "reason": "Documents unclear"}')

        self.assertEqual(audit_log_reason(log), "Documents unclear")

    def test_reason_is_blank_when_missing_or_unreadable(self):
        for value in (None, "", "{}", "not json", "[1, 2]"):
            with self.subTest(value=value):
                self.assertEqual(
                    audit_log_reason(SimpleNamespace(new_values=value)), ""
                )

    def test_audit_table_has_a_reason_column(self):
        rendered = get_template("dashboard/records.html").render(
            {
                "section": "audit_logs",
                "section_title": "Audit Logs",
                "sections": [],
                "rows": [
                    {
                        "name": "staff1",
                        "action": "CODE_REQUEST_REJECTED",
                        "target": "FARMER_CODE_REQUESTS",
                        "reason": "Documents unclear",
                        "created_at": None,
                    }
                ],
                "sort_dir": "desc",
                "status_filter": "all",
            }
        )

        self.assertIn("<th>Reason</th>", rendered)
        self.assertIn("Documents unclear", rendered)

    @patch("dashboard.views.build_dashboard_rows", return_value=([], None))
    @patch("dashboard.views.database_ready_for_dashboard", return_value=True)
    def test_audit_logs_default_to_newest_first(self, _ready, build_rows):
        request = RequestFactory().get("/dashboard/audit-logs/")
        request.user = SimpleNamespace(
            is_active=True,
            is_staff=True,
            is_superuser=True,
            is_authenticated=True,
            has_perm=lambda perm: True,
        )

        dashboard_users(request, section_override="audit_logs")

        self.assertEqual(build_rows.call_args.args[3], "desc")


class DashboardAppRouteTests(SimpleTestCase):
    def test_dashboard_and_admin_routes_stay_outside_api_prefix(self):
        self.assertEqual(reverse("dashboard_users"), "/dashboard/")
        self.assertEqual(reverse("farmers:detail", args=[12]), "/dashboard/farmers/12/")
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
    def test_dashboard_pagination_limits_rows_and_tracks_page_count(self):
        rows, page_obj = _paginate_queryset(list(range(7)), "2", 3)

        self.assertEqual(list(rows), [3, 4, 5])
        self.assertEqual(page_obj.number, 2)
        self.assertEqual(page_obj.paginator.num_pages, 3)

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
        queryset.annotate.return_value = queryset
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
            dashboard_created_at=None,
        )
        queryset = MagicMock()
        queryset.annotate.return_value = queryset
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


class DashboardPermissionTests(SimpleTestCase):
    def test_superuser_has_all_dashboard_permissions(self):
        user = SimpleNamespace(
            is_authenticated=True,
            is_active=True,
            is_staff=True,
            is_superuser=True,
            groups=MagicMock(),
        )

        self.assertTrue(has_dashboard_permission(user, "farmers.issue_farmer_codes"))

    def test_ungrouped_staff_keeps_full_access(self):
        groups = MagicMock()
        groups.exists.return_value = False
        user = SimpleNamespace(
            is_authenticated=True,
            is_active=True,
            is_staff=True,
            is_superuser=False,
            groups=groups,
            has_perm=MagicMock(return_value=False),
        )

        self.assertTrue(has_dashboard_permission(user, "farmers.issue_farmer_codes"))
        user.has_perm.assert_not_called()

    def test_grouped_staff_must_have_the_required_permission(self):
        groups = MagicMock()
        groups.exists.return_value = True
        user = SimpleNamespace(
            is_authenticated=True,
            is_active=True,
            is_staff=True,
            is_superuser=False,
            groups=groups,
            has_perm=MagicMock(return_value=False),
        )

        self.assertFalse(has_dashboard_permission(user, "farmers.issue_farmer_codes"))
        user.has_perm.assert_called_once_with("farmers.issue_farmer_codes")

    def test_auditor_navigation_contains_only_reports_and_audit_logs(self):
        groups = MagicMock()
        groups.exists.return_value = True
        permissions = {
            "farmers.view_dashboard_reports",
            "farmers.view_dashboard_audit_logs",
        }
        user = SimpleNamespace(
            is_authenticated=True,
            is_active=True,
            is_staff=True,
            is_superuser=False,
            groups=groups,
            has_perm=lambda permission: permission in permissions,
        )

        self.assertEqual(
            [item["key"] for item in dashboard_navigation(user)],
            ["reports", "audit_logs"],
        )

    @patch("dashboard.permissions.pending_account_request_count", return_value=2)
    @patch("dashboard.permissions.pending_code_request_farmer_count", return_value=3)
    def test_code_requests_navigation_carries_combined_pending_badge(
        self, count, accounts
    ):
        user = SimpleNamespace(
            is_authenticated=True,
            is_active=True,
            is_staff=True,
            is_superuser=True,
        )

        items = {item["key"]: item for item in dashboard_navigation(user)}

        self.assertEqual(items["code_requests"]["badge"], 5)
        self.assertNotIn("badge", items["reports"])
        count.assert_called_once_with()
        accounts.assert_called_once_with()

    @patch("dashboard.permissions.pending_code_request_farmer_count")
    def test_badge_is_not_queried_without_code_request_access(self, count):
        groups = MagicMock()
        groups.exists.return_value = True
        user = SimpleNamespace(
            is_authenticated=True,
            is_active=True,
            is_staff=True,
            is_superuser=False,
            groups=groups,
            has_perm=lambda permission: permission == "farmers.view_dashboard_reports",
        )

        dashboard_navigation(user)

        count.assert_not_called()

    @patch("farmers.models.FarmerCodeRequest.objects")
    def test_pending_count_is_distinct_farmers_in_review(self, manager):
        chain = manager.filter.return_value.values.return_value.distinct.return_value
        chain.count.return_value = 2

        self.assertEqual(pending_code_request_farmer_count(), 2)
        manager.filter.assert_called_once_with(status="pending_review")
        manager.filter.return_value.values.assert_called_once_with("user_id")


class DashboardWorkflowTests(SimpleTestCase):
    @patch("dashboard.workflows.BulkBuyer.objects.select_for_update")
    def test_invalid_status_is_rejected_before_database_write(self, select_for_update):
        with self.assertRaises(DashboardWorkflowValidationError):
            update_dashboard_status("businesses", 7, "9", None, None)

        select_for_update.assert_not_called()


class DocumentRequestRouteTests(SimpleTestCase):
    def test_farmer_document_request_routes_resolve(self):
        from django.urls import resolve

        self.assertEqual(
            resolve("/api/farmers/document-requests/").url_name,
            "document_requests",
        )
        self.assertEqual(
            resolve("/api/farmers/document-requests/5/submit/").url_name,
            "submit_document_request",
        )
