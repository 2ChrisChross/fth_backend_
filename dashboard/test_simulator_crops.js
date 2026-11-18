const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

class Element {
    constructor() {
        this.children = [];
        this.dataset = {};
        this.listeners = {};
        this.value = "";
        this.hidden = false;
        this.classList = {add() {}, remove() {}, toggle() {}};
    }

    set textContent(value) {
        this.text = value;
        this.children = [];
    }
    get textContent() {
        return (this.text || "") + this.children.map((child) => child.textContent).join("");
    }
    appendChild(child) { this.children.push(child); }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.text = ""; this.children = children; }
    setAttribute() {}
    focus() {}
    closest() { return {open: true}; }
    addEventListener(type, listener) { this.listeners[type] = listener; }
    async trigger(type, event = {}) {
        await this.listeners[type]({preventDefault() {}, ...event});
    }
}

function setup() {
    const elements = {};
    const state = {crops: [], failCrops: false, listingError: null, malformedCalendar: false, requests: []};
    function element(id) {
        return (elements[id] = new Element());
    }
    function form(id, values) {
        const node = element(id);
        node.elements = Object.fromEntries(
            Object.entries(values).map(([name, value]) => {
                const input = new Element();
                input.value = value;
                return [name, input];
            })
        );
        node.formStatus = new Element();
        node.submitButton = new Element();
        node.querySelector = (selector) => selector === "[data-form-status]"
            ? node.formStatus : selector === "button[type=submit]" ? node.submitButton : null;
        node.querySelectorAll = () => [];
        node.reset = () => Object.values(node.elements).forEach((input) => { input.value = ""; });
        return node;
    }

    const root = element("simulator");
    root.dataset = {
        section: "farmers", farmerId: "1", farmerUsername: "test",
        farmerApiUrl: "/sim/api/me/",
    };
    root.querySelector = () => ({value: "csrf"});
    root.querySelectorAll = () => [];
    for (const id of ["sim-status", "sim-results", "farmer-farms", "farmer-listings",
        "farmer-crops", "refresh-crops", "refresh-farms", "refresh-listings",
        "load-listing-calendar"]) element(id);
    elements["farmer-crops"].hidden = true;
    const listing = form("farmer-listing-form", {
        listing_id: "", crop_id: "", farm_id: "1", crop_type_id: "2",
        batch_number: "", title: "Tomatoes", available_stock_kg: "5",
        price_per_kg: "10", is_active: "true",
    });
    form("listing-expense-form", {listing_id: "", tag: "", amount: ""});
    form("listing-calendar-form", {
        listing_id: "", land_preparation_start: "", land_preparation_end: "",
        planting_start: "", planting_end: "", harvesting_start: "", harvesting_end: "",
        packing_duration_days: "", expected_quantity_kg: "", actual_harvested_kg: "",
        preorder_lead_time_days: "", delivery_date: "",
    });
    form("farm-form", {farm_id: ""});

    const document = {
        getElementById: (id) => elements[id] || null,
        createElement: () => new Element(),
        createTextNode: (text) => { const node = new Element(); node.textContent = text; return node; },
    };
    class FormData {
        constructor(node) { this.node = node; }
        entries() {
            return Object.entries(this.node.elements)
                .filter(([, input]) => !input.disabled)
                .map(([name, input]) => [name, input.value])[Symbol.iterator]();
        }
    }
    async function fetch(url, options) {
        state.requests.push([url, options.method, options.body && JSON.parse(options.body)]);
        let payload = [];
        let status = 200;
        if (url.endsWith("crops/")) {
            if (state.failCrops) { status = 503; payload = {detail: "Unavailable"}; }
            else payload = state.crops;
        } else if (url.endsWith("listings/") && options.method === "POST") {
            if (state.listingError) {
                payload = state.listingError;
                status = 400;
            } else {
                const crop = {
                    crop_id: 7, farm_id: 1, crop_type_id: 2, crop_name: "Tomato",
                    price_per_kg: "10.00",
                };
                state.crops.push(crop);
                payload = {...crop, listing_id: 9};
                status = 201;
            }
        } else if (url.endsWith("listings/9/expenses/") && options.method === "POST") {
            payload = {expense_id: 1, ...JSON.parse(options.body)};
            status = 201;
        } else if (url.endsWith("listings/9/calendar/")) {
            payload = {
                calendar_id: 5, land_preparation_start: null, land_preparation_end: null,
                planting_start: "2027-01-01", planting_end: null,
                harvesting_start: null, harvesting_end: null, packing_duration_days: null,
                expected_quantity_kg: null, actual_harvested_kg: null,
                preorder_lead_time_days: null, delivery_date: null,
                ...(options.body ? JSON.parse(options.body) : {}),
            };
            if (state.malformedCalendar) delete payload.planting_end;
        }
        return {ok: status < 400, status, text: async () => JSON.stringify(payload)};
    }
    const source = fs.readFileSync(path.join(__dirname, "static", "dashboard", "simulator.js"), "utf8");
    vm.runInNewContext(source, {document, FormData, fetch, window: {}, URLSearchParams});
    return {elements, listing, state};
}

