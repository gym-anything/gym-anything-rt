(() => {
  "use strict";
  window.GymAnythingRTMechanics = window.GymAnythingRTMechanics || {};

  window.GymAnythingRTMechanics.slot_reel_capture_nonrealtime = {
    rootSelector: ".slot-nonrealtime-captcha",
    render: async (state, helpers) => {
      const app = helpers.app;
      const interaction = String(state.control_condition?.interaction || "full");
      const reels = Array.isArray(state.reels) ? state.reels : [];
      const maxStrikes = Number(state.max_strikes || 3);
      const model = {
        state,
        startedAt: performance.now(),
        active: 0,
        frozen: [],
        captured: "",
        wrong: 0,
        actions: [],
        observed: [],
        ready: false,
        revealTimer: null,
        submitting: false,
        keyHandler: null,
      };
      const now = () => Math.max(0, performance.now() - model.startedAt);
      const shell = () => document.querySelector(".slot-nonrealtime-captcha");
      const reelNode = (index) => document.querySelector(`.slot-nonrealtime-reel[data-index="${index}"]`);
      const currentReel = () => reels[model.active];

      const paint = (index, token, ready) => {
        const node = reelNode(index);
        if (!node) return;
        model.observed[index] = String(token);
        const symbol = node.querySelector(".slot-nonrealtime-symbol");
        if (symbol) symbol.textContent = token;
        node.dataset.active = String(index === model.active);
        node.dataset.ready = String(ready);
        node.dataset.frozen = String(index < model.active);
        node.querySelector(".slot-nonrealtime-window")?.setAttribute("data-ready", String(ready));
      };

      const updateStatus = (message = "", status = "idle") => {
        const readout = document.querySelector(".slot-nonrealtime-readout");
        if (readout) { readout.dataset.status = status; readout.textContent = message; }
        const counter = document.querySelector(".slot-nonrealtime-strikes-count");
        if (counter) counter.textContent = `${model.wrong}/${maxStrikes}`;
        document.querySelectorAll(".slot-nonrealtime-strike-pip").forEach((pip, index) => {
          pip.dataset.active = String(index < model.wrong);
        });
        const button = document.getElementById("slot-nonrealtime-capture");
        if (button) button.disabled = model.submitting;
      };

      const reveal = (index) => {
        if (model.revealTimer) clearTimeout(model.revealTimer);
        model.active = index;
        model.ready = false;
        reels.forEach((_, reelIndex) => {
          const node = reelNode(reelIndex);
          if (node) {
            node.dataset.active = String(reelIndex === index);
            node.dataset.frozen = String(reelIndex < index);
          }
        });
        reels.forEach((reel, reelIndex) => {
          if (reelIndex > index) paint(reelIndex, reel.tokens[Number(reel.phase || 0)], false);
        });
        const reel = reels[index];
        if (!reel) { model.ready = true; updateStatus("READY", "idle"); return; }
        let tokenIndex = Number(reel.phase || 0) % reel.tokens.length;
        const advance = () => {
          if (reel.tokens[tokenIndex] === reel.target) {
            model.ready = true;
            paint(index, reel.target, true);
            updateStatus("TARGET HELD — CAPTURE WHEN READY", "idle");
            return;
          }
          tokenIndex = (tokenIndex + 1) % reel.tokens.length;
          paint(index, reel.tokens[tokenIndex], false);
          model.revealTimer = setTimeout(advance, Number(reel.interval_ms));
        };
        paint(index, reel.tokens[tokenIndex], false);
        model.revealTimer = setTimeout(advance, Number(reel.interval_ms));
        updateStatus("REEL SETTLING…", "idle");
      };

      const submit = async () => {
        if (model.submitting) return;
        model.submitting = true;
        updateStatus("VERIFYING…", "idle");
        try {
          const response = await fetch("/result", {
            method: "POST",
            headers: {"content-type": "application/json"},
            body: JSON.stringify({
              mechanic_id: state.mechanic_id,
              task_id: state.task_id,
              challenge_id: state.challenge_id,
              captured_sequence: model.captured,
              frozen_reel_ids: model.frozen,
              wrong_keys: model.wrong,
              actions: model.actions,
            }),
          });
          const outcome = await response.json();
          if (outcome.passed === true) {
            updateStatus("PASS", "passed");
          } else if (outcome.passed === false) {
            updateStatus("FAIL — NEW ATTEMPT", "error");
            if (outcome.state) await helpers.render(outcome.state);
          } else {
            model.submitting = false;
            updateStatus("VERIFY FAILED", "error");
          }
        } catch (_error) {
          model.submitting = false;
          updateStatus("VERIFY FAILED", "error");
        }
      };

      const capture = (inputSource, enteredKey = null) => {
        if (model.submitting) return;
        const reel = currentReel();
        if (!reel) return;
        const normalized = enteredKey == null ? null : String(enteredKey).toUpperCase();
        const observedToken = model.observed[model.active] || reel.tokens[Number(reel.phase || 0)];
        const keyMatches = interaction === "simplified" || normalized === String(reel.target).toUpperCase();
        const accepted = model.ready && keyMatches;
        const action = {
          sequence: model.actions.length + 1,
          reel_id: reel.id,
          elapsed_ms: Number(now().toFixed(3)),
          observed_token: observedToken,
          entered_key: interaction === "simplified" ? null : normalized,
          accepted,
          decision_state: model.ready ? "held" : "revealing",
          input_source: inputSource,
          event_surface: interaction === "simplified" ? "capture_button_click" : "keyboard_keydown",
        };
        model.actions.push(action);
        if (!accepted) {
          model.wrong += 1;
          updateStatus("WRONG SYMBOL", "error");
          shell()?.classList.remove("slot-nonrealtime-shock");
          void shell()?.offsetWidth;
          shell()?.classList.add("slot-nonrealtime-shock");
          if (model.wrong >= maxStrikes) {
            model.ready = false;
            const button = document.getElementById("slot-nonrealtime-capture");
            if (button) button.disabled = true;
            setTimeout(submit, 260);
          }
          return;
        }
        model.frozen.push(reel.id);
        model.captured += reel.target;
        paint(model.active, reel.target, true);
        const capturedCell = document.querySelectorAll(".slot-nonrealtime-captured span")[model.active];
        if (capturedCell) capturedCell.textContent = reel.target;
        model.active += 1;
        model.ready = false;
        updateStatus("CAPTURED", "idle");
        if (model.active >= reels.length) {
          model.ready = true;
          updateStatus("ALL REELS CAPTURED — VERIFY", "idle");
        } else {
          reveal(model.active);
        }
      };

      document.body.dataset.mechanic = "slot-reel-nonrealtime";
      document.body.dataset.cheatMode = "false";
      app.innerHTML = `
        <section class="slot-nonrealtime-captcha" data-interaction="${helpers.text(interaction)}" data-mechanic="${helpers.text(state.mechanic_id)}" data-challenge-id="${helpers.text(state.challenge_id)}" tabindex="0">
          <header class="slot-nonrealtime-head"><p>STEADY CAPTURE / ${String(reels.length).padStart(2, "0")}</p><h1>${helpers.text(state.prompt || "Capture each settled symbol.")}</h1></header>
          <section class="slot-nonrealtime-stage"><div class="slot-nonrealtime-machine-top"><span>CAPTURE</span><div class="slot-nonrealtime-status"><span>STRIKES</span><strong class="slot-nonrealtime-strikes-count">0/${maxStrikes}</strong>${Array.from({length: maxStrikes}, () => '<i class="slot-nonrealtime-strike-pip" data-active="false"></i>').join("")}</div></div><div class="slot-nonrealtime-reels">
            ${reels.map((reel, index) => `<div class="slot-nonrealtime-reel" data-index="${index}" data-active="${index === 0}" data-ready="false" data-frozen="false"><span class="slot-nonrealtime-arrow">▼</span><div class="slot-nonrealtime-window"><span class="slot-nonrealtime-symbol">${helpers.text(reel.tokens[Number(reel.phase || 0)])}</span></div><span class="slot-nonrealtime-index">0${index + 1}</span></div>`).join("")}
          </div><div class="slot-nonrealtime-captured">${reels.map(() => "<span>·</span>").join("")}</div></section>
          <footer class="slot-nonrealtime-foot"><div class="slot-nonrealtime-readout" data-status="idle"></div>${interaction === "simplified" ? '<button class="slot-nonrealtime-button" id="slot-nonrealtime-capture" type="button">CAPTURE SYMBOL</button>' : ""}<button class="slot-nonrealtime-button" id="slot-nonrealtime-submit" type="button">${helpers.text(state.submit_label || "VERIFY")}</button></footer>
        </section>`;

      if (interaction === "full") {
        model.keyHandler = (event) => {
          if (event.repeat || model.submitting || !/^[a-z0-9]$/i.test(event.key)) return;
          event.preventDefault();
          capture("physical_keyboard", event.key);
        };
        window.addEventListener("keydown", model.keyHandler);
      } else {
        document.getElementById("slot-nonrealtime-capture")?.addEventListener("click", () => capture("capture_button"));
      }
      document.getElementById("slot-nonrealtime-submit")?.addEventListener("click", submit);
      document.querySelector(".slot-nonrealtime-captcha")?.focus();
      reveal(0);
    },
  };
})();
