(function () {
  const timePattern = /^\d{1,2}:\d{2}(?::\d{2})?$/;
  const linePattern = /^\s*(?:(\d{1,2}:\d{2}(?::\d{2})?)\s*(?:(?:-|–|—|->|→)\s*(\d{1,2}:\d{2}(?::\d{2})?))?\s+)?(.+?)\s*$/;
  const urlPattern = /https?:\/\/\S+/gi;
  const platformOrder = ["discogs", "bandcamp", "soundcloud", "youtube", "spotify"];
  const platformLabels = {
    discogs: "Discogs",
    bandcamp: "Bandcamp",
    soundcloud: "SoundCloud",
    youtube: "YouTube",
    spotify: "Spotify",
  };

  function parseTime(value) {
    const clean = String(value || "").trim();
    if (!clean || !timePattern.test(clean)) return null;
    const parts = clean.split(":").map(Number);
    const minutes = parts.length === 3 ? parts[1] : parts[0];
    const seconds = parts[parts.length - 1];
    if (seconds >= 60 || (parts.length === 3 && minutes >= 60)) return null;
    return parts.length === 3 ? parts[0] * 3600 + minutes * 60 + seconds : minutes * 60 + seconds;
  }

  function splitArtistTitle(body) {
    const clean = (body || "").trim().replace(/\s+/g, " ");
    const separator = clean.indexOf(" - ");
    if (separator === -1) return { artist: "", title: clean };
    return {
      artist: clean.slice(0, separator).trim(),
      title: clean.slice(separator + 3).trim(),
    };
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
    platformOrder.forEach((platform) => {
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

  function stripUrls(line) {
    const links = {};
    const matches = (line || "").match(urlPattern) || [];
    for (const rawUrl of matches) {
      const platform = platformFromUrl(rawUrl);
      if (!platform) {
        return {
          text: "",
          links: {},
          error: "Only Discogs, Bandcamp, SoundCloud, YouTube, and Spotify links can be imported.",
        };
      }
      if (links[platform]) {
        return {
          text: "",
          links: {},
          error: `Only one ${platformLabels[platform]} link is allowed per Track ID.`,
        };
      }
      links[platform] = rawUrl;
    }
    return {
      text: (line || "").replace(urlPattern, "").replace(/\s{2,}/g, " ").trim(),
      links,
      error: "",
    };
  }

  function parseLine(line) {
    const { text, links, error } = stripUrls(line);
    if (error) return { error };
    const clean = (text || "").trim();
    if (!clean) return null;
    const match = clean.match(linePattern);
    if (!match) return null;
    const copy = splitArtistTitle(match[3]);
    if (!copy.title) return null;
    return {
      start: timePattern.test(match[1] || "") ? match[1] : "",
      end: timePattern.test(match[2] || "") ? match[2] : "",
      artist: copy.artist,
      title: copy.title,
      links,
    };
  }

  function normalizeRows(rows) {
    return (rows || []).map((row) => ({
      start: row.start || "",
      end: row.end || "",
      artist: row.artist || "",
      title: row.title || "",
      links: normalizeLinks(row.links, row.url),
    }));
  }

  function cleanImportedJsonRows(payload) {
    const cleaned = [];
    payload.forEach((item, offset) => {
      const rowNumber = offset + 1;
      if (!item || typeof item !== "object" || Array.isArray(item)) {
        throw new Error(`Row ${rowNumber}: Track ID must be an object.`);
      }
      const title = String(item.title || "").trim().replace(/\s+/g, " ");
      const artist = String(item.artist || "").trim().replace(/\s+/g, " ");
      const start = String(item.start || item.start_seconds || "").trim();
      const end = String(item.end || item.end_seconds || "").trim();
      const legacyUrl = String(item.url || "").trim();
      const sourceLinks = item.links && typeof item.links === "object" && !Array.isArray(item.links) ? item.links : {};
      const linkValues = Object.values(sourceLinks).map((value) => String(value || "").trim());
      if (![title, artist, start, end, legacyUrl, ...linkValues].some(Boolean)) return;
      if (!title) throw new Error(`Row ${rowNumber}: Track title is required.`);
      if (start && parseTime(start) === null) throw new Error(`Row ${rowNumber}: Use mm:ss or hh:mm:ss.`);
      if (end && parseTime(end) === null) throw new Error(`Row ${rowNumber}: Use mm:ss or hh:mm:ss.`);
      if (end && !start) throw new Error(`Row ${rowNumber}: Add a start time before using an end time.`);

      const links = {};
      const candidates = [...Object.entries(sourceLinks), ...(legacyUrl ? [["__legacy__", legacyUrl]] : [])];
      candidates.forEach(([declaredPlatform, rawUrl]) => {
        const value = String(rawUrl || "").trim();
        if (!value) return;
        let parsed;
        try {
          parsed = new URL(value);
        } catch (error) {
          throw new Error(`Row ${rowNumber}: Enter a valid URL.`);
        }
        if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
          throw new Error(`Row ${rowNumber}: Enter a valid URL.`);
        }
        const detected = platformFromUrl(parsed.toString());
        if (!detected) {
          throw new Error(`Row ${rowNumber}: Only Discogs, Bandcamp, SoundCloud, YouTube, and Spotify links are supported.`);
        }
        if (platformOrder.includes(declaredPlatform) && declaredPlatform !== detected) {
          throw new Error(`Row ${rowNumber}: ${platformLabels[declaredPlatform]} links must use the correct platform URL.`);
        }
        if (links[detected]) {
          throw new Error(`Row ${rowNumber}: Only one ${platformLabels[detected]} link is allowed per Track ID.`);
        }
        links[detected] = parsed.toString();
      });
      cleaned.push({ start, end, artist, title, links });
    });
    return cleaned;
  }

  function initLinkEditor(row, options) {
    const list = row.querySelector(options.listSelector);
    const input = row.querySelector(options.inputSelector);
    const addButton = row.querySelector(options.addSelector);
    const feedback = row.querySelector(options.feedbackSelector);
    if (!list || !input || !addButton || !feedback) return;
    row._trackLinks = normalizeLinks(row._trackLinks);

    function setFeedback(message) {
      feedback.textContent = message || "";
      feedback.classList.toggle("is-visible", Boolean(message));
    }

    function renderLinks() {
      list.innerHTML = "";
      platformOrder.forEach((platform) => {
        const url = row._trackLinks[platform];
        if (!url) return;
        const chip = document.createElement("span");
        chip.className = "tracklist-link-chip";
        chip.innerHTML = `<strong>${platformLabels[platform]}</strong><button type="button" aria-label="Remove ${platformLabels[platform]} link">×</button>`;
        chip.title = url;
        chip.querySelector("button").addEventListener("click", () => {
          delete row._trackLinks[platform];
          renderLinks();
          setFeedback("");
          options.onChange();
        });
        list.appendChild(chip);
      });
    }

    function addLink() {
      const value = (input.value || "").trim();
      if (!value) return;
      let parsed;
      try {
        parsed = new URL(value);
      } catch (error) {
        setFeedback("Enter a full URL.");
        return;
      }
      const platform = platformFromUrl(parsed.toString());
      if (!platform) {
        setFeedback("Only Discogs, Bandcamp, SoundCloud, YouTube, and Spotify links are allowed.");
        return;
      }
      if (row._trackLinks[platform]) {
        setFeedback(`This Track ID already has a ${platformLabels[platform]} link.`);
        return;
      }
      row._trackLinks[platform] = parsed.toString();
      input.value = "";
      setFeedback("");
      renderLinks();
      options.onChange();
    }

    addButton.addEventListener("click", addLink);
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        addLink();
      }
    });

    renderLinks();
  }

  function initEditor(editor) {
    if (editor._tracklistEditorBound) return;
    editor._tracklistEditorBound = true;
    const hidden = document.getElementById(editor.dataset.hiddenInputId);
    const rowsRoot = editor.querySelector("[data-tracklist-rows]");
    const template = editor.querySelector("[data-tracklist-template]");
    const addButton = editor.querySelector("[data-tracklist-add]");
    const importButton = editor.querySelector("[data-tracklist-import]");
    const importTextarea = editor.querySelector("textarea");
    const importFileButton = editor.querySelector("[data-tracklist-import-file]");
    const fileInput = editor.querySelector("[data-tracklist-file-input]");
    const validationSummary = editor.querySelector("[data-tracklist-validation-summary]");
    if (!hidden || !rowsRoot || !template) return;
    const importUrl = editor.dataset.importUrl || "";
    const duration = Number(editor.dataset.duration || 0);
    const csrfToken = editor.closest("form")?.querySelector('input[name="csrfmiddlewaretoken"]')?.value || "";

    function readRowsFromInput() {
      try {
        return normalizeRows(JSON.parse(hidden.value || "[]"));
      } catch (error) {
        return [];
      }
    }

    function rowFromElement(row) {
      return {
        start: row.querySelector("[data-tracklist-start]")?.value.trim() || "",
        end: row.querySelector("[data-tracklist-end]")?.value.trim() || "",
        artist: row.querySelector("[data-tracklist-artist]")?.value.trim() || "",
        title: row.querySelector("[data-tracklist-title]")?.value.trim() || "",
        links: normalizeLinks(row._trackLinks),
      };
    }

    function rowTimeIssues(values) {
      const startRaw = String(values.start || "").trim();
      const endRaw = String(values.end || "").trim();
      const start = parseTime(startRaw);
      const end = parseTime(endRaw);
      const blocking = [];
      const advisory = [];
      if (startRaw && start === null) blocking.push("Start time must use mm:ss or hh:mm:ss.");
      if (endRaw && end === null) blocking.push("End time must use mm:ss or hh:mm:ss.");
      if (end !== null && start === null && !startRaw) blocking.push("Add a start time before using an end time.");
      if (start !== null && end !== null && end <= start) blocking.push("End time must be after the start time.");
      if (duration > 0 && start !== null && start >= duration) {
        advisory.push("This track starts at or after the recording ends.");
      } else if (duration > 0 && end !== null && end > duration) {
        advisory.push("This track ends after the recording.");
      }
      return { blocking, advisory };
    }

    function updateValidation() {
      let blockingCount = 0;
      let advisoryCount = 0;
      const rowElements = Array.from(rowsRoot.querySelectorAll("[data-tracklist-row]"));
      rowElements.forEach((row) => {
        const issues = rowTimeIssues(rowFromElement(row));
        if (issues.blocking.length) blockingCount += 1;
        if (issues.advisory.length) advisoryCount += 1;
        row.classList.toggle("has-time-error", Boolean(issues.blocking.length));
        row.classList.toggle("has-runtime-warning", !issues.blocking.length && Boolean(issues.advisory.length));
        const feedback = row.querySelector("[data-tracklist-time-feedback]");
        if (feedback) {
          feedback.textContent = [...issues.blocking, ...issues.advisory].join(" ");
          feedback.hidden = !feedback.textContent;
        }
      });
      if (validationSummary) {
        const messages = [];
        if (blockingCount) {
          messages.push(`${blockingCount} Track ID${blockingCount === 1 ? " has" : "s have"} a timing issue and must be fixed or removed before saving.`);
        }
        if (advisoryCount) {
          messages.push(`${advisoryCount} Track ID${advisoryCount === 1 ? " extends" : "s extend"} beyond the recording and can still be saved.`);
        }
        validationSummary.textContent = messages.join(" ");
        validationSummary.hidden = !messages.length;
        validationSummary.classList.toggle("has-blocking-errors", Boolean(blockingCount));
      }
      return { blockingCount, advisoryCount };
    }

    function serialize() {
      const rows = Array.from(rowsRoot.querySelectorAll("[data-tracklist-row]"))
        .map(rowFromElement)
        .filter((row) => row.start || row.end || row.artist || row.title || Object.keys(row.links).length);
      hidden.value = JSON.stringify(rows);
      return updateValidation();
    }

    function replaceRows(values) {
      rowsRoot.innerHTML = "";
      const rows = normalizeRows(values || []);
      rows.forEach(addRow);
      if (!rows.length) addRow();
      serialize();
    }

    function addRow(values = {}) {
      const fragment = template.content.cloneNode(true);
      const row = fragment.querySelector("[data-tracklist-row]");
      row.querySelector("[data-tracklist-start]").value = values.start || "";
      row.querySelector("[data-tracklist-end]").value = values.end || "";
      row.querySelector("[data-tracklist-artist]").value = values.artist || "";
      row.querySelector("[data-tracklist-title]").value = values.title || "";
      row._trackLinks = normalizeLinks(values.links, values.url);
      row.querySelector("[data-tracklist-remove]").addEventListener("click", () => {
        row.remove();
        serialize();
      });
      row.querySelectorAll("input").forEach((input) => input.addEventListener("input", serialize));
      initLinkEditor(row, {
        listSelector: "[data-tracklist-link-list]",
        inputSelector: "[data-tracklist-link-input]",
        addSelector: "[data-tracklist-link-add]",
        feedbackSelector: "[data-tracklist-link-feedback]",
        onChange: serialize,
      });
      rowsRoot.appendChild(row);
      serialize();
      return row;
    }

    function renderInitialRows() {
      rowsRoot.innerHTML = "";
      const rows = readRowsFromInput();
      rows.forEach(addRow);
      if (!rows.length) addRow();
    }

    function parseImportedText(text) {
      const rawImported = (text || "").split(/\r?\n/).map(parseLine).filter(Boolean);
      const errorRow = rawImported.find((row) => row && row.error);
      if (errorRow) throw new Error(errorRow.error);
      return rawImported;
    }

    function parseImportedJson(text) {
      let payload;
      try {
        payload = JSON.parse(text || "[]");
      } catch (error) {
        throw new Error("Track ID JSON could not be read.");
      }
      if (!Array.isArray(payload)) throw new Error("Track ID JSON must contain a list of rows.");
      return cleanImportedJsonRows(payload);
    }

    async function importLocalFile(file) {
      const name = (file?.name || "").toLowerCase();
      const text = await file.text();
      if (name.endsWith(".json")) return parseImportedJson(text);
      if (name.endsWith(".txt")) return parseImportedText(text);
      throw new Error("Track ID files must be .json or .txt.");
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
      return normalizeRows(payload.rows || []);
    }

    async function handleImportFile(file) {
      if (!file) return;
      const rows = importUrl ? await importSavedFile(file) : await importLocalFile(file);
      replaceRows(rows);
      if (fileInput) fileInput.value = "";
    }

    addButton?.addEventListener("click", () => {
      addRow().querySelector("[data-tracklist-title]")?.focus();
    });
    importButton?.addEventListener("click", () => {
      const rawImported = (importTextarea?.value || "").split(/\r?\n/).map(parseLine).filter(Boolean);
      const errorRow = rawImported.find((row) => row && row.error);
      if (errorRow) {
        importTextarea.setCustomValidity(errorRow.error);
        importTextarea.reportValidity();
        return;
      }
      importTextarea.setCustomValidity("");
      const imported = rawImported;
      if (!imported.length) return;
      replaceRows(imported);
      importTextarea.value = "";
    });
    importFileButton?.addEventListener("click", () => fileInput?.click());
    fileInput?.addEventListener("change", async () => {
      const file = fileInput.files?.[0];
      if (!file) return;
      try {
        await handleImportFile(file);
        importTextarea?.setCustomValidity("");
      } catch (error) {
        const message = error instanceof Error ? error.message : "Track ID import failed.";
        importTextarea?.setCustomValidity(message);
        importTextarea?.reportValidity();
      }
    });
    editor.closest("form")?.addEventListener("submit", (event) => {
      const validation = serialize();
      if (!validation.blockingCount) return;
      event.preventDefault();
      const firstInvalidRow = rowsRoot.querySelector(".has-time-error");
      firstInvalidRow?.querySelector("[data-tracklist-end], [data-tracklist-start]")?.focus();
      validationSummary?.scrollIntoView({ block: "center", behavior: "smooth" });
    });
    renderInitialRows();
  }

  function initAll() {
    document.querySelectorAll("[data-tracklist-editor]").forEach(initEditor);
  }

  window.addEventListener("mixstream:page-load", initAll);
  document.addEventListener("DOMContentLoaded", initAll);
  initAll();
})();
