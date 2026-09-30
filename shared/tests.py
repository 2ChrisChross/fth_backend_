from django.apps import apps
from django.contrib import admin as django_admin
from django.core.exceptions import FieldDoesNotExist
from django.test import SimpleTestCase

from farmers.models import Farm

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
