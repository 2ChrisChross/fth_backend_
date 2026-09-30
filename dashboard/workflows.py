from django.db import transaction

from businesses.models import BulkBuyer
from logistics.models import Vehicle
from shared.audit import log_staff_audit_change

STATUS_WORKFLOWS = {
    "businesses": {
        "model": BulkBuyer,
        "id_field": "business_id",
        "status_field": "is_verified",
        "allowed_values": {0, 1, 2},
        "target_table": "BULK_BUYERS",
    },
    "logistics": {
        "model": Vehicle,
        "id_field": "vehicle_id",
        "status_field": "current_health_status",
        "allowed_values": {0, 1, 2, 3},
        "target_table": "VEHICLES",
    },
}


class DashboardWorkflowValidationError(Exception):
    pass


class DashboardWorkflowNotFound(Exception):
    pass


def update_dashboard_status(section, target_id, raw_status, staff_user, request):
    workflow = STATUS_WORKFLOWS.get(section)
    if workflow is None:
        raise DashboardWorkflowValidationError("This section has no status workflow.")
    try:
        new_status = int(raw_status)
    except (TypeError, ValueError) as exc:
        raise DashboardWorkflowValidationError("Select a valid status.") from exc
    if new_status not in workflow["allowed_values"]:
        raise DashboardWorkflowValidationError("Select a valid status.")

    model = workflow["model"]
    status_field = workflow["status_field"]
    with transaction.atomic():
        try:
            entity = model.objects.select_for_update().get(
                **{workflow["id_field"]: target_id}
            )
        except model.DoesNotExist as exc:
            raise DashboardWorkflowNotFound from exc

        old_status = getattr(entity, status_field)
        if old_status == new_status:
            return entity
        setattr(entity, status_field, new_status)
        entity.save(update_fields=[status_field])
        log_staff_audit_change(
            staff_user=staff_user,
            user=getattr(entity, "user", None),
            action_type="UPDATE_STATUS",
            target_table=workflow["target_table"],
            target_id=getattr(entity, workflow["id_field"]),
            old_values={status_field: old_status},
            new_values={status_field: new_status},
            request=request,
        )
    return entity