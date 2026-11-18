# Buyer and logistics APIs

These endpoints are an initial backend workflow, not a payment or delivery
platform. They use JSON and require an `Authorization: Bearer <access>` header
except for registration, verification, login, and refresh.

Run `python manage.py migrate` before using the new endpoints. The migrations
add order-reservation and delivery-assignment tables without altering existing
orders.

## Accounts

For buyers use `/api/businesses/`; for logistics managers use `/api/logistics/`.
Each base URL provides:

- `POST register/`: creates a pending account and staff verification request.
  Required fields are defined in the respective registration serializers.
- `POST verify-code/`: submit `{"phone_number": "...", "verification_code": "..."}`.
  New accounts can verify only after staff review, issue a code, and record
  mailing. Issued codes expire after 14 days and are single-use.
- `POST code-requests/`: submit `{"username": "...", "password": "..."}` to
  request another review after rejection or expiry. The response is always
  generic for validly formatted input. Existing accounts created before this
  workflow retain their original verification path.
- `POST login/`: `{"username": "...", "password": "..."}`. Only verified,
  active accounts of the corresponding role can log in. Returns `access` and
  `refresh` tokens.
- `POST token/refresh/`: `{"refresh": "..."}`. Returns a new access token and
  a rotated refresh token; the old refresh token cannot be reused.
- `POST logout/`: submit the current refresh token. It is revoked; the access
  token remains valid until it expires.
- `GET me/`: user details, phone number and basic business or company details.
- `PATCH me/`: update `username`, `first_name`, `middle_name`, `last_name`,
  and/or `new_password`. Changing the password invalidates existing access and
  refresh tokens; log in again.

Access tokens expire after 15 minutes; refresh tokens after seven days.

Staff must deliver the code outside the application. Neither verification nor
code requests currently have rate limiting; add abuse protection and a secure
delivery process before relying on this workflow for production onboarding.
Account verification does not change the separate business or company approval
status.

### Message a farmer

Verified buyers and logistics managers can send a message to any verified,
active farmer using `POST /api/businesses/farmer-messages/` or
`POST /api/logistics/farmer-messages/`, respectively:

```json
{"farmer_id": 1, "body": "Hello from a test account"}
```

The body must be nonempty and at most 4,000 characters. Farmers read these
messages using `GET /api/farmers/messages/`. This requires migration
`api.0012_farmer_messages`. It has no replies, notifications, rate limiting,
or moderation and is not production-ready.

## Buyer marketplace and orders

All paths below start with `/api/businesses/`.

- `GET listings/` lists active, unexpired listings with a matching crop calendar,
  available stock, and a nonnegative price.
- `GET delivery-companies/` lists companies whose manager account is verified and
  active. This does not imply the company itself has been approved.
- `GET orders/` lists orders created by this API, including cancelled orders.
- `POST orders/` reserves stock and creates a single-item order:

  ```json
  {
    "listing_id": 1,
    "quantity_kg": "12.50",
    "delivery_date": "2027-01-15",
    "delivery_company_id": 1
  }
  ```

  `delivery_date` and `delivery_company_id` are optional. Omitting the company
  leaves delivery to be arranged outside this workflow. When a company is chosen,
  the calendar must have a pickup address and the buyer must have a business
  address. The first active business address is used as the destination.
  The current listing price is stored per kilogram, and the total is rounded
  half up to two decimal places. The total is a quote, **not a payment**.
- `POST orders/<order_id>/cancel/` cancels a reservation and restores stock,
  provided it has not been assigned to a trip. A second cancellation is rejected.

Orders have `reservation_status` values `reserved`, `cancelled`, or `delivered`.
The separate legacy `order_status` field is not set by this workflow. Historical
orders without reservations are not shown by this API. Ordering the same listing
twice creates two orders; clients must avoid retrying a request blindly.

## Logistics vehicles and deliveries

All paths below start with `/api/logistics/`.

- `GET vehicles/` and `POST vehicles/` list and create the manager's vehicles.
  Example creation body:

  ```json
  {
    "truck_model": "Truck",
    "plate_number": "ABC-123",
    "max_weight_capacity_kg": "500.00",
    "max_volume_capacity_m3": "10.00",
    "body_type": 1,
    "is_refrigerated": 0
  }
  ```

  `body_type` must be a configured `body_type` ordering value. Boolean-like
  vehicle fields use `0` or `1`. `PATCH vehicles/<vehicle_id>/` updates a vehicle
  and `DELETE vehicles/<vehicle_id>/` soft-deletes it. Neither is allowed while
  that vehicle has a planned or in-transit trip.
- `GET deliveries/` lists only orders explicitly assigned to this company by
  buyers, including their pickup and destination addresses.
- `GET trips/` lists this company's trips. `POST trips/` creates a trip with
  an owned vehicle and one or more unassigned orders:

  ```json
  {"vehicle_id": 1, "order_ids": [1, 2], "eta": "2027-01-15T10:00:00Z"}
  ```

  `eta` is optional. The supplied order of IDs is the drop-off sequence.
  The manager is recorded as the driver. The total order weight must fit the
  vehicle; volume is not calculated. There is no automatic routing or dispatch.
- `PATCH trips/<trip_id>/` changes `trip_status` in sequence from `1` (planned)
  to `2` (in transit) to `3` (completed), for example `{"trip_status": 2}`.
  Completing a trip marks its reservations delivered. There is no proof of
  delivery, dispute handling, trip cancellation, or partial delivery.

These APIs do not charge buyers, pay farmers or carriers, provide refunds, or
send notifications. Review these assumptions before using them for real orders.
