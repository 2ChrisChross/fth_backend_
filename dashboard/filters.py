from django import forms

from farmers.models import CropType, FarmerCodeRequest
from shared.enums import enum_rows
from shared.models import Address, Barangay, Municipality, Province


def location_choices(data):
    province = data.get("province", "") if data is not None else ""
    municipality = data.get("municipality", "") if data is not None else ""
    municipalities = Municipality.objects.all()
    barangays = Barangay.objects.all()
    addresses = Address.objects.all()
    if province:
        municipalities = municipalities.filter(province__name__iexact=province)
        barangays = barangays.filter(municipality__province__name__iexact=province)
        addresses = addresses.filter(province__iexact=province)
    if municipality:
        barangays = barangays.filter(municipality__name__iexact=municipality)

    def choices(reference_names, stored_names, empty_label):
        labels = {name: label for name, label in reference_names if name}
        for name in stored_names:
            if name:
                labels.setdefault(name, name)
        return [("", empty_label)] + sorted(
            labels.items(), key=lambda item: item[1].casefold()
        )

    province_choices = choices(
        ((name, name) for name in Province.objects.values_list("name", flat=True)),
        Address.objects.values_list("province", flat=True).distinct(),
        "Any province",
    )
    municipality_choices = choices(
        (
            (name, f"{name} (independent city)" if independent else name)
            for name, independent in municipalities.values_list("name", "independent")
        ),
        addresses.values_list("municipality_city", flat=True).distinct(),
        "Any city / municipality",
    )
    if municipality:
        addresses = addresses.filter(municipality_city__iexact=municipality)
    barangay_choices = choices(
        ((name, name) for name in barangays.values_list("name", flat=True)),
        addresses.values_list("barangay", flat=True).distinct(),
        "Any barangay",
    )
    return province_choices, municipality_choices, barangay_choices


class DashboardFilterForm(forms.Form):
    def __init__(self, section, data=None, *args, **kwargs):
        super().__init__(data, *args, **kwargs)
        if section in {"farmers", "businesses", "farms"}:
            for name, label, options in zip(
                ("province", "municipality", "barangay"),
                ("Province", "City / municipality", "Barangay"),
                location_choices(data),
            ):
                self.fields[name] = forms.ChoiceField(
                    label=label, required=False, choices=options
                )
        if section in {"farmers", "farms"}:
            self.fields["crop"] = forms.ChoiceField(
                label="Active crop type",
                required=False,
                choices=[("", "Any crop type")]
                + [
                    (str(pk), f"{name or 'Unnamed crop type'} (#{pk})")
                    for pk, name in CropType.objects.order_by(
                        "crop_name", "pk"
                    ).values_list("pk", "crop_name")
                ],
            )
        if section == "farmers":
            self.fields["farm_size"] = forms.ChoiceField(
                label="Active farm size",
                required=False,
                choices=[
                    ("", "Any size"),
                    ("under_1", "Under 1 ha"),
                    ("1_to_10", "1 to under 10 ha"),
                    ("10_plus", "10 ha or more"),
                ],
            )
        if section == "logistics":
            self.fields["body_type"] = forms.ChoiceField(
                label="Vehicle body type",
                required=False,
                choices=[("", "Any type")]
                + [(str(key), value) for key, value in enum_rows("body_type")],
            )
            self.fields["refrigerated"] = forms.ChoiceField(
                label="Refrigerated",
                required=False,
                choices=[("", "Any"), ("1", "Yes"), ("0", "No")],
            )
            for name, label in (
                ("min_capacity", "Min capacity (kg)"),
                ("max_capacity", "Max capacity (kg)"),
            ):
                self.fields[name] = forms.DecimalField(
                    label=label,
                    required=False,
                    min_value=0,
                    max_digits=10,
                    decimal_places=2,
                )
        if section == "audit_logs":
            self.fields["action_type"] = forms.CharField(
                label="Action", required=False, max_length=255
            )
            self.fields["target_type"] = forms.CharField(
                label="Target table", required=False, max_length=255
            )
        if section == "verification":
            self.fields["purpose"] = forms.ChoiceField(
                label="Purpose",
                required=False,
                choices=[("", "Any purpose")] + list(FarmerCodeRequest.Purpose.choices),
            )
        if section != "farms":
            for name, label in (("date_from", "From date"), ("date_to", "To date")):
                self.fields[name] = forms.DateField(
                    label=label,
                    required=False,
                    widget=forms.DateInput(attrs={"type": "date"}),
                )

    def clean(self):
        data = super().clean()
        if (
            data.get("date_from")
            and data.get("date_to")
            and data["date_from"] > data["date_to"]
        ):
            self.add_error("date_to", "End date must be on or after the start date.")
        if (
            data.get("min_capacity") is not None
            and data.get("max_capacity") is not None
        ):
            if data["min_capacity"] > data["max_capacity"]:
                self.add_error(
                    "max_capacity", "Maximum capacity must be at least the minimum."
                )
        return data


def apply_date_filter(queryset, field, filters):
    if filters.get("date_from"):
        queryset = queryset.filter(**{f"{field}__date__gte": filters["date_from"]})
    if filters.get("date_to"):
        queryset = queryset.filter(**{f"{field}__date__lte": filters["date_to"]})
    return queryset


def apply_farm_filters(queryset, filters):
    for name, field in (
        ("province", "address__province"),
        ("municipality", "address__municipality_city"),
        ("barangay", "address__barangay"),
    ):
        if filters.get(name):
            queryset = queryset.filter(**{f"{field}__iexact": filters[name]})
    if filters.get("crop"):
        queryset = queryset.filter(
            crops__deleted_at__isnull=True,
            crops__crop_type_id=filters["crop"],
        ).distinct()
    sizes = {
        "under_1": {"farm_size_hectares__lt": 1},
        "1_to_10": {"farm_size_hectares__gte": 1, "farm_size_hectares__lt": 10},
        "10_plus": {"farm_size_hectares__gte": 10},
    }
    if filters.get("farm_size") in sizes:
        queryset = queryset.filter(**sizes[filters["farm_size"]])
    return queryset
