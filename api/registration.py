from urllib.parse import urlsplit

from django.db import connection

from .models import Address, ElectronicDocument, EnumeratedValue


def normalize_address_payload(data):
    if not isinstance(data, dict):
        return None

    required_fields = ("street_address", "barangay", "municipality_city", "province", "postal_code")
    address = {field: str(data.get(field) or "").strip() for field in required_fields}
    if any(not address[field] for field in required_fields):
        return None

    address["country"] = str(data.get("country") or "Philippines").strip()
    address["gps_coordinates"] = str(data.get("gps_coordinates") or "").strip()
    return address


def normalize_registration_documents(data, required_types):
    if not isinstance(data, list):
        return None

    documents = []
    supplied_types = set()
    for item in data:
        if not isinstance(item, dict):
            return None
        document_type = str(item.get("type") or "").strip().lower().replace(" ", "_")
        file_url = str(item.get("url") or "").strip()
        if not document_type or not file_url or len(file_url) > 500:
            return None
        documents.append({"type": document_type, "url": file_url})
        supplied_types.add(document_type)

    if not set(required_types).issubset(supplied_types):
        return None
    return documents


def resolve_enum_order_id(enum_type, raw_value):
    if raw_value is None:
        return None

    value = str(raw_value).strip()
    if value == "":
        return None

    if value.isdigit():
        return int(value)

    with connection.cursor() as cursor:
        for column in ("order_id", "ordering"):
            try:
                cursor.execute(
                    (
                        f'SELECT {column} FROM "enumerated_values" WHERE LOWER(type) = LOWER(%s) '
                        f'AND LOWER(value) = LOWER(%s) LIMIT 1'
                    ),
                    [str(enum_type), value],
                )
                row = cursor.fetchone()
                if row:
                    return row[0]
            except Exception:
                continue

    try:
        enum = EnumeratedValue.objects.filter(type__iexact=str(enum_type), value__iexact=value).first()
        return enum.ordering if enum is not None else None
    except Exception:
        return None


def create_address(data, address_type):
    return Address.objects.create(
        street_address=data.get("street_address", "").strip(),
        barangay=data.get("barangay", "").strip(),
        municipality_city=data.get("municipality_city", "").strip(),
        province=data.get("province", "").strip(),
        postal_code=data.get("postal_code", "").strip(),
        country=data.get("country", "Philippines").strip() or "Philippines",
        gps_coordinates=data.get("gps_coordinates", "").strip(),
        address_type=address_type,
    )


def create_registration_documents(user, documents, vehicle=None):
    created_documents = []
    for document in documents:
        document_type = str(document["type"]).strip()
        file_url = str(document["url"]).strip()
        path = urlsplit(file_url).path
        file_extension = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        created_documents.append(
            ElectronicDocument.objects.create(
                user=user,
                vehicle=vehicle(document_type) if callable(vehicle) else vehicle,
                doc_title=document_type,
                doc_type=resolve_enum_order_id("document_type", document_type),
                file_url=file_url,
                file_extension=file_extension,
                verification_status=0,
            )
        )
    return created_documents