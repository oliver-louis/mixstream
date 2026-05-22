(function () {
  const TIME_PATTERN = /^\d{1,2}:\d{2}(?::\d{2})?$/;
  const PLATFORM_ORDER = ["discogs", "bandcamp", "soundcloud", "youtube", "spotify"];
  const PLATFORM_LABELS = {
    discogs: "Discogs",
    bandcamp: "Bandcamp",
    soundcloud: "SoundCloud",
    youtube: "YouTube",
    spotify: "Spotify",
  };

  function formatTime(value) {
    if (!Number.isFinite(value)) return "0:00";
    const total = Math.max(0, Math.floor(value));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const seconds = Math.floor(total % 60).toString().padStart(2, "0");
    return hours ? `${hours}:${minutes.toString().padStart(2, "0")}:${seconds}` : `${minutes}:${seconds}`;
  }

  function parseTime(value) {
    const clean = (value || "").trim();
    if (!clean || !TIME_PATTERN.test(clean)) return null;
    const parts = clean.split(":").map(Number);
    if (parts.length === 2) return parts[0] * 60 + parts[1];
    return parts[0] * 3600 + parts[1] * 60 + parts[2];
  }

  function waveformValues(raw) {
    try {
      const values = JSON.parse(raw || "[]");
      if (Array.isArray(values) && values.length) return values.map(Number);
    } catch (error) {}
    return Array.from({ length: 180 }, (_, index) => 0.16 + Math.abs(Math.sin(index * 0.19)) * 0.72);
  }

  function groupValues(values, count) {
    const grouped = [];
    for (let index = 0; index < count; index += 1) {
      const start = Math.floor((index / count) * values.length);
      const end = Math.max(start + 1, Math.floor(((index + 1) / count) * values.length));
      grouped.push(Math.max(...values.slice(start, end)));
    }
    return grouped;
  }

  function platformFromUrl(value) {
    try {
      const parsed = new URL(value);
      const host = (parsed.hostname || "").toLowerCase();
      if (host === "youtu.be" || host === "youtube.com" || host.endsWith(".youtube.com")) return "youtube";
      if (host === "open.spotify.com" || host === "spotify.link") return "spotify";
      if (host === "discogs.com" || host.endsWith(".discogs.com")) return "discogs";
      if (host === "bandcamp.com" || host.endsWith(".bandcamp.com")) return "bandcamp";
      if (host === "soundcloud.com" || host.endsWith(".soundcloud.com")) return "soundcloud";
      return null;
    } catch (error) {
      return null;
    }
  }

  function normalizeLinks(links, legacyUrl) {
    const normalized = {};
    const source = links && typeof links === "object" ? links : {};
    PLATFORM_ORDER.forEach((platform) => {
      const value = (source[platform] || "").trim();
      if (value) normalized[platform] = value;
    });
    const legacy = (legacyUrl || "").trim();
    if (!Object.keys(normalized).length && legacy) {
      const platform = platformFromUrl(legacy);
      if (platform) normalized[platform] = legacy;
    }
    return normalized;
  }

  function normalizeRows(rows) {
    const mapped = (rows || []).map((row, index) => ({
      id: row.id || `row-${index + 1}-${Math.random().toString(36).slice(2, 8)}`,
      start: row.start || "",
      end: row.end || "",
      artist: row.artist || "",
      title: row.title || "",
      links: normalizeLinks(row.links, row.url),
    }));
    const timed = mapped.filter((row) => parseTime(row.start) !== null);
    const untimed = mapped.filter((row) => parseTime(row.start) === null);
    timed.sort((left, right) => (parseTime(left.start) || 0) - (parseTime(right.start) || 0));
    return [...timed, ...untimed];
  }

  function initEditor(root) {
    if (root._timestampEditorBound) return;
    root._timestampEditorBound = true;
    const form = root.querySelector("form");
    const hidden = form?.querySelector('input[name="tracklist_json"]');
    const canvas = root.querySelector("[data-editor-canvas]");
    const audio = root.querySelector("[data-editor-audio]");
    const playButton = root.querySelector("[data-editor-play]");
    const backButton = root.querySelector("[data-editor-back]");
    const forwardButton = root.querySelector("[data-editor-forward]");
    const currentTime = root.querySelector("[data-editor-current]");
    const durationNode = root.querySelector("[data-editor-duration]");
    const addButton = root.querySelector("[data-editor-add-row]");
    const importFileButton = root.querySelector("[data-editor-import-file]");
    const fileInput = root.querySelector("[data-editor-file-input]");
    const rowsRoot = root.querySelector("[data-editor-rows]");
    const template = root.querySelector("[data-editor-row-template]");
    if (!form || !hidden || !canvas || !audio || !rowsRoot || !template) return;

    const values = waveformValues(root.dataset.waveform);
    const audioUrl = root.dataset.audioUrl || root.dataset.audioMp3Url || "";
    const duration = Number(root.dataset.duration || 0);
    const canPlay = Boolean(audioUrl);
    const dpr = window.devicePixelRatio || 1;
    const importUrl = root.dataset.importUrl || "";
    const csrfToken = form.querySelector('input[name="csrfmiddlewaretoken"]')?.value || "";

    let rows = [];
    let selectedId = null;
    let dragging = false;
    let dirty = false;

    if (audioUrl) audio.src = audioUrl;

    try {
      rows = normalizeRows(JSON.parse(hidden.value || "[]"));
    } catch (error) {
      rows = [];
    }
    if (!rows.length) {
      rows = normalizeRows([{ start: "", end: "", artist: "", title: "", url: "" }]);
    }
    selectedId = rows[0]?.id || null;

    function effectiveDuration() {
      return audio.duration || duration || 0;
    }

    function markDirty() {
      dirty = true;
    }

    function syncHidden() {
      hidden.value = JSON.stringify(
        rows.map(({ start, end, artist, title, links }) => ({ start, end, artist, title, links })),
      );
    }

    function replaceRows(nextRows) {
      rows = normalizeRows(nextRows);
      if (!rows.length) {
        rows = normalizeRows([{ start: "", end: "", artist: "", title: "", links: {} }]);
      }
      selectedId = rows[0]?.id || null;
      markDirty();
      syncHidden();
      renderRows();
      renderWaveform();
    }

    function selectRow(id) {
      if (selectedId === id) return;
      selectedId = id;
      renderRows();
      renderWaveform();
    }

    function selectedRow() {
      return rows.find((row) => row.id === selectedId) || null;
    }

    function sortRows() {
      rows = normalizeRows(rows);
    }

    function updateRowField(id, field, value) {
      const row = rows.find((entry) => entry.id === id);
      if (!row) return;
      row[field] = value;
      markDirty();
      syncHidden();
    }

    function setRowLinks(id, nextLinks) {
      const row = rows.find((entry) => entry.id === id);
      if (!row) return;
      row.links = normalizeLinks(nextLinks);
      markDirty();
      syncHidden();
    }

    function setRowTime(id, field, seconds) {
      const row = rows.find((entry) => entry.id === id);
      if (!row) return;
      row[field] = formatTime(seconds);
      if (field === "start" && row.end && parseTime(row.end) !== null && parseTime(row.end) <= parseTime(row.start)) {
        row.end = "";
      }
      if (field === "end" && row.start && parseTime(row.start) !== null && parseTime(row.end) !== null && parseTime(row.end) <= parseTime(row.start)) {
        row.end = "";
      }
      sortRows();
      selectedId = row.id;
      markDirty();
      syncHidden();
      renderRows();
      renderWaveform();
    }

    function addRow(seed = {}) {
      rows.push(
        normalizeRows([
          {
            start: seed.start || "",
            end: seed.end || "",
            artist: seed.artist || "",
            title: seed.title || "",
            links: normalizeLinks(seed.links, seed.url),
          },
        ])[0],
      );
      selectedId = rows[rows.length - 1].id;
      markDirty();
      syncHidden();
      renderRows();
      rowsRoot.querySelector("[data-row-title]")?.focus();
    }

    function removeRow(id) {
      rows = rows.filter((row) => row.id !== id);
      if (!rows.length) addRow();
      else {
        if (selectedId === id) selectedId = rows[0].id;
        markDirty();
        syncHidden();
        renderRows();
        renderWaveform();
      }
    }

    async function importSavedFile(file) {
      const formData = new FormData();
      formData.append("file", file);
      const response = await fetch(importUrl, {
        method: "POST",
        headers: {
          "X-CSRFToken": csrfToken,
          "X-Requested-With": "XMLHttpRequest",
        },
        body: formData,
        credentials: "same-origin",
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload?.error || "Track ID import failed.");
      }
      return payload.rows || [];
    }

    function rowMarkers() {
      const total = effectiveDuration();
      if (!total) return [];
      return rows
        .map((row) => ({
          id: row.id,
          start: parseTime(row.start),
          end: parseTime(row.end),
        }))
        .filter((row) => row.start !== null)
        .map((row) => ({
          ...row,
          startRatio: row.start / total,
          endRatio: row.end !== null ? row.end / total : null,
        }));
    }

    function renderRows() {
      rowsRoot.innerHTML = "";
      const fragment = document.createDocumentFragment();
      rows.forEach((row) => {
        const node = template.content.firstElementChild.cloneNode(true);
        node.dataset.rowId = row.id;
        node.classList.toggle("is-selected", row.id === selectedId);
        const selectButton = node.querySelector("[data-row-select]");
        const startChip = node.querySelector("[data-row-start]");
        const endChip = node.querySelector("[data-row-end]");
        const artistInput = node.querySelector("[data-row-artist]");
        const titleInput = node.querySelector("[data-row-title]");
        const linkList = node.querySelector("[data-row-link-list]");
        const linkInput = node.querySelector("[data-row-link-input]");
        const linkAdd = node.querySelector("[data-row-link-add]");
        const linkFeedback = node.querySelector("[data-row-link-feedback]");
        startChip.textContent = row.start || "Start unset";
        endChip.textContent = row.end || "End unset";
        startChip.classList.toggle("is-set", Boolean(row.start));
        endChip.classList.toggle("is-set", Boolean(row.end));
        artistInput.value = row.artist;
        titleInput.value = row.title;
        selectButton.addEventListener("click", () => selectRow(row.id));
        node.querySelector("[data-row-set-start]").addEventListener("click", () => setRowTime(row.id, "start", audio.currentTime || 0));
        node.querySelector("[data-row-set-end]").addEventListener("click", () => setRowTime(row.id, "end", audio.currentTime || 0));
        node.querySelector("[data-row-set-start]").disabled = !canPlay;
        node.querySelector("[data-row-set-end]").disabled = !canPlay;
        node.querySelector("[data-row-clear-end]").addEventListener("click", () => {
          const target = rows.find((entry) => entry.id === row.id);
          if (!target) return;
          target.end = "";
          markDirty();
          syncHidden();
          renderRows();
          renderWaveform();
        });
        node.querySelector("[data-row-remove]").addEventListener("click", () => removeRow(row.id));
        artistInput.addEventListener("focus", () => selectRow(row.id));
        titleInput.addEventListener("focus", () => selectRow(row.id));
        artistInput.addEventListener("input", () => updateRowField(row.id, "artist", artistInput.value));
        titleInput.addEventListener("input", () => updateRowField(row.id, "title", titleInput.value));
        linkInput.addEventListener("focus", () => selectRow(row.id));
        linkAdd.addEventListener("click", () => {
          const value = (linkInput.value || "").trim();
          if (!value) return;
          let parsed;
          try {
            parsed = new URL(value);
          } catch (error) {
            linkFeedback.textContent = "Enter a full URL.";
            linkFeedback.classList.add("is-visible");
            return;
          }
          const platform = platformFromUrl(parsed.toString());
          if (!platform) {
            linkFeedback.textContent = "Only Discogs, Bandcamp, SoundCloud, YouTube, and Spotify links are allowed.";
            linkFeedback.classList.add("is-visible");
            return;
          }
          if (row.links[platform]) {
            linkFeedback.textContent = `This Track ID already has a ${PLATFORM_LABELS[platform]} link.`;
            linkFeedback.classList.add("is-visible");
            return;
          }
          const nextLinks = { ...row.links, [platform]: parsed.toString() };
          row.links = nextLinks;
          setRowLinks(row.id, nextLinks);
          linkInput.value = "";
          linkFeedback.textContent = "";
          linkFeedback.classList.remove("is-visible");
          renderRows();
        });
        linkInput.addEventListener("keydown", (event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            linkAdd.click();
          }
        });
        linkList.innerHTML = "";
        PLATFORM_ORDER.forEach((platform) => {
          const url = row.links[platform];
          if (!url) return;
          const chip = document.createElement("span");
          chip.className = "tracklist-link-chip";
          chip.innerHTML = `<strong>${PLATFORM_LABELS[platform]}</strong><button type="button" aria-label="Remove ${PLATFORM_LABELS[platform]} link">×</button>`;
          chip.title = url;
          chip.querySelector("button").addEventListener("click", () => {
            const nextLinks = { ...row.links };
            delete nextLinks[platform];
            row.links = nextLinks;
            setRowLinks(row.id, nextLinks);
            renderRows();
          });
          linkList.appendChild(chip);
        });
        fragment.appendChild(node);
      });
      rowsRoot.appendChild(fragment);
    }

    function renderWaveform() {
      const rect = canvas.getBoundingClientRect();
      const width = Math.max(1, Math.floor(rect.width * dpr));
      const height = Math.max(1, Math.floor(rect.height * dpr));
      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
      }
      const ctx = canvas.getContext("2d");
      ctx.clearRect(0, 0, width, height);
      const grouped = groupValues(values, Math.max(60, Math.floor(width / (4 * dpr))));
      const ratio = effectiveDuration() ? (audio.currentTime || 0) / effectiveDuration() : 0;
      const step = width / Math.max(1, grouped.length);
      const barWidth = Math.max(2, Math.floor(step - 2 * dpr));
      const mid = height / 2;
      grouped.forEach((raw, index) => {
        const x = Math.floor(index * step);
        const value = Math.max(0.04, Math.min(1, Number(raw) || 0.05));
        const barHeight = Math.max(8 * dpr, value * height * 0.42);
        const barRatio = index / Math.max(1, grouped.length - 1);
        ctx.fillStyle = barRatio <= ratio ? "#ff5500" : "rgba(255,255,255,.86)";
        ctx.fillRect(x, mid - barHeight, barWidth, barHeight * 2);
      });
      rowMarkers().forEach((marker) => {
        const isSelected = marker.id === selectedId;
        const startX = Math.floor(marker.startRatio * width);
        ctx.fillStyle = isSelected ? "rgba(255,85,0,.9)" : "rgba(255,255,255,.34)";
        ctx.fillRect(startX, 0, Math.max(2, 2 * dpr), height);
        if (marker.endRatio !== null) {
          const endX = Math.floor(marker.endRatio * width);
          ctx.fillStyle = isSelected ? "rgba(255,177,135,.94)" : "rgba(255,255,255,.18)";
          ctx.fillRect(endX, 0, Math.max(2, 2 * dpr), height);
        }
      });
      const playheadX = Math.floor(ratio * width);
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(playheadX, 0, Math.max(2, 2 * dpr), height);
    }

    function syncTime() {
      currentTime.textContent = formatTime(audio.currentTime || 0);
      durationNode.textContent = formatTime(effectiveDuration());
      playButton.textContent = audio.paused ? "▶" : "Ⅱ";
      renderWaveform();
    }

    function seekToClientX(clientX) {
      if (!canPlay || !effectiveDuration()) return;
      const rect = canvas.getBoundingClientRect();
      const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
      audio.currentTime = ratio * effectiveDuration();
      syncTime();
    }

    function seekBy(delta) {
      if (!canPlay || !effectiveDuration()) return;
      audio.currentTime = Math.max(0, Math.min(effectiveDuration(), (audio.currentTime || 0) + delta));
      syncTime();
    }

    canvas.addEventListener("pointerdown", (event) => {
      if (!canPlay) return;
      dragging = true;
      canvas.setPointerCapture(event.pointerId);
      seekToClientX(event.clientX);
    });
    canvas.addEventListener("pointermove", (event) => {
      if (!dragging) return;
      seekToClientX(event.clientX);
    });
    canvas.addEventListener("pointerup", () => {
      dragging = false;
    });
    canvas.addEventListener("pointercancel", () => {
      dragging = false;
    });
    canvas.addEventListener("click", (event) => {
      if (!canPlay) return;
      seekToClientX(event.clientX);
    });

    playButton?.addEventListener("click", () => {
      if (!canPlay) return;
      if (audio.paused) audio.play().catch(() => {});
      else audio.pause();
    });
    backButton?.addEventListener("click", () => seekBy(-5));
    forwardButton?.addEventListener("click", () => seekBy(5));
    addButton?.addEventListener("click", () => addRow({ start: canPlay ? formatTime(audio.currentTime || 0) : "" }));
    importFileButton?.addEventListener("click", () => fileInput?.click());
    fileInput?.addEventListener("change", async () => {
      const file = fileInput.files?.[0];
      if (!file) return;
      try {
        const importedRows = await importSavedFile(file);
        replaceRows(importedRows);
      } catch (error) {
        window.alert(error instanceof Error ? error.message : "Track ID import failed.");
      } finally {
        fileInput.value = "";
      }
    });

    audio.addEventListener("play", () => {
      window.dispatchEvent(new CustomEvent("mixstream:editor-playback"));
      syncTime();
    });
    audio.addEventListener("pause", syncTime);
    audio.addEventListener("timeupdate", syncTime);
    audio.addEventListener("loadedmetadata", syncTime);

    window.addEventListener("resize", renderWaveform);
    form.addEventListener("submit", () => {
      sortRows();
      syncHidden();
      dirty = false;
    });
    window.addEventListener("beforeunload", (event) => {
      if (!dirty) return;
      event.preventDefault();
      event.returnValue = "";
    });
    document.addEventListener("keydown", (event) => {
      const active = document.activeElement;
      const typing = active && (active.tagName === "INPUT" || active.tagName === "TEXTAREA" || active.isContentEditable);
      if (typing) return;
      if (event.code === "ArrowLeft" || event.code === "ArrowRight") {
        event.preventDefault();
        seekBy(event.code === "ArrowLeft" ? -5 : 5);
        return;
      }
      if (event.code === "Space") {
        event.preventDefault();
        if (!canPlay) return;
        if (audio.paused) audio.play().catch(() => {});
        else audio.pause();
      }
    });

    syncHidden();
    renderRows();
    syncTime();
  }

  function initAll() {
    document.querySelectorAll("[data-timestamp-editor]").forEach(initEditor);
  }

  window.addEventListener("mixstream:page-load", initAll);
  document.addEventListener("DOMContentLoaded", initAll);
  initAll();
})();
