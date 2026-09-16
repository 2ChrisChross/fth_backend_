from django.core.exceptions import FieldDoesNotExist
from django.test import SimpleTestCase

from .models import Farm, User


class SchemaRegressionTests(SimpleTestCase):
    def test_user_model_does_not_define_address_relation(self):
        with self.assertRaises(FieldDoesNotExist):
            User._meta.get_field("address")

        self.assertIsNotNone(Farm._meta.get_field("address"))
