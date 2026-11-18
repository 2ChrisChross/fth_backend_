import gzip
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.http import Http404, HttpResponse
from django.test import (
    Client,
    RequestFactory,
    SimpleTestCase,
    TestCase,
    override_settings,
)

from farmers.models import Farm
from shared.models import User

from .region3 import geometry_contains, locate_point, validate_address
from .simulator import (
    simulator_farmer_api,
    simulator_map_asset,
    simulator_map_glyph,
    simulator_map_lookup,
    simulator_map_tile,
    simulator_register,
)

BALER = {
    "street_address": "Test Street",
    "barangay": "Barangay I",
    "municipality_city": "Baler",
    "province": "Aurora",
    "postal_code": "3200",
    "country": "Philippines",
    "gps_coordinates": "15.75999, 121.56087",
}


class Region3ValidationTests(SimpleTestCase):
    def test_valid_locality_and_independent_cities(self):
        self.assertIsNone(validate_address(BALER))
        for province, city, barangay, point in (
            (
                "Pampanga",
                "City of Angeles",
                "Agapito del Rosario",
                "15.14412, 120.58937",
            ),
            ("Zambales", "City of Olongapo", "Asinan", "14.82829, 120.28295"),
        ):
            with self.subTest(city=city):
                self.assertIsNone(
                    validate_address(
                        {
                            **BALER,
                            "province": province,
                            "municipality_city": city,
                            "barangay": barangay,
                            "gps_coordinates": point,
                        }
                    )
                )

    def test_rejects_mismatched_names_and_bad_or_outside_pins(self):
        for changes in (
            {"province": "Bulacan"},
            {"barangay": "Nonexistent"},
            {"country": "Other"},
            {"gps_coordinates": ""},
            {"gps_coordinates": "nan, 121"},
            {"gps_coordinates": "inf, 121"},
            {"gps_coordinates": "91, 121"},
            {"gps_coordinates": "14.5995, 120.9842"},
            {"gps_coordinates": "15.14412, 120.58937"},
        ):
            with self.subTest(changes=changes):
                self.assertIsNotNone(validate_address({**BALER, **changes}))

    def test_polygon_edges_and_holes(self):
        polygon = {
            "type": "Polygon",
            "coordinates": [
                [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]],
                [[1, 1], [2, 1], [2, 2], [1, 2], [1, 1]],
            ],
        }
        self.assertTrue(geometry_contains(polygon, 0, 2))
        self.assertTrue(geometry_contains(polygon, 3, 3))
        self.assertFalse(geometry_contains(polygon, 1.5, 1.5))
        self.assertFalse(geometry_contains(polygon, 4.1, 3))

    def test_reverse_lookup_and_mismatched_barangay(self):
        self.assertEqual(
            locate_point(15.75999, 121.56087),
            {
                "status": "matched",
                "province": "Aurora",
                "municipality_city": "Baler",
                "barangay": "Barangay I",
            },
        )
        self.assertEqual(locate_point(14.5995, 120.9842), {"status": "outside"})
        self.assertIsNotNone(
            validate_address({**BALER, "gps_coordinates": "15.76044, 121.56944"})
        )

    def test_unmatched_and_overlapping_barangays_are_not_guessed(self):
        city_geometry = {
            "type": "Polygon",
            "coordinates": [[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]],
        }
        barangay_geometry = {
            "type": "Polygon",
            "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]],
        }
        entries = [
            (
                {"name": "Province"}, {"name": "City"}, city_geometry,
                (0, 0, 4, 4),
                [
                    ({"name": "First"}, barangay_geometry, (0, 0, 2, 2)),
                    ({"name": "Second"}, barangay_geometry, (0, 0, 2, 2)),
                ],
            )
        ]
        with patch("dashboard.region3.lookup_index", return_value=entries):
            self.assertEqual(locate_point(1, 1), {"status": "ambiguous"})
            self.assertEqual(locate_point(3, 3), {"status": "unresolved"})


