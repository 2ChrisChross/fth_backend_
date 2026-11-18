
# Dashboard reference filters

Run Django migrations before using the updated dashboard (`python manage.py
migrate`). Migration `api.0013_region3_localities` creates and populates
province, city/municipality, and barangay reference tables from the frozen
PSGC 2026-Q2 snapshot. Angeles and Olongapo are independent cities grouped
geographically with Pampanga and Zambales respectively. The migration does
not modify existing addresses or crop types; its data snapshot must remain
unchanged so fresh installations are reproducible. Make future catalogue
updates in a new migration.

Farmers, Bulk Buyers, and farm-detail filters offer catalogue localities plus
values already stored in addresses. Select a province and city/municipality to
narrow the next list; without JavaScript, clear dependent selections and press
Search after changing a parent. Matching is case-insensitive but otherwise
exact, so legacy spellings remain separate choices. Crop choices come from
existing crop types, identify duplicate names by ID, and match active crops
exactly. Older bookmarked filters with partial names or crop names must be
selected again. This migration does not import the separate review-only crop
seed.
