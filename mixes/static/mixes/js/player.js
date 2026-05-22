(function () {
  const player = document.querySelector("[data-player]");
  if (!player) return;

  const audio = player.querySelector("[data-player-audio]");
  const toggle = player.querySelector("[data-player-toggle]");
  const title = player.querySelector("[data-player-title]");
  const artist = player.querySelector("[data-player-artist]");
  const cover = player.querySelector("[data-player-cover]");
  const progress = player.querySelector(".player-progress-fill");
  const progressTrack = player.querySelector("[data-player-progress]");
  const progressMarkers = player.querySelector("[data-player-progress-markers]");
  const time = player.querySelector("[data-player-time]");
  const duration = player.querySelector("[data-player-duration]");
  const volumeToggle = player.querySelector("[data-volume-toggle]");
  const volumeSlider = player.querySelector("[data-volume-slider]");
  const DEFAULT_COVER = document.body?.dataset.defaultCover || "/static/mixes/branding/defaultcover.png";
  const ROOT_STYLES = getComputedStyle(document.documentElement);
  const PLAYED_WAVE_COLOR = ROOT_STYLES.getPropertyValue("--accent").trim() || "#fe640b";
  const HOVER_WAVE_COLOR = ROOT_STYLES.getPropertyValue("--sky").trim() || "#04a5e5";

  function withAlpha(hex, alpha) {
    const value = (hex || "").trim().replace("#", "");
    const expanded = value.length === 3 ? value.split("").map((char) => char + char).join("") : value;
    if (expanded.length !== 6) return `rgba(255,255,255,${alpha})`;
    const r = parseInt(expanded.slice(0, 2), 16);
    const g = parseInt(expanded.slice(2, 4), 16);
    const b = parseInt(expanded.slice(4, 6), 16);
    return `rgba(${r},${g},${b},${alpha})`;
  }

  let currentStreamUrl = "";
  let currentTrack = null;
  let currentTrackData = null;
  let streamCounted = false;
  let mobilePauseIconHeld = false;
  let cueOverride = null;
  let playbackFrame = 0;
  let hasPlaybackStarted = false;
  let mediaSessionBound = false;

  function formatTime(value) {
    if (!Number.isFinite(value)) return "0:00";
    const hours = Math.floor(value / 3600);
    const minutes = Math.floor((value % 3600) / 60);
    const seconds = Math.floor(value % 60).toString().padStart(2, "0");
    if (hours) return `${hours}:${minutes.toString().padStart(2, "0")}:${seconds}`;
    return `${minutes}:${seconds}`;
  }

  function absoluteUrl(url) {
    if (!url) return "";
    try {
      return new URL(url, window.location.href).href;
    } catch (error) {
      return url;
    }
  }

  function mediaSessionArtwork(imageUrl) {
    const artwork = absoluteUrl(imageUrl || DEFAULT_COVER);
    return [
      { src: artwork, sizes: "96x96", type: "image/webp" },
      { src: artwork, sizes: "192x192", type: "image/webp" },
      { src: artwork, sizes: "256x256", type: "image/webp" },
      { src: artwork, sizes: "512x512", type: "image/webp" },
    ];
  }

  function bindMediaSessionActions() {
    if (!("mediaSession" in navigator) || mediaSessionBound) return;
    mediaSessionBound = true;
    navigator.mediaSession.setActionHandler("play", () => playAudio());
    navigator.mediaSession.setActionHandler("pause", () => pauseAudio());
    navigator.mediaSession.setActionHandler("seekbackward", (details) => {
      seekBySeconds(-(details?.seekOffset || 10));
    });
    navigator.mediaSession.setActionHandler("seekforward", (details) => {
      seekBySeconds(details?.seekOffset || 10);
    });
    navigator.mediaSession.setActionHandler("seekto", (details) => {
      if (!Number.isFinite(details?.seekTime)) return;
      const total = audio.duration || Number(currentTrackData?.duration || 0);
      if (!total) return;
      audio.currentTime = Math.max(0, Math.min(total, details.seekTime));
      triggerSeekCue(currentTrack, audio.currentTime);
      syncPlaybackVisuals();
    });
  }

  function updateMediaSession() {
    if (!("mediaSession" in navigator)) return;
    bindMediaSessionActions();
    if (!currentTrackData) {
      navigator.mediaSession.metadata = null;
      return;
    }
    navigator.mediaSession.metadata = new MediaMetadata({
      title: currentTrackData.title || "MixStream",
      artist: currentTrackData.artist || "",
      album: "MixStream",
      artwork: mediaSessionArtwork(currentTrackData.cover),
    });
    navigator.mediaSession.playbackState = audio.paused ? "paused" : "playing";
    if (Number.isFinite(audio.duration) && audio.duration > 0) {
      navigator.mediaSession.setPositionState({
        duration: audio.duration,
        playbackRate: audio.playbackRate || 1,
        position: Math.max(0, Math.min(audio.duration, audio.currentTime || 0)),
      });
    }
  }

  function waveformValues(root) {
    try {
      const values = JSON.parse(root.dataset.waveform || "[]");
      if (Array.isArray(values) && values.length) return values.map(Number);
    } catch (error) {
      return [];
    }
    return Array.from({ length: 180 }, (_, index) => 0.16 + Math.abs(Math.sin(index * 0.19)) * 0.72);
  }

  function tracklistValues(root) {
    const scriptId = root.dataset.tracklistScript;
    if (!scriptId) return [];
    const script = document.getElementById(scriptId);
    if (!script) return [];
    try {
      const values = JSON.parse(script.textContent || "[]");
      if (!Array.isArray(values)) return [];
      return values
        .map((item, index) => {
          const startSeconds = Number(item.start_seconds);
          const endRaw = item.end_seconds;
          const parsedEnd = endRaw === null || endRaw === undefined || endRaw === "" ? null : Number(endRaw);
          const endSeconds = Number.isFinite(parsedEnd) && Number.isFinite(startSeconds) && parsedEnd > startSeconds ? parsedEnd : null;
          return {
            key: Number(item.position) || index + 1,
            title: item.title || "",
            artist: item.artist || "",
            links: item.links && typeof item.links === "object" ? item.links : {},
            startSeconds,
            endSeconds,
            start: item.start || "",
            end: item.end || "",
          };
        })
        .filter((item) => item.title && Number.isFinite(item.startSeconds))
        .sort((a, b) => a.startSeconds - b.startSeconds);
    } catch (error) {
      return [];
    }
  }

  function seekToRatio(ratio) {
    if (!audio.duration) return;
    audio.currentTime = Math.max(0, Math.min(1, ratio)) * audio.duration;
  }

  function triggerSeekCue(root, seconds) {
    if (!root || currentTrack !== root || !currentTrackData?.tracklist?.length) return;
    const item = currentPlayingTracklistItems(currentTrackData.tracklist, seconds)[0];
    if (!item || item.unknown) {
      cueOverride = null;
      return;
    }
    cueOverride = {
      item,
      expiresAt: Date.now() + 3000,
    };
  }

  function prefersMp3Fallback() {
    const ua = navigator.userAgent || "";
    const isAppleMobile = /iPad|iPhone|iPod/.test(ua) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
    const isSafari = /^((?!chrome|android|crios|fxios|edgios).)*safari/i.test(ua);
    return isAppleMobile || isSafari;
  }

  function preferredAudioUrl(root) {
    const opusUrl = root.dataset.audioUrl || "";
    const mp3Url = root.dataset.audioMp3Url || "";
    if (mp3Url && prefersMp3Fallback()) return mp3Url;
    if (opusUrl && audio.canPlayType("audio/ogg; codecs=opus")) return opusUrl;
    return mp3Url || opusUrl;
  }

  function isCurrentRoot(root) {
    if (!currentTrackData) return false;
    return [root.dataset.audioUrl, root.dataset.audioMp3Url].filter(Boolean).includes(currentTrackData.audioUrl);
  }

  function isMobileHero(root) {
    return root.classList.contains("hero-waveform") && window.matchMedia("(max-width: 820px)").matches;
  }

  function pointerRatio(event, canvas) {
    const rect = canvas.getBoundingClientRect();
    const localRatio = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
    if (typeof canvas._waveStart === "number" && typeof canvas._waveVisible === "number") {
      return canvas._waveStart + localRatio * canvas._waveVisible;
    }
    return localRatio;
  }

  function groupedValues(values, count) {
    const grouped = [];
    for (let index = 0; index < count; index += 1) {
      const start = Math.floor((index / count) * values.length);
      const end = Math.max(start + 1, Math.floor(((index + 1) / count) * values.length));
      grouped.push(Math.max(...values.slice(start, end)));
    }
    return grouped;
  }

  function paintCanvas(canvas, values, ratio, follow = false, reflect = false, previewRatio = null) {
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    const width = Math.max(1, Math.floor(rect.width * dpr));
    const height = Math.max(1, Math.floor(rect.height * dpr));
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, width, height);
    const mid = reflect ? Math.floor(height * 0.56) : height / 2;
    const gap = Math.max(1, Math.floor(2 * dpr));
    const visibleBars = Math.max(44, Math.floor(width / (4 * dpr)));
    const totalBars = follow ? Math.max(visibleBars * 4, Math.min(values.length, 720)) : Math.max(36, Math.min(values.length, visibleBars));
    const allBars = groupedValues(values, totalBars);
    const halfWindow = follow ? Math.floor(visibleBars / 2) : 0;
    const visibleRatio = follow ? visibleBars / totalBars : 1;
    const centeredIndex = follow ? ratio * Math.max(1, totalBars - 1) : 0;
    const startIndex = follow ? Math.round(centeredIndex - halfWindow) : 0;
    const endIndex = follow ? startIndex + visibleBars : totalBars;
    const grouped = follow
      ? Array.from({ length: visibleBars }, (_, index) => allBars[startIndex + index] || 0)
      : allBars;
    canvas._waveStart = follow ? startIndex / totalBars : 0;
    canvas._waveVisible = visibleRatio;
    const barStep = width / Math.max(1, grouped.length);
    const barWidth = Math.max(2, Math.floor(barStep - gap));
    grouped.forEach((raw, index) => {
      const dataIndex = follow ? startIndex + index : index;
      if (follow && (dataIndex < 0 || dataIndex >= totalBars)) return;
      const x = Math.floor(index * barStep);
      const value = Math.max(0.04, Math.min(1, Number(raw) || 0.05));
      const barHeight = Math.max(5 * dpr, value * height * (reflect ? 0.43 : 0.48));
      const globalRatio = dataIndex / Math.max(1, totalBars - 1);
      const played = globalRatio <= ratio;
      const previewed = Number.isFinite(previewRatio) && globalRatio <= previewRatio && !played;
      ctx.fillStyle = played ? PLAYED_WAVE_COLOR : previewed ? HOVER_WAVE_COLOR : "rgba(255,255,255,.88)";
      if (reflect) {
        ctx.fillRect(x, mid - barHeight, barWidth, barHeight);
        if (previewed) {
          ctx.fillStyle = "rgba(255,255,255,.2)";
          ctx.fillRect(x, mid - barHeight, barWidth, barHeight);
        }
        ctx.fillStyle = played ? withAlpha(PLAYED_WAVE_COLOR, 0.34) : previewed ? withAlpha(HOVER_WAVE_COLOR, 0.8) : "rgba(255,255,255,.24)";
        ctx.fillRect(x, mid + 1 * dpr, barWidth, barHeight * 0.46);
        if (previewed) {
          ctx.fillStyle = "rgba(255,255,255,.12)";
          ctx.fillRect(x, mid + 1 * dpr, barWidth, barHeight * 0.46);
        }
      } else {
        ctx.fillRect(x, mid - barHeight, barWidth, barHeight * 2);
        if (previewed) {
          ctx.fillStyle = "rgba(255,255,255,.2)";
          ctx.fillRect(x, mid - barHeight, barWidth, barHeight * 2);
        }
      }
    });
  }

  function bindWaveform(root) {
    if (root._waveformBound) return;
    root._waveformBound = true;
    const canvas = root.querySelector("[data-wave-canvas]");
    if (!canvas) return;
    const values = waveformValues(root);
    root._waveformValues = values;
    root._waveformCanvas = canvas;
    paintCanvas(canvas, values, 0);

    let dragging = false;
    let moved = false;
    let startX = 0;
    let startTime = 0;
    const activate = (event) => {
      if (!preferredAudioUrl(root)) return;
      if (currentTrack !== root) loadTrack(root, false);
      seekToRatio(pointerRatio(event, canvas));
      triggerSeekCue(root, audio.currentTime);
      playAudio();
    };
    const seekByDrag = (event) => {
      if (currentTrack !== root) loadTrack(root, false);
      const rect = canvas.getBoundingClientRect();
      const durationValue = audio.duration || Number(root.dataset.duration || 0);
      if (!durationValue) return;
      const visible = typeof canvas._waveVisible === "number" ? canvas._waveVisible : 0.25;
      const deltaRatio = ((startX - event.clientX) / Math.max(1, rect.width)) * visible * 1.6;
      audio.currentTime = Math.max(0, Math.min(durationValue, startTime + deltaRatio * durationValue));
      triggerSeekCue(root, audio.currentTime);
      renderAllWaveforms();
      updateWaveTimes();
    };
    canvas.addEventListener("pointerdown", (event) => {
      dragging = true;
      moved = false;
      startX = event.clientX;
      startTime = currentTrack === root ? audio.currentTime : 0;
      canvas.setPointerCapture(event.pointerId);
      if (isMobileHero(root)) {
        if (currentTrack !== root) loadTrack(root, false);
        return;
      }
      activate(event);
    });
    canvas.addEventListener("pointermove", (event) => {
      if (!dragging) {
        if (!isMobileHero(root)) {
          root._hoverRatio = pointerRatio(event, canvas);
          renderAllWaveforms();
        }
        return;
      }
      if (Math.abs(event.clientX - startX) > 4) moved = true;
      if (isMobileHero(root)) seekByDrag(event);
      else activate(event);
    });
    canvas.addEventListener("pointerup", () => {
      if (isMobileHero(root) && !moved) {
        if (currentTrack !== root) loadTrack(root, false);
        if (audio.paused) playAudio();
        else pauseAudio(true);
      }
      dragging = false;
    });
    canvas.addEventListener("pointerleave", () => {
      root._hoverRatio = null;
      if (!dragging) renderAllWaveforms();
    });
    canvas.addEventListener("pointercancel", () => {
      dragging = false;
      root._hoverRatio = null;
      renderAllWaveforms();
    });
    canvas.addEventListener("click", (event) => {
      if (!isMobileHero(root)) activate(event);
    });
  }

  function renderAllWaveforms() {
    const ratio = audio.duration ? audio.currentTime / audio.duration : 0;
    document.querySelectorAll("[data-waveform]").forEach((root) => {
      if (!root._waveformCanvas) return;
      const isCurrent = isCurrentRoot(root);
      const follow = isMobileHero(root);
      const previewRatio = !follow && Number.isFinite(root._hoverRatio) ? root._hoverRatio : null;
      paintCanvas(root._waveformCanvas, root._waveformValues || waveformValues(root), isCurrent ? ratio : 0, follow, follow, previewRatio);
    });
  }

  function syncPlaybackVisuals() {
    const ratio = audio.duration ? audio.currentTime / audio.duration : 0;
    time.textContent = formatTime(audio.currentTime);
    const total = audio.duration || Number(currentTrackData?.duration || 0);
    duration.textContent = formatTime(Math.max(0, total - (audio.currentTime || 0)));
    if (progress) progress.style.transform = `scaleX(${ratio})`;
    updateProgressMarkersState();
    renderAllWaveforms();
    updateWaveTimes();
    updateTracklistCue();
  }

  function stopPlaybackLoop() {
    if (!playbackFrame) return;
    cancelAnimationFrame(playbackFrame);
    playbackFrame = 0;
  }

  function startPlaybackLoop() {
    if (playbackFrame) return;
    const tick = () => {
      playbackFrame = 0;
      syncPlaybackVisuals();
      if (!audio.paused && !audio.ended) {
        playbackFrame = requestAnimationFrame(tick);
      }
    };
    playbackFrame = requestAnimationFrame(tick);
  }

  function setArtwork(element, imageUrl) {
    const artwork = imageUrl || DEFAULT_COVER;
    element.style.backgroundImage = `url("${artwork}")`;
    element.classList.add("has-cover");
  }

  function shouldShowProgressMarkers() {
    if (!progressTrack || !currentTrackData?.tracklist?.length) return false;
    const width = progressTrack.getBoundingClientRect().width;
    return window.matchMedia("(min-width: 900px)").matches && width >= 220;
  }

  function renderProgressMarkers() {
    if (!progressMarkers || !progressTrack) return;
    progressMarkers.replaceChildren();
    progressTrack.classList.remove("has-markers");
    if (!currentTrackData?.tracklist?.length || !shouldShowProgressMarkers()) return;
    const total = audio.duration || Number(currentTrackData.duration || 0);
    if (!Number.isFinite(total) || total <= 0) return;
    const fragment = document.createDocumentFragment();
    currentTrackData.tracklist
      .filter((item) => Number.isFinite(item.startSeconds) && item.startSeconds > 0 && item.startSeconds < total)
      .forEach((item) => {
        const marker = document.createElement("span");
        marker.className = "player-progress-marker";
        marker.dataset.startSeconds = String(item.startSeconds);
        marker.style.left = `${(item.startSeconds / total) * 100}%`;
        fragment.appendChild(marker);
      });
    progressMarkers.appendChild(fragment);
    progressTrack.classList.add("has-markers");
    updateProgressMarkersState();
  }

  function updateProgressMarkersState() {
    if (!progressMarkers) return;
    const seconds = audio.currentTime || 0;
    progressMarkers.querySelectorAll(".player-progress-marker").forEach((marker) => {
      const startSeconds = Number(marker.dataset.startSeconds);
      marker.classList.toggle("is-played", Number.isFinite(startSeconds) && seconds >= startSeconds);
    });
  }

  function resolveTrackRoot(source) {
    if (source.dataset.waveform) return source;
    const detail = source.closest(".mix-detail");
    if (detail) {
      const detailWaveform = detail.querySelector("[data-waveform]");
      if (detailWaveform) return detailWaveform;
    }
    const card = source.closest(".mix-card");
    if (card) return card.querySelector("[data-waveform]") || source;
    return source.closest("[data-waveform]") || source;
  }

  function sameDetailPath(left, right) {
    if (!left || !right) return false;
    return new URL(left, window.location.href).pathname === new URL(right, window.location.href).pathname;
  }

  function syncCurrentTrackContextFromPage() {
    if (!currentTrackData?.detailUrl) return;
    const pageRoot = Array.from(document.querySelectorAll("[data-waveform]")).find((root) =>
      sameDetailPath(root.dataset.detailUrl || "", currentTrackData.detailUrl),
    );
    if (!pageRoot) return;
    currentTrack = pageRoot;
    currentTrackData = {
      ...currentTrackData,
      title: pageRoot.dataset.title || currentTrackData.title,
      artist: pageRoot.dataset.artist || currentTrackData.artist,
      cover: pageRoot.dataset.cover || currentTrackData.cover,
      streamUrl: pageRoot.dataset.streamUrl || currentTrackData.streamUrl,
      duration: Number(pageRoot.dataset.duration || currentTrackData.duration || 0),
      tracklist: tracklistValues(pageRoot),
    };
    currentStreamUrl = currentTrackData.streamUrl;
    title.textContent = currentTrackData.title;
    artist.textContent = currentTrackData.artist;
    setArtwork(cover, currentTrackData.cover);
    updateMediaSession();
    renderProgressMarkers();
    updateTracklistCue();
    renderAllWaveforms();
  }

  function loadTrack(source, autoplay = true) {
    const root = resolveTrackRoot(source);
    const audioUrl = preferredAudioUrl(root);
    if (!audioUrl) return;
    currentTrack = root;
    currentTrackData = {
      audioUrl,
      opusUrl: root.dataset.audioUrl || "",
      mp3Url: root.dataset.audioMp3Url || "",
      title: root.dataset.title,
      artist: root.dataset.artist,
      cover: root.dataset.cover,
      streamUrl: root.dataset.streamUrl || root.dataset.playUrl || "",
      detailUrl: root.dataset.detailUrl || "",
      duration: Number(root.dataset.duration || 0),
      tracklist: tracklistValues(root),
    };
    currentStreamUrl = currentTrackData.streamUrl;
    streamCounted = false;
    cueOverride = null;
    hasPlaybackStarted = false;
    if (audio.src !== new URL(currentTrackData.audioUrl, window.location.href).href) {
      audio.src = currentTrackData.audioUrl;
    }
    title.textContent = currentTrackData.title;
    artist.textContent = currentTrackData.artist;
    setArtwork(cover, currentTrackData.cover);
    updateMediaSession();
    renderProgressMarkers();
    player.hidden = false;
    renderAllWaveforms();
    if (autoplay) playAudio();
    updatePlayButtons();
    updateTracklistCue();
  }

  function swapToMp3Fallback() {
    if (!currentTrackData || !currentTrackData.mp3Url || currentTrackData.audioUrl === currentTrackData.mp3Url) return false;
    const wasPaused = audio.paused;
    const previousTime = audio.currentTime || 0;
    currentTrackData.audioUrl = currentTrackData.mp3Url;
    audio.src = currentTrackData.mp3Url;
    audio.addEventListener("loadedmetadata", () => {
      if (previousTime && audio.duration) {
        audio.currentTime = Math.min(previousTime, Math.max(0, audio.duration - 0.25));
      }
      if (!wasPaused) playAudio();
    }, { once: true });
    audio.load();
    return true;
  }

  function playAudio() {
    mobilePauseIconHeld = false;
    const playPromise = audio.play();
    updatePlayButtons(true);
    if (playPromise && typeof playPromise.catch === "function") {
      playPromise.catch(() => updatePlayButtons());
    }
  }

  function pauseAudio(holdPauseIcon = false) {
    mobilePauseIconHeld = holdPauseIcon;
    audio.pause();
    updatePlayButtons(false);
  }

  function dismissPlayerForEditor() {
    stopPlaybackLoop();
    audio.pause();
    audio.removeAttribute("src");
    audio.load();
    currentStreamUrl = "";
    currentTrack = null;
    currentTrackData = null;
    streamCounted = false;
    mobilePauseIconHeld = false;
    cueOverride = null;
    hasPlaybackStarted = false;
    if (progress) progress.style.transform = "scaleX(0)";
    title.textContent = "";
    artist.textContent = "";
    time.textContent = "0:00";
    duration.textContent = "0:00";
    progressMarkers?.replaceChildren();
    progressTrack?.classList.remove("has-markers");
    player.hidden = true;
    renderAllWaveforms();
    updateWaveTimes();
    updateTracklistCue();
    updatePlayButtons(false);
    updateMediaSession();
  }

  function seekBySeconds(delta) {
    const total = audio.duration || Number(currentTrackData?.duration || 0);
    if (!total) return;
    audio.currentTime = Math.max(0, Math.min(total, audio.currentTime + delta));
    triggerSeekCue(currentTrack, audio.currentTime);
    updateMediaSession();
    renderAllWaveforms();
    updateWaveTimes();
    updateTracklistCue();
  }

  function isTypingTarget(element) {
    if (!element) return false;
    const tag = element.tagName;
    return element.isContentEditable || tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || tag === "BUTTON";
  }

  function openFullPlayer() {
    if (!currentTrackData) return;
    const detailUrl = currentTrackData.detailUrl;
    if (!detailUrl) return;
    if (window.location.pathname === new URL(detailUrl, window.location.href).pathname) {
      window.scrollTo({ top: 0, behavior: "smooth" });
      return;
    }
    visit(detailUrl);
  }

  function currentCodec() {
    if (!currentTrackData) return "";
    return currentTrackData.audioUrl === currentTrackData.mp3Url ? "mp3" : "opus";
  }

  function countStream() {
    if (streamCounted || !currentStreamUrl) return;
    const percent = audio.duration ? Math.round((audio.currentTime / audio.duration) * 100) : 0;
    if (percent < 10 && audio.currentTime < 20) return;
    streamCounted = true;
    fetch(currentStreamUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": document.cookie.match(/csrftoken=([^;]+)/)?.[1] || "",
      },
      body: JSON.stringify({
        codec: currentCodec(),
        seconds_listened: Math.floor(audio.currentTime),
        percent_listened: percent,
      }),
    }).catch(() => {});
  }

  function countViews() {
    document.querySelectorAll("[data-view-url]").forEach((root) => {
      if (root._viewCounted) return;
      root._viewCounted = true;
      fetch(root.dataset.viewUrl, {
        method: "POST",
        headers: { "X-CSRFToken": document.cookie.match(/csrftoken=([^;]+)/)?.[1] || "" },
      }).catch(() => {});
    });
  }

  function setTracklistPanelState(panel, isOpen) {
    if (!panel) return;
    panel.classList.toggle("is-open", isOpen);
    panel.hidden = !isOpen;
    const owner = panel.closest(".mix-detail");
    owner?.querySelectorAll("[data-tracklist-toggle]").forEach((button) => {
      button.setAttribute("aria-expanded", isOpen ? "true" : "false");
      button.textContent = isOpen ? "Hide Track IDs" : "Track IDs";
      button.classList.toggle("is-open", isOpen);
    });
  }

  function bindPage() {
    document.querySelectorAll("[data-waveform]").forEach(bindWaveform);
    syncCurrentTrackContextFromPage();
    document.querySelectorAll("[data-play-card], .play-small").forEach((button) => {
      if (button._playBound) return;
      button._playBound = true;
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        const root = resolveTrackRoot(button.closest("[data-waveform]") || button);
        if (!preferredAudioUrl(root)) return;
        const isCurrent = isCurrentRoot(root);
        if (isCurrent) {
          if (audio.paused) playAudio();
          else pauseAudio();
        } else {
          loadTrack(root);
        }
      });
    });
    document.querySelectorAll("a[href]").forEach((link) => {
      if (link._pjaxBound) return;
      link._pjaxBound = true;
      link.addEventListener("click", (event) => {
        if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        const url = new URL(link.href, window.location.href);
        if (!canVisit(url)) return;
        event.preventDefault();
        visit(url.href);
      });
    });
    document.querySelectorAll("[data-mobile-back]").forEach((button) => {
      if (button._mobileBackBound) return;
      button._mobileBackBound = true;
      button.addEventListener("click", () => {
        if (document.referrer && new URL(document.referrer).origin === window.location.origin && history.length > 1) {
          history.back();
        } else {
          visit("/");
        }
      });
    });
    document.querySelectorAll("[data-tracklist-toggle]").forEach((button) => {
      if (button._tracklistToggleBound) return;
      button._tracklistToggleBound = true;
      button.setAttribute("aria-expanded", "false");
      button.addEventListener("click", () => {
        const panel = button.closest(".mix-detail")?.querySelector("[data-mobile-tracklist]");
        if (!panel) return;
        setTracklistPanelState(panel, panel.hidden);
      });
    });
    document.querySelectorAll("[data-tracklist-close]").forEach((button) => {
      if (button._tracklistCloseBound) return;
      button._tracklistCloseBound = true;
      button.addEventListener("click", () => {
        const panel = button.closest("[data-mobile-tracklist]");
        if (!panel) return;
        setTracklistPanelState(panel, false);
      });
    });
    document.querySelectorAll("[data-track-seek-seconds]").forEach((button) => {
      if (button._trackSeekBound) return;
      button._trackSeekBound = true;
      button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        const seconds = Number(button.dataset.trackSeekSeconds);
        if (!Number.isFinite(seconds)) return;
        const root = resolveTrackRoot(button.closest(".mix-detail") || button);
        if (!preferredAudioUrl(root)) return;
        if (!isCurrentRoot(root)) {
          loadTrack(root, false);
        }
        const seekToSeconds = () => {
          if (!audio.duration) return;
          audio.currentTime = Math.max(0, Math.min(seconds, Math.max(0, audio.duration - 0.1)));
          triggerSeekCue(root, audio.currentTime);
          if (audio.paused) playAudio();
          updateTracklistCue();
          renderAllWaveforms();
        };
        if (audio.readyState >= 1 && audio.duration) {
          seekToSeconds();
        } else {
          audio.addEventListener("loadedmetadata", seekToSeconds, { once: true });
        }
      });
    });
    renderAllWaveforms();
    updateWaveTimes();
    updateTracklistCue();
    updatePlayButtons();
    countViews();
    window.dispatchEvent(new CustomEvent("mixstream:page-load"));
  }

  function canVisit(url) {
    if (url.origin !== window.location.origin) return false;
    if (url.pathname.startsWith("/admin/")) return false;
    if (url.pathname.startsWith("/oidc/")) return false;
    if (url.pathname.startsWith("/login/")) return false;
    if (url.pathname.includes("/audio/")) return false;
    return true;
  }

  async function visit(url, push = true) {
    const response = await fetch(url, { headers: { "X-Requested-With": "fetch" } });
    if (!response.ok) {
      window.location.href = url;
      return;
    }
    const html = await response.text();
    const doc = new DOMParser().parseFromString(html, "text/html");
    const nextMain = doc.querySelector("main.shell");
    const currentMain = document.querySelector("main.shell");
    if (!nextMain || !currentMain) {
      window.location.href = url;
      return;
    }
    document.title = doc.title;
    document.body.className = doc.body.className;
    currentMain.replaceWith(nextMain);
    if (push) history.pushState({}, "", url);
    window.scrollTo({ top: 0 });
    bindPage();
  }

  toggle.addEventListener("click", () => {
    if (audio.paused) playAudio();
    else pauseAudio();
  });

  if (volumeSlider) {
    volumeSlider.addEventListener("input", () => {
      audio.volume = Number(volumeSlider.value);
      audio.muted = audio.volume === 0;
      updateVolumeButton();
    });
  }
  if (volumeToggle) {
    volumeToggle.addEventListener("click", () => {
      audio.muted = !audio.muted;
      updateVolumeButton();
    });
  }

  if (progressTrack) {
    const seekProgress = (event) => {
      const rect = progressTrack.getBoundingClientRect();
      seekToRatio((event.clientX - rect.left) / rect.width);
      triggerSeekCue(currentTrack, audio.currentTime);
    };
    progressTrack.addEventListener("click", (event) => {
      event.stopPropagation();
      seekProgress(event);
    });
    progressTrack.addEventListener("pointerdown", (event) => {
      event.stopPropagation();
      progressTrack.setPointerCapture(event.pointerId);
      seekProgress(event);
    });
    progressTrack.addEventListener("pointermove", (event) => {
      event.stopPropagation();
      if (event.buttons) seekProgress(event);
    });
  }

  document.addEventListener("keydown", (event) => {
    if (event.repeat || isTypingTarget(document.activeElement) || !currentTrackData) return;
    if (event.code === "ArrowLeft" || event.code === "ArrowRight") {
      event.preventDefault();
      seekBySeconds(event.code === "ArrowLeft" ? -10 : 10);
      return;
    }
    if (event.code !== "Space") return;
    event.preventDefault();
    if (audio.paused) playAudio();
    else pauseAudio();
  });

  document.querySelectorAll("[data-player-open]").forEach((target) => {
    target.addEventListener("click", openFullPlayer);
    target.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") openFullPlayer();
    });
  });

  audio.addEventListener("play", () => {
    hasPlaybackStarted = true;
    toggle.textContent = "Ⅱ";
    updatePlayButtons();
    updateMediaSession();
    syncPlaybackVisuals();
    startPlaybackLoop();
  });
  audio.addEventListener("pause", () => {
    stopPlaybackLoop();
    toggle.textContent = "▶";
    updatePlayButtons();
    updateMediaSession();
    syncPlaybackVisuals();
  });
  audio.addEventListener("loadedmetadata", () => {
    duration.textContent = formatTime(audio.duration);
    updateMediaSession();
    renderProgressMarkers();
    updateWaveTimes();
  });
  audio.addEventListener("error", () => {
    if (!swapToMp3Fallback()) updatePlayButtons();
  });
  audio.addEventListener("timeupdate", () => {
    updateMediaSession();
    syncPlaybackVisuals();
    countStream();
  });
  audio.addEventListener("ended", () => {
    stopPlaybackLoop();
    updateMediaSession();
    syncPlaybackVisuals();
    updatePlayButtons(false);
  });
  audio.addEventListener("volumechange", updateVolumeButton);

  function updatePlayButtons(forcePlaying = null) {
    const isPlaying = forcePlaying === null ? !audio.paused : forcePlaying;
    toggle.textContent = isPlaying ? "Ⅱ" : "▶";
    document.querySelectorAll("[data-play-card], .play-small").forEach((button) => {
      const root = resolveTrackRoot(button.closest("[data-waveform]") || button);
      const isCurrent = isCurrentRoot(root);
      button.textContent = isCurrent && (isPlaying || mobilePauseIconHeld) ? "Ⅱ" : "▶";
      button.classList.toggle("is-playing", Boolean(isCurrent && isPlaying));
      button.classList.toggle("is-paused", Boolean(isCurrent && !isPlaying));
      if (root.dataset.waveform) {
        root.classList.toggle("is-playing", Boolean(isCurrent && isPlaying));
        root.classList.toggle("is-paused", Boolean(isCurrent && !isPlaying));
      }
    });
  }

  function updateWaveTimes() {
    document.querySelectorAll("[data-waveform]").forEach((root) => {
      const isCurrent = isCurrentRoot(root);
      const current = root.querySelector("[data-wave-current]");
      const remaining = root.querySelector("[data-wave-remaining]");
      const total = root.querySelector("[data-wave-duration]");
      const totalSeconds = isCurrent && audio.duration ? audio.duration : Number(root.dataset.duration || 0);
      if (current) current.textContent = formatTime(isCurrent ? audio.currentTime : 0);
      if (remaining) {
        const showRemaining = isCurrent && hasPlaybackStarted && Number.isFinite(totalSeconds) && totalSeconds > 0;
        remaining.hidden = !showRemaining;
        remaining.textContent = `(${formatTime(Math.max(0, totalSeconds - (isCurrent ? audio.currentTime : 0)))})`;
      }
      if (total) total.textContent = formatTime(totalSeconds);
    });
  }

  function activeTracklistItem(items, seconds) {
    if (!items || !items.length) return null;
    for (let index = 0; index < items.length; index += 1) {
      const item = items[index];
      const next = items[index + 1];
      const end = Number.isFinite(item.endSeconds) ? item.endSeconds : next?.startSeconds;
      if (seconds >= item.startSeconds && (end === undefined || end === null || seconds < end)) {
        return item;
      }
    }
    return null;
  }

  function recentlyTriggeredTracklistItem(items, seconds) {
    if (!items || !items.length) return null;
    for (let index = items.length - 1; index >= 0; index -= 1) {
      const item = items[index];
      if (seconds >= item.startSeconds && seconds < item.startSeconds + 10) return item;
    }
    return null;
  }

  function currentPlayingTracklistItems(items, seconds) {
    if (!items || !items.length) return [];
    const activeItems = items
      .filter((item, index) => {
        if (!Number.isFinite(item.startSeconds) || seconds < item.startSeconds) return false;
        const next = items[index + 1];
        const hasExplicitEnd = Number.isFinite(item.endSeconds) && item.endSeconds > item.startSeconds;
        if (hasExplicitEnd) {
          return seconds < item.endSeconds;
        }
        if (Number.isFinite(next?.startSeconds)) {
          return seconds < next.startSeconds;
        }
        return seconds < item.startSeconds + 600;
      })
      .sort((left, right) => right.startSeconds - left.startSeconds);
    if (activeItems.length) return activeItems;
    const last = items[items.length - 1];
    const lastHasExplicitEnd = Number.isFinite(last?.endSeconds) && last.endSeconds > last.startSeconds;
    if (!lastHasExplicitEnd && Number.isFinite(last?.startSeconds) && seconds >= last.startSeconds + 600) {
      return [{ artist: "???", title: "???", unknown: true, key: "unknown-final" }];
    }
    return [];
  }

  function cuePlayheadX(root, ratio) {
    const canvas = root?._waveformCanvas;
    if (!canvas) return 0;
    const rect = canvas.getBoundingClientRect();
    if (!rect.width) return 0;
    if (isMobileHero(root) && typeof canvas._waveStart === "number" && typeof canvas._waveVisible === "number" && canvas._waveVisible > 0) {
      const localRatio = (ratio - canvas._waveStart) / canvas._waveVisible;
      return Math.max(0, Math.min(1, localRatio)) * rect.width;
    }
    return Math.max(0, Math.min(1, ratio)) * rect.width;
  }

  function clearTracklistHighlights() {
    document.querySelectorAll(".tracklist-item.is-active").forEach((row) => row.classList.remove("is-active"));
  }

  function updateTracklistActiveRows(items) {
    const activeKeys = new Set(
      (Array.isArray(items) ? items : [])
        .filter((item) => item && !item.unknown)
        .map((item) => String(item.key)),
    );
    document.querySelectorAll(".tracklist-item").forEach((row) => {
      row.classList.toggle("is-current", !audio.paused && activeKeys.has(String(row.dataset.trackIdKey)));
    });
  }

  function jumpToTracklistItem(item) {
    if (!item) return;
    const mobilePanel = document.querySelector("[data-mobile-tracklist]");
    const onMobile = window.matchMedia("(max-width: 820px)").matches;
    if (onMobile && mobilePanel && mobilePanel.hidden) {
      setTracklistPanelState(mobilePanel, true);
    }
    const rows = Array.from(document.querySelectorAll(`[data-track-id-key="${item.key}"]`));
    if (!rows.length) return;
    const target = onMobile && mobilePanel ? rows.find((row) => row.closest("[data-mobile-tracklist]")) || rows[0] : rows.find((row) => !row.closest("[data-mobile-tracklist]")) || rows[0];
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    clearTracklistHighlights();
    target.classList.add("is-active");
    window.setTimeout(() => target.classList.remove("is-active"), 1800);
    history.replaceState({}, "", `#track-id-${item.key}`);
  }

  function updateCurrentTrackPills(items) {
    const list = document.querySelector("[data-current-track-list]");
    if (!list) return;
    const activeItems = Array.isArray(items) ? items : [];
    if (!hasPlaybackStarted || !activeItems.length) {
      list.classList.remove("is-visible");
      list.setAttribute("aria-hidden", "true");
      list.replaceChildren();
      return;
    }
    const fragment = document.createDocumentFragment();
    activeItems.forEach((item) => {
      const pill = document.createElement("button");
      pill.type = "button";
      pill.className = "current-track-pill";
      const label = document.createElement("span");
      label.className = "current-track-label";
      label.textContent = "Currently Playing:";
      const artistNode = document.createElement("span");
      artistNode.className = "current-track-artist";
      artistNode.textContent = item.artist ? `${item.artist} -` : "";
      const titleNode = document.createElement("span");
      titleNode.className = "current-track-title";
      titleNode.textContent = item.title;
      pill.append(label, artistNode, titleNode);
      if (!item.unknown) {
        pill.addEventListener("click", () => jumpToTracklistItem(item));
      }
      fragment.appendChild(pill);
    });
    list.replaceChildren(fragment);
    list.classList.add("is-visible");
    list.setAttribute("aria-hidden", "false");
  }

  function updateTracklistCue() {
    document.querySelectorAll(".track-cue").forEach((cue) => {
      if (cue.closest("[data-waveform]") !== currentTrack) cue.classList.remove("is-visible");
    });
    if (!currentTrack || !currentTrack.classList.contains("hero-waveform") || !currentTrackData) {
      updateCurrentTrackPills([]);
      updateTracklistActiveRows([]);
      return;
    }
    const seconds = audio.currentTime || 0;
    const ratio = audio.duration ? seconds / audio.duration : 0;
    if (cueOverride && cueOverride.expiresAt <= Date.now()) {
      cueOverride = null;
    }
    const item = cueOverride?.item || recentlyTriggeredTracklistItem(currentTrackData.tracklist, seconds);
    const nowPlayingItems = currentPlayingTracklistItems(currentTrackData.tracklist, seconds);
    updateCurrentTrackPills(nowPlayingItems);
    updateTracklistActiveRows(nowPlayingItems);
    let cue = currentTrack.querySelector(".track-cue");
    if (!item) {
      cue?.classList.remove("is-visible");
      return;
    }
    if (!cue) {
      cue = document.createElement("div");
      cue.className = "track-cue";
      currentTrack.appendChild(cue);
    }
    const key = `${item.startSeconds}:${item.artist}:${item.title}`;
    if (cue.dataset.key !== key) {
      cue.dataset.key = key;
      cue.innerHTML = "";
      const titleText = document.createElement("button");
      titleText.type = "button";
      titleText.className = "track-cue-title";
      titleText.innerHTML = item.artist
        ? `<span class="track-cue-artist">${item.artist}</span> <span class="track-cue-sep">-</span> <span class="track-cue-track">${item.title}</span>`
        : `<span class="track-cue-track">${item.title}</span>`;
      titleText.addEventListener("click", () => jumpToTracklistItem(item));
      cue.append(titleText);
    } else {
      const titleButton = cue.querySelector(".track-cue-title");
      if (titleButton) {
        titleButton.onclick = () => jumpToTracklistItem(item);
      }
    }
    const x = cuePlayheadX(currentTrack, ratio);
    const cueWidth = cue.offsetWidth || 280;
    const minLeft = 6;
    const maxLeft = Math.max(minLeft, currentTrack.clientWidth - cueWidth - 6);
    const clampedLeft = Math.max(minLeft, Math.min(maxLeft, x - cueWidth / 2));
    const pointerX = Math.max(10, Math.min(cueWidth - 10, x - clampedLeft));
    cue.style.left = `${clampedLeft}px`;
    cue.style.setProperty("--cue-pointer-x", `${pointerX}px`);
    cue.classList.add("is-visible");
  }

  function updateVolumeButton() {
    if (!volumeToggle || !volumeSlider) return;
    const effectiveVolume = audio.muted ? 0 : audio.volume;
    volumeToggle.textContent = effectiveVolume === 0 ? "🔇" : effectiveVolume < 0.5 ? "🔉" : "🔊";
    if (!audio.muted) volumeSlider.value = audio.volume;
  }

  window.addEventListener("popstate", () => {
    visit(window.location.href, false);
  });
  window.addEventListener("resize", () => {
    renderAllWaveforms();
    renderProgressMarkers();
  });
  window.addEventListener("mixstream:editor-playback", dismissPlayerForEditor);
  updateVolumeButton();
  bindPage();
})();
