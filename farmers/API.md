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