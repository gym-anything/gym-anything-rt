(() => {
  'use strict';
  function noise(seed, index) {
    let x = (seed ^ Math.imul(index + 1, 0x9e3779b9)) >>> 0;
    x = Math.imul(x ^ (x >>> 16), 0x85ebca6b) >>> 0;
    x = Math.imul(x ^ (x >>> 13), 0xc2b2ae35) >>> 0;
    return ((x ^ (x >>> 16)) >>> 0) / 4294967295 * 2 - 1;
  }
  function motion(seed, ms, span = 1600) {
    const u = Math.max(0, ms) / span, n = Math.floor(u), f = u - n;
    return noise(seed, n) + (noise(seed, n + 1) - noise(seed, n)) * f * f * (3 - 2 * f);
  }
  function integral(seed, ms, span = 1600) {
    const u = Math.max(0, ms) / span, n = Math.floor(u), f = u - n;
    let sum = 0;
    for (let i = 0; i < n; i++) sum += (noise(seed, i) + noise(seed, i + 1)) / 2;
    return span * (sum + noise(seed, n) * f + (noise(seed, n + 1) - noise(seed, n)) * (f**3 - f**4 / 2));
  }
  function vector(spec, ms) {
    return spec.amplitude.map((a, i) => a * motion(spec.seed + i * 7919, ms, spec.span_ms));
  }
  window.RealtimeFourMotion = {noise, motion, integral, vector};
})();