class Region3SimulatorTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @patch(
        "dashboard.simulator.register_buyer",
        return_value=SimpleNamespace(status_code=201),
    )
    @patch("dashboard.simulator.check_simulator")
    def test_registration_rejects_bad_address_before_calling_api(self, check, register):
        for section, organization in (
            ("businesses", "business_address"),
            ("logistics", "company_address"),
        ):
            with self.subTest(section=section):
                request = self.factory.post(
                    "/",
                    data=json.dumps(
                        {
                            "personal_address": BALER,
                            organization: {**BALER, "barangay": "wrong"},
                        }
                    ),
                    content_type="application/json",
                )
                response = simulator_register(request, section)
                self.assertEqual(response.status_code, 400)
                self.assertIn(organization, json.loads(response.content))
        register.assert_not_called()

    @patch(
        "dashboard.simulator.FarmDetailView.as_view",
        return_value=lambda request, **kwargs: HttpResponse(status=200),
    )
    @patch("dashboard.simulator.get_object_or_404", return_value=SimpleNamespace())
    @patch("dashboard.simulator.resolve_enum_order_id", return_value=1)
    @patch("dashboard.simulator.check_simulator")
    def test_farm_updates_preserve_legacy_address_unless_replaced(
        self, check, role, farmer, view
    ):
        for payload, expected in (
            ({"farm_size_hectares": "5"}, 200),
            ({"address": {"street_address": "New"}}, 400),
            ({"address": BALER}, 200),
        ):
            request = self.factory.patch(
                "/", data=json.dumps(payload), content_type="application/json"
            )
            self.assertEqual(
                simulator_farmer_api(request, 1, "farms/2/").status_code, expected
            )

    @patch("dashboard.simulator.check_simulator")
    def test_tile_tms_conversion_and_missing_data_error(self, check):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "local_map_data").mkdir()
            request = self.factory.get("/")
            with override_settings(BASE_DIR=base):
                self.assertEqual(simulator_map_tile(request, 1, 0, 0).status_code, 503)
                tile = gzip.compress(b"test tile")
                with closing(
                    sqlite3.connect(base / "local_map_data" / "philippines.mbtiles")
                ) as db:
                    with db:
                        db.execute(
                            "CREATE TABLE tiles "
                            "(zoom_level, tile_column, tile_row, tile_data)"
                        )
                        db.execute("INSERT INTO tiles VALUES (1, 0, 1, ?)", (tile,))
                response = simulator_map_tile(request, 1, 0, 0)
                self.assertEqual(response.content, tile)
                self.assertEqual(response["Content-Encoding"], "gzip")
                self.assertEqual(simulator_map_tile(request, 1, 0, 1).status_code, 204)
                with self.assertRaises(Http404):
                    simulator_map_tile(request, 1, 2, 0)

    def test_post_still_requires_csrf(self):
        response = Client(enforce_csrf_checks=True).post(
            "/dashboard/local-test/businesses/register/",
            data="{}",
            content_type="application/json",
            REMOTE_ADDR="127.0.0.1",
        )
        self.assertEqual(response.status_code, 403)
        response = Client(enforce_csrf_checks=True).post(
            "/dashboard/local-map/lookup/", data="{}",
            content_type="application/json", REMOTE_ADDR="127.0.0.1",
        )
        self.assertEqual(response.status_code, 403)

    @patch("dashboard.simulator.simulator_allowed", return_value=False)
    def test_map_resources_require_the_local_simulator_gate(self, allowed):
        request = self.factory.get("/")
        for operation, args in (
            (simulator_map_asset, ("maplibre-gl.js",)),
            (simulator_map_glyph, ("Open Sans Regular", "0-255.pbf")),
            (simulator_map_tile, (1, 0, 0)),
        ):
            with self.subTest(operation=operation):
                with self.assertRaises(Http404):
                    operation(request, *args)
        request = self.factory.post("/", data="{}", content_type="application/json")
        with self.assertRaises(Http404):
            simulator_map_lookup(request)

    @patch("dashboard.simulator.check_simulator")
    def test_lookup_validates_and_identifies_coordinates(self, check):
        for payload, expected in (
            ({"latitude": 15.75999, "longitude": 121.56087}, "matched"),
            ({"latitude": 14.5995, "longitude": 120.9842}, "outside"),
        ):
            request = self.factory.post("/", data=json.dumps(payload), content_type="application/json")
            response = simulator_map_lookup(request)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(json.loads(response.content)["status"], expected)
        for payload in (
            {"latitude": "nan", "longitude": 120},
            {"latitude": True, "longitude": 120},
            {"latitude": 91, "longitude": 120},
            {},
        ):
            request = self.factory.post("/", data=json.dumps(payload), content_type="application/json")
            self.assertEqual(simulator_map_lookup(request).status_code, 400)


