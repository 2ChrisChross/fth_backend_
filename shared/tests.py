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

