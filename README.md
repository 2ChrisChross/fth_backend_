# FTH Backend Local Setup

This guide covers local PostgreSQL development. It does not describe production deployment.

## Prerequisites

- PostgreSQL running locally on `localhost:5432`.
- Python dependencies installed from `requirements.txt` in the repository's `env` virtual environment.
- An empty PostgreSQL database named `fth_local_test_env`, unless you are connecting to an existing database.

The project reads `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, and `POSTGRES_PORT`. Defaults are `fth_local_test_env`, `postgres`, empty password, `localhost`, and `5432`. Set the password in your local shell or secret manager; do not commit it. The `psql` commands below may prompt separately for the PostgreSQL password.

In PowerShell, from this directory, set the connection values for the current session. Enter the password at the secure prompt:

```powershell
$env:POSTGRES_DB = "fth_local_test_env"
$env:POSTGRES_USER = "postgres"
$env:POSTGRES_HOST = "localhost"
$env:POSTGRES_PORT = "5432"
$secure = Read-Host "PostgreSQL password" -AsSecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $env:POSTGRES_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
}
```

## Fresh Database

Create the database if it does not exist, using your PostgreSQL client or database GUI. Then run these from the `fth_backend` directory:

```powershell
psql -U postgres -h localhost -p 5432 -d fth_local_test_env -v ON_ERROR_STOP=1 -f database_migrations/20260930_local_dev_schema.sql
psql -U postgres -h localhost -p 5432 -d fth_local_test_env -v ON_ERROR_STOP=1 -f database_migrations/20260930_local_dev_seed.sql
..\env\Scripts\python.exe manage.py migrate
```

In a GUI, connect to `fth_local_test_env` and execute the schema script first, the seed script second, and `..\env\Scripts\python.exe manage.py migrate` from the project terminal last. The schema script creates tables including `BULK_BUYERS` and `LOGISTICS_COMPANIES`; it uses plain `CREATE TABLE`, so run it only once against an empty database. The seed script is optional development data.

## Existing Database

Do not rerun the full schema script against an existing database. Set the connection values above, then run:

```powershell
..\env\Scripts\python.exe manage.py migrate
```

The Django rename migrations rename `BUSINESSES` to `BULK_BUYERS` and `LOGISTICS_BUSINESSES` to `LOGISTICS_COMPANIES` when the old tables exist. If the new tables already exist, those operations are skipped. If both or neither name exists, the migration stops with an error; inspect the database before proceeding.

`20260929_registration_profiles.sql` is an additive compatibility script for databases that are missing registration-profile columns or constraints. It expects the new table names, so on a database with the old names, run `manage.py migrate` before this script. The complete fresh schema already contains these fields, so it does not need this script.

## Start the Project

After migrations are applied, create an admin account and start Django:

```powershell
..\env\Scripts\python.exe manage.py createsuperuser
..\env\Scripts\python.exe manage.py runserver
```

The admin site is at `http://127.0.0.1:8000/admin/`. The dashboard starts at `http://127.0.0.1:8000/dashboard/`.

## Tests

Run all app tests from this directory:

```powershell
..\env\Scripts\python.exe manage.py test
```

The `shared` app keeps the historical Django migration label `api` for compatibility with existing migration history; this is separate from its Python package name.

## Code Style

Install development tools with `..\env\Scripts\python.exe -m pip install -r requirements-dev.txt`. Check lint with `..\env\Scripts\python.exe -m ruff check .` and format Python files with `..\env\Scripts\python.exe -m ruff format .`. Ruff checks E/F/I rules at 88 columns; generated migrations are exempt from E501 because they contain long serialized field definitions.