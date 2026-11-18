document.querySelectorAll("form[data-auto-filter] select").forEach((select) => {
    select.addEventListener("change", () => {
        if (select.name === "province" || select.name === "municipality") {
            const dependents = select.name === "province"
                ? ["municipality", "barangay"]
                : ["barangay"];
            dependents.forEach((name) => {
                const field = select.form.elements.namedItem(name);
                if (field) field.value = "";
            });
        }
        select.form.requestSubmit();
    });
});
