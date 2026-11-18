-- REVIEW DRAFT: Region III crop-type candidates, not an automatic migration.
--
-- This catalogue is not exhaustive and does not establish that each crop is
-- commercially available in every province. Regional evidence includes farm
-- production, demonstrations, research, and planned support.
--
-- Before use:
-- 1. Back up the target database and review this list with local stakeholders.
-- 2. Compare existing crop names, local names and varieties; reconcile aliases
--    manually. The name comparison below only handles case and outer spaces.
--    It does not merge aliases. Duplicate matching names abort the transaction.
-- 3. Decide whether the category labels and distinction between pepper types
--    suit the application. This script updates shelf life for matching names
--    with an estimate but leaves their names and categories unchanged. For
--    rows with NULL estimates it preserves existing values.
-- 4. Run only with explicit approval on the intended PostgreSQL database.
--    This file inserts reference types, not farm crops or stock.
--
-- Shelf-life assumptions:
-- * Estimates are approximate whole days after harvest for sound, whole,
--   fresh, uncut produce kept shaded at warm ambient temperature, generally
--   around 25-30 C, without special coatings or refrigeration. The exact
--   conditions, cultivars, maturity and end points vary by source below.
-- * Where a source gives a range, the midpoint is rounded to a whole day;
--   otherwise the study's reported result is used. These are starting points,
--   not measured population averages or food-safety expiry dates. Some lots
--   deteriorate sooner; assess each lot and validate with local experts.
-- * NULL means insufficient comparable evidence, not unlimited freshness.
--   Fresh grains/legumes need prompt drying or processing; their safe storage
--   depends on moisture. Rice should ideally be dried within 24 hours (S10);
--   warm wet sorghum may need drying within hours (S11).
-- * The local seed_farms command substitutes seven days for NULL. That
--   simulator fallback is not a storage recommendation.
--
-- Shelf-life sources (S codes refer to the rows below):
-- S1: Mango controls averaged 4.0 and 4.67 days for two varieties at
--     approximately 30 C; 4 is their rounded mean, not a local cultivar study.
-- https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0347546
-- S2: Guava review reports 3-4 days at room temperature; rounded midpoint 4.
-- https://pmc.ncbi.nlm.nih.gov/articles/PMC10930470/
-- S3: Whole watermelon, 7-14 days at 20-25 C; rounded midpoint 11.
--     This cooler-temperature household guidance may overestimate warm life.
-- https://productlifespans.com/blogs/food-beverage-shelf-life/how-long-does-watermelon-last
-- S4: Uncoated eggplant 4, tomato 7, and okra 7 days at 29 +/- 2 C.
-- https://www.ajol.info/index.php/sa/article/view/270460/255635
-- S5: Untreated okra 3 days at ambient conditions. Okra's estimate 5 is the
--     midpoint of S4 and S5; the shorter observed life is 3 days.
-- https://econpapers.repec.org/RePEc:bjf:journl:v:11:y:2026:i:10:p:28-39
-- S6: Uncoated green chilli 5 days at 26 +/- 2 C; applied to both pepper
--     labels as an approximation, not proof for every pepper variety.
-- https://www.sciencedirect.com/science/article/pii/S0925521414000398
-- S7: Yardlong bean control 2-3 days; the abstract describes 15 C as ambient,
--     so the rounded midpoint 3 could overestimate life in warmer storage.
-- https://agris.fao.org/search/en/providers/122456/records/64722617f762bd4124ec8c7a
-- S8: Bitter gourd 3-4 days at 20 C; rounded midpoint 4 could overestimate
--     life in warmer storage.
-- https://hal.science/hal-05049073v1
-- S9: Philippine guide gives pechay 3-7 days at room temperature; midpoint 5.
-- https://orminagri.com/wp-content/uploads/2023/09/Shelf-Life-of-Vegetables-Legumes-at-Room-Temperature.pdf
-- S10: Fresh paddy drying guidance:
-- http://knowledgebank.irri.org/step-by-step-production/postharvest/drying
-- S11: Fresh sorghum drying guidance:
-- https://fieldreport.caes.uga.edu/publications/C1017/grain-sorghum-harvesting-drying-and-storing/
-- S12: Fresh cassava physiological deterioration starts at 24-72 hours;
--      2 days is the midpoint for onset, not a safe-use or expiration date.
-- https://pmc.ncbi.nlm.nih.gov/articles/PMC10011484/
-- S13: Ambient paddy straw mushrooms spoiled after two days; 1 day is a
--      conservative placeholder rather than a measured average.
-- https://pmc.ncbi.nlm.nih.gov/articles/PMC8076411/
-- S14: Lettuce visual-quality shelf life 7 days at 25 C, 51% RH.
-- https://bjas.bajas.edu.iq/index.php/bjas/article/view/3109
-- S15: Unpacked bottle gourd control 10 days at room temperature; actual
--      temperature is not specified in the abstract, so verify locally.
-- https://worldveg.tind.io/record/28302
--
-- The lock prevents concurrent writes while this script checks and inserts.
-- It cannot prevent future inserts of duplicates. There is no unique name
-- constraint; create one only after separately resolving existing duplicates.
--
-- Regional sources, with each row marked by source code(s):
-- R1: Mabalacat lowland vegetables, planted and harvested:
-- https://rfo3.da.gov.ph/index.php/harvest-festival-ng-isinagawang-lowland-vegetable-techno-demo-idinaos-sa-mabalacat-city/
-- R2: Regional vegetable and legume production; rice and onion:
-- https://rfo3.da.gov.ph/index.php/lowland-vegetable-and-legumes-stakeholders-meeting-isinagawa/
-- R3: Regional research and demonstrations, including feed crops:
-- https://rfo3.da.gov.ph/index.php/research-outreach-station-for-hillyland-development-2/
-- R4: Tarlac farm: guava, rice and two mushroom types:
-- https://rfo3.da.gov.ph/index.php/win-na-win-ang-mushroom-queen-ng-tarlac/
-- R5: Regional mango-grower programme:
-- https://rfo3.da.gov.ph/index.php/supply-and-delivery-of-pesticides-for-distribution-to-the-mango-growers-associations-and-cooperatives-in-central-luzon-under-the-hvcdp-fy-2025-regular-program/
-- R6: Regional calamansi production:
-- https://rfo3.da.gov.ph/index.php/pasilidad-para-sa-calamansi-processing-at-vegetable-cold-storage-ipinagkaloob-ng-da-region-3/
-- R7: Dinalupihan project, including watermelon:
-- https://rfo3.da.gov.ph/index.php/10-farmers-10-eclectic-dinalupihan-project-seeing-success/
-- R8: Regional office planting: pechay and lettuce:
-- https://rfo3.da.gov.ph/index.php/sama-samang-pagtatanim-isinagawa-ng-da-rfo-3/
-- R9: Planned ginger planting-material distribution in Region III:
-- https://rfo3.da.gov.ph/index.php/supply-and-delivery-of-4000-kilograms-luya-rhizomes-to-be-distributed-to-indigenous-people-group-of-region-3-under-da-4ks-program-cy-2023-with-pr-no-2023-01-0166-and-abc-of-php-600000-00/
--
-- Additional Philippine candidates, NOT included in the executable insert:
-- banana (saging), melon, papaya, strawberry, cucumber (pipino), bell pepper,
-- chayote (sayote), water spinach (kangkong), mustard greens (mustasa),
-- Chinese cabbage (wombok), kale, radish (labanos), carrot (karot), turmeric
-- (luyang dilaw), basil (balanoy), mint (yerba buena), oregano, lemongrass
-- (tanglad), parsley, coriander, spring onion (sibuyas dahon), cherry tomato.
-- Source: https://nupap.da.gov.ph/commodities-produced/
-- These national programme listings alone do not prove local production or
-- suitability in Region III. Check local evidence and avoid overlapping
-- generic/variety names before adding any of them.

