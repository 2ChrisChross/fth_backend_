# Farmer API

Base URL: `/api/farmers/`

All request and response bodies are JSON unless noted otherwise. Farmer access
tokens must be sent as `Authorization: Bearer <access>`.

## Farmer Authentication

### Log in

`POST /api/farmers/login/`

```json
{
  "username": "farmer-name",
  "password": "your-password"
}
```

Successful response (`200`):

```json
{
  "access": "<access-jwt>",
  "refresh": "<refresh-jwt>"
}
```

Only verified, active farmer accounts can log in. Access tokens expire after 15
minutes. Refresh tokens expire after 7 days and rotate when refreshed.

### Refresh tokens

`POST /api/farmers/token/refresh/`

```json
{
  "refresh": "<refresh-jwt>"
}
```

Successful response (`200`) contains a new `access` and rotated `refresh`
token. Store the returned refresh token and stop using the submitted one.

### Log out

`POST /api/farmers/logout/`

Requires a valid access token and the matching refresh token:

```json
{
  "refresh": "<refresh-jwt>"
}
```

Successful response is `204 No Content`. The refresh token is revoked. The
current access token remains valid until its short expiry.

### Read or update the farmer profile

`GET /api/farmers/me/` requires a farmer access token. The response includes the
farmer's `user_id`, `username`, name, registered phone number, and farm size and
address when present. Passwords and verification codes are never returned.

`PATCH /api/farmers/me/` accepts any subset of these fields:

```json
{
  "username": "new-farmer-name",
  "first_name": "First",
  "middle_name": "Middle",
  "last_name": "Last",
  "new_password": "a-new-password"
}
```

The username must be unique. Password changes use the Django-configured
password validators. A successful response returns the updated profile, not the
new password.

## Registration And Verification

### Register

`POST /api/farmers/register/` creates the farmer, farm, phone, and submitted
documents. It also creates a `verification` code request in `pending_review`
status. Registration does not issue or expose a verification code, and does not
issue JWTs. The mobile client must upload documents to its document-storage
service separately and send the resulting URLs in this request; there is no
multipart upload endpoint yet.

```json
{
  "phonenumber": "+639123456789",
  "username": "farmer-name",
  "password": "your-password",
  "firstname": "First",
  "lastname": "Last",
  "role": "Farmer",
  "region": "Region name",
  "province": "Province name",
  "municipality": "Municipality name",
  "baranggay": "Barangay name",
  "house_number": "12",
  "street": "Farm Road",
  "postal_code": "1000",
  "farm_size": "2.50",
  "farm_region": "Region name",
  "farm_province": "Province name",
  "farm_municipality": "Municipality name",
  "farm_barangay": "Barangay name",
  "farm_house_number": "12",
  "farm_street": "Farm Road",
  "farm_postal_code": "1000",
  "documents": [
    "https://files.example/utility-bill.jpg",
    "https://files.example/valid-id.jpg",
    "https://files.example/owner-address.jpg",
    "https://files.example/farm-ownership.jpg"
  ],
  "document_types": [
    "Utility Bills",
    "Valid_ID",
    "Owner_Address",
    "Farm_Ownership"
  ]
}
```

`role` must be `Farmer`; at least four non-empty document URLs are required.
Optional fields include `middle_name`, `language`, `preferred_language`,
`onboarding_status`, `payment_method`, `preferred_payment_method`,
`municipality_city`, `barangay`, `country`, and `farm_country`. A successful
response (`201`) includes `user_id`, `phone_id`, `farm_id`, and
`code_request_id`.

After staff review, approval, code issuance, and mailing, submit:

`POST /api/farmers/verify-code/`

```json
{
  "phone_number": "+639123456789",
  "verification_code": "ABCD2345"
}
```

Successful response: `{"valid": true}`. This consumes the one-time code and
verifies the account; it does not log the farmer in. The farmer then uses the
username/password login endpoint.

### Request a verification or recovery code

`POST /api/farmers/code-requests/`

```json
{
  "phone_number": "+639123456789",
  "first_name": "First",
  "last_name": "Last",
  "purpose": "recovery"
}
```

`purpose` is `verification` or `recovery`. Verification requests are for
unverified farmers; recovery requests are for verified farmers. Registration
creates the initial verification request automatically. The endpoint always
returns `202` with a generic message so it does not disclose whether an account
matches the submitted details. Staff review and mail approved codes.

### Recover access

`POST /api/farmers/recover/`

```json
{
  "phone_number": "+639123456789",
  "verification_code": "ABCD2345"
}
```

A valid mailed recovery code is consumed and returns normal farmer `access` and
`refresh` JWTs. These tokens grant full farmer API access. Use `GET /me/` to
retrieve a forgotten username and `PATCH /me/` to change the password or
username. Invalid or expired codes return `400`.

Codes are stored as password hashes, expire 14 days after staff issue them, and
can be used only once. A replacement request invalidates any outstanding code
for that purpose.

## Farms, Listings, Orders And Messages

The following paths start with `/api/farmers/` and require a verified farmer's
access token. Each endpoint limits results and changes to that farmer's records.

- `GET farms/` lists active farms. `POST farms/` creates a farm with
  `farm_size_hectares` and an `address` object containing `street_address`,
  `barangay`, `municipality_city`, `province`, and `postal_code`. `country`
  and `gps_coordinates` are optional. Farm IDs are generated by the database;
  do not provide `farm_id` when creating a farm. Multiple farms may have the
  same address.
