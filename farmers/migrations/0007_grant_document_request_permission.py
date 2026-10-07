from django.db import migrations

GROUP_NAMES = ("Reviewer", "Code-mail clerk", "Auditor", "Support editor")
CODENAME = "request_farmer_documents"
NAME = "Can request additional documents from farmers"


def grant_document_request_permission(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")
    database = schema_editor.connection.alias
    content_type, _ = ContentType.objects.using(database).get_or_create(
        app_label="farmers",
        model="farmercoderequest",
    )
    permission, _ = Permission.objects.using(database).get_or_create(
        content_type=content_type,
        codename=CODENAME,
        defaults={"name": NAME},
    )
    for group in Group.objects.using(database).filter(name__in=GROUP_NAMES):
        group.permissions.add(permission)


class Migration(migrations.Migration):
    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("farmers", "0006_farmer_document_requests"),
    ]

    operations = [
        migrations.RunPython(
            grant_document_request_permission, migrations.RunPython.noop
        ),
    ]
