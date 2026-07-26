// Operator Development - click-to-drill-down modal.
// Main stat -> domains -> sub-domains -> capabilities -> concepts,
// all inside one small modal instead of separate cluttered page
// sections. Data comes from the JSON embedded by the server in
// #operator-tree-data - no extra network requests needed.
(function () {
    var dataEl = document.getElementById("operator-tree-data");
    var modal = document.getElementById("operator-drilldown-modal");
    if (!dataEl || !modal) {
        return;
    }

    var payload = JSON.parse(dataEl.textContent);
    var tree = payload.tree || {};
    var conceptsByCapability = payload.concepts_by_capability || {};

    var breadcrumbEl = modal.querySelector(".drilldown-breadcrumb");
    var titleEl = modal.querySelector(".drilldown-title");
    var listEl = modal.querySelector(".drilldown-list");
    var backBtn = modal.querySelector(".drilldown-back");
    var closeBtn = modal.querySelector(".drilldown-close");

    // Each stack entry is {name, node} for a tree node, or
    // {name, concepts: [...]} once we've drilled into a capability's
    // concept list (concepts are the end of the line - no further click).
    var stack = [];

    function scoreLabel(node) {
        if (node.node_type === "skill") {
            return "Lv " + (node.level || 0) + " \u00b7 " + (node.xp || 0) + " XP";
        }
        return (node.average_level || 0).toFixed(2);
    }

    function clearList() {
        listEl.innerHTML = "";
    }

    function showEmpty(message) {
        var empty = document.createElement("p");
        empty.className = "drilldown-empty";
        empty.textContent = message;
        listEl.appendChild(empty);
    }

    function renderConcepts(concepts) {
        clearList();
        if (!concepts.length) {
            showEmpty("No concepts mapped for this capability yet.");
            return;
        }
        concepts.forEach(function (concept) {
            var row = document.createElement("div");
            row.className = "drilldown-row drilldown-leaf";
            var name = document.createElement("span");
            name.textContent = concept.name;
            var score = document.createElement("span");
            score.textContent = "Lv " + concept.level + " \u00b7 " + concept.xp + " XP";
            row.appendChild(name);
            row.appendChild(score);
            listEl.appendChild(row);
        });
    }

    function renderNode(node) {
        clearList();
        var children = node.children || {};
        var names = Object.keys(children);

        if (names.length) {
            names.forEach(function (childName) {
                var child = children[childName];
                var row = document.createElement("button");
                row.type = "button";
                row.className = "drilldown-row";
                var name = document.createElement("span");
                name.textContent = childName;
                var score = document.createElement("span");
                score.textContent = scoreLabel(child);
                row.appendChild(name);
                row.appendChild(score);
                row.addEventListener("click", function () {
                    stack.push({ name: childName, node: child });
                    renderCurrent();
                });
                listEl.appendChild(row);
            });
            return;
        }

        // No further tree children - this is a capability leaf. If it
        // has real concepts, drill into those instead of dead-ending.
        var concepts = node.competency_id ? conceptsByCapability[node.competency_id] : null;
        if (concepts) {
            stack.push({ name: "Concepts", concepts: concepts });
            renderCurrent();
            return;
        }
        showEmpty("Nothing tracked here yet.");
    }

    function renderCurrent() {
        var current = stack[stack.length - 1];
        titleEl.textContent = current.name;
        breadcrumbEl.textContent = stack.map(function (item) { return item.name; }).join(" \u203a ");
        backBtn.style.visibility = stack.length > 1 ? "visible" : "hidden";

        if (current.concepts) {
            renderConcepts(current.concepts);
        } else {
            renderNode(current.node);
        }
    }

    function openModal(statName) {
        var node = tree[statName];
        if (!node) {
            return;
        }
        stack = [{ name: statName, node: node }];
        modal.classList.add("is-open");
        modal.setAttribute("aria-hidden", "false");
        renderCurrent();
    }

    function closeModal() {
        modal.classList.remove("is-open");
        modal.setAttribute("aria-hidden", "true");
        stack = [];
    }

    document.querySelectorAll(".main-stat-row").forEach(function (row) {
        row.addEventListener("click", function () {
            openModal(row.dataset.stat);
        });
        row.addEventListener("keydown", function (event) {
            if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                openModal(row.dataset.stat);
            }
        });
    });

    backBtn.addEventListener("click", function () {
        if (stack.length > 1) {
            stack.pop();
            renderCurrent();
        }
    });

    closeBtn.addEventListener("click", closeModal);

    modal.addEventListener("click", function (event) {
        if (event.target === modal) {
            closeModal();
        }
    });

    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape" && modal.classList.contains("is-open")) {
            closeModal();
        }
    });
})();

// Simple static-content modals (Operator Hub, Explored Capabilities, Skill
// Tree) - these just toggle visibility of pre-rendered content, no data
// drilldown needed since the server already rendered everything inside.
(function () {
    document.querySelectorAll(".operator-summary-card[data-modal]").forEach(function (card) {
        var modal = document.getElementById(card.dataset.modal);
        if (!modal) {
            return;
        }
        card.addEventListener("click", function () {
            modal.classList.add("is-open");
            modal.setAttribute("aria-hidden", "false");
        });
    });

    document.querySelectorAll("[data-static-modal]").forEach(function (modal) {
        var closeBtn = modal.querySelector(".drilldown-close");
        function close() {
            modal.classList.remove("is-open");
            modal.setAttribute("aria-hidden", "true");
        }
        if (closeBtn) {
            closeBtn.addEventListener("click", close);
        }
        modal.addEventListener("click", function (event) {
            if (event.target === modal) {
                close();
            }
        });
        document.addEventListener("keydown", function (event) {
            if (event.key === "Escape" && modal.classList.contains("is-open")) {
                close();
            }
        });
    });
})();
