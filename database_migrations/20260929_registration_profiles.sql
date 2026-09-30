ALTER TABLE "USERS" ADD COLUMN IF NOT EXISTS "username" VARCHAR(150);
ALTER TABLE "USERS" ADD COLUMN IF NOT EXISTS "date_of_birth" DATE;
ALTER TABLE "USERS" ADD COLUMN IF NOT EXISTS "personal_address_id" INTEGER;
CREATE UNIQUE INDEX IF NOT EXISTS "uq_users_username" ON "USERS" ("username") WHERE "username" IS NOT NULL;

ALTER TABLE "ADDRESSES" ADD COLUMN IF NOT EXISTS "postal_code" VARCHAR(20);
ALTER TABLE "BULK_BUYERS" ADD COLUMN IF NOT EXISTS "address_id" INTEGER;

ALTER TABLE "VEHICLES" ADD COLUMN IF NOT EXISTS "is_refrigerated" SMALLINT NOT NULL DEFAULT 0;
ALTER TABLE "VEHICLES" ADD COLUMN IF NOT EXISTS "logistics_business_id" INTEGER;

CREATE TABLE IF NOT EXISTS "LOGISTICS_COMPANIES" (
    "logistics_business_id" SERIAL PRIMARY KEY,
    "user_id" INTEGER UNIQUE,
    "address_id" INTEGER,
    "business_name" VARCHAR(255) NOT NULL,
    "contact_phone" VARCHAR(255) NOT NULL,
    "contact_email" VARCHAR(255) NOT NULL,
    "is_verified" SMALLINT NOT NULL DEFAULT 0,
    "date_time_created" TIMESTAMPTZ,
    "date_time_deleted" TIMESTAMPTZ,
    CONSTRAINT "fk_logistics_business_user" FOREIGN KEY ("user_id") REFERENCES "USERS" ("user_id") ON DELETE SET NULL,
    CONSTRAINT "fk_logistics_business_address" FOREIGN KEY ("address_id") REFERENCES "ADDRESSES" ("address_id") ON DELETE SET NULL
);

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_users_personal_address') THEN
        ALTER TABLE "USERS" ADD CONSTRAINT "fk_users_personal_address"
            FOREIGN KEY ("personal_address_id") REFERENCES "ADDRESSES" ("address_id") ON DELETE SET NULL;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_bulk_buyers_address') THEN
        ALTER TABLE "BULK_BUYERS" ADD CONSTRAINT "fk_bulk_buyers_address"
            FOREIGN KEY ("address_id") REFERENCES "ADDRESSES" ("address_id") ON DELETE SET NULL;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_vehicles_logistics_business') THEN
        ALTER TABLE "VEHICLES" ADD CONSTRAINT "fk_vehicles_logistics_business"
            FOREIGN KEY ("logistics_business_id") REFERENCES "LOGISTICS_COMPANIES" ("logistics_business_id") ON DELETE SET NULL;
    END IF;
END $$;