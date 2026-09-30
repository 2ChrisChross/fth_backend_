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

## Production Checklist

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