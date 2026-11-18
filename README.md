
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

## Simulator on Render

The simulator changes real records in the configured database. Staff with
dashboard-management permission can select a farmer and access or edit their
records without that farmer's password, including unverified farmers. Review
staff permissions before enabling it: by the existing dashboard policy,
ungrouped staff also have full dashboard access. Keep `DEBUG=False` and take a
verified database backup.

The live simulator is **off by default**, independently of `DEBUG`. To enable
it, set `ENABLE_LIVE_SIMULATOR=true` in Render and redeploy. Set it to `false`
or remove it and redeploy to disable it. `ENABLE_LOCAL_SIMULATOR` still enables
the original local-only mode and does not allow access through a proxy or to
a remote database.

The map uses MapLibre and locally served OpenStreetMap Shortbread tiles. Append
these commands to the existing Render build command, after dependency
installation, and ensure failures stop the build:

```sh
npm ci && python manage.py prepare_simulator_assets
```

The preparation command downloads the
[BBBike Philippines Shortbread archive](https://data.bbbike.org/osm/mbtiles/region/asia/philippines/)
and validates its MBTiles database. It may download roughly 374 MB and needs
around 900 MB of temporary disk while extracting; the installed tiles occupy
roughly 490 MB. Actual sizes change as the source is updated. Builds fail
explicitly if the assets cannot be downloaded or validated. The assets live in
the build filesystem, not Git; future builds must prepare them again when they
are absent. Map data is OpenStreetMap contributors' data under the Open Database
License; the map displays the attribution.

After deployment, sign in as an authorized dashboard manager and click the
Farmers, Bulk Buyers, or Logistics page title to open its simulator. The banner
identifies live-database mode. Farmer simulator access is logged without
passwords or request bodies.
