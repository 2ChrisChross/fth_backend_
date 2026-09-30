BEGIN;

CREATE TABLE "ADDRESSES" (
    "address_id" SERIAL PRIMARY KEY,
    "street_address" VARCHAR(255),
    "barangay" VARCHAR(255),
    "municipality_city" VARCHAR(255),
    "province" VARCHAR(255),
    "postal_code" VARCHAR(20),
    "country" VARCHAR(255) NOT NULL DEFAULT 'Philippines',
    "gps_coordinates" VARCHAR(255),
    "address_type" VARCHAR(255)
);

CREATE TABLE "ENUMERATED_VALUES" (
    "enum_id" SERIAL PRIMARY KEY,
    "enumerated_value_id" BIGINT,
    "type" VARCHAR(100) NOT NULL,
    "value" VARCHAR(100) NOT NULL,
    "ordering" INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT "uq_enumerated_value" UNIQUE ("type", "value")
);

CREATE TABLE "USERS" (
    "user_id" SERIAL PRIMARY KEY,
    "username" VARCHAR(150) UNIQUE,
    "password_hash" VARCHAR(255),
    "date_of_birth" DATE,
    "personal_address_id" INTEGER REFERENCES "ADDRESSES" ("address_id") ON DELETE SET NULL,
    "preferred_language" BIGINT,
    "role" BIGINT,
    "onboarding_status" BIGINT,
    "is_verified" SMALLINT,
    "deleted_at" TIMESTAMPTZ,
    "first_name" VARCHAR(255),
    "middle_name" VARCHAR(255),
    "last_name" VARCHAR(255),
    "average_rating" NUMERIC(5, 2),
    "preferred_payment_method" BIGINT,
    "total_earnings" NUMERIC(12, 2),
    "verification_code" VARCHAR(8)
);

CREATE TABLE "PHONE_NUMBERS" (
    "phone_id" SERIAL PRIMARY KEY,
    "user_id" INTEGER REFERENCES "USERS" ("user_id") ON DELETE SET NULL,
    "mobile_number" VARCHAR(255),
    "phone_type" VARCHAR(255),
    "contact_status" BIGINT,
    "is_verified" BIGINT,
    "start_date" TIMESTAMPTZ,
    "end_date" TIMESTAMPTZ,
    "last_tested_at" TIMESTAMPTZ
);

CREATE TABLE "EMAIL_ADDRESSES" (
    "email_id" SERIAL PRIMARY KEY,
    "user_id" INTEGER REFERENCES "USERS" ("user_id") ON DELETE SET NULL,
    "email_address" VARCHAR(255),
    "email_type" BIGINT,
    "is_verified" BIGINT,
    "created_at" TIMESTAMPTZ,
    "deleted_at" TIMESTAMPTZ
);

CREATE TABLE "LOGISTICS_COMPANIES" (
    "logistics_business_id" SERIAL PRIMARY KEY,
    "user_id" INTEGER UNIQUE REFERENCES "USERS" ("user_id") ON DELETE SET NULL,
    "address_id" INTEGER REFERENCES "ADDRESSES" ("address_id") ON DELETE SET NULL,
    "business_name" VARCHAR(255) NOT NULL,
    "contact_phone" VARCHAR(255) NOT NULL,
    "contact_email" VARCHAR(255) NOT NULL,
    "is_verified" SMALLINT NOT NULL DEFAULT 0,
    "date_time_created" TIMESTAMPTZ,
    "date_time_deleted" TIMESTAMPTZ
);

CREATE TABLE "BULK_BUYERS" (
    "business_id" SERIAL PRIMARY KEY,
    "user_id" INTEGER REFERENCES "USERS" ("user_id") ON DELETE SET NULL,
    "address_id" INTEGER REFERENCES "ADDRESSES" ("address_id") ON DELETE SET NULL,
    "business_name" VARCHAR(255),
    "business_type" BIGINT,
    "registration_number" VARCHAR(255),
    "is_verified" SMALLINT,
    "date_time_created" TIMESTAMPTZ,
    "date_time_deleted" TIMESTAMPTZ
);

CREATE TABLE "FARMS" (
    "farm_id" SERIAL PRIMARY KEY,
    "user_id" INTEGER REFERENCES "USERS" ("user_id") ON DELETE SET NULL,
    "address_id" INTEGER REFERENCES "ADDRESSES" ("address_id") ON DELETE SET NULL,
    "farm_size_hectares" NUMERIC(10, 2),
    "deleted_at" TIMESTAMPTZ
);

CREATE TABLE "CROP_TYPES" (
    "crop_type_id" SERIAL PRIMARY KEY,
    "crop_name" VARCHAR(255),
    "category" VARCHAR(255),
    "base_shelf_life_days" SMALLINT
);

