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

## Endpoint Reference

This section gives the route-level contract, including authentication,
parameters, request fields, success responses, and errors implemented by each
view. Validation error messages can vary; examples are representative.

### Route index

| Method | Route | Authentication and authorization | Parameters |
| --- | --- | --- | --- |
| `POST` | `/api/farmers/register/` | Public | None |
| `POST` | `/api/farmers/verify-code/` | Public | None |
| `POST` | `/api/farmers/login/` | Public | None |
| `POST` | `/api/farmers/token/refresh/` | Public; farmer refresh token in body | None |
| `POST` | `/api/farmers/logout/` | Farmer JWT; matching refresh token in body | None |
| `GET`, `PATCH` | `/api/farmers/me/` | Farmer JWT | None |
| `POST` | `/api/farmers/code-requests/` | Public | None |
| `POST` | `/api/farmers/recover/` | Public | None |
| `GET` | `/api/farmers/admin/code-requests/` | Staff session; `farmers.view_farmer_code_requests` | Optional `status` query |
| `GET` | `/api/farmers/admin/code-requests/{request_id}/` | Staff session; `farmers.view_farmer_applications` | Integer `request_id` path |
| `POST` | `/api/farmers/admin/code-requests/{request_id}/review/` | Staff session; `farmers.review_farmer_code_requests` | Integer `request_id` path |
| `POST` | `/api/farmers/admin/code-requests/{request_id}/issue-code/` | Staff session; `farmers.issue_farmer_codes` | Integer `request_id` path |
| `POST` | `/api/farmers/admin/code-requests/{request_id}/mark-mailed/` | Staff session; `farmers.issue_farmer_codes` | Integer `request_id` path |
| `POST` | `/api/farmers/admin/farmers/{user_id}/verify/` | Staff session; `farmers.manually_verify_farmer` | Integer `user_id` path |

Compatibility routes `/api/register/` and `/api/verify-code/` also accept
`POST` and call the same public registration and verification handlers as
`/api/farmers/register/` and `/api/farmers/verify-code/`.

### Common headers, authentication, and errors

- Public routes need no `Authorization` header.
- For farmer-protected routes, include the issued access JWT in the standard authorization header.
  Access tokens expire after 15 minutes.
- Staff routes use the Django staff session cookie, not farmer JWTs. Accounts
  must be active and have `is_staff=True`; unsafe (`POST`) requests must include
  Django's CSRF token (normally the `X-CSRFToken` header). Each route also needs
  the permission in the route index. Superusers and staff users with no groups
  pass the dashboard permission check.
- Send `Content-Type: application/json` with JSON request bodies. GET routes
  have no body.
- Validation errors normally use `400 Bad Request` and a field-to-message-list
  object, for example `{"phone_number":["This field is required."]}`.
  Authentication/permission failures are `401` or `403`, depending on the
  authentication class. Missing staff resources return `404`.
- There is no pagination. The staff request list returns every matching
  request; its only filter is the optional `status` query parameter.

### `POST /api/farmers/register/`

Public; returns `201 Created`. Registration creates the user, personal address,
phone, farm, first four documents, and a `verification`/`pending_review`
request. It does not verify the account or return a code or JWT.

| Field | Required | Contract |
| --- | --- | --- |
| `phonenumber` | Yes | 7–25 characters matching `^\+?[0-9\s().-]{7,25}$` |
| `username` | Yes | 1–150 characters containing only letters, digits, `_`, `.`, or `-` |
| `password` | Yes | Non-empty string; stored as a password hash |
| `firstname`, `lastname` | Yes | Strings, maximum 255 characters |
| `role` | Effectively yes | Must equal the exact string `Farmer` |
| `region`, `province`, `municipality`, `baranggay`, `house_number`, `street` | Yes | Strings, maximum 255 characters |
| `postal_code` | Yes | 3–20 characters; starts alphanumeric, then alphanumeric, spaces, or hyphens |
| `farm_size` | Yes | Decimal, minimum `0`, at most 10 digits and 2 decimal places |
| `farm_region`, `farm_province`, `farm_municipality`, `farm_barangay`, `farm_house_number`, `farm_street` | Yes | Strings, maximum 255 characters |
| `farm_postal_code` | Yes | Same format as `postal_code` |
| `documents` | At least four required | List of at least four non-empty HTTP(S) URLs; only the first four are stored |
| `document_types` | No | Optional list; supported values: `Utility Bills`, `Valid_ID`, `Owner_Address`, `Farm_Ownership`; omitted entries are filled from these defaults in order |

