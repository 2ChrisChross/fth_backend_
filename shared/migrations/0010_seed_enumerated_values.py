from django.db import migrations

from shared.enums import TABLE, order_column

ENUMERATED_VALUES = (
    ("role", "Farmer", 1),
    ("role", "Bulk_Buyer", 2),
    ("role", "Logistics_Manager", 3),
    ("language", "English", 1),
    ("onboarding_status", "Profile_Created", 1),
    ("body_type", "Other", 1),
    ("document_type", "Utility Bills", 1),
    ("document_type", "Valid_ID", 2),
    ("document_type", "Owner_Address", 3),
    ("document_type", "Farm_Ownership", 4),
    ("document_type", "Birth_Certificate", 5),
    ("document_type", "business_utility_bill", 6),
    ("document_type", "business_permit", 7),
    ("document_type", "National_ID", 8),
    ("document_type", "ltfrb_franchise_for_trucking", 9),
    ("document_type", "vehicle_photo", 10),
    ("document_type", "vehicle_driver_license", 11),
    ("document_type", "official_receipt", 12),
    ("document_type", "certificate_of_registration", 13),
    ("document_type", "NBI_Clearance", 14),
    ("calendar_status", "Land_Preparation", 1),
    ("calendar_status", "Planting", 2),
    ("calendar_status", "Growing", 3),
    ("calendar_status", "Harvesting", 4),
    ("calendar_status", "Packing", 5),
    ("calendar_status", "Ready_for_Delivery", 6),
    ("calendar_status", "Delivered", 7),
)


def seed_enumerated_values(apps, schema_editor):
    """Add missing rows only; existing rows are never changed."""
    connection = schema_editor.connection
    column = order_column(connection_=connection)
    if column is None:
        print("\n  Skipped enumerated seed: no ordering column found.")
        return
    table = connection.ops.quote_name(TABLE)
    quoted = connection.ops.quote_name(column)
    with connection.cursor() as cursor:
        for type_, value, ordering in ENUMERATED_VALUES:
            cursor.execute(
                f"SELECT 1 FROM {table} WHERE type = %s AND LOWER(value) = LOWER(%s)",
                [type_, value],
            )
            if cursor.fetchone():
                continue
            cursor.execute(
                f"SELECT 1 FROM {table} WHERE type = %s AND {quoted} = %s",
                [type_, ordering],
            )
            if cursor.fetchone():
                print(
                    f"\n  Skipped {type_}/{value}: ordering {ordering} is already used."
                )
                continue
            cursor.execute(
                f"INSERT INTO {table} (type, value, {quoted}) VALUES (%s, %s, %s)",
                [type_, value, ordering],
            )


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0009_repair_legacy_model_columns"),
    ]

    operations = [
        migrations.RunPython(seed_enumerated_values, migrations.RunPython.noop),
    ]
