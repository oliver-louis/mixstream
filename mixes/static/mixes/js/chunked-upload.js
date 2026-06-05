(function () {
  const PLACEHOLDER_ID = "00000000-0000-0000-0000-000000000000";

  function csrfToken(form) {
    return form.querySelector('input[name="csrfmiddlewaretoken"]')?.value || "";
  }

  function urlFor(template, uploadId) {
    return template.replace(PLACEHOLDER_ID, uploadId);
  }

  function setProgress(form, value, text) {
    const root = form.querySelector("[data-upload-progress]");
    if (!root) return;
    root.hidden = false;
    const fill = root.querySelector("[data-upload-progress-fill]");
    const status = root.querySelector("[data-upload-progress-status]");
    if (fill) fill.style.transform = `scaleX(${Math.max(0, Math.min(1, value))})`;
    if (status) status.textContent = text;
  }

  async function postFormData(url, formData, token) {
    const response = await fetch(url, {
      method: "POST",
      body: formData,
      headers: { "X-CSRFToken": token },
      credentials: "same-origin",
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const fieldErrors = payload.errors
        ? Object.values(payload.errors).flat().map((error) => error.message || String(error)).join(" ")
        : "";
      throw new Error(payload.error || fieldErrors || "Upload failed.");
    }
    return payload;
  }

  function startPayload(form, file, chunkSize) {
    const data = new FormData(form);
    data.delete("audio_file");
    data.append("audio_filename", file.name);
    data.append("audio_content_type", file.type || "");
    data.append("audio_size", String(file.size));
    data.append("chunk_size", String(chunkSize));
    return data;
  }

  async function uploadInChunks(form, file) {
    const token = csrfToken(form);
    const chunkSize = Number(form.dataset.chunkSize || 52428800);
    const submit = form.querySelector('button[type="submit"]');
    submit.disabled = true;
    setProgress(form, 0.01, "Preparing upload...");
    let uploadId = "";
    try {
      const started = await postFormData(form.dataset.chunkStartUrl, startPayload(form, file, chunkSize), token);
      uploadId = started.upload_id;
      const totalChunks = started.total_chunks;
      const chunkUrl = urlFor(form.dataset.chunkUrlTemplate, uploadId);
      for (let index = 0; index < totalChunks; index += 1) {
        const chunk = file.slice(index * chunkSize, Math.min(file.size, (index + 1) * chunkSize));
        const data = new FormData();
        data.append("index", String(index));
        data.append("chunk", chunk, file.name);
        await postFormData(chunkUrl, data, token);
        setProgress(form, (index + 1) / totalChunks, `Uploaded chunk ${index + 1} of ${totalChunks}...`);
      }
      setProgress(form, 1, "Finalizing upload...");
      const completed = await postFormData(urlFor(form.dataset.chunkCompleteUrlTemplate, uploadId), new FormData(), token);
      window.location.assign(completed.redirect_url);
    } catch (error) {
      if (uploadId && form.dataset.chunkAbortUrlTemplate) {
        postFormData(urlFor(form.dataset.chunkAbortUrlTemplate, uploadId), new FormData(), token).catch(() => {});
      }
      setProgress(form, 0, error instanceof Error ? error.message : "Upload failed.");
      submit.disabled = false;
    }
  }

  function initForm(form) {
    if (form._chunkedUploadBound) return;
    form._chunkedUploadBound = true;
    form.addEventListener("submit", (event) => {
      const audio = form.querySelector('input[type="file"][name="audio_file"]');
      const file = audio?.files?.[0];
      if (!file) return;
      event.preventDefault();
      uploadInChunks(form, file);
    });
  }

  function initAll() {
    document.querySelectorAll("[data-chunked-upload]").forEach(initForm);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initAll);
  } else {
    initAll();
  }
  window.addEventListener("mixstream:page-load", initAll);
})();
