from urllib.parse import urlsplit

from django.contrib.auth.hashers import make_password
from django.db import transaction

from farmers.models import Farm, FarmerCodeRequest
from shared.audit import log_staff_audit_change
from shared.models import ElectronicDocument, PhoneNumber, User
from shared.registration import create_address, resolve_enum_order_id


@transaction.atomic
def create_farmer_registration(data, request, staff_user=None):
	phone_number = data["phonenumber"]
	username = data["username"]
	first_name = data["firstname"]
	middle_name = (
		data.get("middle_name")
		or data.get("midle_name")
		or data.get("middlename")
		or ""
	)
	last_name = data["lastname"]

	preferred_language = resolve_enum_order_id(
		"language", data.get("language") or data.get("preferred_language")
	)
	role_order_id = resolve_enum_order_id("role", "Farmer")
	onboarding_status_id = resolve_enum_order_id(
		"onboarding_status",
		data.get("onboarding_status") or "Profile_Created",
	)
	payment_method_id = resolve_enum_order_id(
		"payment_method",
		data.get("payment_method") or data.get("preferred_payment_method"),
	)

	user_address = create_address(
		{
			"street_address": f"{data.get('house_number', '')} {data.get('street', '')}"
			if data.get("house_number")
			else data.get("street") or "",
			"barangay": data.get("baranggay") or data.get("barangay") or "",
			"municipality_city": data.get("municipality")
			or data.get("municipality_city")
			or "",
			"province": data.get("province") or "",
			"postal_code": data.get("postal_code") or "",
			"country": data.get("country") or "Philippines",
			"gps_coordinates": data.get("farm_region") or data.get("region") or "",
		},
		"residence",
	)
	user = User.objects.create(
		username=username,
		password_hash=make_password(data["password"]),
		personal_address=user_address,
		preferred_language=preferred_language,
		role=role_order_id,
		onboarding_status=onboarding_status_id,
		preferred_payment_method=payment_method_id,
		first_name=first_name,
		middle_name=middle_name or None,
		last_name=last_name,
		is_verified=0,
	)
	phone = PhoneNumber.objects.create(
		user=user,
		mobile_number=phone_number,
		phone_type="mobile",
		contact_status=1,
		is_verified=0,
	)

	farm_address = create_address(
		{
			"street_address": f"{data['farm_house_number']} {data['farm_street']}"
			if data["farm_house_number"]
			else data["farm_street"],
			"barangay": data["farm_barangay"],
			"municipality_city": data["farm_municipality"],
			"province": data["farm_province"],
			"postal_code": data["farm_postal_code"],
			"country": data.get("farm_country") or "Philippines",
			"gps_coordinates": data["farm_region"],
		},
		"farm",
	)
	farm = Farm.objects.create(
		user=user,
		address=farm_address,
		farm_size_hectares=data["farm_size"],
	)

	document_type_order_ids = []
	document_urls = data["document_urls"]
	document_type_names = data["document_type_names"]
	for index, url in enumerate(document_urls[:4], start=1):
		path = urlsplit(url).path
		file_extension = path.rsplit(".", 1)[-1].lower() if "." in path else ""
		doc_type_name = (
			document_type_names[index - 1]
			if index - 1 < len(document_type_names)
			else "Utility Bills"
		)
		doc_type_order_id = resolve_enum_order_id("document_type", doc_type_name) or 1
		document_type_order_ids.append(doc_type_order_id)
		ElectronicDocument.objects.create(
			user=user,
			doc_title=f"Registration document {index}",
			doc_type=doc_type_order_id,
			file_url=url,
			file_extension=file_extension,
			verification_status=0,
		)

	code_request = FarmerCodeRequest.objects.create(
		user=user,
		purpose=FarmerCodeRequest.Purpose.VERIFICATION,
	)
	if staff_user is not None:
		log_staff_audit_change(
			staff_user=staff_user,
			user=user,
			action_type="CREATE",
			target_table="USERS",
			target_id=user.user_id,
			old_values={},
			new_values={
				"username": username,
				"first_name": first_name,
				"middle_name": middle_name or None,
				"last_name": last_name,
				"phone_number": phone_number,
				"farm_id": farm.farm_id,
				"code_request_id": code_request.request_id,
			},
			request=request,
		)

	return {
		"user": user,
		"phone": phone,
		"farm": farm,
		"code_request": code_request,
		"language_order_id": preferred_language,
		"role_order_id": role_order_id,
		"onboarding_status_order_id": onboarding_status_id,
		"payment_method_order_id": payment_method_id,
		"document_type_order_ids": document_type_order_ids,
		"document_count": len(document_urls[:4]),
	}