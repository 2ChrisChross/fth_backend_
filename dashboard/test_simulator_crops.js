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
    const state = {crops: [], failCrops: false, requests: []};
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
        node.querySelector = () => null;
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
        "farmer-crops", "refresh-crops", "refresh-farms", "refresh-listings"]) element(id);
    elements["farmer-crops"].hidden = true;
    const listing = form("farmer-listing-form", {
        listing_id: "", crop_id: "", farm_id: "1", crop_type_id: "2",
        batch_number: "", title: "Tomatoes", available_stock_kg: "5",
        price_per_kg: "10", is_active: "true",
    });
    form("crop-expense-form", {crop_id: "", tag: "", amount: ""});
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
        state.requests.push([url, options.method]);
        let payload = [];
        let status = 200;
        if (url.endsWith("crops/")) {
            if (state.failCrops) { status = 503; payload = {detail: "Unavailable"}; }
            else payload = state.crops;
        } else if (url.endsWith("listings/") && options.method === "POST") {
            const crop = {
                crop_id: 7, farm_id: 1, crop_type_id: 2, crop_name: "Tomato",
                price_per_kg: "10.00",
            };
            state.crops.push(crop);
            payload = {...crop, listing_id: 9};
            status = 201;
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
    assert.equal(state.requests.filter(([url]) => url.endsWith("crops/")).length, 2);
    const cropCard = elements["farmer-crops"].children[0];
    const useCrop = cropCard.children.find((child) => child.textContent === "Use crop");
    await useCrop.trigger("click");
    assert.equal(listing.elements.crop_id.value, 7);
    assert.equal(elements["crop-expense-form"].elements.crop_id.value, 7);
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
