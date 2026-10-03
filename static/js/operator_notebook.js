(() => {
  "use strict";

  const drawer = document.getElementById("notebookDrawer");
  const backdrop = document.getElementById("notebookBackdrop");
  const content = document.getElementById("notebookContent");
  if (!drawer || !backdrop || !content) return; // page has no notebook drawer (shouldn't happen on the Learning Hub, but be safe)

  let currentTrackId = null;
  let evidenceFilesOnDisk = []; // filenames already saved server-side for this unit

  function escapeHtml(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // Tiny dependency-free markdown renderer: headers, bold/italic, code,
  // lists, quotes, links, images, paragraphs. Images resolve against the
  // real evidence/<filename> route for this track/unit.
  function renderMarkdown(src) {
    if (!src || !src.trim()) return '<p class="nb-empty">Nothing written yet.</p>';
    const lines = escapeHtml(src).split(/\r?\n/);
    let html = "", inList = null, paraBuf = [];

    const inline = (text) => text
      .replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (m, alt, target) => {
        if (currentTrackId && evidenceFilesOnDisk.includes(target)) {
          const src = `/operator/learning/tracks/${encodeURIComponent(currentTrackId)}/evidence/${encodeURIComponent(target)}`;
          return `<img src="${src}" alt="${alt}">`;
        }
        return `<span class="nb-broken-img">🖼 ${alt || target}</span>`;
      })
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\*([^*]+)\*/g, "<em>$1</em>")
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');

    const flushPara = () => { if (paraBuf.length) { html += `<p>${inline(paraBuf.join(" "))}</p>`; paraBuf = []; } };
    const closeList = () => { if (inList) { html += `</${inList}>`; inList = null; } };

    for (const raw of lines) {
      const line = raw.trim();
      if (!line) { flushPara(); closeList(); continue; }
      const h = line.match(/^(#{1,3})\s+(.*)$/);
      if (h) { flushPara(); closeList(); const lvl = h[1].length; html += `<h${lvl}>${inline(h[2])}</h${lvl}>`; continue; }
      const ul = line.match(/^[-*]\s+(.*)$/);
      if (ul) { flushPara(); if (inList !== "ul") { closeList(); html += "<ul>"; inList = "ul"; } html += `<li>${inline(ul[1])}</li>`; continue; }
      const ol = line.match(/^\d+\.\s+(.*)$/);
      if (ol) { flushPara(); if (inList !== "ol") { closeList(); html += "<ol>"; inList = "ol"; } html += `<li>${inline(ol[1])}</li>`; continue; }
      closeList(); paraBuf.push(line);
    }
    flushPara(); closeList();
    return html || '<p class="nb-empty">Nothing written yet.</p>';
  }

  function fieldRow(key, label, hint) {
    return `
      <div class="nb-section">
        <div class="nb-section-head">
          <h2>${label}</h2>
          <span class="nb-save-status" id="nb-status-${key}"><span class="dot"></span><span>Saved</span></span>
        </div>
        ${hint ? `<p class="nb-section-sub">${hint}</p>` : ""}
        <div class="nb-split">
          <div class="nb-pane"><div class="nb-pane-label">Write (Markdown)</div><textarea class="nb-textarea" id="nb-input-${key}"></textarea></div>
          <div class="nb-pane"><div class="nb-pane-label">Preview</div><div class="nb-preview" id="nb-preview-${key}"></div></div>
        </div>
      </div>`;
  }

  function render(data) {
    currentTrackId = data.track_id;
    evidenceFilesOnDisk = data.evidence_files || [];

    const hasNotes = data.notes !== null && data.notes !== undefined;
    const hasReflection = data.reflection !== null && data.reflection !== undefined;
    const hasEvidence = data.evidence_text !== null && data.evidence_text !== undefined;

    const rewardRows = (data.reward_preview?.items || [])
      .map((item) => `<span class="nb-req pass">${item.name} · ${item.xp} XP</span>`)
      .join("");

    content.innerHTML = `
      <div class="nb-track-label">${escapeHtml(data.track_title)}</div>
      <div class="nb-title-row"><h1>${escapeHtml(data.unit_title)}</h1></div>
      <p class="nb-meta">Unit ${data.unit_index + 1} of ${data.unit_count}</p>
      <div class="nb-progress-pill">${escapeHtml(String(data.reward_preview?.total_xp ?? "?"))} XP on completion</div>
      <div class="nb-req-strip" style="margin-top:.8rem">${rewardRows}</div>

      ${hasNotes ? fieldRow("notes", "Notes") : ""}
      ${hasReflection ? fieldRow("reflection", "Reflection") : ""}
      ${hasEvidence ? `
        <div class="nb-section">
          <div class="nb-section-head"><h2>Evidence</h2><span class="nb-save-status" id="nb-status-evidence_text"><span class="dot"></span><span>Saved</span></span></div>
          <div class="nb-evidence-zone" id="nb-dropzone">Drag a file here — or click to browse<input type="file" id="nb-file-input" multiple></div>
          <div class="nb-evidence-chips" id="nb-evidence-chips"></div>
          <div class="nb-split">
            <div class="nb-pane"><div class="nb-pane-label">Write (Markdown)</div><textarea class="nb-textarea" id="nb-input-evidence_text"></textarea></div>
            <div class="nb-pane"><div class="nb-pane-label">Preview</div><div class="nb-preview" id="nb-preview-evidence_text"></div></div>
          </div>
        </div>` : ""}

      <div class="nb-actions">
        <button class="nb-button secondary" type="button" id="nb-save-btn">Save Notebook</button>
        <button class="nb-button" type="button" id="nb-complete-btn">Mark Unit Complete</button>
      </div>
      <p class="nb-section-sub" id="nb-missing-note" style="display:none;margin-top:.6rem"></p>
    `;

    if (hasNotes) wireField("notes", data.notes);
    if (hasReflection) wireField("reflection", data.reflection);
    if (hasEvidence) wireField("evidence_text", data.evidence_text);
    if (hasEvidence) wireEvidenceZone();

    document.getElementById("nb-save-btn").addEventListener("click", saveNotebook);
    document.getElementById("nb-complete-btn").addEventListener("click", completeUnit);
  }

  function wireField(key, initialValue) {
    const input = document.getElementById(`nb-input-${key}`);
    const preview = document.getElementById(`nb-preview-${key}`);
    const status = document.getElementById(`nb-status-${key}`);
    input.value = initialValue || "";
    preview.innerHTML = renderMarkdown(input.value);
    input.addEventListener("input", () => {
      preview.innerHTML = renderMarkdown(input.value);
      status.classList.remove("saved");
      status.querySelector("span:last-child").textContent = "Unsaved";
    });
  }

  function renderEvidenceChips() {
    const chips = document.getElementById("nb-evidence-chips");
    if (!chips) return;
    chips.innerHTML = evidenceFilesOnDisk
      .map((name) => `<span class="nb-chip">📎 ${escapeHtml(name)}</span>`)
      .join("");
  }

  function wireEvidenceZone() {
    renderEvidenceChips();
    const zone = document.getElementById("nb-dropzone");
    const fileInput = document.getElementById("nb-file-input");

    const addFiles = async (fileList) => {
      for (const file of Array.from(fileList)) {
        await uploadEvidence(file);
      }
    };

    zone.addEventListener("click", () => fileInput.click());
    fileInput.addEventListener("change", (e) => addFiles(e.target.files));
    ["dragenter", "dragover"].forEach((evt) => zone.addEventListener(evt, (e) => { e.preventDefault(); zone.classList.add("drag-over"); }));
    ["dragleave", "drop"].forEach((evt) => zone.addEventListener(evt, (e) => { e.preventDefault(); zone.classList.remove("drag-over"); }));
    zone.addEventListener("drop", (e) => { if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files); });
  }

  async function uploadEvidence(file) {
    const formData = new FormData();
    formData.append("file", file);
    try {
      const response = await fetch(`/operator/learning/tracks/${encodeURIComponent(currentTrackId)}/evidence`, {
        method: "POST",
        body: formData,
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Upload failed");
      if (!evidenceFilesOnDisk.includes(result.filename)) evidenceFilesOnDisk.push(result.filename);
      renderEvidenceChips();

      const input = document.getElementById("nb-input-evidence_text");
      const preview = document.getElementById("nb-preview-evidence_text");
      const ref = `\n![${result.filename.replace(/\.[a-z0-9]+$/i, "").replace(/[_-]/g, " ")}](${result.filename})\n`;
      input.value = (input.value ? input.value + "\n" : "") + ref.trim();
      preview.innerHTML = renderMarkdown(input.value);
      const status = document.getElementById("nb-status-evidence_text");
      status.classList.remove("saved");
      status.querySelector("span:last-child").textContent = "Unsaved";
    } catch (error) {
      alert(`Evidence upload failed: ${error.message}`);
    }
  }

  async function saveNotebook() {
    const payload = {};
    ["notes", "reflection", "evidence_text"].forEach((key) => {
      const input = document.getElementById(`nb-input-${key}`);
      if (input) payload[key] = input.value;
    });
    try {
      const response = await fetch(`/operator/learning/tracks/${encodeURIComponent(currentTrackId)}/notebook`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Save failed");
      ["notes", "reflection", "evidence_text"].forEach((key) => {
        const status = document.getElementById(`nb-status-${key}`);
        if (status) { status.classList.add("saved"); status.querySelector("span:last-child").textContent = "Saved"; }
      });
    } catch (error) {
      alert(`Couldn't save: ${error.message}`);
    }
  }

  async function completeUnit() {
    await saveNotebook();
    try {
      await fetch(`/operator/learning/tracks/${encodeURIComponent(currentTrackId)}/complete`, { method: "POST" });
    } finally {
      // A full reload picks up the advanced current_unit_index, refreshed
      // percentages, and the existing XP receipt toast (learning_receipts.js
      // already polls /api/learning/receipts/latest independently of this).
      window.location.reload();
    }
  }

  async function openNotebook(trackId) {
    drawer.classList.add("open");
    backdrop.classList.add("open");
    content.innerHTML = '<p class="nb-empty">Loading…</p>';
    try {
      const response = await fetch(`/operator/learning/tracks/${encodeURIComponent(trackId)}/notebook`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Couldn't load this unit.");
      render(data);
    } catch (error) {
      content.innerHTML = `<p class="nb-empty">${escapeHtml(error.message)}</p>`;
    }
  }

  function closeNotebook() {
    drawer.classList.remove("open");
    backdrop.classList.remove("open");
  }

  document.querySelectorAll("[data-notebook-track]").forEach((button) => {
    button.addEventListener("click", () => openNotebook(button.getAttribute("data-notebook-track")));
  });
  document.getElementById("notebookClose").addEventListener("click", closeNotebook);
  backdrop.addEventListener("click", closeNotebook);
})();
