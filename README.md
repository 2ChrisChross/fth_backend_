# fth_backend_
# FTH backend

The Django dashboard is available at `/api/dashboard/`. Its left navigation provides
separate views for farmers, logistics vehicles and drivers, businesses, authentication
status, and database audit logs. Use the search field in each section to filter records.

Dashboard create, update, and delete actions write to the existing `AUDIT_LOGS` table
when it is available in the configured database.