BEGIN;

LOCK TABLE "CROP_TYPES" IN SHARE ROW EXCLUSIVE MODE;

CREATE TEMPORARY TABLE crop_type_review_seed (
    crop_name TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    base_shelf_life_days SMALLINT CHECK (base_shelf_life_days > 0)
) ON COMMIT DROP;

INSERT INTO crop_type_review_seed (crop_name, category, base_shelf_life_days)
VALUES
    ('Mango', 'Fruit', 4),                     -- R5; S1
    ('Calamansi', 'Fruit', NULL),              -- R6; kalamansi
    ('Guava', 'Fruit', 4),                     -- R4; bayabas, S2
    ('Watermelon', 'Fruit', 11),               -- R7; pakwan, S3
    ('Eggplant', 'Vegetable', 4),              -- R1, R2; talong, S4
    ('Tomato', 'Vegetable', 7),                -- R1, R2; kamatis, S4
    ('Hot Pepper', 'Vegetable', 5),            -- R1; hot chili, S6
    ('Siling Panigang', 'Vegetable', 5),       -- R1; long green chili, S6
    ('Squash', 'Vegetable', NULL),             -- R1, R2; kalabasa
    ('String Bean', 'Vegetable', 3),           -- R1, R2; sitaw, S7
    ('Bitter Gourd', 'Vegetable', 4),          -- R1, R2; ampalaya, S8
    ('Okra', 'Vegetable', 5),                  -- R1; S4, S5
    ('Sponge Gourd', 'Vegetable', NULL),       -- R1; patola
    ('Bottle Gourd', 'Vegetable', 10),         -- R1; upo, S15
    ('Onion', 'Vegetable', NULL),              -- R2, R3; sibuyas
    ('Pechay', 'Vegetable', 5),                -- R8; bok choy, S9
    ('Lettuce', 'Vegetable', 7),               -- R8; S14
    ('Peanut', 'Legume', NULL),                -- R2, R3; mani
    ('Mung Bean', 'Legume', NULL),             -- R2, R3; monggo
    ('Soybean', 'Legume', NULL),               -- R3; research/feed
    ('Sweet Potato', 'Root Crop', NULL),       -- R3; kamote
    ('Cassava', 'Root Crop', 2),               -- R3; kamoteng kahoy, S12
    ('Yam Bean', 'Root Crop', NULL),           -- R3; singkamas
    ('Rice', 'Grain', NULL),                   -- R2, R3, R4; palay, S10
    ('Corn', 'Grain', NULL),                   -- R3; yellow corn, mais
    ('Sorghum', 'Grain', NULL),                -- R3; research/feed, S11
    ('Ginger', 'Spice', NULL),                 -- R9; luya
    ('Oyster Mushroom', 'Mushroom', NULL),     -- R4; kabuteng pamaypay
    ('Paddy Straw Mushroom', 'Mushroom', 1);   -- R4; kabuteng saging, S13

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM "CROP_TYPES" AS existing
        JOIN crop_type_review_seed AS seed
            ON lower(btrim(existing."crop_name")) = lower(btrim(seed.crop_name))
        GROUP BY lower(btrim(existing."crop_name"))
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'Duplicate crop names match this seed; reconcile them before running it';
    END IF;
END $$;

UPDATE "CROP_TYPES" AS existing
SET "base_shelf_life_days" = seed.base_shelf_life_days
FROM crop_type_review_seed AS seed
WHERE lower(btrim(existing."crop_name")) = lower(btrim(seed.crop_name))
    AND seed.base_shelf_life_days IS NOT NULL
    AND existing."base_shelf_life_days" IS DISTINCT FROM seed.base_shelf_life_days;

INSERT INTO "CROP_TYPES" ("crop_name", "category", "base_shelf_life_days")
SELECT seed.crop_name, seed.category, seed.base_shelf_life_days
FROM crop_type_review_seed AS seed
WHERE NOT EXISTS (
    SELECT 1
    FROM "CROP_TYPES" AS existing
    WHERE lower(btrim(existing."crop_name")) = lower(btrim(seed.crop_name))
);

COMMIT;
