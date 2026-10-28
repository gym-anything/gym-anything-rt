(() => {
  "use strict";

  const native = {
    dateNow: Date.now.bind(Date),
    performanceNow: performance.now.bind(performance),
    setTimeout: window.setTimeout.bind(window),
    clearTimeout: window.clearTimeout.bind(window),
    setInterval: window.setInterval.bind(window),
    clearInterval: window.clearInterval.bind(window),
    requestAnimationFrame: window.requestAnimationFrame.bind(window),
    cancelAnimationFrame: window.cancelAnimationFrame.bind(window),
    fetch: window.fetch.bind(window),
  };
  const parameters = new URLSearchParams(window.location.search);
  const initialMode = parameters.get("time_mode") === "paused" ? "paused" : "live";
  const startPaused = parameters.get("start_paused") === "1";
  const controlEnabled = parameters.get("time_control") === "1";
  const timeScale = Number(parameters.get("time_scale") ?? "1");
  if (!Number.isFinite(timeScale) || timeScale <= 0 || timeScale > 1) {
    throw new RangeError("time_scale must be finite and in (0, 1]");
  }
  const nativePerformanceOrigin = native.performanceNow();
  const nativeDateOrigin = native.dateNow();
  const clientId = `${nativeDateOrigin}-${Math.random().toString(16).slice(2)}`;

  let mode = initialMode;
  let running = initialMode === "live" && !startPaused;
  let accumulatedMs = 0;
  let runStartedAt = running ? native.performanceNow() : null;
  let ready = false;
  let lastCommandSequence = 0;
  let commandPhase = running ? "running" : "paused";
  let windowStartedWallMs = null;
  let windowCompletedWallMs = null;
  let windowStartedTaskMs = null;
  let windowCompletedTaskMs = null;
  let runWindowStartedNativeMs = null;
  let taskTimeCeilingMs = null;
  let runWindowToken = 0;
  let nextTimerId = 1;
  let nextAnimationFrameId = 1;
  let nextActionId = 1;
  let lastInputCommandSequence = 0;
  let activeInputArm = null;
  let inputCompletionToken = 0;
  let interactionClockTaskMs = null;
  let interactionClockNativeMs = null;
  let interactionClockLastArmNativeMs = null;

  const timers = new Map();
  const animationFrames = new Map();
  const pendingActions = new Map();
  const actionIdleResolvers = new Set();
  const controllerPausedAnimations = new Set();
  const scaledAnimationRates = new WeakMap();
  let animationFrameCredit = 0;
  const audioContexts = new Set();
  const controllerPausedAudioContexts = new Set();

  function elapsedMs() {
    const elapsed = accumulatedMs + (running && runStartedAt != null ? (native.performanceNow() - runStartedAt) * timeScale : 0);
    return taskTimeCeilingMs == null ? elapsed : Math.min(elapsed, taskTimeCeilingMs);
  }

  function virtualPerformanceNow() {
    return nativePerformanceOrigin + elapsedMs();
  }

  function virtualDateNow() {
    return Math.round(nativeDateOrigin + elapsedMs());
  }

  // Interaction transcripts sometimes need the duration between native input
  // samples even while the task world is paused. During an armed input batch,
  // preserve that within-action duration on top of the frozen task boundary.
  // This clock is for input evidence only; timers, animation, physics, Date,
  // and performance.now continue to use the task clock above.
  function interactionNow() {
    if (running || !activeInputArm) return virtualPerformanceNow();
    const taskBoundaryMs = Number(activeInputArm.startedTaskMs ?? elapsedMs());
    const nativeBoundaryMs = Number(interactionClockNativeMs ?? activeInputArm.startedNativeMs ?? native.performanceNow());
    return nativePerformanceOrigin + taskBoundaryMs + Math.max(0, native.performanceNow() - nativeBoundaryMs);
  }

  function pauseDocumentAnimations(root = document) {
    if (typeof root.getAnimations !== "function") return;
    for (const animation of root.getAnimations({subtree: true})) {
      if (animation.playState !== "running" && animation.playState !== "pending") continue;
      try {
        animation.pause();
        controllerPausedAnimations.add(animation);
      } catch (_error) {
        // A detached animation can disappear between enumeration and pause.
      }
    }
    if (root === document) {
      for (const child of window.GymAnythingRTTime?.childWindows || []) {
        if (!child.closed) pauseDocumentAnimations(child.document);
      }
    }
  }

  function scaleDocumentAnimations(root = document) {
    if (timeScale === 1 || typeof root.getAnimations !== "function") return;
    for (const animation of root.getAnimations({subtree: true})) {
      if (scaledAnimationRates.get(animation) === animation.playbackRate) continue;
      const rate = animation.playbackRate * timeScale;
      animation.updatePlaybackRate(rate);
      scaledAnimationRates.set(animation, rate);
    }
    if (root === document) {
      for (const child of window.GymAnythingRTTime?.childWindows || []) {
        if (!child.closed) scaleDocumentAnimations(child.document);
      }
    }
  }

  function resumeDocumentAnimations() {
    for (const animation of controllerPausedAnimations) {
      try {
        animation.play();
      } catch (_error) {
        // Detached animations need no further work.
      }
    }
    controllerPausedAnimations.clear();
  }

  function pauseAudio() {
    for (const context of audioContexts) {
      if (context.state !== "running") continue;
      controllerPausedAudioContexts.add(context);
      context.suspend().catch(() => {});
    }
  }

  function resumeAudio() {
    for (const context of controllerPausedAudioContexts) {
      if (context.state === "suspended") context.resume().catch(() => {});
    }
    controllerPausedAudioContexts.clear();
  }

  // A task can register the finite visual/physical transition that an input
  // has already started.  This is deliberately independent of time mode: the
  // same action still takes the same task time in a normal browser session.
  // The paused evaluator uses it only to place the pause boundary after that
  // existing transition, rather than freezing an accepted input halfway
  // through its own lockout animation.
  function beginAction(label = "interaction") {
    const id = nextActionId++;
    let settled = false;
    pendingActions.set(id, {
      label: String(label),
      started_task_time_ms: Math.round(elapsedMs() * 1000) / 1000,
    });
    return {
      id,
      settle() {
        if (settled) return;
        settled = true;
        pendingActions.delete(id);
        if (pendingActions.size) return;
        for (const resolve of actionIdleResolvers) resolve();
        actionIdleResolvers.clear();
      },
    };
  }

  function waitForActionsToSettle() {
    if (!pendingActions.size) return Promise.resolve();
    return new Promise((resolve) => actionIdleResolvers.add(resolve));
  }

  function pause() {
    if (!running) {
      // Input handlers still execute while task time is frozen. They can
      // create a CSS/Web Animation without inserting a node, so every paused
      // barrier must re-scan the document instead of treating pause as a
      // no-op. Timers and requestAnimationFrame callbacks remain queued.
      pauseDocumentAnimations();
      pauseAudio();
      return status();
    }
    accumulatedMs = elapsedMs();
    runStartedAt = null;
    running = false;
    taskTimeCeilingMs = null;
    commandPhase = "paused";
    // A canvas-based task normally paints from requestAnimationFrame.  Render
    // the state at the exact pause boundary once, then leave any newly queued
    // frame pending until task time resumes.  Without this flush, a task that
    // starts paused can expose an empty canvas to its first observation.
    flushAnimationFrames();
    pauseDocumentAnimations();
    pauseAudio();
    return status();
  }

  async function pauseAfterActions(sequence) {
    if (!running) return status();
    if (pendingActions.size) {
      commandPhase = "settling_actions";
      await postStatus();
      await waitForActionsToSettle();
      // A newer command wins while this command is waiting for an action to
      // settle.  It must not unexpectedly pause a newly resumed task.
      if (sequence != null && sequence !== lastCommandSequence) return status();
    }
    return pause();
  }

  function resume(maxTaskTimeMs = null) {
    taskTimeCeilingMs = Number.isFinite(maxTaskTimeMs) ? Number(maxTaskTimeMs) : null;
    if (running) return status();
    runStartedAt = native.performanceNow();
    running = true;
    commandPhase = "running";
    resumeDocumentAnimations();
    resumeAudio();
    return status();
  }

  function setMode(nextMode) {
    if (nextMode !== "live" && nextMode !== "paused") {
      throw new TypeError(`unsupported time mode: ${nextMode}`);
    }
    mode = nextMode;
    runWindowToken += 1;
    if (mode === "live") resume();
    else pause();
    postStatus();
    return status();
  }

  function status() {
    return {
      client_id: clientId,
      mode,
      time_scale: timeScale,
      state: running ? "running" : "paused",
      phase: commandPhase,
      ready,
      sequence: lastCommandSequence,
      task_time_ms: Math.round(elapsedMs() * 1000) / 1000,
      native_time_ms: native.performanceNow(),
      native_date_ms: native.dateNow(),
      window_started_wall_ms: windowStartedWallMs,
      window_completed_wall_ms: windowCompletedWallMs,
      window_started_task_ms: windowStartedTaskMs,
      window_completed_task_ms: windowCompletedTaskMs,
      pending_action_count: pendingActions.size,
      pending_actions: [...pendingActions.values()].map((action) => ({...action})),
    };
  }

  function markReady() {
    // `main()` marks readiness after the mechanic has installed its first
    // requestAnimationFrame callback.  Flush it even when the controller was
    // initialized paused so obs.screen always contains the rendered world.
    flushAnimationFrames();
    ready = true;
    postStatus();
  }

  function normalizeCallback(callback) {
    if (typeof callback === "function") return callback;
    return () => window.eval(String(callback));
  }

  function scheduleTimer(callback, delay, interval, args) {
    const id = nextTimerId++;
    const delayMs = Math.max(0, Number(delay) || 0);
    timers.set(id, {
      callback: normalizeCallback(callback),
      args,
      dueMs: elapsedMs() + delayMs,
      intervalMs: interval ? Math.max(1, delayMs) : null,
    });
    return id;
  }

  window.setTimeout = (callback, delay = 0, ...args) => scheduleTimer(callback, delay, false, args);
  window.setInterval = (callback, delay = 0, ...args) => scheduleTimer(callback, delay, true, args);
  window.clearTimeout = (id) => timers.delete(Number(id));
  window.clearInterval = window.clearTimeout;

  window.requestAnimationFrame = (callback) => {
    const id = nextAnimationFrameId++;
    animationFrames.set(id, callback);
    return id;
  };
  window.cancelAnimationFrame = (id) => animationFrames.delete(Number(id));

  Date.now = virtualDateNow;
  try {
    Object.defineProperty(performance, "now", {configurable: true, value: virtualPerformanceNow});
  } catch (_error) {
    try {
      Object.defineProperty(Performance.prototype, "now", {configurable: true, value: virtualPerformanceNow});
    } catch (_ignored) {
      // The compatibility test fails if a browser prevents both replacements.
    }
  }

  for (const name of ["AudioContext", "webkitAudioContext"]) {
    const Constructor = window[name];
    if (typeof Constructor !== "function") continue;
    window[name] = new Proxy(Constructor, {
      construct(target, argumentsList, newTarget) {
        const context = Reflect.construct(target, argumentsList, newTarget);
        audioContexts.add(context);
        if (!running && context.state === "running") {
          controllerPausedAudioContexts.add(context);
          context.suspend().catch(() => {});
        }
        return context;
      },
    });
  }

  function drainTimers() {
    if (!running) return;
    const now = elapsedMs();
    const due = [...timers.entries()]
      .filter(([, timer]) => timer.dueMs <= now)
      .sort((left, right) => left[1].dueMs - right[1].dueMs);
    for (const [id, timer] of due) {
      if (!timers.has(id)) continue;
      if (timer.intervalMs == null) timers.delete(id);
      else timer.dueMs += timer.intervalMs * Math.max(1, Math.floor((now - timer.dueMs) / timer.intervalMs) + 1);
      try {
        timer.callback(...timer.args);
      } catch (error) {
        native.setTimeout(() => { throw error; }, 0);
      }
    }
  }

  function flushAnimationFrames() {
    if (!animationFrames.size) return;
    const callbacks = [...animationFrames.values()];
    animationFrames.clear();
    const timestamp = virtualPerformanceNow();
    for (const callback of callbacks) {
      try {
        callback(timestamp);
      } catch (error) {
        native.setTimeout(() => { throw error; }, 0);
      }
    }
  }

  function animationLoop() {
    scaleDocumentAnimations();
    if (running) {
      // Also slow mechanics that advance by one fixed step per animation frame.
      animationFrameCredit += timeScale;
      if (animationFrameCredit >= 1) {
        animationFrameCredit -= 1;
        flushAnimationFrames();
      }
    }
    native.requestAnimationFrame(animationLoop);
  }

  native.setInterval(drainTimers, 4);
  native.requestAnimationFrame(animationLoop);

  const observer = new MutationObserver(() => {
    if (!running) native.setTimeout(() => pauseDocumentAnimations(), 0);
  });
  observer.observe(document.documentElement, {
    attributes: true,
    childList: true,
    subtree: true,
  });

  const inputEventTypes = [
    "pointermove", "pointerdown", "pointerup", "pointercancel",
    "mousedown", "mouseup", "click", "dblclick", "contextmenu", "auxclick",
    "wheel", "dragstart", "dragover", "drop", "dragend",
    "keydown", "keyup", "beforeinput", "input", "change",
  ];

  function inputEventCategory(event) {
    return ["keydown", "keyup", "beforeinput", "input", "change"].includes(event.type)
      ? "keyboard"
      : "mouse";
  }

  function inputCategoryMatches(event, arm) {
    return arm.category === "mixed" || inputEventCategory(event) === arm.category;
  }

  function inputStatus(phase, arm = activeInputArm) {
    const clock = status();
    return {
      client_id: clientId,
      command_sequence: Number(arm?.commandSequence || lastInputCommandSequence),
      arm_sequence: Number(arm?.armSequence || 0),
      phase,
      category: arm?.category || null,
      required: Boolean(arm?.required),
      receipt_confirmed: Boolean(arm?.events?.length),
      observed_event_count: Number(arm?.events?.length || 0),
      observed_events: [...(arm?.events || [])],
      task_time_ms: clock.task_time_ms,
      controller_state: clock.state,
      native_time_ms: native.performanceNow(),
      native_date_ms: native.dateNow(),
    };
  }

  async function postInputStatus(phase, arm = activeInputArm) {
    if (!controlEnabled) return;
    try {
      await native.fetch("/input-control/status", {
        method: "POST",
        headers: {"content-type": "application/json"},
        body: JSON.stringify(inputStatus(phase, arm)),
        cache: "no-store",
      });
    } catch (_error) {
      // The command poll retries. Task time remains frozen during the barrier.
    }
  }

  function finishInputBarrier(arm) {
    if (activeInputArm !== arm || !arm.completionRequested) return;
    if (!running) pause();
    const phase = arm.events.length ? "completed" : "missing";
    activeInputArm = null;
    void postInputStatus(phase, arm);
  }

  function scheduleInputBarrierCompletion(arm) {
    if (activeInputArm !== arm || !arm.completionRequested) return;
    const token = ++inputCompletionToken;
    const sinceHandler = native.performanceNow() - Number(arm.lastHandlerCompletedNativeMs || 0);
    const quietDelay = arm.events.length
      ? Math.max(0, 32 - sinceHandler)
      : (arm.required ? 500 : 50);
    native.setTimeout(() => {
      if (token !== inputCompletionToken || activeInputArm !== arm) return;
      finishInputBarrier(arm);
    }, quietDelay);
  }

  function recordInputEvent(event) {
    const arm = activeInputArm;
    if (!arm || !event.isTrusted || !inputCategoryMatches(event, arm)) return;
    // Operating-system key repeat is a consequence of a previously delivered
    // key-down, not a new injected action. Letting repeats reset the quiet
    // boundary makes a deliberate held key impossible to acknowledge.
    if (event.type === "keydown" && event.repeat) return;
    const observed = {
      type: String(event.type),
      category: inputEventCategory(event),
      native_time_ms: native.performanceNow(),
      task_time_ms: Math.round(elapsedMs() * 1000) / 1000,
      x: Number.isFinite(event.clientX) ? Number(event.clientX) : null,
      y: Number.isFinite(event.clientY) ? Number(event.clientY) : null,
      button: Number.isFinite(event.button) ? Number(event.button) : null,
      key: typeof event.key === "string" ? event.key : null,
      code: typeof event.code === "string" ? event.code : null,
    };
    arm.events.push(observed);
    if (arm.events.length > 64) arm.events.shift();
    // A capture listener runs before the task handler. A native zero-delay
    // task records the barrier only after synchronous dispatch has finished.
    native.setTimeout(() => {
      if (activeInputArm !== arm) return;
      observed.handler_completed_native_time_ms = native.performanceNow();
      arm.lastHandlerCompletedNativeMs = observed.handler_completed_native_time_ms;
      scheduleInputBarrierCompletion(arm);
    }, 0);
  }

  function installInputListeners(targetWindow = window) {
    try {
      if (targetWindow.__gymAnythingRTInputBarrierInstalled) return;
      targetWindow.__gymAnythingRTInputBarrierInstalled = true;
      for (const eventType of inputEventTypes) {
        targetWindow.addEventListener(eventType, recordInputEvent, true);
      }
    } catch (_error) {
      // Cross-origin child windows are outside the task's shared clock.
    }
  }

  async function applyInputCommand(command) {
    const sequence = Number(command.sequence) || 0;
    if (sequence <= lastInputCommandSequence) return;
    lastInputCommandSequence = sequence;
    const kind = String(command.command || "status");
    if (kind === "arm") {
      inputCompletionToken += 1;
      const armedNativeMs = native.performanceNow();
      const armedTaskMs = elapsedMs();
      const clockExpired = interactionClockLastArmNativeMs == null
        || armedNativeMs - interactionClockLastArmNativeMs > 1500;
      if (interactionClockTaskMs == null || Math.abs(armedTaskMs - interactionClockTaskMs) > .01 || clockExpired) {
        interactionClockTaskMs = armedTaskMs;
        interactionClockNativeMs = armedNativeMs;
      }
      interactionClockLastArmNativeMs = armedNativeMs;
      activeInputArm = {
        armSequence: Number(command.arm_sequence) || sequence,
        commandSequence: sequence,
        category: String(command.category || "mixed"),
        required: command.required !== false,
        completionRequested: false,
        startedNativeMs: armedNativeMs,
        startedTaskMs: armedTaskMs,
        lastHandlerCompletedNativeMs: 0,
        events: [],
      };
      if (!running) pause();
      await postInputStatus("armed", activeInputArm);
      return;
    }
    const armSequence = Number(command.arm_sequence) || 0;
    if (!activeInputArm || activeInputArm.armSequence !== armSequence) {
      const orphan = {
        armSequence,
        commandSequence: sequence,
        category: null,
        required: false,
        events: [],
      };
      await postInputStatus(kind === "cancel" ? "cancelled" : "missing", orphan);
      return;
    }
    activeInputArm.commandSequence = sequence;
    if (kind === "cancel") {
      inputCompletionToken += 1;
      const cancelled = activeInputArm;
      activeInputArm = null;
      await postInputStatus("cancelled", cancelled);
      return;
    }
    if (kind === "complete") {
      activeInputArm.completionRequested = true;
      await postInputStatus("completing", activeInputArm);
      scheduleInputBarrierCompletion(activeInputArm);
    }
  }

  async function pollInputCommands() {
    if (!controlEnabled) return;
    try {
      const response = await native.fetch(
        `/input-control?after=${lastInputCommandSequence}`,
        {cache: "no-store"},
      );
      if (response.ok) await applyInputCommand(await response.json());
    } catch (_error) {
      // Polling continues while task time stays independent of server access.
    }
  }

  async function postStatus() {
    if (!controlEnabled) return;
    try {
      await native.fetch("/time-control/status", {
        method: "POST",
        headers: {"content-type": "application/json"},
        body: JSON.stringify(status()),
        cache: "no-store",
      });
    } catch (_error) {
      // The next polling cycle retries after transient server startup races.
    }
  }

  function runFor(milliseconds, startDelayMs, sequence) {
    const duration = Math.max(0, Number(milliseconds) || 0);
    const startDelay = Math.max(0, Number(startDelayMs) || 0);
    const token = ++runWindowToken;
    pause();
    commandPhase = "scheduled";
    windowStartedWallMs = null;
    windowCompletedWallMs = null;
    windowStartedTaskMs = null;
    windowCompletedTaskMs = null;
    runWindowStartedNativeMs = null;
    postStatus();
    const startWindow = () => {
      if (token !== runWindowToken || sequence !== lastCommandSequence) return;
      windowStartedTaskMs = elapsedMs();
      const taskEndMs = windowStartedTaskMs + duration;
      resume(taskEndMs);
      commandPhase = "running_window";
      windowStartedWallMs = native.dateNow();
      runWindowStartedNativeMs = native.performanceNow();
      postStatus();
      native.setTimeout(() => {
        if (token !== runWindowToken || sequence !== lastCommandSequence) return;
        pause();
        commandPhase = "completed";
        windowCompletedWallMs = native.dateNow();
        windowCompletedTaskMs = elapsedMs();
        postStatus();
      }, duration / timeScale);
    };
    if (startDelay > 0) native.setTimeout(startWindow, startDelay);
    else startWindow();
  }

  async function applyCommand(command) {
    const sequence = Number(command.sequence) || 0;
    if (sequence <= lastCommandSequence) return;
    lastCommandSequence = sequence;
    const kind = String(command.command || "status");
    if (kind === "pause") {
      runWindowToken += 1;
      pause();
    } else if (kind === "settle_pause") {
      runWindowToken += 1;
      await pauseAfterActions(sequence);
    } else if (kind === "resume") {
      runWindowToken += 1;
      resume();
    }
    else if (kind === "run_for") {
      runFor(command.milliseconds, command.start_delay_ms, sequence);
      return;
    }
    commandPhase = running ? "running" : "paused";
    await postStatus();
  }

  async function pollCommands() {
    if (!controlEnabled) return;
    try {
      const response = await native.fetch(`/time-control?after=${lastCommandSequence}`, {cache: "no-store"});
      if (response.ok) await applyCommand(await response.json());
    } catch (_error) {
      // Polling continues. The task clock is independent of server availability.
    }
  }

  const originalOpen = window.open.bind(window);
  const childWindows = new Set();
  window.open = (...args) => {
    const child = originalOpen(...args);
    if (child) {
      childWindows.add(child);
      native.setTimeout(() => installInputListeners(child), 0);
    }
    return child;
  };

  window.GymAnythingRTTime = {
    pause,
    pauseAfterActions,
    resume,
    runFor: (milliseconds, startDelayMs = 0) => runFor(
      milliseconds,
      startDelayMs,
      lastCommandSequence,
    ),
    beginAction,
    setMode,
    status,
    interactionNow,
    markReady,
    childWindows,
    native,
  };

  if (!running) native.setTimeout(() => pauseDocumentAnimations(), 0);
  installInputListeners();
  if (controlEnabled) {
    native.setInterval(pollCommands, 20);
    native.setInterval(pollInputCommands, 20);
    native.setInterval(postStatus, 250);
    pollCommands();
    pollInputCommands();
  }
})();
