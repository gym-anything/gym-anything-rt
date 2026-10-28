(() => {
  "use strict";

  const nativeFetch = window.fetch.bind(window);
  const parameters = new URLSearchParams(window.location.search);
  const environmentId = String(parameters.get("environment") || "");
  const requestedAttempt = Number.parseInt(parameters.get("attempt") || "", 10);
  const requestedDifficulty = Number.parseInt(parameters.get("difficulty") || "", 10);
  const requestedInteraction = String(parameters.get("interaction") || "");
  const validEnvironment = /^[a-z0-9_]+_env$/.test(environmentId);
  const pageBase = new URL("./", window.location.href);
  const runtimeBase = new URL("runtime/", pageBase);
  const challengeUrl = new URL(`challenges/${encodeURIComponent(environmentId)}.json`, pageBase);

  window.GYM_ANYTHING_RT_ASSET_BASE = runtimeBase.href;
  window.GYM_ANYTHING_RT_BROWSER_PLAY = true;

  let bundle = null;
  let activeProfile = null;
  let activeInteractionProfile = null;
  let selectedInteraction = "";
  let bundleError = null;
  let challengeIndex = 0;
  let stateReadCount = 0;
  let lastResult = null;
  let worker = null;
  let messageId = 0;
  let grillWitness = null;
  let slotWitness = null;
  const grillGestures = new Map();
  const pendingGrades = new Map();

  function jsonResponse(payload, status = 200) {
    return new Response(JSON.stringify(payload), {
      status,
      headers: {"content-type": "application/json; charset=utf-8", "cache-control": "no-store"},
    });
  }

  function browserPlayError(message) {
    document.body.dataset.mechanic = "waiting";
    const app = document.getElementById("app");
    if (app) {
      app.innerHTML = `<section class="runtime-panel"><p>${String(message).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")}</p></section>`;
    }
  }

  const bundlePromise = (validEnvironment
    ? nativeFetch(challengeUrl, {headers: {accept: "application/json"}})
        .then((response) => {
          if (!response.ok) throw new Error(`browser challenge unavailable (${response.status})`);
          return response.json();
        })
        .then((value) => {
          if (!Array.isArray(value.challenges) || !value.challenges.length) throw new Error("browser challenge pool is empty");
          bundle = value;
          const selectedDifficulty = Number.isInteger(requestedDifficulty)
            ? requestedDifficulty
            : requestedInteraction ? Number(bundle.default_difficulty) : null;
          if (Number.isInteger(selectedDifficulty)) {
            activeProfile = bundle.difficulty_profiles?.[String(selectedDifficulty)] || null;
            if (!activeProfile) throw new Error(`difficulty ${selectedDifficulty} is unavailable for this environment`);
          }
          selectedInteraction = requestedInteraction || String(bundle.default_interaction || "");
          if (requestedInteraction && !["simplified", "full"].includes(requestedInteraction)) throw new Error(`interaction ${requestedInteraction} is unavailable for this environment`);
          if (activeProfile?.interaction_profiles) {
            activeInteractionProfile = activeProfile.interaction_profiles[selectedInteraction] || null;
            if (!activeInteractionProfile) throw new Error(`interaction ${selectedInteraction} is unavailable at difficulty ${selectedDifficulty}`);
          }
          const challenges = activeInteractionProfile?.challenges || activeProfile?.challenges || bundle.challenges;
          if (!Array.isArray(challenges) || !challenges.length) throw new Error("selected difficulty has no browser challenges");
          challengeIndex = Number.isInteger(requestedAttempt)
            ? Math.abs(requestedAttempt) % challenges.length
            : crypto.getRandomValues(new Uint32Array(1))[0] % challenges.length;
          document.title = `${bundle.title || "Gym-Anything-RT"}${activeProfile ? ` · L${activeProfile.level}` : ""}${activeInteractionProfile ? ` · ${selectedInteraction}` : ""} · Browser Play`;
          return bundle;
        })
    : Promise.reject(new Error("A valid environment was not selected")))
    .catch((error) => {
      bundleError = error;
      browserPlayError(error.message);
      return null;
    });

  function currentChallenge() {
    if (bundleError) throw bundleError;
    if (!bundle) throw new Error("browser challenge is not ready");
    return (activeInteractionProfile?.challenges || activeProfile?.challenges || bundle.challenges)[challengeIndex];
  }

  function resetGrillWitness() {
    grillGestures.clear();
    const challenge = currentChallenge();
    const truth = challenge.ground_truth || {};
    const condition = truth.control_condition || {};
    grillWitness = {
      version: 1,
      mechanic_id: String(truth.mechanic_id || ""),
      task_id: String(truth.task_id || ""),
      challenge_id: String(truth.challenge_id || ""),
      interaction: String(condition.interaction || "full"),
      clock_source: "static_browser_task_clock_v1",
      actions: [],
    };
  }

  function resetSlotWitness() {
    const challenge = currentChallenge();
    const truth = challenge.ground_truth || {};
    const condition = truth.control_condition || {};
    slotWitness = {
      version: 1,
      mechanic_id: String(truth.mechanic_id || ""),
      task_id: String(truth.task_id || ""),
      challenge_id: String(truth.challenge_id || ""),
      interaction: String(condition.interaction || "full"),
      clock_source: "static_browser_task_clock_v1",
      actions: [],
    };
  }

  function grillIdentity(payload) {
    const truth = currentChallenge().ground_truth || {};
    return (
      String(payload.mechanic_id || "") === "parallel_grillmaster"
      && String(payload.task_id || "") === String(truth.task_id || "")
      && String(payload.challenge_id || "") === String(truth.challenge_id || "")
    );
  }

  function handleGrillGesture(options, witnessedRoute) {
    let payload;
    try {
      payload = JSON.parse(String(options.body || "{}"));
    } catch (_error) {
      return jsonResponse({ok: false, error: "invalid JSON body"}, 400);
    }
    if (!grillIdentity(payload)) {
      return jsonResponse({ok: false, error: "gesture identity rejected"}, 400);
    }
    if (!grillWitness || grillWitness.challenge_id !== String(payload.challenge_id)) {
      resetGrillWitness();
    }
    const expected = grillWitness.interaction === "simplified"
      ? "simplified_selection"
      : "full_drag_begin";
    if (witnessedRoute !== expected) {
      return jsonResponse({ok: false, error: "gesture surface rejected"}, 400);
    }
    const token = crypto.randomUUID();
    grillGestures.set(token, {
      food_id: String(payload.food_id || ""),
      witnessed_route: expected,
      created_task_time_ms: performance.now(),
    });
    return jsonResponse({ok: true, gesture_token: token});
  }

  function handleGrillAction(options, witnessedRoute) {
    let payload;
    try {
      payload = JSON.parse(String(options.body || "{}"));
    } catch (_error) {
      return jsonResponse({ok: false, error: "invalid JSON body"}, 400);
    }
    if (!grillIdentity(payload) || !grillWitness) {
      return jsonResponse({ok: false, error: "action identity rejected"}, 400);
    }
    const token = String(payload.gesture_token || "");
    const gesture = grillGestures.get(token);
    grillGestures.delete(token);
    const foodId = String(payload.food_id || "");
    const kind = String(payload.kind || "");
    const evidence = payload.event_evidence || {};
    if (!gesture || gesture.food_id !== foodId) {
      return jsonResponse({ok: false, error: "matching gesture is missing"}, 400);
    }
    const simplified = grillWitness.interaction === "simplified";
    const expectedGestureRoute = simplified
      ? "simplified_selection"
      : "full_drag_begin";
    const expectedActionRoute = simplified
      ? "simplified_proxy"
      : "full_drop";
    const expectedDestination = kind === "start" ? "grill" : kind === "serve" ? "tray" : "";
    const expectedControl = kind === "start" ? "grill-start-selected" : "grill-serve-selected";
    const surfaceMatches = simplified
      ? evidence.control_id === expectedControl
      : evidence.drop_zone === expectedDestination;
    if (
      gesture.witnessed_route !== expectedGestureRoute
      || witnessedRoute !== expectedActionRoute
      || !expectedDestination
      || payload.destination !== expectedDestination
      || !surfaceMatches
    ) {
      return jsonResponse({ok: false, error: "action event surface rejected"}, 400);
    }
    const action = {
      sequence: grillWitness.actions.length + 1,
      kind,
      food_id: foodId,
      input_source: simplified ? "grill_proxy_controls" : "food_drag",
      event_surface: simplified ? "selection_plus_proxy_button" : "html_drag_drop",
      witnessed_route: witnessedRoute,
      task_time_ms: Math.round(performance.now() * 1000) / 1000,
    };
    grillWitness.actions.push(action);
    return jsonResponse({ok: true, witness_action: action});
  }

  function handleSlotAction(options) {
    let payload;
    try {
      payload = JSON.parse(String(options.body || "{}"));
    } catch (_error) {
      return jsonResponse({ok: false, error: "invalid JSON body"}, 400);
    }
    const challenge = currentChallenge();
    const truth = challenge.ground_truth || {};
    const state = challenge.public_state || {};
    if (!slotWitness || slotWitness.challenge_id !== String(truth.challenge_id || "")) {
      resetSlotWitness();
    }
    const identityMatches = (
      String(payload.mechanic_id || "") === "slot_reel_capture"
      && String(payload.task_id || "") === String(truth.task_id || "")
      && String(payload.challenge_id || "") === String(truth.challenge_id || "")
    );
    const simplified = slotWitness.interaction === "simplified";
    const expectedSource = simplified ? "capture_button" : "physical_keyboard";
    const expectedSurface = simplified ? "capture_button_click" : "keyboard_keydown";
    if (
      !identityMatches
      || payload.is_trusted !== true
      || String(payload.input_source || "") !== expectedSource
      || String(payload.event_surface || "") !== expectedSurface
    ) {
      return jsonResponse({ok: false, error: "slot-reel action identity rejected"}, 400);
    }
    const acceptedCount = slotWitness.actions.filter((action) => action.accepted === true).length;
    const reel = (state.reels || [])[acceptedCount];
    const reelId = String((truth.reel_ids || [])[acceptedCount] || "");
    const target = String(truth.sequence || "")[acceptedCount] || "";
    const elapsedMs = Number(payload.client_elapsed_ms);
    if (
      !reel
      || String(reel.id || "") !== reelId
      || !Number.isFinite(elapsedMs)
      || elapsedMs < 0
    ) {
      return jsonResponse({ok: false, error: "slot-reel action state rejected"}, 400);
    }
    const tokenIndex = (
      Math.floor(elapsedMs / Number(reel.interval_ms))
      + Number(reel.phase || 0)
    ) % reel.tokens.length;
    const observedToken = String(reel.tokens[tokenIndex] || "");
    const cyclePosition = (elapsedMs % Number(reel.interval_ms)) / Number(reel.interval_ms);
    const ratio = Number(state.capture_window_ratio || truth.capture_window_ratio || 1);
    const captureReady = ratio >= 1 || Math.abs(cyclePosition - 0.5) <= ratio / 2;
    const enteredKey = simplified ? null : String(payload.entered_key || "").toUpperCase();
    if (!simplified && !/^[A-Z0-9]$/.test(enteredKey)) {
      return jsonResponse({ok: false, error: "slot-reel keyboard action rejected"}, 400);
    }
    const action = {
      sequence: slotWitness.actions.length + 1,
      reel_id: reelId,
      elapsed_ms: elapsedMs,
      observed_token: observedToken,
      entered_key: enteredKey,
      accepted: observedToken === target && captureReady && (simplified || enteredKey === target),
      input_source: expectedSource,
      event_surface: expectedSurface,
    };
    slotWitness.actions.push(action);
    return jsonResponse({ok: true, witness_action: action});
  }

  function ensureWorker() {
    if (worker) return worker;
    worker = new Worker(new URL("grader_worker.js", runtimeBase), {type: "module"});
    worker.addEventListener("message", (event) => {
      const pending = pendingGrades.get(event.data?.id);
      if (!pending) return;
      pendingGrades.delete(event.data.id);
      clearTimeout(pending.timeout);
      if (event.data.ok) pending.resolve(event.data.grade);
      else pending.reject(new Error(event.data.error || "browser grader failed"));
    });
    worker.addEventListener("error", (event) => {
      for (const pending of pendingGrades.values()) {
        clearTimeout(pending.timeout);
        pending.reject(new Error(event.message || "browser grader worker crashed"));
      }
      pendingGrades.clear();
      worker?.terminate();
      worker = null;
    });
    return worker;
  }

  function gradeInBrowser(payload, challenge, runtimeContext = null) {
    const id = ++messageId;
    const activeWorker = ensureWorker();
    return new Promise((resolve, reject) => {
      const timeout = window.setTimeout(() => {
        if (!pendingGrades.delete(id)) return;
        worker?.terminate();
        worker = null;
        reject(new Error("browser grader initialization timed out"));
      }, 90_000);
      pendingGrades.set(id, {resolve, reject, timeout});
      activeWorker.postMessage({
        id,
        graderUrl: new URL(bundle.grader, pageBase).href,
        payload,
        groundTruth: challenge.ground_truth,
        publicState: challenge.public_state,
        runtimeContext,
      });
    });
  }

  async function handleState() {
    await bundlePromise;
    const challenges = activeInteractionProfile?.challenges || activeProfile?.challenges || bundle.challenges;
    if (stateReadCount > 0) challengeIndex = (challengeIndex + 1) % challenges.length;
    stateReadCount += 1;
    resetGrillWitness();
    resetSlotWitness();
    return jsonResponse(currentChallenge().public_state);
  }

  function failedResult(feedback, grade = null) {
    const challenges = activeInteractionProfile?.challenges || activeProfile?.challenges || bundle.challenges;
    challengeIndex = (challengeIndex + 1) % challenges.length;
    resetGrillWitness();
    resetSlotWitness();
    if (grade) window.dispatchEvent(new CustomEvent("gym-anything-rt-browser-grade", {detail: {passed: false, grade}}));
    return jsonResponse({
      ok: true,
      passed: false,
      feedback,
      state: currentChallenge().public_state,
    });
  }

  async function handleResult(options) {
    await bundlePromise;
    if (String(options.method || "GET").toUpperCase() !== "POST") {
      return lastResult ? jsonResponse(lastResult) : jsonResponse({error: "no result submitted"}, 404);
    }
    let payload;
    try {
      payload = JSON.parse(String(options.body || "{}"));
    } catch (_error) {
      return jsonResponse({error: "invalid JSON body"}, 400);
    }
    const challenge = currentChallenge();
    if (String(payload.mechanic_id || "") !== String(challenge.ground_truth.mechanic_id || "")) {
      return failedResult("mechanic mismatch");
    }
    if (String(payload.challenge_id || "") !== String(challenge.ground_truth.challenge_id || "")) {
      return failedResult("stale challenge");
    }
    try {
      const mechanicId = String(payload.mechanic_id || "");
      const runtimeWitness = mechanicId === "parallel_grillmaster"
        ? grillWitness
        : mechanicId === "slot_reel_capture"
          ? slotWitness
          : null;
      const runtimeContext = runtimeWitness
        ? {
            surface: "static_browser_nonauthoritative",
            witness: runtimeWitness,
          }
        : null;
      const grade = await gradeInBrowser(payload, challenge, runtimeContext);
      const passed = grade?.passed === true;
      lastResult = {
        ...payload,
        ...(runtimeContext ? {static_witness: runtimeWitness} : {}),
        browser_grade: grade,
        submitted_at: new Date().toISOString(),
      };
      if (passed) {
        const storageKey = `gym-anything-rt-browser-results:${environmentId}${activeProfile ? `:d${activeProfile.level}` : ""}${activeInteractionProfile ? `:i${selectedInteraction}` : ""}`;
        localStorage.setItem(storageKey, JSON.stringify(lastResult));
        window.dispatchEvent(new CustomEvent("gym-anything-rt-browser-grade", {detail: {passed: true, grade}}));
        return jsonResponse({ok: true, passed: true, feedback: grade.feedback || "pass"});
      }
      return failedResult(grade?.feedback || "failed", grade);
    } catch (error) {
      console.error("Browser verifier failed", error);
      return jsonResponse({error: `browser verifier failed: ${error.message}`}, 500);
    }
  }

  window.fetch = async (input, options = {}) => {
    const raw = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const url = new URL(raw, window.location.href);
    if (url.origin === window.location.origin && url.pathname === "/state") return handleState();
    if (url.origin === window.location.origin && url.pathname === "/result") return handleResult(options);
    if (url.origin === window.location.origin && url.pathname === "/parallel-grillmaster/full/drag-begin") return handleGrillGesture(options, "full_drag_begin");
    if (url.origin === window.location.origin && url.pathname === "/parallel-grillmaster/simplified/select") return handleGrillGesture(options, "simplified_selection");
    if (url.origin === window.location.origin && url.pathname === "/parallel-grillmaster/full/drop") return handleGrillAction(options, "full_drop");
    if (url.origin === window.location.origin && url.pathname === "/parallel-grillmaster/simplified/proxy") return handleGrillAction(options, "simplified_proxy");
    if (url.origin === window.location.origin && url.pathname === "/slot-reel/action") return handleSlotAction(options);
    if (url.origin === window.location.origin && url.pathname === "/cheat") return jsonResponse({error: "not found"}, 404);
    return nativeFetch(input, options);
  };

  window.GYM_ANYTHING_RT_BROWSER_READY = bundlePromise;
})();
