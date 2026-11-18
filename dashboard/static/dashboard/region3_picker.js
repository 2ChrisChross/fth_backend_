(() => {
    "use strict";

    const root = document.getElementById("simulator");
    const pickers = Array.from(root.querySelectorAll(".region3-picker"));
    if (!pickers.length) return;

    const tileUrl = new URL(root.dataset.tileUrl, location.href).href.replace(/0\/0\/0\.pbf$/, "{z}/{x}/{y}.pbf");
    const glyphUrl = new URL(root.dataset.glyphUrl, location.href).href.replace("FONTSTACK", "{fontstack}").replace("RANGE", "{range}");
    const style = {
        version: 8,
        glyphs: glyphUrl,
        sources: {
            local: {type: "vector", tiles: [tileUrl], minzoom: 0, maxzoom: 14},
        },
        layers: [
            {id: "background", type: "background", paint: {"background-color": "#f0eee3"}},
            {id: "ocean", type: "fill", source: "local", "source-layer": "ocean", paint: {"fill-color": "#b6dce9"}},
            {id: "water", type: "fill", source: "local", "source-layer": "water_polygons", paint: {"fill-color": "#b6dce9"}},
            {id: "land", type: "fill", source: "local", "source-layer": "land", paint: {"fill-color": "#d9e8cf"}},
            {id: "buildings", type: "fill", source: "local", "source-layer": "buildings", paint: {"fill-color": "#c8c0b3"}},
            {id: "roads", type: "line", source: "local", "source-layer": "streets", paint: {"line-color": "#ffffff", "line-width": ["interpolate", ["linear"], ["zoom"], 8, 0.6, 15, 3]}},
            {id: "road-labels", type: "symbol", source: "local", "source-layer": "street_labels", minzoom: 12, layout: {"symbol-placement": "line", "text-field": ["coalesce", ["get", "name"], ""], "text-font": ["Open Sans Regular"], "text-size": 11}, paint: {"text-color": "#504e49", "text-halo-color": "#ffffff", "text-halo-width": 1}},
            {id: "places", type: "symbol", source: "local", "source-layer": "place_labels", layout: {"text-field": ["coalesce", ["get", "name"], ""], "text-font": ["Open Sans Regular"], "text-size": 12}, paint: {"text-color": "#333333", "text-halo-color": "#ffffff", "text-halo-width": 1}},
        ],
    };

    function setupPicker(element, provinces) {
        const prefix = element.dataset.prefix;
        const form = element.closest("form");
        const province = form.elements[`${prefix}province`];
        const city = form.elements[`${prefix}municipality_city`];
        const barangay = form.elements[`${prefix}barangay`];
        const confirmed = form.elements[`${prefix}gps_coordinates`];
        const latitude = element.querySelector("[data-latitude]");
        const longitude = element.querySelector("[data-longitude]");
        const status = element.querySelector("[data-pin-status]");
        const mapStatus = element.querySelector("[data-map-status]");
        const map = new maplibregl.Map({
            container: element.querySelector(".region3-map"),
            style,
            center: [120.75, 15.4],
            zoom: 7,
            maxZoom: 19,
        });
        map.addControl(new maplibregl.NavigationControl());
        const marker = new maplibregl.Marker({draggable: true});
        let markerPlaced = false;
        let lookupGeneration = 0;
        let lookupTimer;

        function clearPin() {
            lookupGeneration += 1;
            clearTimeout(lookupTimer);
            confirmed.value = "";
            status.textContent = "No pin confirmed.";
            status.classList.remove("error");
        }
        function positionMarker(lat, lng) {
            marker.setLngLat([lng, lat]);
            if (!markerPlaced) {
                marker.addTo(map);
                markerPlaced = true;
            }
        }
        function options(select, label, entries) {
            select.replaceChildren(new Option(label, ""));
            entries.forEach((entry) => select.add(new Option(
                entry.name + (entry.independent ? " (independent city)" : ""),
                entry.name,
            )));
        }
        function selectedProvince() {
            return provinces.find((item) => item.name === province.value);
        }
        function selectedCity() {
            return selectedProvince()?.cities.find((item) => item.name === city.value);
        }
        function clearLocation() {
            province.value = "";
            options(city, "Select municipality or city", []);
            options(barangay, "Select barangay", []);
        }
        async function lookupPoint() {
            const lat = Number(latitude.value);
            const lng = Number(longitude.value);
            if (!latitude.value || !longitude.value || !Number.isFinite(lat) || !Number.isFinite(lng) ||
                lat < -90 || lat > 90 || lng < -180 || lng > 180) {
                status.textContent = "⚠ Click the map or enter a valid latitude and longitude.";
                status.classList.add("error");
                return false;
            }
            const generation = ++lookupGeneration;
            confirmed.value = "";
            status.classList.remove("error");
            status.textContent = "Checking the pin against local boundaries...";
            try {
                const response = await fetch(root.dataset.lookupUrl, {
                    method: "POST",
                    credentials: "same-origin",
                    headers: {"Content-Type": "application/json", "X-CSRFToken": root.querySelector("[name=csrfmiddlewaretoken]").value},
                    body: JSON.stringify({latitude: Number(lat.toFixed(7)), longitude: Number(lng.toFixed(7))}),
                });
                if (!response.ok) throw new Error(`Local boundary lookup failed (HTTP ${response.status}).`);
                const result = await response.json();
                if (generation !== lookupGeneration) return false;
                if (result.status !== "matched") {
                    const message = result.status === "outside"
                        ? "This pin is outside Region III. Choose another location."
                        : "The barangay cannot be determined reliably here. Move the pin away from the boundary.";
                    status.textContent = `⚠ ${message}`;
                    status.classList.add("error");
                    return false;
                }
                province.value = result.province;
                options(city, "Select municipality or city", selectedProvince()?.cities || []);
                city.value = result.municipality_city;
                options(barangay, "Select barangay", selectedCity()?.barangays || []);
                barangay.value = result.barangay;
                if (!province.value || !city.value || !barangay.value) {
                    throw new Error("The boundary lookup returned an unknown locality.");
                }
                status.textContent = "Pin is within Region III. Check the approximate locality and confirm the pin.";
                return true;
            } catch (error) {
                if (generation === lookupGeneration) {
                    status.textContent = `⚠ ${error.message}`;
                    status.classList.add("error");
                }
                return false;
            }
        }
        function setPoint(lat, lng) {
            clearPin();
            clearLocation();
            latitude.value = lat.toFixed(7);
            longitude.value = lng.toFixed(7);
            positionMarker(lat, lng);
            lookupPoint();
        }
        function resetPosition() {
            clearPin();
            latitude.value = "";
            longitude.value = "";
            if (markerPlaced) marker.remove();
            markerPlaced = false;
        }
        province.addEventListener("change", () => {
            options(city, "Select municipality or city", selectedProvince()?.cities || []);
            options(barangay, "Select barangay", []);
            resetPosition();
        });
        city.addEventListener("change", () => {
            options(barangay, "Select barangay", selectedCity()?.barangays || []);
            resetPosition();
            const center = selectedCity()?.center;
            if (center) map.flyTo({center: [center[1], center[0]], zoom: 12});
        });
        barangay.addEventListener("change", () => {
            resetPosition();
            const center = selectedCity()?.barangays.find((item) => item.name === barangay.value)?.center;
            if (center) map.flyTo({center: [center[1], center[0]], zoom: 15});
        });
        function onCoordinateInput() {
            clearPin();
            clearLocation();
            if (markerPlaced) marker.remove();
            markerPlaced = false;
            if (latitude.value && longitude.value) lookupTimer = setTimeout(lookupPoint, 400);
        }
        latitude.addEventListener("input", onCoordinateInput);
        longitude.addEventListener("input", onCoordinateInput);
        map.on("click", (event) => setPoint(event.lngLat.lat, event.lngLat.lng));
        marker.on("dragend", () => {
            const point = marker.getLngLat();
            setPoint(point.lat, point.lng);
        });
        map.on("load", () => {
            if (!mapStatus.classList.contains("error")) mapStatus.textContent = "Local map loaded.";
        });
        map.on("error", (event) => {
            mapStatus.textContent = `Map error: ${event.error?.message || "Map data could not be loaded."} Check the local map setup in README.`;
            mapStatus.classList.add("error");
        });
        element.querySelector("[data-confirm-pin]").addEventListener("click", async () => {
            clearTimeout(lookupTimer);
            const lat = Number(latitude.value);
            const lng = Number(longitude.value);
            if (!await lookupPoint()) return;
            positionMarker(lat, lng);
            map.flyTo({center: [lng, lat], zoom: Math.max(map.getZoom(), 15)});
            confirmed.value = `${lat.toFixed(7)}, ${lng.toFixed(7)}`;
            status.classList.remove("error");
            status.textContent = `Pin confirmed: ${confirmed.value}.`;
        });
        options(province, "Select province", provinces);
        element.closest("details")?.addEventListener("toggle", () => map.resize());
        window.addEventListener("resize", () => map.resize());
        return {
            fillTest() {
                province.value = provinces[0].name;
                province.dispatchEvent(new Event("change"));
                city.value = provinces[0].cities[0].name;
                city.dispatchEvent(new Event("change"));
                barangay.value = provinces[0].cities[0].barangays[0].name;
                barangay.dispatchEvent(new Event("change"));
            },
        };
    }

    window.region3Ready = (async () => {
        const response = await fetch(root.dataset.locationsUrl, {credentials: "same-origin"});
        if (!response.ok) throw new Error("Region III locality data could not be loaded.");
        const data = await response.json();
        if (typeof maplibregl === "undefined") throw new Error("Map renderer missing. Run npm install and restart the server.");
        const tileCheck = await fetch(root.dataset.tileUrl, {credentials: "same-origin"});
        if (!tileCheck.ok) throw new Error("Local map tiles are missing or unavailable. See README for setup.");
        const instances = pickers.map((element) => ({element, picker: setupPicker(element, data.provinces)}));
        return {
            fillTest(form) {
                instances.filter((item) => item.element.closest("form") === form)
                    .forEach((item) => item.picker.fillTest());
            },
        };
    })().catch((error) => {
        pickers.forEach((element) => {
            const status = element.querySelector("[data-map-status]");
            status.textContent = error.message;
            status.classList.add("error");
        });
        return null;
    });
})();
