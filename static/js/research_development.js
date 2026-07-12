document.addEventListener("DOMContentLoaded", () => {
    const tabs = document.querySelectorAll(".rnd-tab");
    const panels = document.querySelectorAll(".rnd-tab-panel");

    tabs.forEach((tab) => {
        tab.addEventListener("click", () => {
            const target = tab.dataset.tab;

            tabs.forEach((item) => item.classList.remove("active"));
            panels.forEach((panel) => panel.classList.remove("active"));

            tab.classList.add("active");

            const targetPanel = document.getElementById(target);
            if (targetPanel) {
                targetPanel.classList.add("active");
            }
        });
    });
});
