(() => {
  'use strict';

  // The donor's key plane moves continuously.  The matched counterpart keeps
  // the same generated keyboard and click surface, but freezes the plane at
  // its initial layout.  In particular, there is no timer, animation frame,
  // CSS animation, or autonomous state update to outrun a pending click.
  const FIXED_ROTATION = Object.freeze({yaw: 0, roll: 0, pitch: 0});

  let cleanup = () => {};

  function render(state, h) {
    cleanup();
    document.body.dataset.mechanic = 'rotating-keyboard-nonrealtime';
    const keyboard = state.keyboard || {};
    const interaction = state.control_condition?.interaction || 'full';
    const target = String(keyboard.target || '');
    const source = interaction === 'simplified' ? 'physical_keyboard' : 'onscreen_keys';
    const attemptStartMs = performance.now();
    const model = {
      input: '',
      inputSource: null,
      events: [],
      keyHandler: null,
      submitted: false,
    };
    window.rotatingKeyboardNonRealtimeModel = model;

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
        <footer class="interaction-foot"><div class="readout" data-status="idle"></div><button class="interaction-submit rkv2-submit" id="submit-rotating-nonrealtime" type="button">${h.text(state.submit_label || 'CONFIRM')}</button></footer>
      </section>`;

    const deck = h.app.querySelector('.rkv2-deck');
    const entry = h.app.querySelector('.rkv2-entry');

    function currentElapsedMs() {
      const elapsed = performance.now() - attemptStartMs;
      return Number.isFinite(elapsed) ? Math.max(0, elapsed) : 0;
    }

    function paintFixedLayout() {
      deck.style.transform = `rotateX(${FIXED_ROTATION.pitch}deg) rotateY(${FIXED_ROTATION.yaw}deg) rotateZ(${FIXED_ROTATION.roll}deg)`;
    }

    function updateDisplay() {
      entry.innerHTML = target.split('').map((_, index) => {
        const filled = index < model.input.length;
        return `<span data-filled="${filled ? 'true' : 'false'}">${filled ? h.text(model.input[index]) : ''}</span>`;
      }).join('');
    }

    function acceptCharacter(key) {
      if (model.submitted || model.input.length >= target.length) return;
      model.events.push({
        key,
        input_source: source,
        schedule_elapsed_ms: currentElapsedMs(),
        observed_yaw_deg: FIXED_ROTATION.yaw,
        observed_roll_deg: FIXED_ROTATION.roll,
        observed_pitch_deg: FIXED_ROTATION.pitch,
      });
      model.input += key;
      model.inputSource = source;
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
        // Full interaction remains mouse-only. Keyboard activation is not a
        // substitute for the existing on-screen action surface.
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

    h.app.querySelector('#submit-rotating-nonrealtime').addEventListener('click', async () => {
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
    paintFixedLayout();
    cleanup = () => {
      if (model.keyHandler) window.removeEventListener('keydown', model.keyHandler);
    };
  }

  window.GymAnythingRTMechanics = window.GymAnythingRTMechanics || {};
  window.GymAnythingRTMechanics.rotating_keyboard_nonrealtime = {rootSelector: '.rkv2-captcha', render};
})();