- `PATCH farms/<farm_id>/` updates `farm_size_hectares` and/or address fields.
  An address change creates a new farm address; it does not change pickup
  addresses saved on existing crop calendars or orders.
- `GET crop-types/` lists crop type IDs. `GET crops/` lists the farmer's active
  crops, including those without a marketplace listing. `GET listings/` lists
  the farmer's crop listings. `POST listings/` can create a crop, calendar, and
  listing:

  ```json
  {
    "farm_id": 1,
    "crop_type_id": 1,
    "batch_number": "TEST-1",
    "title": "Tomatoes",
    "available_stock_kg": "50.00",
    "price_per_kg": "25.00",
    "is_active": true
  }
  ```

  Alternatively, replace `farm_id` and `crop_type_id` with an owned `crop_id`
  to list an existing crop. Its most recent calendar is copied as the initial
  schedule, or a new calendar is created if needed. Omit `available_stock_kg` when listing an existing
  crop; its stock remains unchanged. Stock is shared by all listings for the
  crop and can be changed separately through a listing update. The batch
  number is optional. A new
  calendar uses the farm's current address as its pickup address and has no
  growing-stage dates by default.
  `PATCH listings/<listing_id>/` changes any of `batch_number`, `title`,
  `available_stock_kg`, `price_per_kg`, and `is_active`. Stock is the remaining
  **unreserved** quantity; changing it does not alter existing reservations.
  Deactivate a listing to remove it from the buyer marketplace.
- `GET listings/<listing_id>/calendar/` reads the listing's schedule.
  `PATCH` accepts any subset of `land_preparation_start`, `land_preparation_end`,
  `planting_start`, `planting_end`, `harvesting_start`, `harvesting_end`,
  `packing_duration_days`, `expected_quantity_kg`, `actual_harvested_kg`,
  `preorder_lead_time_days`, and `delivery_date`. Dates use `YYYY-MM-DD`;
  fields can be cleared with `null`, durations and quantities must be
  non-negative, and each end date must be on or after its corresponding start.
  Scheduling resets the stored manual stage so dashboard stage calculation uses
  dates. The dashboard's crop-level stage uses the crop's most recently created
  calendar. The delivery date is planned; the existing stage calculation calls
  it delivered once that date arrives, not as confirmation of an actual delivery.
  If the calendar is shared by other listings or referenced by an order, a copy
  is made before updating it, preserving the other listing and past order.
  Harvest quantities are informational and do not change marketplace stock.
- `GET listings/<listing_id>/expenses/` lists operating expenses for a listing
  of an active crop on the farmer's active farm. `POST` to the same path adds an expense, for
  example `{"tag": "Fertilizer", "amount": "500.00"}`. Tags are free text,
  amounts are non-negative totals (not per kilogram), and multiple entries,
  including repeated tags, are allowed. Use the same currency as the listing
  price. Expenses belong to the listing, not other listings of the same crop;
  they do not automatically change prices. Editing and deletion are not yet
  exposed. The former crop-expense API is no longer available. The legacy crop
  expense table is retained; migration `farmers.0009` stops if it contains
  records, so they can be reviewed rather than silently reassigned.
- `GET orders/` lists orders created through the buyer reservation workflow
  for the farmer's crops, including `reservation_status` and `delivery_status`.
  The latter is `not_assigned`, `awaiting_trip`, `planned`, `in_transit`,
  `completed`, or `unknown`. Historical orders without a reservation are not
  included. The separate legacy `order_status` may be null.
- `GET messages/` lists messages addressed to this farmer, including sender
  identity, sender kind, body and time. Verified buyers and logistics managers
  can send messages using their respective `farmer-messages/` endpoint. This
  requires the `api.0012_farmer_messages` migration. There are no replies,
  notifications, rate limits, or moderation; do not rely on it in production.

## Staff Code Administration

Staff endpoints use Django session authentication and require an authenticated
staff account (`is_staff`). Unsafe requests also require the Django CSRF token.
These endpoints are intended for the existing Django dashboard, not the Flutter
client. The farmer `User` model is separate from Django's staff-user model.

- `GET /api/farmers/admin/code-requests/` lists requests. Optional `?status=`
  accepts `pending_review`, `approved`, `rejected`, `code_issued`, `mailed`,
  `completed`, or `expired`.
- `GET /api/farmers/admin/code-requests/{request_id}/` returns request details,
  submitted documents, and staff audit events.
- `POST /api/farmers/admin/code-requests/{request_id}/review/` accepts
  `{"decision":"approve","reason":"..."}` or
  `{"decision":"reject","reason":"..."}`. Rejection requires a reason.
- `POST /api/farmers/admin/code-requests/{request_id}/issue-code/` issues a code
  for an approved request. The plaintext code is returned only in this staff
  response so staff can mail it. Do not log or expose this response to farmers.
- `POST /api/farmers/admin/code-requests/{request_id}/mark-mailed/` records the
  staff member and time the code was mailed.
- `POST /api/farmers/admin/farmers/{user_id}/verify/` manually verifies an
  account; the request must include a non-empty `reason`.

Request transitions are enforced by the API. Repeated review, issue, or mailing
actions that do not match the current state return `409 Conflict`.