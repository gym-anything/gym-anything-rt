(() => {
  'use strict';

  // Independent JavaScript implementation of the seed-driven nonperiodic
  // schedule. shared_runtime/server/incubator_graders/rotating_keyboard_v2.py
  // implements the identical PRNG, draw order and closed-form integral a
  // second time so rendering (here) and grading (there) can be checked
  // against each other instead of trusting one shared implementation.
  function mulberry32Step(state) {
    let a = (state + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return {state: a >>> 0, unit: ((t ^ (t >>> 14)) >>> 0) / 4294967296};
  }

  function smoothstep(u) {
    u = u < 0 ? 0 : (u > 1 ? 1 : u);
    return u * u * (3 - 2 * u);
  }

  function smoothstepIntegral(u) {
    u = u < 0 ? 0 : (u > 1 ? 1 : u);
    return u ** 3 - 0.5 * u ** 4;
  }

  // Lazily extended waypoint stream with prefix sums; never loops, never
  // settles into a constant tail, however long the attempt runs.
  function createSchedule(motion) {
    const segMin = Number(motion.segment_ms_min);
    const segMax = Number(motion.segment_ms_max);
    const yawMin = Number(motion.yaw_rate_min_deg_s);
    const yawMax = Number(motion.yaw_rate_max_deg_s);
    const rollMin = Number(motion.roll_rate_min_deg_s);
    const rollMax = Number(motion.roll_rate_max_deg_s);
    const pitchMax = Number(motion.pitch_max_deg);
    let state = Number(motion.seed) >>> 0;
    const draw = () => {
      const step = mulberry32Step(state);
      state = step.state;
      return step.unit;
    };
    const rate = (low, high) => {
      const magnitude = low + draw() * (high - low);
      const sign = draw() < 0.5 ? -1 : 1;
      return magnitude * sign;
    };
    const yaw0 = rate(yawMin, yawMax);
    const roll0 = rate(rollMin, rollMax);
    const times = [0];
    const gaps = [0];
    const yawRates = [yaw0];
    const rollRates = [roll0];
    const pitches = [0];
    const cumYaw = [0];
    const cumRoll = [0];
    function append() {
      const gap = segMin + draw() * (segMax - segMin);
      const yaw = rate(yawMin, yawMax);
      const roll = rate(rollMin, rollMax);
      const pitch = -pitchMax + draw() * (2 * pitchMax);
      const durationS = gap / 1000;
      cumYaw.push(cumYaw[cumYaw.length - 1] + durationS * 0.5 * (yawRates[yawRates.length - 1] + yaw));
      cumRoll.push(cumRoll[cumRoll.length - 1] + durationS * 0.5 * (rollRates[rollRates.length - 1] + roll));
      times.push(times[times.length - 1] + gap);
      gaps.push(gap);
      yawRates.push(yaw);
      rollRates.push(roll);
      pitches.push(pitch);
    }
    function ensure(elapsedMs) {
      while (times[times.length - 1] <= elapsedMs) append();
    }
    function waypoint(index) {
      while (times.length <= index) append();
      return {t: times[index], yaw_rate: yawRates[index], roll_rate: rollRates[index], pitch: pitches[index]};
    }
    function anglesAt(elapsedMs) {
      const elapsed = Math.max(0, Number(elapsedMs) || 0);
      ensure(elapsed);
      let low = 0;
      let high = times.length - 1;
      while (high - low > 1) {
        const mid = (low + high) >> 1;
        if (times[mid] <= elapsed) low = mid;
        else high = mid;
      }
      const index = low;
      const gap = gaps[index + 1];
      const durationS = gap / 1000;
      const u = (elapsed - times[index]) / gap;
      const yawLeft = yawRates[index];
      const yawRight = yawRates[index + 1];
      const rollLeft = rollRates[index];
      const rollRight = rollRates[index + 1];
      const yaw = cumYaw[index] + durationS * (yawLeft * u + (yawRight - yawLeft) * smoothstepIntegral(u));
      const roll = cumRoll[index] + durationS * (rollLeft * u + (rollRight - rollLeft) * smoothstepIntegral(u));
      const pitch = pitches[index] + (pitches[index + 1] - pitches[index]) * smoothstep(u);
      return {yaw, roll, pitch};
    }
    return {anglesAt, waypoint, ensure};
  }

  function anglesAt(motion, elapsedMs) {
    return createSchedule(motion).anglesAt(elapsedMs);
  }

  // Exposed so an isolated Playwright check can call the exact production
  // dynamics with a seed's public motion spec and compare against the Python
  // grader's independent recomputation at the same task times.
  window.RotatingKeyboardV2Dynamics = {mulberry32Step, createSchedule, anglesAt};

  let cleanup = () => {};

  function render(state, h) {
    cleanup();
    document.body.dataset.mechanic = 'rotating-keyboard-v2';
    const keyboard = state.keyboard || {};
    const interaction = state.control_condition?.interaction || 'full';
    const schedule = createSchedule(keyboard.motion || {});
    const spinAfter = Math.max(0, Number(keyboard.spin_after_characters ?? 1));
    const target = String(keyboard.target || '');
    const source = interaction === 'simplified' ? 'physical_keyboard' : 'onscreen_keys';

    const model = {
      input: '',
      inputSource: null,
      events: [],
      spinStartMs: null,
      keyHandler: null,
      submitted: false,
    };
    window.rotatingKeyboardV2Model = model;

    h.app.innerHTML = `
      <section class="rkv2-captcha${target.length > 6 ? ' rkv2-long-code' : ''}" data-interaction="${h.text(interaction)}" data-mechanic="${h.text(state.mechanic_id)}" data-challenge-id="${h.text(state.challenge_id)}">
        <header class="interaction-head rkv2-head"><p>COORDINATE CHECK / 04V2</p><h1>${h.text(state.prompt)}</h1></header>
        <section class="rkv2-stage">
          <div class="rkv2-fixed"><span>${interaction === 'simplified' ? 'TYPE ON YOUR KEYBOARD' : 'CONFIRM'}</span><strong>${h.text(target)}</strong><div class="rkv2-entry"></div></div>
          <div class="rkv2-perspective"><div class="rkv2-deck" style="--key-width:${Number(keyboard.key_width || 38)}px;--key-height:${Number(keyboard.key_height || 45)}px">
            ${(keyboard.rows || []).map((row) => `<div class="rkv2-row">${row.split('').map((key) => `<button type="button" class="rkv2-key" data-key="${h.text(key)}">${h.text(key)}</button>`).join('')}</div>`).join('')}
            <div class="rkv2-row rkv2-row-short"><button type="button" class="rkv2-key rkv2-delete" data-key="BACKSPACE">ERASE</button></div>
          </div></div>
        </section>
        <footer class="interaction-foot"><div class="readout" data-status="idle"></div><button class="interaction-submit rkv2-submit" id="submit-rotating-v2" type="button">${h.text(state.submit_label || 'CONFIRM')}</button></footer>
      </section>`;

    const deck = h.app.querySelector('.rkv2-deck');
    const entry = h.app.querySelector('.rkv2-entry');

    function currentElapsedMs() {
      return model.spinStartMs == null ? 0 : Math.max(0, performance.now() - model.spinStartMs);
    }

    function updateDisplay() {
      entry.innerHTML = target.split('').map((_, index) => {
        const filled = index < model.input.length;
        return `<span data-filled="${filled ? 'true' : 'false'}">${filled ? h.text(model.input[index]) : ''}</span>`;
      }).join('');
    }

    function paint() {
      if (model.spinStartMs == null) {
        deck.style.transform = 'rotateX(0deg) rotateY(0deg) rotateZ(0deg)';
        return;
      }
      const angles = schedule.anglesAt(currentElapsedMs());
      deck.style.transform = `rotateX(${angles.pitch}deg) rotateY(${angles.yaw}deg) rotateZ(${angles.roll}deg)`;
    }

    // Motion starts as soon as the entered length reaches spin_after_characters;
    // with spin_after_characters = 0 that is immediately at render, before any input.
    function activateIfNeeded() {
      if (model.spinStartMs == null && model.input.length >= spinAfter) {
        model.spinStartMs = performance.now();
        deck.classList.add('is-spinning');
      }
    }

    function acceptCharacter(key) {
      if (model.submitted || model.input.length >= target.length) return;
      const elapsed = currentElapsedMs();
      const angles = model.spinStartMs == null ? {yaw: 0, roll: 0, pitch: 0} : schedule.anglesAt(elapsed);
      model.events.push({
        key,
        input_source: source,
        schedule_elapsed_ms: elapsed,
        observed_yaw_deg: angles.yaw,
        observed_roll_deg: angles.roll,
        observed_pitch_deg: angles.pitch,
      });
      model.input += key;
      model.inputSource = source;
      activateIfNeeded();
      updateDisplay();
      h.setReadout('', 'idle');
    }

    function eraseCharacter() {
      if (model.submitted || !model.input.length) return;
      model.input = model.input.slice(0, -1);
      model.events.pop();
      updateDisplay();
      h.setReadout('', 'idle');
    }

    h.app.querySelectorAll('.rkv2-key').forEach((button) => {
      button.tabIndex = -1;
      button.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') event.preventDefault();
      });
      button.addEventListener('click', (event) => {
        // Full interaction requires hitting the moving key with the pointer.
        // Browser keyboard activation generates a click with detail === 0.
        if (interaction !== 'full' || event.detail === 0) return;
        const key = button.dataset.key;
        if (key === 'BACKSPACE') eraseCharacter();
        else acceptCharacter(key);
      });
    });

    if (interaction === 'simplified') {
      const alphabet = new Set((keyboard.rows || []).join('').split(''));
      model.keyHandler = (event) => {
        if (event.repeat) return;
        const key = String(event.key || '').toUpperCase();
        if (key === 'BACKSPACE') {
          eraseCharacter();
          event.preventDefault();
          return;
        }
        if (!alphabet.has(key)) return;
        event.preventDefault();
        acceptCharacter(key);
      };
      window.addEventListener('keydown', model.keyHandler);
    }

    h.app.querySelector('#submit-rotating-v2').addEventListener('click', async () => {
      if (model.submitted) return;
      model.submitted = true;
      const payload = {
        mechanic_id: state.mechanic_id,
        task_id: state.task_id,
        challenge_id: state.challenge_id,
        interaction_mode: interaction,
        text: model.input,
        input_source: model.inputSource,
        events: model.events,
      };
      try {
        const response = await fetch('/result', {
          method: 'POST',
          headers: {'content-type': 'application/json'},
          body: JSON.stringify(payload),
        });
        const outcome = await response.json();
        if (outcome.passed === true) {
          h.setReadout('PASS', 'passed');
        } else if (outcome.passed === false) {
          model.submitted = false;
          if (outcome.state) render(outcome.state, h);
          h.setReadout('FAIL', 'error');
        } else {
          model.submitted = false;
        }
      } catch (_error) {
        model.submitted = false;
        h.setReadout('FAIL', 'error');
      }
    });

    updateDisplay();
    activateIfNeeded();
    paint();
    let frame = requestAnimationFrame(function loop() {
      paint();
      frame = requestAnimationFrame(loop);
    });
    cleanup = () => {
      cancelAnimationFrame(frame);
      if (model.keyHandler) window.removeEventListener('keydown', model.keyHandler);
    };
  }

  window.GymAnythingRTMechanics = window.GymAnythingRTMechanics || {};
  window.GymAnythingRTMechanics.rotating_keyboard_v2 = {rootSelector: '.rkv2-captcha', render};
})();
