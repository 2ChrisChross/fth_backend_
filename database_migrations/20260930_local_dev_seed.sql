BEGIN;

INSERT INTO "ENUMERATED_VALUES" ("type", "value", "ordering") VALUES
    ('role', 'Farmer', 1),
    ('role', 'Bulk_Buyer', 2),
    ('role', 'Logistics_Manager', 3),
    ('language', 'English', 1),
    ('onboarding_status', 'Profile_Created', 1),
    ('body_type', 'Other', 1),
    ('document_type', 'Utility Bills', 1),
    ('document_type', 'Valid_ID', 2),
    ('document_type', 'Owner_Address', 3),
    ('document_type', 'Farm_Ownership', 4),
    ('document_type', 'birth_certificate', 5),
    ('document_type', 'business_utility_bill', 6),
    ('document_type', 'business_permit', 7),
    ('document_type', 'national_id', 8),
    ('document_type', 'ltfrb_franchise_for_trucking', 9),
    ('document_type', 'vehicle_photo', 10),
    ('document_type', 'vehicle_driver_license', 11),
    ('document_type', 'official_receipt', 12),
    ('document_type', 'certificate_of_registration', 13),
    ('document_type', 'nbi_clearance', 14)
ON CONFLICT ("type", "value") DO UPDATE
SET "ordering" = EXCLUDED."ordering";

INSERT INTO "CROP_TYPES" ("crop_name", "category", "base_shelf_life_days")
SELECT seed."crop_name", seed."category", seed."base_shelf_life_days"
FROM (VALUES
    ('Mango', 'Fruit', 10),
    ('Banana', 'Fruit', 7),
    ('Tomato', 'Vegetable', 7)
) AS seed("crop_name", "category", "base_shelf_life_days")
WHERE NOT EXISTS (
    SELECT 1 FROM "CROP_TYPES" existing WHERE existing."crop_name" = seed."crop_name"
);

COMMIT;