RUN_DATABASE_TESTS = os.environ.get("FTH_DATABASE_TESTS") == "1"


@skipUnless(RUN_DATABASE_TESTS, "Requires a preinitialized PostgreSQL test database")
@override_settings(DEBUG=True, ENABLE_LOCAL_SIMULATOR=True)
class Region3DatabaseTests(TestCase):
    databases = {"default"} if RUN_DATABASE_TESTS else set()

    def test_farmer_registration_and_farm_address_updates(self):
        staff = get_user_model().objects.create_superuser(
            username="region3_staff", password="LocalStaff!482"
        )
        self.client.force_login(staff)
        personal_pin = "15.75999, 121.56087"
        farm_pin = "15.76044, 121.56944"
        data = {
            "username": "region3_farmer",
            "password": "FarmerPassword!482",
            "firstname": "Test",
            "lastname": "Farmer",
            "phonenumber": "09123456789",
            "role": "Farmer",
            "region": "Region III",
            "province": "Aurora",
            "municipality": "Baler",
            "baranggay": "Barangay I",
            "house_number": "123",
            "street": "Test Street",
            "postal_code": "3200",
            "country": "Philippines",
            "personal_gps_coordinates": personal_pin,
            "farm_size": "2",
            "farm_region": "Region III",
            "farm_province": "Aurora",
            "farm_municipality": "Baler",
            "farm_barangay": "Sabang",
            "farm_house_number": "123",
            "farm_street": "Farm Road",
            "farm_postal_code": "3200",
            "farm_country": "Philippines",
            "farm_gps_coordinates": farm_pin,
            "documents": ["https://example.com/doc.jpg"] * 4,
            "document_types": [
                "Utility Bills",
                "Valid_ID",
                "Owner_Address",
                "Farm_Ownership",
            ],
        }
        response = self.client.post(
            "/dashboard/local-test/farmers/register/",
            data,
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        user = User.objects.get(username=data["username"])
        farm = Farm.objects.get(user=user)
        self.assertEqual(user.personal_address.gps_coordinates, personal_pin)
        self.assertEqual(farm.address.gps_coordinates, farm_pin)

        collection_url = f"/dashboard/local-test/farmers/{user.pk}/api/farms/"
        response = self.client.post(
            collection_url,
            {"farm_size_hectares": "4.5", "address": BALER},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        new_farm = Farm.objects.get(pk=response.json()["farm_id"])
        self.assertEqual(new_farm.user_id, user.pk)
        self.assertEqual(new_farm.address.gps_coordinates, BALER["gps_coordinates"])

        url = f"/dashboard/local-test/farmers/{user.pk}/api/farms/{farm.pk}/"
        old_address = farm.address_id
        response = self.client.patch(
            url, {"farm_size_hectares": "3"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        farm.refresh_from_db()
        self.assertEqual(farm.address_id, old_address)
        response = self.client.patch(
            url,
            {"address": {"street_address": "Incomplete"}},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400, response.content)
        response = self.client.patch(
            url, {"address": BALER}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        farm.refresh_from_db()
        self.assertNotEqual(farm.address_id, old_address)
        self.assertEqual(farm.address.gps_coordinates, BALER["gps_coordinates"])