CREATE TABLE "VEHICLES" (
    "vehicle_id" SERIAL PRIMARY KEY,
    "user_id" INTEGER REFERENCES "USERS" ("user_id") ON DELETE SET NULL,
    "logistics_business_id" INTEGER REFERENCES "LOGISTICS_COMPANIES" ("logistics_business_id") ON DELETE SET NULL,
    "truck_model" VARCHAR(255),
    "plate_number" VARCHAR(255),
    "max_weight_capacity_kg" NUMERIC(10, 2),
    "max_volume_capacity_m3" NUMERIC(10, 2),
    "body_type" BIGINT,
    "is_refrigerated" SMALLINT NOT NULL DEFAULT 0,
    "is_air_conditioned" SMALLINT,
    "fuel_consumption_liters_per_100km" SMALLINT,
    "total_distance_meters" BIGINT,
    "current_health_status" BIGINT,
    "deleted_at" TIMESTAMPTZ
);

CREATE TABLE "ELECTRONIC_DOCUMENTS" (
    "doc_id" SERIAL PRIMARY KEY,
    "user_id" INTEGER REFERENCES "USERS" ("user_id") ON DELETE SET NULL,
    "vehicle_id" INTEGER REFERENCES "VEHICLES" ("vehicle_id") ON DELETE SET NULL,
    "doc_title" VARCHAR(255),
    "doc_type" BIGINT,
    "file_url" VARCHAR(500),
    "file_extension" VARCHAR(50),
    "verification_status" BIGINT,
    "rejection_reason" TEXT,
    "expiration_date" DATE,
    "date_time_deleted" TIMESTAMPTZ,
    "date_time_uploaded" TIMESTAMPTZ
);

CREATE TABLE "AUDIT_LOGS" (
    "log_id" SERIAL PRIMARY KEY,
    "user_id" INTEGER REFERENCES "USERS" ("user_id") ON DELETE SET NULL,
    "action_type" VARCHAR(255),
    "target_table" VARCHAR(255),
    "target_id" INTEGER,
    "old_values" TEXT,
    "new_values" TEXT,
    "ip_address" VARCHAR(255),
    "created_at" TIMESTAMPTZ
);

CREATE TABLE "CROPS" (
    "crop_id" SERIAL PRIMARY KEY,
    "farm_id" INTEGER REFERENCES "FARMS" ("farm_id") ON DELETE SET NULL,
    "crop_type_id" INTEGER REFERENCES "CROP_TYPES" ("crop_type_id") ON DELETE SET NULL,
    "batch_number" VARCHAR(255),
    "available_stock_kg" NUMERIC(12, 2),
    "price_per_kg" NUMERIC(12, 2),
    "crop_image_url" VARCHAR(500),
    "harvested_at" TIMESTAMPTZ,
    "expires_at" TIMESTAMPTZ,
    "deleted_at" TIMESTAMPTZ
);

CREATE TABLE "CROP_CALENDARS" (
    "calendar_id" SERIAL PRIMARY KEY,
    "crop_id" INTEGER REFERENCES "CROPS" ("crop_id") ON DELETE SET NULL,
    "pickup_address_id" INTEGER REFERENCES "ADDRESSES" ("address_id") ON DELETE SET NULL,
    "calendar_status" BIGINT,
    "land_preparation_start" DATE,
    "land_preparation_end" DATE,
    "planting_start" DATE,
    "planting_end" DATE,
    "harvesting_start" DATE,
    "harvesting_end" DATE,
    "packing_duration_days" SMALLINT,
    "expected_quantity_kg" NUMERIC(12, 2),
    "actual_harvested_kg" NUMERIC(12, 2),
    "preorder_lead_time_days" SMALLINT,
    "delivery_date" DATE
);

CREATE TABLE "MARKETPLACE_LISTINGS" (
    "listing_id" SERIAL PRIMARY KEY,
    "crop_id" INTEGER REFERENCES "CROPS" ("crop_id") ON DELETE SET NULL,
    "calendar_id" INTEGER REFERENCES "CROP_CALENDARS" ("calendar_id") ON DELETE SET NULL,
    "listing_title" VARCHAR(255),
    "listing_type" BIGINT,
    "listing_price_per_kg" NUMERIC(12, 2),
    "is_active" SMALLINT,
    "created_at" TIMESTAMPTZ
);

CREATE TABLE "ORDERS" (
    "order_id" SERIAL PRIMARY KEY,
    "buyer_id" INTEGER REFERENCES "USERS" ("user_id") ON DELETE SET NULL,
    "order_type" BIGINT,
    "total_payment" NUMERIC(12, 2),
    "delivery_date" DATE,
    "order_status" BIGINT,
    "created_at" TIMESTAMPTZ,
    "updated_at" TIMESTAMPTZ,
    "deleted_at" TIMESTAMPTZ
);

CREATE TABLE "ORDER_ITEMS" (
    "order_item_id" SERIAL PRIMARY KEY,
    "order_id" INTEGER REFERENCES "ORDERS" ("order_id") ON DELETE SET NULL,
    "calendar_id" INTEGER REFERENCES "CROP_CALENDARS" ("calendar_id") ON DELETE SET NULL,
    "quantity_ordered_kg" NUMERIC(12, 2),
    "price_at_purchase" NUMERIC(12, 2)
);

