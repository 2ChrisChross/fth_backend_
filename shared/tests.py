from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.contrib import admin as django_admin
from django.core.exceptions import FieldDoesNotExist
from django.test import SimpleTestCase

from farmers.models import Farm

from .audit import log_staff_audit_change
from .models import User


class SchemaRegressionTests(SimpleTestCase):
    def test_domain_models_are_registered_in_django_admin(self):
        app_labels = {"api", "farmers", "businesses", "logistics"}
        domain_models = [
            model for model in apps.get_models() if model._meta.app_label in app_labels
        ]

        self.assertTrue(domain_models)
        self.assertTrue(
            all(django_admin.site.is_registered(model) for model in domain_models)
        )

    def test_user_model_does_not_define_address_relation(self):
        with self.assertRaises(FieldDoesNotExist):
            User._meta.get_field("address")

        self.assertIsNotNone(Farm._meta.get_field("address"))

    @patch("shared.audit.AuditLog.objects.create")
    def test_staff_audit_writer_records_staff_actor(self, create_audit):
        staff_user = SimpleNamespace(pk=4)
        domain_user = SimpleNamespace(pk=12)
        request = SimpleNamespace(META={"REMOTE_ADDR": "127.0.0.1"})

        log_staff_audit_change(
            staff_user=staff_user,
            user=domain_user,
            action_type="UPDATE_STATUS",
            target_table="VEHICLES",
            target_id=3,
            old_values={"status": 0},
            new_values={"status": 1},
            request=request,
        )

        self.assertEqual(create_audit.call_args.kwargs["staff_user"], staff_user)
        self.assertEqual(create_audit.call_args.kwargs["user"], domain_user)
        self.assertEqual(create_audit.call_args.kwargs["ip_address"], "127.0.0.1")


