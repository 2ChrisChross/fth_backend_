from django.db import migrations

ROLE_PERMISSIONS = {
    "Reviewer": (
        "view_farmer_applications",
        "view_farmer_code_requests",
        "review_farmer_code_requests",
        "manually_verify_farmer",
    ),
    "Code-mail clerk": (
        "view_farmer_code_requests",
        "issue_farmer_codes",
    ),
    "Auditor": (
        "view_dashboard_reports",
        "view_dashboard_audit_logs",
    ),
    "Support editor": ("manage_dashboard_records",),
}
PERMISSION_NAMES = {
    "view_farmer_applications": "Can view farmer applications and documents",
    "view_farmer_code_requests": "Can view farmer code requests",
    "review_farmer_code_requests": "Can approve or reject farmer code requests",
    "issue_farmer_codes": "Can issue farmer verification or recovery codes",
    "manually_verify_farmer": "Can manually verify farmer accounts",
    "view_dashboard_reports": "Can view dashboard reports",
    "view_dashboard_audit_logs": "Can view dashboard audit logs",
    "manage_dashboard_records": "Can create and edit dashboard records",
}


def create_dashboard_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")
    database = schema_editor.connection.alias
    content_type, _ = ContentType.objects.using(database).get_or_create(
        app_label="farmers",
        model="farmercoderequest",
    )
    permissions = {}
    for codename, name in PERMISSION_NAMES.items():
        permission, _ = Permission.objects.using(database).get_or_create(
            content_type=content_type,
            codename=codename,
            defaults={"name": name},
        )
        permissions[codename] = permission

    for group_name, permission_codenames in ROLE_PERMISSIONS.items():
        group, _ = Group.objects.using(database).get_or_create(name=group_name)
        group.permissions.add(
            *(permissions[codename] for codename in permission_codenames)
        )


class Migration(migrations.Migration):
    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("farmers", "0004_alter_farmercoderequest_options"),
    ]

    operations = [
        migrations.RunPython(create_dashboard_groups, migrations.RunPython.noop),
    ]