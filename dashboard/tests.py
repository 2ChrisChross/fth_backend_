import re
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.template.loader import get_template
from django.test import RequestFactory, SimpleTestCase
from django.urls import Resolver404, resolve, reverse

from .farmer_views import (
    _create_farmer_from_dashboard,
    dashboard_user_form,
    farmer_detail,
)
from .forms import DashboardAuthenticationForm
from .permissions import dashboard_navigation, has_dashboard_permission
from .services import (
    _paginate_queryset,
    build_dashboard_rows,
    database_ready_for_dashboard,
)
from .views import dashboard_users, farmer_code_requests
from .workflows import DashboardWorkflowValidationError, update_dashboard_status


class DashboardSidebarTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

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
    def test_farmers_tab_uses_farmer_create_label(self, mock_db):
        response = dashboard_users(
            self.staff_request("/dashboard/"), section_override="farmers"
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
        self.assertContains(response, "Farmer Code Requests")
        self.assertContains(response, "Logistics")
        self.assertContains(response, "Bulk Buyers")
        self.assertContains(response, "Audit Logs")

    @patch("dashboard.views.database_ready_for_dashboard", return_value=False)
    def test_dashboard_create_actions_stay_with_their_entity(self, mock_db):
        request = self.staff_request("/dashboard/", {"section": "businesses"})
        response = dashboard_users(request)

        self.assertContains(response, "Add New Bulk Buyer")
        self.assertNotContains(response, "Add New Vehicle")

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
            "/dashboard/create/",
            "/dashboard/create/businesses/",
            "/dashboard/farmers/create/",
            "/dashboard/farmers/edit/1/",
            "/dashboard/farmers/delete/1/",
            "/dashboard/businesses/create/",
            "/dashboard/logistics/create/",
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

    def test_dashboard_templates_compile(self):
        for template_name in (
            "dashboard/login.html",
            "dashboard/records.html",
            "dashboard/reports.html",
            "dashboard/farmer_code_requests.html",
            "dashboard/farmer_code_request_detail.html",
            "dashboard/farmer_detail.html",
            "dashboard/farmer_form.html",
            "dashboard/farmer_delete_confirm.html",
            "dashboard/bulk_buyer_vehicle_form.html",
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

    @patch("dashboard.views.User.objects.filter")
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

    @patch("dashboard.farmer_views.database_ready_for_dashboard", return_value=True)
    def test_add_farmer_form_uses_registration_contract(self, mock_database_ready):
        response = dashboard_user_form(self.staff_request("/dashboard/farmers/create/"))

        self.assertContains(response, 'name="phonenumber"')
        self.assertContains(response, 'name="username"')
        self.assertContains(response, 'name="password"')
        self.assertContains(response, 'name="firstname"')
        self.assertContains(response, 'name="farm_region"')
        self.assertContains(response, 'name="document_1"')
        self.assertContains(response, 'name="document_4"')
        self.assertContains(response, 'name="document_type_1"')

    @patch("dashboard.farmer_views.EnumeratedValue.objects.filter", return_value=[])
    @patch("dashboard.farmer_views.get_object_or_404")
    @patch("dashboard.farmer_views.database_ready_for_dashboard", return_value=True)
    def test_edit_farmer_form_uses_prefilled_registration_layout(
        self, mock_database_ready, get_user, document_types
    ):
        personal_address = SimpleNamespace(
            street_address="10 Main Road",
            barangay="Barangay 1",
            municipality_city="Laoag City",
            province="Ilocos Norte",
            postal_code="2900",
            country="Philippines",
            gps_coordinates="Region I",
        )
        farm_address = SimpleNamespace(
            street_address="12 Farm Road",
            barangay="Barangay 2",
            municipality_city="Laoag City",
            province="Ilocos Norte",
            postal_code="2901",
            country="Philippines",
            gps_coordinates="Region I",
        )
        phone = SimpleNamespace(mobile_number="09123456789")
        farm = SimpleNamespace(farm_size_hectares="2.50", address=farm_address)
        documents = [
            SimpleNamespace(
                file_url=f"https://files.example/{index}.jpg", doc_type=index
            )
            for index in range(1, 5)
        ]
        user = SimpleNamespace(
            user_id=12,
            username="farmer-one",
            first_name="Juan",
            middle_name="",
            last_name="Dela Cruz",
            personal_address=personal_address,
            preferred_language=1,
            preferred_payment_method=2,
            phone_numbers=SimpleNamespace(first=lambda: phone),
            farms=SimpleNamespace(first=lambda: farm),
            electronic_documents=SimpleNamespace(order_by=lambda field: documents),
        )
        get_user.return_value = user

        response = dashboard_user_form(
            self.staff_request("/dashboard/farmers/edit/12/"), 12
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="phonenumber"')
        self.assertContains(response, 'name="farm_region"')
        self.assertContains(response, 'name="document_4"')
        self.assertContains(response, 'name="farm_size" type="number"')
        self.assertContains(response, 'value="farmer-one"')
        self.assertContains(response, 'value="https://files.example/1.jpg"')
        password_input = re.search(
            r'<input[^>]*name="password"[^>]*>', response.content.decode()
        )
        self.assertIsNotNone(password_input)
        self.assertNotIn("required", password_input.group())

    @patch("dashboard.farmer_views._save_farmer_dashboard_form")
    @patch("dashboard.farmer_views.get_object_or_404")
    @patch("dashboard.farmer_views.database_ready_for_dashboard", return_value=True)
    def test_edit_farmer_rejects_invalid_phone_and_missing_required_fields(
        self, mock_database_ready, get_user, save_farmer
    ):
        user = SimpleNamespace(
            user_id=12,
            phone_numbers=SimpleNamespace(first=lambda: None),
            farms=SimpleNamespace(first=lambda: None),
        )
        get_user.return_value = user
        request = self.factory.post(
            "/dashboard/farmers/edit/12/", {"phonenumber": "not a phone"}
        )
        request.user = self.staff_request("/dashboard/").user

        response = dashboard_user_form(request, 12)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "phonenumber")
        self.assertContains(response, "region")
        save_farmer.assert_not_called()

    @patch("dashboard.farmer_views.create_farmer_registration")
    @patch("dashboard.farmer_views.FarmerDashboardRegistrationSerializer")
    def test_add_farmer_maps_four_documents_into_registration_payload(
        self, registration_serializer, create_registration
    ):
        serializer = registration_serializer.return_value
        serializer.is_valid.return_value = True
        serializer.validated_data = {"username": "staff-created"}
        request = self.factory.post(
            "/dashboard/farmers/create/",
            {
                "phonenumber": "+639123456789",
                "username": "staff-created",
                "password": "InitialPass!123",
                "document_1": "https://files.example/one.jpg",
                "document_2": "https://files.example/two.jpg",
                "document_3": "https://files.example/three.jpg",
                "document_4": "https://files.example/four.jpg",
                "document_type_1": "Utility Bills",
                "document_type_2": "Valid_ID",
                "document_type_3": "Owner_Address",
                "document_type_4": "Farm_Ownership",
            },
        )
        request.user = self.staff_request("/dashboard/").user

        response = _create_farmer_from_dashboard(request)

        registration_serializer.assert_called_once()
        payload = registration_serializer.call_args.kwargs["data"]
        self.assertEqual(
            payload["documents"],
            [
                "https://files.example/one.jpg",
                "https://files.example/two.jpg",
                "https://files.example/three.jpg",
                "https://files.example/four.jpg",
            ],
        )
        self.assertEqual(
            payload["document_types"],
            ["Utility Bills", "Valid_ID", "Owner_Address", "Farm_Ownership"],
        )
        create_registration.assert_called_once_with(
            serializer.validated_data,
            request,
            staff_user=request.user,
        )
        self.assertEqual(response.status_code, 302)


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


class DashboardWorkflowTests(SimpleTestCase):
    @patch("dashboard.workflows.BulkBuyer.objects.select_for_update")
    def test_invalid_status_is_rejected_before_database_write(self, select_for_update):
        with self.assertRaises(DashboardWorkflowValidationError):
            update_dashboard_status("businesses", 7, "9", None, None)

        select_for_update.assert_not_called()
