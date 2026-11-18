# Admin Dashboard Operations

## Apply Schema And Create Initial Staff

Run migrations from the `fth_backend` project directory:

```powershell
..\env\Scripts\python.exe manage.py migrate
..\env\Scripts\python.exe manage.py createsuperuser
```

The migrations create the dashboard role groups and permissions. The first
superuser can sign in to Django admin at `/admin/` and manage staff accounts
under **Authentication and Authorization**.

## Create Staff Accounts And Assign Roles

Create a Django user, set a strong password, and enable **Staff status**. Staff
then sign in to the custom dashboard at `/dashboard/login/`; the dashboard uses
Django sessions and CSRF-protected POST forms. Do not create staff records in the
farmer `USERS` table.

The sidebar separates user records (Farmers, Logistics and Bulk Buyers) from
dashboard features such as reports, verification requests and audit logs.

Assign one or more groups to limit an account:

| Group | Access |
| --- | --- |
| `Reviewer` | View farmer applications and documents, approve/reject code requests, and manually verify farmers. |
| `Code-mail clerk` | View the code-request queue, issue codes, and record mailing. The plaintext code is shown only on issuance. |
| `Auditor` | View reports and audit logs. |
| `Support editor` | View and manage ordinary farmer, bulk-buyer, and logistics records. |

Django combines permissions from all assigned groups. Superusers have all
permissions. Per the configured policy, an `is_staff` user with no groups also
has full dashboard access; assign a role group to restrict that account.

## Verification Codes

Registration creates a pending verification request. A reviewer approves or
rejects it; a code-mail clerk issues the code and mails it outside the
application, then records that it was mailed. Issuing a code displays it once in
the staff dashboard message; do not copy it into logs, tickets, or farmer-facing
responses. Codes are stored as hashes and expire 14 days after issuance.

Recovery uses the same staff queue with purpose `recovery`. A valid recovery
code grants full farmer JWT access, as configured for this API. Manual
verification requires a reason and is limited to reviewers and superusers.

The **Verification Requests** page combines farmer, bulk-buyer and logistics
requests; filter by request type, status, purpose and requested date. Bulk-buyer
and logistics requests have account verification as their purpose; recovery
requests are farmer-only. The farmer code queue's view,
review and issue permissions also govern these requests; application access and
review permissions are both required to open submitted documents. Review, issue
and mark mailed follow the same process.
Staff with manual-verification permission can verify an account from its request
detail after supplying a reason; the override is recorded in staff activity.

Dashboard filter and sort dropdowns apply as soon as their selection changes.
Use Search for text, number and date fields; a filter button appears if
JavaScript is off. Filters combine and remain in effect when paging or updating
status. Clear resets the page's filters.

- Farmers can be filtered by active farm location, size and active crop type.
  All farm criteria must match the same active farm.
- On a farmer's Farms tab, filter active or archived farms by location, size and
  active crop type. Archived crops do not match crop filters.
- Bulk buyers can be filtered by business address; logistics vehicles by body
  type, refrigeration and weight capacity. Audit logs can be filtered by action
  and target table. Location, crop, action and target searches are partial and
  case-insensitive.
- Date bounds are inclusive and use the dashboard's configured time zone.
  Farmer and vehicle creation dates come from their earliest creation audit
  event; bulk buyers use their creation timestamp or, if absent, that audit
  event. Records without an available creation date cannot match a date filter.

On the Farmers, Logistics and Bulk Buyers lists, right-click the table or use
**Columns** to show or hide columns. Drag a column's right edge to resize it;
keyboard users can focus that edge and use the left and right arrow keys
(Shift changes the width faster). **Reset columns** restores the defaults.
The table fills the available dashboard width and scrolls horizontally when
its columns need more space.
Each list keeps its own choices and widths in the current browser tab until
that tab is closed. No record data is saved in these preferences.
The farmer's optional phone and farm columns show the first phone and first farm
by their IDs; the first farm may be archived. Open the farmer to see all farms.

## Production Checklist

- In Render's build command, run `python manage.py collectstatic --noinput`
  after installing requirements and before starting the server. WhiteNoise
  serves the collected dashboard assets. Do not rely on `DEBUG` to
  serve static files in production.
- Set a unique, high-entropy `SECRET_KEY` in the deployment environment; do not
  use the development fallback.
- Set `DEBUG=False` and configure `ALLOWED_HOSTS` for the deployed domains.
- Serve the dashboard only over HTTPS; enable secure session and CSRF cookies
  and the appropriate HSTS policy at the application or trusted proxy.
- Apply and verify migrations in staging before production, and back up the
  database before applying schema changes.
- Keep the physical code-mailing process restricted to authorized staff and
  review audit events regularly.
- Run the test suite and lint before deployment:

```powershell
..\env\Scripts\python.exe manage.py test farmers businesses logistics shared.tests dashboard
..\env\Scripts\python.exe -m ruff check .
```