Optional fields are `middle_name` (also accepted as `midle_name` or
`middlename`), `language`/`preferred_language`, `onboarding_status`,
`payment_method`/`preferred_payment_method`, `municipality_city`, `barangay`,
`country`, and `farm_country`. `document_type` is accepted as an alias for
`document_types`; if no document list is supplied, `document_1` through
`document_4` are accepted. Address and enum values follow registration mapping
logic. Valid enum labels depend on database seed data; an unknown optional enum
label can resolve to `null`. Registration does not perform an
application-level username uniqueness check, so clients should not depend on a
particular duplicate-registration error response.

Request:

```json
{
  "phonenumber": "+639123456789",
  "username": "juan-dela-cruz",
  "password": "example-password",
  "firstname": "Juan",
  "lastname": "Dela Cruz",
  "role": "Farmer",
  "region": "Region I",
  "province": "Ilocos Norte",
  "municipality": "Laoag City",
  "baranggay": "Barangay 1",
  "house_number": "12",
  "street": "Main Street",
  "postal_code": "2900",
  "farm_size": "2.50",
  "farm_region": "Region I",
  "farm_province": "Ilocos Norte",
  "farm_municipality": "Laoag City",
  "farm_barangay": "Barangay 1",
  "farm_house_number": "13",
  "farm_street": "Farm Road",
  "farm_postal_code": "2900",
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

Success (`201`):

```json
{
  "message": "Registration successful.",
  "user_id": 123,
  "username": "juan-dela-cruz",
  "phone_id": 456,
  "farm_id": 789,
  "code_request_id": 999,
  "language_order_id": null,
  "role_order_id": 2,
  "onboarding_status_order_id": 1,
  "payment_method_order_id": null,
  "document_type_order_ids": [1, 2, 3, 4],
  "document_count": 4
}
```

Missing/invalid fields, role, farm size, document count/type, or URL return
`400`. Example:

```json
{"role": ["Must be Farmer."]}
```

### `POST /api/farmers/verify-code/`

Public; body fields: `phone_number` (string, maximum 255 characters) and
`verification_code` (non-empty string, maximum 8 characters). The code must be
unexpired, for verification, and marked `mailed` by staff.

Success (`200`) for either a valid or invalid/expired code:

```json
{"valid": true}
```

```json
{"valid": false}
```

The `true` result consumes the code, completes the request, verifies the farmer
and phone, and does not issue tokens. Missing/invalid body fields return `400`.

### `POST /api/farmers/login/`

Public; JSON body:

```json
{"username": "juan-dela-cruz", "password": "example-password"}
```

Both fields are required strings; username is limited to 150 characters.
Success (`200`):

```json
{"access": "<access-jwt>", "refresh": "<refresh-jwt>"}
```

Invalid credentials return `401` with
`{"detail":"Invalid username or password."}`. An unverified account or
non-farmer role returns `403` with a `detail` message. Soft-deleted users
cannot log in.

### `POST /api/farmers/token/refresh/`

Public; JSON body `{"refresh":"<refresh-jwt>"}`. The token must belong to an
active, verified farmer and must not be expired or revoked. Success (`200`)
contains replacement tokens:

```json
{"access": "<new-access-jwt>", "refresh": "<new-refresh-jwt>"}
```

Invalid, expired, revoked, or ineligible-account tokens are rejected (normally
`401`; malformed/missing body fields may return `400`). Refresh rotation is
enabled; replace the stored refresh token with the response value.

### `POST /api/farmers/logout/`

Requires a farmer access JWT. JSON body:

```json
{"refresh": "<refresh-jwt>"}
```

Success is `204 No Content` with no response body. Missing or invalid refresh
tokens return `400`:

```json
{"detail": "A valid refresh token is required."}
```

A refresh token belonging to another farmer returns `403`:

```json
{"detail": "Refresh token does not belong to the authenticated farmer."}
```

The refresh token is revoked; an issued access token remains usable until it
expires.

### `GET /api/farmers/me/`

Requires a farmer access JWT; no body or query parameters. Success (`200`) has
this shape (farm and address may be `null`):

```json
{
  "user_id": 123,
  "username": "juan-dela-cruz",
  "first_name": "Juan",
  "middle_name": null,
  "last_name": "Dela Cruz",
  "phone_number": "+639123456789",
  "farm": {
    "farm_id": 789,
    "farm_size_hectares": "2.50",
    "address": {
      "street_address": "13 Farm Road",
      "barangay": "Barangay 1",
      "municipality_city": "Laoag City",
      "province": "Ilocos Norte",
      "postal_code": "2900",
      "country": "Philippines",
      "gps_coordinates": "Region I"
    }
  }
}
```

### `PATCH /api/farmers/me/`

Requires a farmer access JWT. All fields are optional:

```json
{
  "username": "new-username",
  "first_name": "Juan",
  "middle_name": "M",
  "last_name": "Dela Cruz",
  "new_password": "a-new-password"
}
```

Username is limited to 150 characters; names to 255. `middle_name` can be blank
or `null`. `new_password` is checked by Django's configured password
validators. Success (`200`) returns the `GET /me/` shape without a password.
Invalid fields, a used username, or a rejected password return `400`, for
example `{"username":["This username is already in use."]}`.

### `POST /api/farmers/code-requests/`

Public; JSON body:

```json
{
  "phone_number": "+639123456789",
  "first_name": "Juan",
  "last_name": "Dela Cruz",
  "purpose": "verification"
}
```

All fields are required strings; phone/name lengths are at most 255. `purpose`
must be `verification` or `recovery`. Verification requests are for unverified
farmers; recovery requests are for verified farmers. Invalid body fields return
`400`.

A valid request body always receives `202 Accepted`, whether or not an account
matches:

```json
{"detail": "If the account is eligible, the request will be reviewed."}
```

The generic response avoids confirming account existence. Repeated eligible
requests reuse an open request; a replacement request invalidates an
outstanding issued/mailed code for that purpose.

### `POST /api/farmers/recover/`

Public; JSON body:

```json
{
  "phone_number": "+639123456789",
  "verification_code": "ABCD2345"
}
```

Both fields are required; phone number is at most 255 characters and code at
most 8. Only an unexpired, mailed recovery-purpose code for a verified farmer
is accepted. Success (`200`) consumes the code and returns:

```json
{"access": "<access-jwt>", "refresh": "<refresh-jwt>"}
```

Invalid or expired codes return `400`:

```json
{"detail": "The recovery code is invalid or expired."}
```

Malformed or missing fields also return `400`.

### `GET /api/farmers/admin/code-requests/`

Requires a Django staff session and `farmers.view_farmer_code_requests`; no
request body. Optional `status` must be `pending_review`, `approved`,
`rejected`, `code_issued`, `mailed`, `completed`, or `expired`. An unknown value
returns `400`:

```json
{"status": ["Select a valid request status."]}
```

Success (`200`) is an unpaginated array. Each result includes request ID,
purpose, status, request/review/issue/expiry/mail timestamps, review reason,
and a farmer object with ID, username, first/last name, and nullable phone.

```json
[
  {
    "request_id": 999,
    "purpose": "verification",
    "status": "pending_review",
    "requested_at": "2026-10-01T10:30:00Z",
    "reviewed_at": null,
    "review_reason": "",
    "code_issued_at": null,
    "code_expires_at": null,
    "mailed_at": null,
    "farmer": {
      "user_id": 123,
      "username": "juan-dela-cruz",
      "first_name": "Juan",
      "last_name": "Dela Cruz",
      "phone_number": "+639123456789"
    }
  }
]
```

### `GET /api/farmers/admin/code-requests/{request_id}/`

Requires a Django staff session and `farmers.view_farmer_applications`.
`request_id` is an integer path parameter; there is no body or query parameter.
Success (`200`) includes request timestamps/status and reviewer, issuer, and
mailer IDs; farmer identity and verification state; document metadata; and
staff audit events.

```json
{
  "request_id": 999,
  "purpose": "verification",
  "status": "pending_review",
  "requested_at": "2026-10-01T10:30:00Z",
  "reviewed_at": null,
  "reviewed_by": null,
  "review_reason": "",
  "code_issued_at": null,
  "code_expires_at": null,
  "issued_by": null,
  "mailed_at": null,
  "mailed_by": null,
  "farmer": {
    "user_id": 123,
    "username": "juan-dela-cruz",
    "first_name": "Juan",
    "middle_name": null,
    "last_name": "Dela Cruz",
    "phone_number": "+639123456789",
    "is_verified": false,
    "documents": [
      {
        "doc_id": 1,
        "doc_title": "Registration document 1",
        "file_url": "https://files.example/document.jpg",
        "verification_status": 0
      }
    ]
  },
  "audit_events": []
}
```

An unknown request returns `404`.

### `POST /api/farmers/admin/code-requests/{request_id}/review/`

Requires a Django staff session and `farmers.review_farmer_code_requests`.
`request_id` is an integer path parameter. JSON body:

```json
{"decision": "approve", "reason": ""}
```

`decision` must be `approve` or `reject` (case-insensitive after trimming);
`reason` is optional for approval and required for rejection.

Success (`200`):

```json
{"request_id": 999, "status": "approved"}
```

Invalid decision or rejection without a reason returns `400`, for example
`{"detail":"A reason is required when rejecting a request."}`. Unknown request
returns `404`; a request not in `pending_review` returns `409`:

```json
{"detail": "Only pending requests can be reviewed."}
```

### `POST /api/farmers/admin/code-requests/{request_id}/issue-code/`

Requires a Django staff session and `farmers.issue_farmer_codes`.
`request_id` is an integer path parameter; no body is required. Only approved
requests for currently eligible farmer accounts can receive a code.

Success (`200`; response includes `Cache-Control: no-store`):

```json
{
  "request_id": 999,
  "status": "code_issued",
  "code": "ABCD2345",
  "expires_at": "2026-10-15T10:30:00Z"
}
```

Unknown request returns `404`; wrong state or ineligible account returns `409`.
The plaintext code is revealed only in this response. Do not log, cache, or
expose it to farmers. Codes are random eight-character uppercase strings and
expire 14 days after issuance.

### `POST /api/farmers/admin/code-requests/{request_id}/mark-mailed/`

Requires a Django staff session and `farmers.issue_farmer_codes`.
`request_id` is an integer path parameter; no body is required. The request
must be in `code_issued` state and the code must not have expired.

Success (`200`):

```json
{"request_id": 999, "status": "mailed"}
```

Unknown request returns `404`. Invalid state or an expired code returns `409`;
an expired request is changed to `expired`.

### `POST /api/farmers/admin/farmers/{user_id}/verify/`

Requires a Django staff session and `farmers.manually_verify_farmer`.
`user_id` is an integer path parameter. JSON body:

```json
{"reason": "Documents verified in person"}
```

`reason` must be non-empty after trimming. Success (`200`):

```json
{"user_id": 123, "is_verified": true}
```

Missing reason returns `400`; unknown/soft-deleted farmer returns `404`; a
non-farmer or already verified account returns `409`. Manual verification also
marks the farmer's phone verified and completes open verification requests.

## Registration workflow and limitations

1. The client uploads documents to its own storage service and sends their
   HTTP(S) URLs to registration; this API does not upload files.
2. Registration creates an unverified account and pending verification request.
   Staff review, issue a code, physically mail it outside the system, and record
   that it was mailed.
3. The client submits the mailed code to `/verify-code/`. Successful
   verification consumes it; the farmer then logs in.
4. Recovery follows the same staff review/issue/mail path with purpose
   `recovery`; `/recover/` consumes a valid mailed recovery code and returns
   farmer tokens.

The API checks that document URLs are HTTP(S) but does not fetch documents or
verify their contents. A new eligible request invalidates an outstanding
issued/mailed code for that purpose. Codes are password-hashed at rest and can
be used once. Staff actions are audited. The implementation has no page-based
pagination, document upload, automatic mailing, or separate farmer-list route.
Valid optional enum labels depend on database contents; this repository does
not define a deployment-specific API host/base URL.