CREATE TABLE "ORDER_STATUS_HISTORY" (
    "history_id" SERIAL PRIMARY KEY,
    "order_id" INTEGER REFERENCES "ORDERS" ("order_id") ON DELETE SET NULL,
    "status_changed_to" BIGINT,
    "updated_by_role" VARCHAR(255),
    "changed_at" TIMESTAMPTZ
);

CREATE TABLE "DELIVERY_TRIPS" (
    "trip_id" SERIAL PRIMARY KEY,
    "driver_id" INTEGER REFERENCES "USERS" ("user_id") ON DELETE SET NULL,
    "vehicle_id" INTEGER REFERENCES "VEHICLES" ("vehicle_id") ON DELETE SET NULL,
    "weight_utilization_pct" NUMERIC(5, 2),
    "volume_utilization_pct" NUMERIC(5, 2),
    "eta" TIMESTAMPTZ,
    "current_delivery_target" VARCHAR(255),
    "trip_status" BIGINT
);

CREATE TABLE "TRIP_MANIFESTS" (
    "manifest_id" SERIAL PRIMARY KEY,
    "trip_id" INTEGER REFERENCES "DELIVERY_TRIPS" ("trip_id") ON DELETE SET NULL,
    "order_id" INTEGER REFERENCES "ORDERS" ("order_id") ON DELETE SET NULL,
    "dropoff_sequence" SMALLINT
);

CREATE TABLE "VEHICLE_STATUS_HISTORY" (
    "history_id" SERIAL PRIMARY KEY,
    "vehicle_id" INTEGER REFERENCES "VEHICLES" ("vehicle_id") ON DELETE SET NULL,
    "trip_id" INTEGER REFERENCES "DELIVERY_TRIPS" ("trip_id") ON DELETE SET NULL,
    "status_changed_to" BIGINT,
    "issue_type" VARCHAR(255),
    "component_location" VARCHAR(255),
    "description" TEXT,
    "photo_url" VARCHAR(500),
    "start_date" TIMESTAMPTZ,
    "end_date" TIMESTAMPTZ
);

CREATE INDEX "idx_users_personal_address" ON "USERS" ("personal_address_id");
CREATE INDEX "idx_logistics_companies_address" ON "LOGISTICS_COMPANIES" ("address_id");
CREATE INDEX "idx_phone_numbers_user" ON "PHONE_NUMBERS" ("user_id");
CREATE INDEX "idx_email_addresses_user" ON "EMAIL_ADDRESSES" ("user_id");
CREATE INDEX "idx_bulk_buyers_user" ON "BULK_BUYERS" ("user_id");
CREATE INDEX "idx_bulk_buyers_address" ON "BULK_BUYERS" ("address_id");
CREATE INDEX "idx_farms_user" ON "FARMS" ("user_id");
CREATE INDEX "idx_farms_address" ON "FARMS" ("address_id");
CREATE INDEX "idx_vehicles_user" ON "VEHICLES" ("user_id");
CREATE INDEX "idx_vehicles_logistics_business" ON "VEHICLES" ("logistics_business_id");
CREATE INDEX "idx_documents_user" ON "ELECTRONIC_DOCUMENTS" ("user_id");
CREATE INDEX "idx_documents_vehicle" ON "ELECTRONIC_DOCUMENTS" ("vehicle_id");
CREATE INDEX "idx_audit_logs_user" ON "AUDIT_LOGS" ("user_id");
CREATE INDEX "idx_crops_farm" ON "CROPS" ("farm_id");
CREATE INDEX "idx_crops_type" ON "CROPS" ("crop_type_id");
CREATE INDEX "idx_crop_calendars_crop" ON "CROP_CALENDARS" ("crop_id");
CREATE INDEX "idx_crop_calendars_address" ON "CROP_CALENDARS" ("pickup_address_id");
CREATE INDEX "idx_marketplace_crop" ON "MARKETPLACE_LISTINGS" ("crop_id");
CREATE INDEX "idx_marketplace_calendar" ON "MARKETPLACE_LISTINGS" ("calendar_id");
CREATE INDEX "idx_orders_buyer" ON "ORDERS" ("buyer_id");
CREATE INDEX "idx_order_items_order" ON "ORDER_ITEMS" ("order_id");
CREATE INDEX "idx_order_items_calendar" ON "ORDER_ITEMS" ("calendar_id");
CREATE INDEX "idx_order_history_order" ON "ORDER_STATUS_HISTORY" ("order_id");
CREATE INDEX "idx_delivery_trips_driver" ON "DELIVERY_TRIPS" ("driver_id");
CREATE INDEX "idx_delivery_trips_vehicle" ON "DELIVERY_TRIPS" ("vehicle_id");
CREATE INDEX "idx_trip_manifests_trip" ON "TRIP_MANIFESTS" ("trip_id");
CREATE INDEX "idx_trip_manifests_order" ON "TRIP_MANIFESTS" ("order_id");
CREATE INDEX "idx_vehicle_history_vehicle" ON "VEHICLE_STATUS_HISTORY" ("vehicle_id");
CREATE INDEX "idx_vehicle_history_trip" ON "VEHICLE_STATUS_HISTORY" ("trip_id");

COMMIT;