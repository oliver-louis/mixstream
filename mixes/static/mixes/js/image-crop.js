(function () {
  let modal = null;
  let activeCropper = null;

  function ensureModal() {
    if (modal) return modal;
    modal = document.createElement("div");
    modal.className = "crop-modal";
    modal.hidden = true;
    modal.innerHTML = `
      <div class="crop-dialog" role="dialog" aria-modal="true" aria-label="Select image">
        <div class="crop-dialog-head">
          <strong>Select image</strong>
          <button type="button" class="icon-button" data-crop-close aria-label="Close">×</button>
        </div>
        <div class="crop-dropzone" data-crop-dropzone tabindex="0">
          <canvas data-crop-canvas width="900" height="900"></canvas>
          <div class="crop-empty" data-crop-empty>
            <strong>Drop or paste an image</strong>
            <span>Browse from your device, drag one here, or press Ctrl/⌘+V.</span>
          </div>
        </div>
        <div class="crop-actions">
          <button class="button secondary" type="button" data-crop-browse>Browse</button>
          <label>
            <span>Zoom</span>
            <input data-crop-zoom type="range" min="1" max="3" step="0.01" value="1">
          </label>
          <button class="button primary" type="button" data-crop-apply disabled>Use image</button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
    return modal;
  }

  function initCropper(root) {
    if (root._cropReady) return;
    root._cropReady = true;

    const input = document.getElementById(root.dataset.inputId);
    const open = root.querySelector("[data-crop-open]");
    const status = root.querySelector("[data-crop-status]");
    if (!input || !open) return;

    input.classList.add("file-input-hidden");
    open.addEventListener("click", () => openModal({ input, status, aspect: Number(root.dataset.aspect || 1), outputName: root.dataset.outputName || "image.jpg" }));
  }

  function imageFileFromTransfer(transfer) {
    const file = Array.from(transfer?.files || []).find((candidate) => candidate.type.startsWith("image/"));
    if (file) return file;
    for (const item of Array.from(transfer?.items || [])) {
      if (item.type.startsWith("image/")) return item.getAsFile();
    }
    return null;
  }

  function openModal(config) {
    const dialog = ensureModal();
    const canvas = dialog.querySelector("[data-crop-canvas]");
    const dropzone = dialog.querySelector("[data-crop-dropzone]");
    const empty = dialog.querySelector("[data-crop-empty]");
    const zoom = dialog.querySelector("[data-crop-zoom]");
    const apply = dialog.querySelector("[data-crop-apply]");
    const browse = dialog.querySelector("[data-crop-browse]");
    const close = dialog.querySelector("[data-crop-close]");
    const ctx = canvas.getContext("2d");
    const aspect = Math.max(0.25, config.aspect || 1);
    const canvasWidth = 900;
    const canvasHeight = Math.round(canvasWidth / aspect);
    const state = { image: null, scale: 1, x: 0, y: 0, dragging: false, startX: 0, startY: 0 };

    activeCropper = { config, state };
    canvas.width = canvasWidth;
    canvas.height = canvasHeight;
    canvas.style.aspectRatio = `${aspect} / 1`;
    zoom.value = "1";
    apply.disabled = true;
    empty.hidden = false;
    draw();
    dialog.hidden = false;
    document.body.classList.add("crop-modal-open");
    dropzone.focus();

    function closeModal() {
      dialog.hidden = true;
      document.body.classList.remove("crop-modal-open");
      activeCropper = null;
    }

    function draw() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = "#0d0f10";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      if (!state.image) return;
      const base = Math.max(canvas.width / state.image.width, canvas.height / state.image.height);
      const scale = base * state.scale;
      const width = state.image.width * scale;
      const height = state.image.height * scale;
      const minX = canvas.width - width;
      const minY = canvas.height - height;
      state.x = Math.min(0, Math.max(minX, state.x));
      state.y = Math.min(0, Math.max(minY, state.y));
      ctx.drawImage(state.image, state.x, state.y, width, height);
    }

    function setInputFile(file) {
      const transfer = new DataTransfer();
      transfer.items.add(file);
      config.input.files = transfer.files;
      config.input.dispatchEvent(new Event("change", { bubbles: true }));
      if (config.status) config.status.textContent = file.name;
    }

    function loadFile(file) {
      if (!file || !file.type.startsWith("image/")) return;
      const image = new Image();
      image.onload = () => {
        state.image = image;
        state.scale = 1;
        state.x = 0;
        state.y = 0;
        zoom.value = "1";
        empty.hidden = true;
        apply.disabled = false;
        draw();
        URL.revokeObjectURL(image.src);
      };
      image.src = URL.createObjectURL(file);
    }

    function pickFromInput() {
      config.input.click();
    }

    function handleDrop(event) {
      event.preventDefault();
      dropzone.classList.remove("is-dragging");
      const file = imageFileFromTransfer(event.dataTransfer);
      if (file) loadFile(file);
    }

    function handlePaste(event) {
      if (dialog.hidden || activeCropper?.config !== config) return;
      const file = imageFileFromTransfer(event.clipboardData);
      if (file) {
        event.preventDefault();
        loadFile(file);
      }
    }

    config.input.onchange = () => loadFile(config.input.files && config.input.files[0]);
    browse.onclick = pickFromInput;
    close.onclick = closeModal;
    zoom.oninput = () => {
      state.scale = Number(zoom.value);
      draw();
    };
    apply.onclick = () => {
      if (!state.image) return;
      canvas.toBlob((blob) => {
        if (!blob) return;
        setInputFile(new File([blob], config.outputName, { type: "image/jpeg" }));
        closeModal();
      }, "image/jpeg", 0.9);
    };
    dropzone.ondragover = (event) => {
      event.preventDefault();
      dropzone.classList.add("is-dragging");
    };
    dropzone.ondragleave = () => dropzone.classList.remove("is-dragging");
    dropzone.ondrop = handleDrop;
    canvas.onpointerdown = (event) => {
      if (!state.image) return;
      state.dragging = true;
      state.startX = event.clientX - state.x;
      state.startY = event.clientY - state.y;
      canvas.setPointerCapture(event.pointerId);
    };
    canvas.onpointermove = (event) => {
      if (!state.dragging) return;
      state.x = event.clientX - state.startX;
      state.y = event.clientY - state.startY;
      draw();
    };
    canvas.onpointerup = () => {
      state.dragging = false;
    };
    document.onpaste = handlePaste;
    document.onkeydown = (event) => {
      if (!dialog.hidden && event.key === "Escape") closeModal();
    };
  }

  function initAll() {
    document.querySelectorAll("[data-image-crop]").forEach(initCropper);
  }

  window.addEventListener("mixstream:page-load", initAll);
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initAll);
  } else {
    initAll();
  }
})();
