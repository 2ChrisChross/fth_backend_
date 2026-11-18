(() => {
    const table = document.querySelector("[data-column-table]");
    if (!table) return;

    const menu = document.getElementById("column-menu");
    const menuButton = document.querySelector("[data-column-menu-button]");
    const options = menu.querySelector("[data-column-options]");
    const warning = menu.querySelector("[data-column-warning]");
    const headers = Array.from(table.querySelectorAll("thead th[data-column]"));
    const minWidth = 80;
    const maxWidth = 10000;
    const storageKey = `dashboard.columns.${table.dataset.columnTable}`;
    const columns = headers.map((header) => ({
        key: header.dataset.column,
        label: header.textContent.trim(),
        defaultVisible: !header.hidden,
        defaultWidth: Math.min(
            maxWidth, Math.max(minWidth, Math.round(header.getBoundingClientRect().width) || 180)
        ),
        header,
        cells: Array.from(table.querySelectorAll(`tbody td[data-column="${header.dataset.column}"]`)),
    }));

    const warn = (message) => {
        warning.textContent = message;
        warning.hidden = false;
    };
    let saved = null;
    try {
        const raw = sessionStorage.getItem(storageKey);
        if (raw) saved = JSON.parse(raw);
    } catch (error) {
        warn("Column preferences could not be loaded; defaults are being used.");
    }

    const knownKeys = new Set(columns.map((column) => column.key));
    const visible = saved && Array.isArray(saved.visible)
        ? saved.visible.filter((key) => knownKeys.has(key))
        : columns.filter((column) => column.defaultVisible).map((column) => column.key);
    if (!visible.length) {
        visible.push(...columns.filter((column) => column.defaultVisible).map((column) => column.key));
    }
    const savedWidths = saved && saved.widths && typeof saved.widths === "object"
        ? saved.widths : {};

    const colgroup = document.createElement("colgroup");
    table.insertBefore(colgroup, table.firstChild);
    columns.forEach((column) => {
        column.visible = visible.includes(column.key);
        const width = savedWidths[column.key];
        column.width = typeof width === "number" && Number.isFinite(width)
            ? Math.min(maxWidth, Math.max(minWidth, width))
            : column.defaultWidth;
        column.col = document.createElement("col");
        colgroup.appendChild(column.col);

        const label = document.createElement("label");
        column.checkbox = document.createElement("input");
        column.checkbox.type = "checkbox";
        label.append(column.checkbox, document.createTextNode(column.label));
        options.appendChild(label);

        column.handle = document.createElement("div");
        column.handle.className = "column-resize";
        column.handle.tabIndex = 0;
        column.handle.setAttribute("role", "separator");
        column.handle.setAttribute("aria-orientation", "vertical");
        column.handle.setAttribute("aria-label", `Resize ${column.label} column`);
        column.handle.setAttribute("aria-valuemin", minWidth);
        column.handle.setAttribute("aria-valuemax", maxWidth);
        column.header.appendChild(column.handle);
    });

    function render() {
        const visibleCount = columns.filter((column) => column.visible).length;
        let totalWidth = 0;
        columns.forEach((column) => {
            column.header.hidden = !column.visible;
            column.col.hidden = !column.visible;
            column.cells.forEach((cell) => { cell.hidden = !column.visible; });
            column.checkbox.checked = column.visible;
            column.checkbox.disabled = column.visible && visibleCount === 1;
            column.col.style.width = `${column.width}px`;
            if (column.visible) totalWidth += column.width;
        });
        table.style.width = `${totalWidth}px`;
        columns.filter((column) => column.visible).forEach((column) => {
            const actualWidth = Math.round(column.header.getBoundingClientRect().width);
            column.handle.setAttribute("aria-valuemax", Math.max(maxWidth, actualWidth));
            column.handle.setAttribute("aria-valuenow", actualWidth);
            column.handle.setAttribute("aria-valuetext", `${actualWidth} pixels`);
        });
    }

    function syncVisibleWidths() {
        columns.filter((column) => column.visible).forEach((column) => {
            column.width = Math.min(maxWidth, Math.max(minWidth, column.header.getBoundingClientRect().width));
        });
    }

    function save() {
        const state = {
            visible: columns.filter((column) => column.visible).map((column) => column.key),
            widths: Object.fromEntries(columns.map((column) => [column.key, column.width])),
        };
        try {
            sessionStorage.setItem(storageKey, JSON.stringify(state));
        } catch (error) {
            warn("Column preferences could not be saved in this tab.");
        }
    }

    columns.forEach((column) => {
        column.checkbox.addEventListener("change", () => {
            column.visible = column.checkbox.checked;
            render();
            save();
        });
        column.handle.addEventListener("pointerdown", (event) => {
            if (event.button !== 0) return;
            event.preventDefault();
            syncVisibleWidths();
            column.handle.setPointerCapture(event.pointerId);
            const startX = event.clientX;
            const startWidth = column.width;
            const move = (moveEvent) => {
                column.width = Math.min(maxWidth, Math.max(minWidth, startWidth + moveEvent.clientX - startX));
                render();
            };
            const end = () => {
                column.handle.removeEventListener("pointermove", move);
                column.handle.removeEventListener("pointerup", end);
                column.handle.removeEventListener("pointercancel", end);
                save();
            };
            column.handle.addEventListener("pointermove", move);
            column.handle.addEventListener("pointerup", end);
            column.handle.addEventListener("pointercancel", end);
        });
        column.handle.addEventListener("keydown", (event) => {
            if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
            event.preventDefault();
            syncVisibleWidths();
            const change = (event.shiftKey ? 40 : 10) * (event.key === "ArrowRight" ? 1 : -1);
            column.width = Math.min(maxWidth, Math.max(minWidth, column.width + change));
            render();
            save();
        });
    });

    function closeMenu() {
        menu.hidden = true;
        menuButton.setAttribute("aria-expanded", "false");
    }
    function openMenu(x, y) {
        menu.hidden = false;
        menuButton.setAttribute("aria-expanded", "true");
        const rect = menu.getBoundingClientRect();
        menu.style.left = `${Math.max(0, Math.min(x, window.innerWidth - rect.width))}px`;
        menu.style.top = `${Math.max(0, Math.min(y, window.innerHeight - rect.height))}px`;
    }
    menuButton.addEventListener("click", () => {
        if (!menu.hidden) {
            closeMenu();
            return;
        }
        const rect = menuButton.getBoundingClientRect();
        openMenu(rect.left, rect.bottom);
    });
    table.closest(".table-wrap").addEventListener("contextmenu", (event) => {
        if (event.target.closest("input, select, textarea, button")) return;
        event.preventDefault();
        openMenu(event.clientX, event.clientY);
    });
    document.addEventListener("click", (event) => {
        if (!menu.hidden && !menu.contains(event.target) && event.target !== menuButton) closeMenu();
    });
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && !menu.hidden) {
            closeMenu();
            menuButton.focus();
        }
    });
    menu.querySelector("[data-column-reset]").addEventListener("click", () => {
        columns.forEach((column) => {
            column.visible = column.defaultVisible;
            column.width = column.defaultWidth;
        });
        render();
        save();
    });
    window.addEventListener("resize", render);
    table.classList.add("columns-ready");
    menuButton.hidden = false;
    render();
})();