test("My crops displays records in the panel and refreshes after saving", async () => {
    const {elements, listing, state} = setup();
    await elements["refresh-crops"].trigger("click");
    assert.equal(elements["farmer-crops"].hidden, false);
    assert.match(elements["farmer-crops"].textContent, /No crops found/);

    await listing.trigger("submit");
    assert.match(elements["farmer-crops"].textContent, /Tomato/);
    assert.match(listing.formStatus.textContent, /listing ID 9, crop ID 7/);
    assert.equal(elements["listing-expense-form"].elements.listing_id.value, 9);
    assert.equal(state.requests.filter(([url]) => url.endsWith("crops/")).length, 2);
    const cropCard = elements["farmer-crops"].children[0];
    const useCrop = cropCard.children.find((child) => child.textContent === "Use crop");
    await useCrop.trigger("click");
    assert.equal(listing.elements.crop_id.value, 7);
    assert.equal(elements["listing-expense-form"].elements.listing_id.value, 9);
});

test("listing validation errors are displayed beside the save button", async () => {
    const {listing, state} = setup();
    state.listingError = {crop_type_id: ["Invalid crop type."]};
    await listing.trigger("submit");
    assert.match(listing.formStatus.textContent, /crop type id: Invalid crop type/);
    assert.equal(state.crops.length, 0);
});

test("a listing ID with new crop fields gives a clear error without saving", async () => {
    const {listing, state} = setup();
    listing.elements.listing_id.value = "1";
    await listing.trigger("submit");
    assert.match(listing.formStatus.textContent, /clear Listing ID/);
    assert.equal(state.requests.filter(([, method]) => method === "POST").length, 0);
});

test("expenses are submitted for the selected listing", async () => {
    const {elements, listing, state} = setup();
    await listing.trigger("submit");
    const expense = elements["listing-expense-form"];
    expense.elements.tag.value = "Fuel";
    expense.elements.amount.value = "12.50";
    await expense.trigger("submit");
    const request = state.requests.find(([url]) => url.endsWith("listings/9/expenses/"));
    assert.equal(request[1], "POST");
    assert.equal(request[2].tag, "Fuel");
    assert.equal(request[2].amount, "12.50");
    assert.equal(expense.formStatus.textContent, "Expense added.");
});

test("schedules must be loaded for the selected listing before saving", async () => {
    const {elements, listing, state} = setup();
    await listing.trigger("submit");
    const calendar = elements["listing-calendar-form"];
    await calendar.trigger("submit");
    assert.match(calendar.formStatus.textContent, /Load this listing/);
    await elements["load-listing-calendar"].trigger("click");
    assert.equal(calendar.elements.planting_start.value, "2027-01-01");
    calendar.elements.planting_start.value = "";
    calendar.elements.packing_duration_days.value = "3";
    await calendar.trigger("submit");
    const request = state.requests.find(([url, method]) => url.endsWith("listings/9/calendar/") && method === "PATCH");
    assert.equal(request[2].planting_start, null);
    assert.equal(request[2].packing_duration_days, "3");
    assert.equal(calendar.formStatus.textContent, "Schedule saved.");
    calendar.elements.listing_id.value = "10";
    await calendar.elements.listing_id.trigger("input");
    await calendar.trigger("submit");
    assert.match(calendar.formStatus.textContent, /Load this listing/);
    assert.equal(state.requests.filter(([, method]) => method === "PATCH").length, 1);
});

test("incomplete schedule responses cannot be saved", async () => {
    const {elements, listing, state} = setup();
    await listing.trigger("submit");
    const calendar = elements["listing-calendar-form"];
    state.malformedCalendar = true;
    await elements["load-listing-calendar"].trigger("click");
    assert.match(calendar.formStatus.textContent, /incomplete schedule/);
    assert.equal(calendar.elements.planting_start.disabled, true);
    await calendar.trigger("submit");
    assert.match(calendar.formStatus.textContent, /Load this listing/);
});

test("My crops shows loading failures and can retry", async () => {
    const {elements, state} = setup();
    state.failCrops = true;
    await elements["refresh-crops"].trigger("click");
    assert.match(elements["farmer-crops"].textContent, /Could not load crops/);
    assert.match(elements["sim-status"].textContent, /Could not load crops/);
    state.failCrops = false;
    state.crops.push({crop_id: 1, crop_name: "Rice"});
    await elements["refresh-crops"].trigger("click");
    assert.match(elements["farmer-crops"].textContent, /Rice/);
});
