document.addEventListener("DOMContentLoaded", () => {
    const shell = document.querySelector(".lab-shell");
    if (!shell) return;

    const links = [...document.querySelectorAll("[data-room]")];
    const panels = [...document.querySelectorAll("[data-room-panel]")];
    const openers = [...document.querySelectorAll("[data-open-room]")];
    const sidebar = document.querySelector(".lab-sidebar");
    const sidebarToggle = document.querySelector(".sidebar-toggle");

    const validRooms = new Set(panels.map((panel) => panel.dataset.roomPanel));

    function openRoom(room, options = {}) {
        if (!validRooms.has(room)) room = shell.dataset.defaultRoom || "hub";

        links.forEach((link) => link.classList.toggle("active", link.dataset.room === room));
        panels.forEach((panel) => panel.classList.toggle("active", panel.dataset.roomPanel === room));

        if (options.updateHash !== false) {
            history.replaceState(null, "", `#${room}`);
        }
        sessionStorage.setItem("zero-rnd-room", room);

        if (options.scroll !== false) {
            document.querySelector(".lab-stage")?.scrollIntoView({ behavior: "smooth", block: "start" });
        }
    }

    links.forEach((link) => link.addEventListener("click", () => openRoom(link.dataset.room)));
    openers.forEach((button) => button.addEventListener("click", () => openRoom(button.dataset.openRoom)));

    sidebarToggle?.addEventListener("click", () => {
        sidebar?.classList.toggle("collapsed");
    });

    const projectSearch = document.getElementById("project-search");
    projectSearch?.addEventListener("input", () => {
        const query = projectSearch.value.trim().toLowerCase();
        document.querySelectorAll("[data-project-name]").forEach((card) => {
            card.hidden = Boolean(query) && !card.dataset.projectName.includes(query);
        });
    });

    document.querySelectorAll("[data-project-target]").forEach((button) => {
        button.addEventListener("click", () => {
            openRoom("projects", { scroll: false });
            requestAnimationFrame(() => {
                const target = document.getElementById(`project-${button.dataset.projectTarget}`);
                target?.scrollIntoView({ behavior: "smooth", block: "center" });
                target?.classList.add("highlight");
                setTimeout(() => target?.classList.remove("highlight"), 1400);
            });
        });
    });

    const hashRoom = window.location.hash.replace("#", "");
    const storedRoom = sessionStorage.getItem("zero-rnd-room");
    openRoom(validRooms.has(hashRoom) ? hashRoom : (validRooms.has(storedRoom) ? storedRoom : "hub"), {
        updateHash: false,
        scroll: false,
    });

    window.addEventListener("hashchange", () => {
        const room = window.location.hash.replace("#", "");
        if (validRooms.has(room)) openRoom(room, { updateHash: false, scroll: false });
    });
});