class SeedFarmsCommandTests(SimpleTestCase):
    def test_refuses_remote_database_hosts(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError

        remote = {"default": {"HOST": "db.example.com"}}
        with patch("shared.management.commands.seed_farms.settings") as settings:
            settings.DATABASES = remote
            with self.assertRaises(CommandError):
                call_command("seed_farms")

    @patch("shared.management.commands.seed_farms.transaction")
    @patch("shared.management.commands.seed_farms._backfill_calendars", return_value=0)
    @patch("shared.management.commands.seed_farms._create_farm")
    @patch("shared.management.commands.seed_farms._seeded_farms")
    @patch("shared.management.commands.seed_farms.CropType")
    @patch("shared.management.commands.seed_farms.User")
    @patch("shared.management.commands.seed_farms._farmer_role_id", return_value=1)
    def test_only_missing_farms_are_created(
        self, _role, users, crop_types, seeded_farms, create_farm, _backfill, _transaction
    ):
        from django.core.management import call_command

        users.objects.filter.return_value.order_by.return_value = [object()]
        crop_types.objects.order_by.return_value = [object()]
        seeded_farms.return_value.count.return_value = 1

        with patch("shared.management.commands.seed_farms.settings") as settings:
            settings.DATABASES = {"default": {"HOST": "localhost"}}
            call_command("seed_farms", farms=3, crops=1)

        self.assertEqual(create_farm.call_count, 2)
        self.assertEqual([c.args[1] for c in create_farm.call_args_list], [2, 3])


class CropCalendarStageTests(SimpleTestCase):
    def _calendar(self, start):
        from datetime import timedelta
        from types import SimpleNamespace

        d = timedelta(days=1)
        prep_end = start + 13 * d
        plant_start = prep_end + d
        plant_end = plant_start + 13 * d
        harvest_start = plant_end + 31 * d
        harvest_end = harvest_start + 13 * d
        return SimpleNamespace(
            land_preparation_start=start,
            land_preparation_end=prep_end,
            planting_start=plant_start,
            planting_end=plant_end,
            harvesting_start=harvest_start,
            harvesting_end=harvest_end,
            packing_duration_days=3,
            delivery_date=harvest_end + 4 * d,
        )

    def test_stage_for_each_phase(self):
        from datetime import date, timedelta

        from dashboard.services import crop_calendar_stage

        today = date(2026, 10, 8)
        expected = {
            -5: "Land preparation",
            -20: "Planting",
            -45: "Growing",
            -65: "Harvesting",
            -73: "Packing",
            10: "Scheduled",
            -100: "Delivered",
        }
        for offset, stage in expected.items():
            calendar = self._calendar(today + timedelta(days=offset))
            self.assertEqual(crop_calendar_stage(calendar, today), stage, offset)

    def test_no_calendar(self):
        from dashboard.services import crop_calendar_stage

        self.assertEqual(crop_calendar_stage(None), "No calendar")

    def test_stock_only_from_harvesting_onward(self):
        from dashboard.services import stage_has_stock

        for stage in ("Land preparation", "Planting", "Growing", "Scheduled", "No calendar"):
            self.assertFalse(stage_has_stock(stage), stage)
        for stage in ("Harvesting", "Packing", "Ready for delivery", "Delivered"):
            self.assertTrue(stage_has_stock(stage), stage)


def _fake_connection(columns, existing=()):
    """A connection whose ENUMERATED_VALUES has the given columns and rows."""
    from unittest.mock import MagicMock

    conn = MagicMock()
    conn.ops.quote_name.side_effect = lambda name: f'"{name}"'
    conn.introspection.get_table_description.return_value = [
        SimpleNamespace(name=name) for name in columns
    ]
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    inserts = []
    state = {}

    def execute(sql, params=None):
        state["sql"], state["params"] = sql, params
        if sql.startswith("INSERT"):
            inserts.append(params)

    def fetchone():
        sql, params = state["sql"], state["params"]
        if "AND value =" in sql:
            hit = any(r[0] == params[0] and r[1] == params[1] for r in existing)
        elif "SELECT 1" in sql:
            hit = any(r[0] == params[0] and r[2] == params[1] for r in existing)
        else:
            hit = False
        return (1,) if hit else None

    cursor.execute.side_effect = execute
    cursor.fetchone.side_effect = fetchone
    return conn, inserts


class OrderColumnTests(SimpleTestCase):
    def test_modern_column_is_detected(self):
        from .enums import order_column

        conn, _ = _fake_connection(["type", "value", "ordering"])
        self.assertEqual(order_column(connection_=conn), "ordering")

    def test_legacy_order_id_column_is_detected(self):
        from .enums import order_column

        conn, _ = _fake_connection(["type", "value", "order_id"])
        self.assertEqual(order_column(connection_=conn), "order_id")

    def test_missing_column_returns_none_and_no_rows(self):
        from .enums import enum_rows, order_column

        conn, _ = _fake_connection(["type", "value"])
        self.assertIsNone(order_column(connection_=conn))
        self.assertEqual(enum_rows("role", connection_=conn), [])

    def test_enum_rows_selects_the_detected_legacy_column(self):
        from .enums import enum_rows

        conn, _ = _fake_connection(["type", "value", "order_id"])
        cursor = conn.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [(2, "Valid_ID")]

        rows = enum_rows("document_type", ("Valid_ID",), connection_=conn)

        sql = cursor.execute.call_args.args[0]
        self.assertIn('"order_id"', sql)
        self.assertNotIn('"ordering"', sql)
        self.assertEqual(rows, [(2, "Valid_ID")])


class SeedEnumeratedValuesMigrationTests(SimpleTestCase):
    def _run(self, columns, existing=()):
        from importlib import import_module

        migration = import_module("shared.migrations.0010_seed_enumerated_values")
        conn, inserts = _fake_connection(columns, existing)
        editor = SimpleNamespace(connection=conn)
        migration.seed_enumerated_values(None, editor)
        return migration, inserts

    def test_all_rows_are_created_on_an_empty_table(self):
        migration, inserts = self._run(["type", "value", "ordering"])
        self.assertEqual(len(inserts), len(migration.ENUMERATED_VALUES))

    def test_legacy_order_id_table_is_seeded_through_its_own_column(self):
        migration, inserts = self._run(["type", "value", "order_id"])
        self.assertEqual(len(inserts), len(migration.ENUMERATED_VALUES))

    def test_existing_rows_are_never_duplicated(self):
        existing = [("role", "Farmer", 1)]
        migration, inserts = self._run(["type", "value", "ordering"], existing)
        self.assertNotIn(("role", "Farmer", 1), [tuple(i) for i in inserts])
        self.assertEqual(len(inserts), len(migration.ENUMERATED_VALUES) - 1)

    def test_row_is_skipped_when_its_ordering_belongs_to_another_value(self):
        existing = [("calendar_status", "Other", 1)]
        _, inserts = self._run(["type", "value", "ordering"], existing)
        values = {i[1] for i in inserts}
        self.assertNotIn("Land_Preparation", values)
        self.assertIn("Planting", values)

    def test_nothing_is_written_without_an_ordering_column(self):
        _, inserts = self._run(["type", "value"])
        self.assertEqual(inserts, [])
