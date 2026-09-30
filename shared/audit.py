import json

from django.utils import timezone

from .models import AuditLog


def _serialize_model(instance):
    if instance is None:
        return {}
    payload = {}
    for field in instance._meta.fields:
        value = getattr(instance, field.name)
        if hasattr(value, "isoformat"):
            payload[field.name] = value.isoformat()
        else:
            payload[field.name] = value
    return payload


def _log_audit_change(
    user,
    action_type,
    target_table,
    target_id,
    old_values=None,
    new_values=None,
    request=None,
):
    try:
        ip_address = ""
        if request is not None:
            forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
            if forwarded_for:
                ip_address = forwarded_for.split(",")[0].strip()
            else:
                ip_address = request.META.get("REMOTE_ADDR", "")

        AuditLog.objects.create(
            user=user,
            action_type=action_type,
            target_table=target_table,
            target_id=target_id,
            old_values=json.dumps(old_values, default=str)
            if old_values is not None
            else None,
            new_values=json.dumps(new_values, default=str)
            if new_values is not None
            else None,
            ip_address=ip_address,
            created_at=timezone.now(),
        )
    except Exception:
        pass
