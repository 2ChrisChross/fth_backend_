import json
from pathlib import Path

import django.db.models.deletion
from django.db import migrations, models


def seed_region3(apps, schema_editor):
    Province = apps.get_model("api", "Province")
    Municipality = apps.get_model("api", "Municipality")
    Barangay = apps.get_model("api", "Barangay")
    using = schema_editor.connection.alias
    data_path = Path(__file__).parent / "data" / "region3_localities_2026_q2.json"
    with data_path.open(encoding="utf-8") as file:
        provinces = json.load(file)

    Province.objects.using(using).bulk_create(
        [
            Province(code=province["code"], name=province["name"])
            for province in provinces
        ]
    )
    Municipality.objects.using(using).bulk_create(
        [
            Municipality(
                code=city["code"],
                name=city["name"],
                province_id=province["code"],
                independent=city.get("independent", False),
            )
            for province in provinces
            for city in province["cities"]
        ]
    )
    Barangay.objects.using(using).bulk_create(
        [
            Barangay(
                code=barangay["code"],
                name=barangay["name"],
                municipality_id=city["code"],
            )
            for province in provinces
            for city in province["cities"]
            for barangay in city["barangays"]
        ],
        batch_size=500,
    )


class Migration(migrations.Migration):
    dependencies = [("api", "0012_farmer_messages")]

    operations = [
        migrations.CreateModel(
            name="Province",
            fields=[
                (
                    "code",
                    models.CharField(max_length=10, primary_key=True, serialize=False),
                ),
                ("name", models.CharField(max_length=255)),
            ],
            options={"db_table": "PROVINCES"},
        ),
        migrations.CreateModel(
            name="Municipality",
            fields=[
                (
                    "code",
                    models.CharField(max_length=10, primary_key=True, serialize=False),
                ),
                ("name", models.CharField(max_length=255)),
                ("independent", models.BooleanField(default=False)),
                (
                    "province",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="municipalities",
                        to="api.province",
                    ),
                ),
            ],
            options={"db_table": "MUNICIPALITIES"},
        ),
        migrations.CreateModel(
            name="Barangay",
            fields=[
                (
                    "code",
                    models.CharField(max_length=10, primary_key=True, serialize=False),
                ),
                ("name", models.CharField(max_length=255)),
                (
                    "municipality",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="barangays",
                        to="api.municipality",
                    ),
                ),
            ],
            options={"db_table": "BARANGAYS"},
        ),
        migrations.RunPython(seed_region3, migrations.RunPython.noop),
    ]
