(() => {
  "use strict";

  const clock = window.GymAnythingRTTime;
  if (!window.GYM_ANYTHING_RT_BROWSER_PLAY || !clock) return;

  const native = clock.native;
  const parameters = new URLSearchParams(window.location.search);
  let selectedMode = parameters.get("time_mode") === "paused" ? "paused" : "live";
  let settings = null;
  let collecting = false;
  let captureStream = null;
  let captureVideo = null;
  let capturedFrames = [];
  let selectedFrameIndex = 0;

  const control = document.createElement("aside");
  control.className = "rt-demo-inspector rt-demo-clock";
  control.dataset.clockState = clock.status().state;
  control.dataset.collapsed = "true";
  control.setAttribute("aria-label", "Real-time demo control");
  control.innerHTML = `
    <div class="rt-demo-clock__topline">
      <span class="rt-demo-clock__name">Agent observation</span>
      <span class="rt-demo-clock__state" data-demo-clock-state>Running</span>
      <button class="rt-demo-clock__collapse" type="button" data-demo-action="collapse" aria-expanded="false" aria-label="Expand observation controls">+</button>
    </div>
    <div class="rt-demo-clock__body">
      <div class="rt-demo-clock__modes" aria-label="Time condition">
        <button class="rt-demo-clock__mode" type="button" data-demo-mode="live" aria-pressed="false">Live</button>
        <button class="rt-demo-clock__mode" type="button" data-demo-mode="paused" aria-pressed="false">Paused</button>
      </div>
      <div class="rt-demo-clock__readout">
        <span class="rt-demo-clock__time" data-demo-task-time>00:00.0</span>
        <span class="rt-demo-clock__limit" data-demo-time-limit>of --:-- task time</span>
      </div>
      <dl class="rt-demo-clock__spec">
        <div><dt>Window</dt><dd data-demo-window>—</dd></div>
        <div><dt>Frames</dt><dd data-demo-frames>—</dd></div>
        <div><dt>Input</dt><dd>1280×720</dd></div>
      </dl>
      <button class="rt-demo-clock__capture" type="button" data-demo-action="capture" disabled>Capture model observation</button>
      <p class="rt-demo-clock__note" data-demo-note>Loading this environment’s observation settings.</p>
    </div>
  `;

  const viewer = document.createElement("section");
  viewer.className = "rt-demo-inspector rt-demo-observation";
  viewer.dataset.open = "false";
  viewer.setAttribute("aria-label", "Captured model observation");
  viewer.setAttribute("aria-hidden", "true");
  viewer.innerHTML = `
    <header class="rt-demo-observation__head">
      <div>
        <p class="rt-demo-observation__eyebrow" data-demo-observation-meta>Model observation</p>
        <h2 class="rt-demo-observation__title">Frames sent to the model</h2>
      </div>
      <button class="rt-demo-observation__close" type="button" data-demo-action="close-viewer">Close</button>
    </header>
    <div class="rt-demo-observation__stage">
      <figure class="rt-demo-observation__screen-wrap">
        <img class="rt-demo-observation__screen" data-demo-screen alt="Selected observation frame">
        <figcaption class="rt-demo-observation__screen-label" data-demo-screen-label></figcaption>
      </figure>
    </div>
    <nav class="rt-demo-observation__film" data-demo-film aria-label="Observation frames"></nav>
  `;

  document.body.append(control, viewer);

  const modeButtons = [...control.querySelectorAll("[data-demo-mode]")];
  const captureButton = control.querySelector('[data-demo-action="capture"]');
  const taskTime = control.querySelector("[data-demo-task-time]");
  const timeLimit = control.querySelector("[data-demo-time-limit]");
  const clockState = control.querySelector("[data-demo-clock-state]");
  const windowValue = control.querySelector("[data-demo-window]");
  const frameValue = control.querySelector("[data-demo-frames]");
  const note = control.querySelector("[data-demo-note]");
  const screen = viewer.querySelector("[data-demo-screen]");
  const screenLabel = viewer.querySelector("[data-demo-screen-label]");
  const observationMeta = viewer.querySelector("[data-demo-observation-meta]");
  const film = viewer.querySelector("[data-demo-film]");

  function formatClock(milliseconds) {
    const totalTenths = Math.max(0, Math.floor(Number(milliseconds || 0) / 100));
    const minutes = Math.floor(totalTenths / 600);
    const seconds = Math.floor((totalTenths % 600) / 10);
    const tenths = totalTenths % 10;
    return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}.${tenths}`;
  }

  function formatLimit(seconds) {
    const whole = Math.max(0, Number(seconds) || 0);
    return `${String(Math.floor(whole / 60)).padStart(2, "0")}:${String(whole % 60).padStart(2, "0")}`;
  }

  function formatOffset(milliseconds) {
    const value = Math.round(Number(milliseconds || 0) * 10) / 10;
    return `+${value} ms`;
  }

  function setNote(message, kind = "info") {
    note.textContent = message;
    note.dataset.kind = kind;
  }

  function syncClock() {
    const status = clock.status();
    control.dataset.clockState = status.state;
    clockState.textContent = status.state === "running" ? "Running" : "Paused";
    taskTime.textContent = formatClock(status.task_time_ms);
    for (const button of modeButtons) {
      button.setAttribute("aria-pressed", String(button.dataset.demoMode === selectedMode));
    }
  }

  function setMode(mode, {updateUrl = true} = {}) {
    if (mode !== "live" && mode !== "paused") return;
    selectedMode = mode;
    if (typeof clock.setMode === "function") clock.setMode(mode);
    else if (mode === "live") clock.resume();
    else clock.pause();
    if (updateUrl) {
      const url = new URL(window.location.href);
      url.searchParams.set("time_mode", mode);
      history.replaceState(null, "", url);
    }
    setNote(mode === "paused"
      ? "Inputs apply to the frozen state. Motion advances only during the next captured observation."
      : "The task keeps running during observation and while the model would be responding.");
    syncClock();
  }

  function frameTargets(durationMs, count) {
    if (count === 1) return [durationMs];
    return Array.from({length: count}, (_item, index) => durationMs * index / (count - 1));
  }

  function releaseFrames() {
    for (const frame of capturedFrames) URL.revokeObjectURL(frame.url);
    capturedFrames = [];
    film.replaceChildren();
  }

  function clearCaptureStream() {
    if (captureVideo) {
      captureVideo.pause();
      captureVideo.srcObject = null;
      captureVideo.remove();
    }
    captureVideo = null;
    captureStream = null;
  }

  async function nextCapturedVideoFrame() {
    if (!captureVideo) return;
    await new Promise((resolve) => {
      let resolved = false;
      const finish = () => {
        if (resolved) return;
        resolved = true;
        resolve();
      };
      if (typeof captureVideo.requestVideoFrameCallback === "function") {
        captureVideo.requestVideoFrameCallback(finish);
      }
      native.setTimeout(finish, 120);
    });
  }

  async function ensureCaptureStream() {
    const activeTrack = captureStream?.getVideoTracks?.()[0];
    if (activeTrack?.readyState === "live" && captureVideo?.readyState >= 2) return;
    clearCaptureStream();
    if (!navigator.mediaDevices?.getDisplayMedia) {
      throw new Error("This browser does not support tab capture. Open the demo in a current Chrome, Edge, Firefox, or Safari browser.");
    }
    captureStream = await navigator.mediaDevices.getDisplayMedia({
      video: {frameRate: {ideal: 30, max: 60}, cursor: "always"},
      audio: false,
      preferCurrentTab: true,
      selfBrowserSurface: "include",
      surfaceSwitching: "exclude",
    });
    const track = captureStream.getVideoTracks()[0];
    if (!track) throw new Error("The selected capture source has no video track.");
    track.addEventListener("ended", clearCaptureStream, {once: true});
    captureVideo = document.createElement("video");
    captureVideo.hidden = true;
    captureVideo.muted = true;
    captureVideo.playsInline = true;
    captureVideo.srcObject = captureStream;
    control.append(captureVideo);
    await captureVideo.play();
    if (captureVideo.readyState < 2) {
      await new Promise((resolve, reject) => {
        const timeout = native.setTimeout(() => reject(new Error("The captured tab did not produce a video frame.")), 5000);
        captureVideo.addEventListener("loadeddata", () => {
          native.clearTimeout(timeout);
          resolve();
        }, {once: true});
      });
    }
    await nextCapturedVideoFrame();
  }

  function snapshot(targetOffsetMs, taskStartMs) {
    if (!captureVideo || captureVideo.readyState < 2) {
      return Promise.reject(new Error("The captured tab is not ready."));
    }
    const canvas = document.createElement("canvas");
    canvas.width = 1280;
    canvas.height = 720;
    const context = canvas.getContext("2d", {alpha: false});
    context.imageSmoothingEnabled = true;
    context.imageSmoothingQuality = "low";
    context.drawImage(captureVideo, 0, 0, canvas.width, canvas.height);
    const actualTaskOffsetMs = clock.status().task_time_ms - taskStartMs;
    return new Promise((resolve, reject) => {
      canvas.toBlob((blob) => {
        if (!blob) {
          reject(new Error("The browser could not encode the captured frame."));
          return;
        }
        resolve({
          url: URL.createObjectURL(blob),
          targetOffsetMs,
          actualTaskOffsetMs,
        });
      }, "image/png");
    });
  }

  function renderSelectedFrame(index) {
    const frame = capturedFrames[index];
    if (!frame) return;
    selectedFrameIndex = index;
    screen.src = frame.url;
    const isLatest = index === capturedFrames.length - 1;
    screenLabel.textContent = `Frame ${index + 1} of ${capturedFrames.length} · ${formatOffset(frame.targetOffsetMs)}${isLatest ? " · obs.screen" : ""}`;
    for (const [frameIndex, button] of [...film.children].entries()) {
      button.setAttribute("aria-pressed", String(frameIndex === index));
    }
  }

  function openViewer(frames) {
    capturedFrames = frames;
    film.replaceChildren(...frames.map((frame, index) => {
      const button = document.createElement("button");
      button.className = "rt-demo-frame";
      button.type = "button";
      button.dataset.demoFrame = String(index);
      button.setAttribute("aria-pressed", "false");
      const image = document.createElement("img");
      image.src = frame.url;
      image.alt = `Observation frame ${index + 1}`;
      const caption = document.createElement("span");
      const label = document.createElement("b");
      label.textContent = index === frames.length - 1 ? `F${index + 1} · screen` : `F${index + 1}`;
      const offset = document.createElement("i");
      offset.textContent = formatOffset(frame.targetOffsetMs);
      caption.append(label, offset);
      button.append(image, caption);
      return button;
    }));
    observationMeta.textContent = `${selectedMode} · ${settings.observation_window_ms} ms · ${frames.length} frame${frames.length === 1 ? "" : "s"} · 1280 × 720`;
    viewer.dataset.open = "true";
    viewer.setAttribute("aria-hidden", "false");
    renderSelectedFrame(frames.length - 1);
  }

  async function collectObservation() {
    if (collecting || !settings) return;
    collecting = true;
    captureButton.disabled = true;
    captureButton.textContent = "Waiting for tab capture";
    setNote("Select This Tab in the browser prompt. The control panel is removed from every captured frame.");
    try {
      await ensureCaptureStream();
      if (selectedMode === "paused") clock.pause();
      document.documentElement.dataset.agentCapture = "true";
      await nextCapturedVideoFrame();
      await nextCapturedVideoFrame();

      releaseFrames();
      const durationMs = Number(settings.observation_window_ms);
      const count = Number(settings.frames_per_observation);
      const targets = frameTargets(durationMs, count);
      const taskStartMs = clock.status().task_time_ms;
      const wallStartMs = native.performanceNow();
      const framePromises = [];
      let firstScheduledIndex = 0;

      if (targets[0] === 0) {
        framePromises.push(snapshot(0, taskStartMs));
        firstScheduledIndex = 1;
      }
      if (selectedMode === "paused" && durationMs > 0) clock.runFor(durationMs);

      for (let index = firstScheduledIndex; index < targets.length; index += 1) {
        const targetOffsetMs = targets[index];
        framePromises.push(new Promise((resolve, reject) => {
          const waitMs = Math.max(0, targetOffsetMs - (native.performanceNow() - wallStartMs));
          native.setTimeout(() => {
            snapshot(targetOffsetMs, taskStartMs).then(resolve, reject);
          }, waitMs);
        }));
      }

      const frames = await Promise.all(framePromises);
      frames.sort((left, right) => left.targetOffsetMs - right.targetOffsetMs);
      if (selectedMode === "paused") clock.pause();
      else clock.resume();
      document.documentElement.removeAttribute("data-agent-capture");
      openViewer(frames);
      setNote(`${frames.length} frame${frames.length === 1 ? "" : "s"} captured. The final frame is the model’s obs.screen.`);
    } catch (error) {
      document.documentElement.removeAttribute("data-agent-capture");
      if (selectedMode === "paused") clock.pause();
      const cancelled = error?.name === "NotAllowedError" || error?.name === "AbortError";
      setNote(cancelled
        ? "Tab capture was cancelled. Capture again, then select This Tab."
        : String(error?.message || error), "error");
    } finally {
      collecting = false;
      captureButton.disabled = false;
      captureButton.textContent = "Capture model observation";
      syncClock();
    }
  }

  control.addEventListener("click", (event) => {
    const modeButton = event.target.closest("[data-demo-mode]");
    if (modeButton) {
      setMode(modeButton.dataset.demoMode);
      return;
    }
    const action = event.target.closest("[data-demo-action]")?.dataset.demoAction;
    if (action === "collapse") {
      const collapsed = control.dataset.collapsed !== "true";
      control.dataset.collapsed = String(collapsed);
      event.target.setAttribute("aria-expanded", String(!collapsed));
      event.target.setAttribute("aria-label", `${collapsed ? "Expand" : "Collapse"} observation controls`);
      event.target.textContent = collapsed ? "+" : "−";
    } else if (action === "capture") {
      collectObservation();
    }
  });

  viewer.addEventListener("click", (event) => {
    const action = event.target.closest("[data-demo-action]")?.dataset.demoAction;
    if (action === "close-viewer") {
      viewer.dataset.open = "false";
      viewer.setAttribute("aria-hidden", "true");
      return;
    }
    const frameButton = event.target.closest("[data-demo-frame]");
    if (frameButton) renderSelectedFrame(Number(frameButton.dataset.demoFrame));
  });

  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && viewer.dataset.open === "true") {
      viewer.dataset.open = "false";
      viewer.setAttribute("aria-hidden", "true");
    }
  });

  window.addEventListener("beforeunload", () => {
    releaseFrames();
    for (const track of captureStream?.getTracks?.() || []) track.stop();
  });

  window.GYM_ANYTHING_RT_BROWSER_READY.then((bundle) => {
    if (!bundle?.real_time) throw new Error("This environment has no browser observation settings.");
    settings = bundle.real_time;
    windowValue.textContent = `${settings.observation_window_ms} ms`;
    frameValue.textContent = String(settings.frames_per_observation);
    timeLimit.textContent = `of ${formatLimit(settings.play_time_seconds)} task time`;
    captureButton.disabled = false;
    setMode(selectedMode, {updateUrl: false});
  }).catch((error) => {
    setNote(String(error?.message || error), "error");
  });

  native.setInterval(syncClock, 100);
  syncClock();
})();
