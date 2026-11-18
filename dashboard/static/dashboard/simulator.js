(() => {
    "use strict";

    const root = document.getElementById("simulator");
    const section = root.dataset.section;
    const csrf = root.querySelector("[name=csrfmiddlewaretoken]").value;
    const status = document.getElementById("sim-status");
    const results = document.getElementById("sim-results");
    let access = null;
    let refresh = null;
    let sessionGeneration = 0;
    const selectedFarmer = root.dataset.farmerId ? {
        user_id: root.dataset.farmerId,
        username: root.dataset.farmerUsername,
    } : null;
    let farmerPage = 1;
    let calendarGeneration = 0;
    let loadedCalendarListing = null;
    let loadedCalendarValues = null;
    const calendarFields = [
        "land_preparation_start", "land_preparation_end", "planting_start", "planting_end",
        "harvesting_start", "harvesting_end", "packing_duration_days", "expected_quantity_kg",
        "actual_harvested_kg", "preorder_lead_time_days", "delivery_date",
    ];

    function setStatus(message, isError = false) {
        status.textContent = message;
        status.classList.toggle("error", isError);
    }

    function fill(formId, field, value, append = false) {
        const form = document.getElementById(formId);
        if (!form) return;
        const input = form.elements[field];
        if (!input) return;
        input.value = append && input.value ? `${input.value}, ${value}` : value;
        form.closest("details").open = true;
        input.focus();
    }

    function addSelectButton(parent, text, callback) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = text;
        button.addEventListener("click", callback);
        parent.appendChild(button);
    }

    function renderValue(parent, value) {
        if (value === null || typeof value !== "object") {
            parent.appendChild(document.createTextNode(value === null ? "—" : String(value)));
            return;
        }
        if (Array.isArray(value)) {
            if (!value.length) {
                parent.textContent = "No records.";
                return;
            }
            value.forEach((item) => {
                const card = document.createElement("div");
                card.className = "record";
                renderValue(card, item);
                if (item && typeof item === "object") {
                    if (section === "farmers" && item.request_id) {
                        addSelectButton(card, "Select request", () => fill("document-submit-form", "request_id", item.request_id));
                    }
                    if (section === "farmers" && item.farm_id && !item.crop_id) {
                        addSelectButton(card, "Select farm", () => {
                            const form = document.getElementById("farmer-listing-form");
                            form.elements.listing_id.value = "";
                            form.elements.crop_id.value = "";
                            updateListingStockInput();
                            fill("farm-form", "farm_id", item.farm_id);
                            fill("farmer-listing-form", "farm_id", item.farm_id);
                        });
                    }
                    if (section === "farmers" && item.crop_type_id && !item.listing_id) {
                        if (!item.crop_id) {
                            addSelectButton(card, "Select crop type", () => {
                                const form = document.getElementById("farmer-listing-form");
                                form.elements.listing_id.value = "";
                                form.elements.crop_id.value = "";
                                updateListingStockInput();
                                fill("farmer-listing-form", "crop_type_id", item.crop_type_id);
                            });
                        }
                    }
                    if (section === "farmers" && item.crop_id && !item.listing_id) {
                        addSelectButton(card, "Use crop", () => {
                            const form = document.getElementById("farmer-listing-form");
                            form.reset();
                            if (item.price_per_kg !== null) form.elements.price_per_kg.value = item.price_per_kg;
                            fill("farmer-listing-form", "crop_id", item.crop_id);
                            updateListingStockInput();
                        });
                    }
                    if (section === "farmers" && item.listing_id) {
                        addSelectButton(card, "Select listing", () => {
                            const form = document.getElementById("farmer-listing-form");
                            form.reset();
                            updateListingStockInput();
                            fill("farmer-listing-form", "listing_id", item.listing_id);
                            fill("listing-expense-form", "listing_id", item.listing_id);
                            selectCalendarListing(item.listing_id);
                        });
                    } else if (section === "businesses" && item.listing_id) {
                        addSelectButton(card, "Use listing", () => fill("order-form", "listing_id", item.listing_id));
                    }
                    if (section === "businesses" && item.company_id) {
                        addSelectButton(card, "Use company", () => fill("order-form", "delivery_company_id", item.company_id));
                    }
                    if (item.order_id) {
                        if (section === "businesses") {
                            addSelectButton(card, "Select order", () => fill("cancel-form", "order_id", item.order_id));
                        } else if (section === "logistics") {
                            addSelectButton(card, "Add to trip", () => fill("trip-form", "order_ids", item.order_id, true));
                        }
                    }
                    if (section === "logistics" && item.vehicle_id && !item.trip_id) {
                        addSelectButton(card, "Select vehicle", () => {
                            fill("vehicle-form", "vehicle_id", item.vehicle_id);
                            fill("vehicle-delete-form", "vehicle_id", item.vehicle_id);
                            fill("trip-form", "vehicle_id", item.vehicle_id);
                        });
                    }
                    if (section === "logistics" && item.trip_id && !item.order_id) {
                        addSelectButton(card, "Select trip", () => fill("trip-status-form", "trip_id", item.trip_id));
                    }
                }
                parent.appendChild(card);
            });
            return;
        }
        const list = document.createElement("dl");
        Object.entries(value).forEach(([key, item]) => {
            const label = document.createElement("dt");
            label.textContent = key.replaceAll("_", " ");
            const detail = document.createElement("dd");
            renderValue(detail, item);
            list.append(label, detail);
        });
        parent.appendChild(list);
    }

    function show(value) {
        results.replaceChildren();
        renderValue(results, value);
    }

    async function request(url, method = "GET", data = null, authenticated = true, isCurrent = () => true, showErrors = true) {
        if (authenticated && !access) throw new Error("Sign in first.");
        const headers = {Accept: "application/json", "X-CSRFToken": csrf};
        if (data !== null) headers["Content-Type"] = "application/json";
        if (authenticated) headers.Authorization = `Bearer ${access}`;
        const response = await fetch(url, {
            method,
            headers,
            credentials: "same-origin",
            body: data === null ? undefined : JSON.stringify(data),
        });
        const text = await response.text();
        if (!isCurrent()) throw new Error("Farmer selection changed; the previous result was discarded.");
        let payload = null;
        if (text) {
            try {
                payload = JSON.parse(text);
            } catch {
                throw new Error(`Unexpected server response (HTTP ${response.status}).`);
            }
        }
        if (!response.ok) {
            if (showErrors) {
                show(payload);
                const error = new Error(`Request failed (HTTP ${response.status}). See results.`);
                error.details = payload;
                throw error;
            }
            const detail = payload && typeof payload.detail === "string" ? ` ${payload.detail}` : "";
            throw new Error(`Request failed (HTTP ${response.status}).${detail}`);
        }
        return payload;
    }

    function api(path, method = "GET", data = null, authenticated = true, isCurrent = () => true, showErrors = true) {
        if (section === "farmers" && authenticated) {
            if (!selectedFarmer) throw new Error("Select a farmer first.");
            const url = root.dataset.farmerApiUrl.replace(/me\/$/, path);
            return request(url, method, data, false, isCurrent, showErrors);
        }
        return request(`/api/${section}/${path}`, method, data, authenticated, isCurrent, showErrors);
    }

    function formData(form) {
        return Object.fromEntries(new FormData(form).entries());
    }

    function nonempty(data) {
        return Object.fromEntries(Object.entries(data).filter(([, value]) => value !== ""));
    }

    function handle(formId, operation) {
        const form = document.getElementById(formId);
        if (!form) return;
        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            const formStatus = form.querySelector("[data-form-status]");
            if (formStatus) formStatus.textContent = "";
            const buttons = Array.from(form.querySelectorAll("button[type=submit]"));
            buttons.forEach((button) => { button.disabled = true; });
            try {
                await operation(form, formData(form), event.submitter);
            } catch (error) {
                setStatus(error.message, true);
                if (formStatus) {
                    const details = error.details;
                    formStatus.textContent = details && typeof details === "object"
                        ? Object.entries(details).map(([field, value]) => {
                            const message = Array.isArray(value) ? value.join(" ") : value;
                            return `${field.replaceAll("_", " ")}: ${typeof message === "object" ? JSON.stringify(message) : message}`;
                        }).join(" ")
                        : error.message;
                    formStatus.classList.add("error");
                }
            } finally {
                buttons.forEach((button) => { button.disabled = false; });
            }
        });
    }

    function handleButton(id, operation) {
        const button = document.getElementById(id);
        if (!button) return;
        button.addEventListener("click", async () => {
            try {
                await operation();
            } catch (error) {
                setStatus(error.message, true);
            }
        });
    }

    function invalidateCalendar(form) {
        calendarGeneration += 1;
        loadedCalendarListing = null;
        loadedCalendarValues = null;
        for (const field of calendarFields) form.elements[field].disabled = true;
        const formStatus = form.querySelector("[data-form-status]");
        formStatus.textContent = "Load this listing's schedule before saving.";
        formStatus.classList.remove("error");
    }

    function selectCalendarListing(listingId) {
        const form = document.getElementById("listing-calendar-form");
        if (!form) return;
        fill("listing-calendar-form", "listing_id", listingId);
        invalidateCalendar(form);
    }

    function address(values, prefix) {
        const fields = ["street_address", "barangay", "municipality_city", "province", "postal_code", "country", "gps_coordinates"];
        return Object.fromEntries(fields.map((field) => [field, values[`${prefix}_${field}`]]));
    }

    function updateListingStockInput() {
        const form = document.getElementById("farmer-listing-form");
        if (!form) return;
        const existingCrop = Boolean(form.elements.crop_id.value);
        form.elements.available_stock_kg.disabled = existingCrop;
        if (existingCrop) form.elements.available_stock_kg.value = "";
    }

    const collectionGeneration = {farms: 0, crops: 0, listings: 0};

    async function loadFarmerCollection(kind) {
        const generation = ++collectionGeneration[kind];
        const list = document.getElementById(`farmer-${kind}`);
        list.textContent = `Loading ${kind}...`;
        list.setAttribute("aria-busy", "true");
        try {
            const records = await api(`${kind}/`, "GET", null, true, () => generation === collectionGeneration[kind], false);
            if (!Array.isArray(records)) throw new Error("Unexpected response from the server.");
            list.replaceChildren();
            if (records.length) {
                renderValue(list, records);
            } else {
                list.textContent = `No ${kind} found for this farmer.`;
            }
            return true;
        } catch (error) {
            if (generation !== collectionGeneration[kind]) return null;
            list.textContent = `Could not load ${kind}. ${error.message}`;
            return false;
        } finally {
            if (generation === collectionGeneration[kind]) list.setAttribute("aria-busy", "false");
        }
    }

    async function loadFarmers(page) {
        const search = document.getElementById("farmer-search-form").elements.q.value;
        const params = new URLSearchParams({page: String(page), q: search});
        const data = await request(`${root.dataset.farmersUrl}?${params}`, "GET", null, false);
        farmerPage = data.page;
        const list = document.getElementById("farmer-list");
        list.replaceChildren();
        if (!data.farmers.length) list.textContent = "No farmers found.";
        data.farmers.forEach((farmer) => {
            const card = document.createElement("div");
            card.className = "record";
            const name = [farmer.first_name, farmer.last_name].filter(Boolean).join(" ");
            card.appendChild(document.createTextNode(
                `${name || "Unnamed"} — ${farmer.username || "No username"} (ID ${farmer.user_id}; ${farmer.is_verified ? "verified" : "not verified"}) `
            ));
            const link = document.createElement("a");
            link.href = root.dataset.farmerDetailUrl.replace(/0\/$/, `${farmer.user_id}/`);
            link.textContent = "Select farmer";
            card.appendChild(link);
            list.appendChild(card);
        });
        document.getElementById("farmer-page").textContent = `Page ${data.page} of ${data.pages}`;
        document.getElementById("farmer-previous").disabled = !data.has_previous;
        document.getElementById("farmer-next").disabled = !data.has_next;
    }

    if (selectedFarmer) {
        document.getElementById("farmer-listing-form").elements.crop_id.addEventListener("input", updateListingStockInput);
        const calendarForm = document.getElementById("listing-calendar-form");
        calendarForm.elements.listing_id.addEventListener("input", () => invalidateCalendar(calendarForm));
        invalidateCalendar(calendarForm);
        handleButton("refresh-crops", async () => {
            document.getElementById("farmer-crops").hidden = false;
            const loaded = await loadFarmerCollection("crops");
            if (loaded === true) setStatus("Crops loaded.");
            else if (loaded === false) setStatus("Could not load crops. See the crop list.", true);
        });
        for (const kind of ["farms", "listings"]) {
            handleButton(`refresh-${kind}`, async () => {
                if (await loadFarmerCollection(kind)) setStatus(`${kind === "farms" ? "Farms" : "Listings"} refreshed.`);
            });
            loadFarmerCollection(kind);
        }
    }
    if (document.getElementById("farmer-search-form")) {
        handle("farmer-search-form", () => loadFarmers(1));
        handleButton("farmer-previous", () => loadFarmers(farmerPage - 1));
        handleButton("farmer-next", () => loadFarmers(farmerPage + 1));
        loadFarmers(1).catch((error) => {
            document.getElementById("farmer-list").textContent = "Could not load farmers.";
            setStatus(error.message, true);
        });
    }

    const generateRegistration = document.getElementById("generate-registration");
    if (generateRegistration && window.region3Ready) {
        window.region3Ready.then((picker) => { generateRegistration.disabled = !picker; });
    } else if (generateRegistration) {
        setStatus("Region III address picker is unavailable. Check the local setup.", true);
    }

    handleButton("generate-registration", async () => {
        const bytes = crypto.getRandomValues(new Uint8Array(16));
        const token = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
        const phone = `09${Array.from(bytes.slice(0, 9), (byte) => byte % 10).join("")}`;
        const companyPhone = `09${Array.from(bytes.slice(7, 16), (byte) => byte % 10).join("")}`;
        const form = document.getElementById("register-form");
        const values = {
            username: `test_${section}_${token}`,
            password: `Test!${token}a9`,
            first_name: "Test",
            middle_name: "",
            last_name: "User",
            date_of_birth: "1990-01-01",
            phone_number: phone,
            farm_size: "2.50",
            business_name: `Test Buyer ${token}`,
            company_name: `Test Logistics ${token}`,
            company_phone: companyPhone,
            company_email: `test_${token}@example.com`,
            vehicle_model: "Test Truck",
            vehicle_plate_number: `TEST-${token}`,
            vehicle_weight: "1000",
            vehicle_volume: "10",
            vehicle_body_type: "Other",
            vehicle_refrigerated: "false",
        };
        for (const prefix of ["personal", "organization"]) {
            Object.assign(values, {
                [`${prefix}_street_address`]: section === "farmers" ? "Test Street" : "123 Test Street",
                [`${prefix}_house_number`]: "123",
                [`${prefix}_postal_code`]: "3200",
                [`${prefix}_country`]: "Philippines",
            });
        }
        for (const [name, value] of Object.entries(values)) {
            if (form.elements[name]) form.elements[name].value = value;
        }
        const picker = await window.region3Ready;
        if (!picker) throw new Error("Region III picker is unavailable; check the map setup.");
        picker.fillTest(form);
        form.querySelectorAll("[name^=doc_]").forEach((input) => {
            input.value = `https://example.com/test-documents/${input.name.slice(4)}`;
        });
        setStatus("Test data filled. Place and confirm both pins, review the data, and copy the password.");
    });

    handleButton("toggle-registration-password", () => {
        const input = document.getElementById("register-form").elements.password;
        const button = document.getElementById("toggle-registration-password");
        const showPassword = input.type === "password";
        input.type = showPassword ? "text" : "password";
        button.textContent = showPassword ? "Hide password" : "Show password";
        button.setAttribute("aria-pressed", String(showPassword));
    });

    handle("register-form", async (form, values) => {
        if (!values.personal_gps_coordinates || !values.organization_gps_coordinates) {
            throw new Error("Place and confirm a pin for each address.");
        }
        let payload;
        if (section === "farmers") {
            payload = {
                username: values.username,
                password: values.password,
                firstname: values.first_name,
                middle_name: values.middle_name,
                lastname: values.last_name,
                phonenumber: values.phone_number,
                role: "Farmer",
                region: "Region III",
                province: values.personal_province,
                municipality: values.personal_municipality_city,
                baranggay: values.personal_barangay,
                house_number: values.personal_house_number,
                street: values.personal_street_address,
                postal_code: values.personal_postal_code,
                country: values.personal_country,
                farm_size: values.farm_size,
                farm_region: "Region III",
                personal_gps_coordinates: values.personal_gps_coordinates,
                farm_gps_coordinates: values.organization_gps_coordinates,
                farm_province: values.organization_province,
                farm_municipality: values.organization_municipality_city,
                farm_barangay: values.organization_barangay,
                farm_house_number: values.organization_house_number,
                farm_street: values.organization_street_address,
                farm_postal_code: values.organization_postal_code,
                farm_country: values.organization_country,
                documents: [values.doc_utility_bill, values.doc_valid_id, values.doc_owner_address, values.doc_farm_ownership],
                document_types: ["Utility Bills", "Valid_ID", "Owner_Address", "Farm_Ownership"],
            };
        } else {
            payload = {
                username: values.username,
                password: values.password,
                first_name: values.first_name,
                middle_name: values.middle_name,
                last_name: values.last_name,
                date_of_birth: values.date_of_birth,
                phone_number: values.phone_number,
                role: section === "businesses" ? "Bulk_Buyer" : "Logistics_Manager",
                personal_address: address(values, "personal"),
                documents: Object.entries(values)
                    .filter(([name]) => name.startsWith("doc_"))
                    .map(([name, url]) => ({type: name.slice(4), url})),
            };
            if (section === "businesses") {
                payload.business_name = values.business_name;
                payload.business_address = address(values, "organization");
            } else {
                payload.company_name = values.company_name;
                payload.company_phone = values.company_phone;
                payload.company_email = values.company_email;
                payload.company_address = address(values, "organization");
                payload.vehicle = {
                    model: values.vehicle_model,
                    plate_number: values.vehicle_plate_number,
                    max_weight_capacity_kg: values.vehicle_weight,
                    max_volume_capacity_m3: values.vehicle_volume,
                    body_type: values.vehicle_body_type,
                    is_refrigerated: values.vehicle_refrigerated === "true",
                };
            }
        }
        const result = await request(root.dataset.registerUrl, "POST", payload, false);
        form.elements.password.value = "";
        document.getElementById("verify-form").elements.phone_number.value = values.phone_number;
        document.getElementById("verify-form").elements.verification_code.value = "";
        const codeForm = document.getElementById("code-request-form");
        if (section === "farmers") {
            codeForm.elements.phone_number.value = values.phone_number;
            codeForm.elements.first_name.value = values.first_name;
            codeForm.elements.last_name.value = values.last_name;
            document.getElementById("recover-form").elements.phone_number.value = values.phone_number;
        } else {
            codeForm.elements.username.value = values.username;
        }
        if (section !== "farmers") document.getElementById("login-form").elements.username.value = values.username;
        show(result);
        setStatus("Account created. Staff review and code mailing are required before verification.");
    });

    handle("code-request-form", async (form, values) => {
        const result = await api("code-requests/", "POST", values, false);
        if (form.elements.password) form.elements.password.value = "";
        show(result);
        setStatus("Code request submitted. See results below.");
    });

    handle("verify-form", async (form, values) => {
        const result = await api("verify-code/", "POST", values, false);
        show(result);
        if (result.valid) {
            form.elements.verification_code.value = "";
            setStatus(section === "farmers" ? "Account verified. Select the farmer to test login." : "Account verified. You can now sign in.");
        } else {
            setStatus("Verification failed. Check the phone number and code.", true);
        }
    });

    handle("recover-form", async (form, values) => {
        access = null;
        refresh = null;
        const generation = ++sessionGeneration;
        await request("/api/farmers/recover/", "POST", values, false, () => generation === sessionGeneration);
        if (generation !== sessionGeneration) {
            throw new Error("Farmer selection changed; the recovery result was discarded.");
        }
        form.elements.verification_code.value = "";
        show({detail: "Account recovery succeeded."});
        setStatus("Account recovery succeeded. Select a farmer to manage their records.");
    });

    handle("document-list-form", async (form, values) => {
        const result = await api("document-requests/", "POST", values, false);
        form.elements.password.value = "";
        show(result);
        setStatus("Document requests loaded. See results below.");
    });

    handle("document-submit-form", async (form, values) => {
        const {request_id, ...payload} = values;
        const result = await api(`document-requests/${request_id}/submit/`, "POST", payload, false);
        form.elements.password.value = "";
        show(result);
        setStatus("Document submitted.");
    });

    handle("login-form", async (form, values) => {
        if (section === "farmers" && !selectedFarmer) throw new Error("Select a farmer first.");
        access = null;
        refresh = null;
        const generation = ++sessionGeneration;
        let result;
        try {
            result = await request(`/api/${section}/login/`, "POST", values, false, () => generation === sessionGeneration);
        } finally {
            if (section === "farmers" && generation === sessionGeneration) form.elements.password.value = "";
        }
        if (generation !== sessionGeneration) {
            throw new Error("Farmer selection changed; the login result was discarded.");
        }
        if (section === "farmers") {
            show({detail: "Farmer login succeeded."});
            setStatus(`Login succeeded for ${values.username}.`);
        } else {
            access = result.access;
            refresh = result.refresh;
            form.elements.password.value = "";
            show({detail: "Signed in."});
            setStatus(`Signed in as ${values.username}.`);
        }
    });

    if (section !== "farmers") {
        handleButton("refresh-token", async () => {
            if (!refresh) throw new Error("Sign in first.");
            const result = await api("token/refresh/", "POST", {refresh}, false);
            access = result.access;
            refresh = result.refresh;
            show({detail: "Session refreshed."});
            setStatus("Session refreshed.");
        });

        handleButton("logout", async () => {
            if (!refresh) throw new Error("Sign in first.");
            await api("logout/", "POST", {refresh});
            access = null;
            refresh = null;
            show({detail: "Signed out."});
            setStatus("Signed out.");
        });
    }

    handle("profile-form", async (form, values) => {
        const data = nonempty(values);
        if (!Object.keys(data).length) throw new Error("Enter at least one profile change.");
        const result = await api("me/", "PATCH", data);
        if (section === "farmers" && data.username) {
            for (const id of ["document-list-form", "document-submit-form"]) {
                const username = document.getElementById(id).elements.username;
                if (username.value === selectedFarmer.username) username.value = result.username;
            }
            selectedFarmer.username = result.username;
            document.getElementById("login-form").elements.username.value = result.username;
            document.getElementById("selected-farmer").textContent = `Selected: ${result.username} (ID ${selectedFarmer.user_id}).`;
        }
        if (data.new_password && section !== "farmers") {
            access = null;
            refresh = null;
            form.elements.new_password.value = "";
            setStatus("Password changed. Sign in again.");
        } else {
            form.elements.new_password.value = "";
            setStatus("Profile updated.");
        }
        show(result);
    });

    handle("farm-form", async (form, values, submitter) => {
        const {farm_id, farm_size_hectares, replace_address, ...addressFields} = values;
        const updating = submitter && submitter.dataset.action === "update";
        if (updating && !farm_id) throw new Error("Enter the farm ID to update.");
        if (!updating && farm_id) {
            await api("farms/", "POST", {farm_id});
            throw new Error("Farm IDs are assigned automatically. Clear the ID to add a farm.");
        }
        const payload = {};
        if (!updating && !farm_size_hectares) throw new Error("Enter the farm size in hectares.");
        if (farm_size_hectares !== "") payload.farm_size_hectares = farm_size_hectares;
        if (!updating || replace_address) {
            if (!addressFields.gps_coordinates) throw new Error("Place and confirm the farm address pin.");
            payload.address = nonempty(addressFields);
        }
        if (!Object.keys(payload).length) throw new Error("Enter at least one farm field.");
        show(await api(updating ? `farms/${farm_id}/` : "farms/", updating ? "PATCH" : "POST", payload));
        setStatus(updating ? "Farm updated." : "Farm created.");
        const formStatus = form.querySelector("[data-form-status]");
        formStatus.textContent = updating ? "Farm updated." : "Farm created.";
        formStatus.classList.remove("error");
        if (await loadFarmerCollection("farms") === false) {
            setStatus("Farm saved, but the farm list could not be refreshed.", true);
            formStatus.textContent = "Farm saved, but the farm list could not be refreshed.";
            formStatus.classList.add("error");
        }
    });

    handle("listing-expense-form", async (form, values) => {
        const {listing_id, ...payload} = values;
        show(await api(`listings/${listing_id}/expenses/`, "POST", payload));
        form.elements.tag.value = "";
        form.elements.amount.value = "";
        const formStatus = form.querySelector("[data-form-status]");
        formStatus.textContent = "Expense added.";
        formStatus.classList.remove("error");
        setStatus("Expense added.");
    });

    handleButton("view-listing-expenses", async () => {
        const listingId = document.getElementById("listing-expense-form").elements.listing_id.value;
        if (!/^[1-9]\d*$/.test(listingId)) throw new Error("Enter a valid listing ID.");
        show(await api(`listings/${listingId}/expenses/`));
        setStatus("Listing expenses loaded. See results below.");
    });

    handleButton("load-listing-calendar", async () => {
        const form = document.getElementById("listing-calendar-form");
        const listingId = form.elements.listing_id.value;
        if (!/^[1-9]\d*$/.test(listingId)) {
            form.querySelector("[data-form-status]").textContent = "Enter a valid listing ID.";
            throw new Error("Enter a valid listing ID.");
        }
        invalidateCalendar(form);
        const generation = calendarGeneration;
        const formStatus = form.querySelector("[data-form-status]");
        formStatus.textContent = "Loading schedule...";
        try {
            const data = await api(`listings/${listingId}/calendar/`, "GET", null, true,
                () => generation === calendarGeneration && form.elements.listing_id.value === listingId, false);
            if (!data || typeof data !== "object" || calendarFields.some((field) => !Object.hasOwn(data, field))) {
                throw new Error("The server returned an incomplete schedule.");
            }
            loadedCalendarValues = {};
            for (const field of calendarFields) {
                const value = data[field] === null ? "" : String(data[field]);
                form.elements[field].value = value;
                form.elements[field].disabled = false;
                loadedCalendarValues[field] = value;
            }
            loadedCalendarListing = listingId;
            formStatus.textContent = "Schedule loaded. Edit the fields and save.";
            formStatus.classList.remove("error");
            setStatus("Schedule loaded.");
        } catch (error) {
            if (generation !== calendarGeneration) return;
            formStatus.textContent = `Could not load schedule. ${error.message}`;
            formStatus.classList.add("error");
            throw error;
        }
    });

    handle("listing-calendar-form", async (form, values) => {
        const {listing_id, ...fields} = values;
        if (listing_id !== loadedCalendarListing) throw new Error("Load this listing's schedule before saving.");
        const generation = calendarGeneration;
        const payload = Object.fromEntries(calendarFields
            .filter((field) => fields[field] !== loadedCalendarValues[field])
            .map((field) => [field, fields[field] || null]));
        if (!Object.keys(payload).length) throw new Error("Change at least one schedule field before saving.");
        const result = await api(`listings/${listing_id}/calendar/`, "PATCH", payload);
        show(result);
        if (generation === calendarGeneration && form.elements.listing_id.value === listing_id) {
            loadedCalendarValues = Object.fromEntries(calendarFields.map((field) =>
                [field, result[field] === null ? "" : String(result[field])]));
            form.querySelector("[data-form-status]").textContent = "Schedule saved.";
            form.querySelector("[data-form-status]").classList.remove("error");
        }
        setStatus("Schedule saved.");
    });

    handle("farmer-listing-form", async (form, values) => {
        const payload = nonempty(values);
        const id = payload.listing_id;
        delete payload.listing_id;
        if (id && (payload.farm_id || payload.crop_type_id || payload.crop_id)) {
            throw new Error("Listing ID is for updates. To create a listing, clear Listing ID; it is assigned automatically.");
        }
        if (payload.is_active !== undefined) payload.is_active = payload.is_active === "true";
        if (!Object.keys(payload).length) throw new Error("Enter at least one listing field.");
        const result = await api(id ? `listings/${id}/` : "listings/", id ? "PATCH" : "POST", payload);
        show(result);
        const message = `${id ? "Listing updated" : "Listing created"}: listing ID ${result.listing_id}, crop ID ${result.crop_id}.`;
        setStatus(message);
        const formStatus = form.querySelector("[data-form-status]");
        formStatus.textContent = message;
        formStatus.classList.remove("error");
        document.getElementById("listing-expense-form").elements.listing_id.value = result.listing_id;
        selectCalendarListing(result.listing_id);
        const refreshes = [loadFarmerCollection("listings")];
        if (!document.getElementById("farmer-crops").hidden) {
            refreshes.push(loadFarmerCollection("crops"));
        }
        if ((await Promise.all(refreshes)).includes(false)) {
            setStatus("Listing saved, but some lists could not be refreshed.", true);
            formStatus.textContent = `${message} Some lists could not be refreshed.`;
            formStatus.classList.add("error");
        }
    });
    if (selectedFarmer) {
        const form = document.getElementById("farmer-listing-form");
        form.querySelector("[data-form-status]").textContent = "";
        form.querySelector("button[type=submit]").disabled = false;
    }

    handle("farmer-message-form", async (form, values) => {
        show(await api("farmer-messages/", "POST", values));
        form.elements.body.value = "";
        setStatus("Message sent.");
    });

    root.querySelectorAll("[data-get]").forEach((button) => {
        button.addEventListener("click", async () => {
            try {
                show(await api(button.dataset.get));
                setStatus("Records loaded. See results below.");
            } catch (error) {
                setStatus(error.message, true);
            }
        });
    });

    handle("order-form", async (form, values) => {
        const payload = nonempty(values);
        show(await api("orders/", "POST", payload));
        setStatus("Order reserved. See results below.");
    });

    handle("cancel-form", async (form, values) => {
        show(await api(`orders/${values.order_id}/cancel/`, "POST", {}));
        setStatus("Order cancelled.");
    });

    handle("vehicle-form", async (form, values) => {
        const payload = nonempty(values);
        const id = payload.vehicle_id;
        delete payload.vehicle_id;
        show(await api(id ? `vehicles/${id}/` : "vehicles/", id ? "PATCH" : "POST", payload));
        setStatus(id ? "Vehicle updated." : "Vehicle created.");
    });

    handle("vehicle-delete-form", async (form, values) => {
        await api(`vehicles/${values.vehicle_id}/`, "DELETE");
        show({detail: "Vehicle removed."});
        setStatus("Vehicle removed.");
    });

    handle("trip-form", async (form, values) => {
        const ids = values.order_ids.split(",").map((id) => id.trim());
        if (ids.some((id) => !/^[1-9]\d*$/.test(id))) {
            throw new Error("Enter positive order IDs separated by commas.");
        }
        const payload = {vehicle_id: values.vehicle_id, order_ids: ids.map(Number)};
        if (values.eta) payload.eta = new Date(values.eta).toISOString();
        show(await api("trips/", "POST", payload));
        setStatus("Trip created.");
    });

    handle("trip-status-form", async (form, values) => {
        show(await api(`trips/${values.trip_id}/`, "PATCH", {trip_status: Number(values.trip_status)}));
        setStatus("Trip updated.");
    });
})();
