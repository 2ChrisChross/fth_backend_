document.querySelectorAll("form[data-auto-filter] select").forEach((select) => {
    select.addEventListener("change", () => select.form.requestSubmit());
});
