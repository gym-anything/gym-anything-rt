(() => {
  "use strict";
  window.GymAnythingRTMechanics = window.GymAnythingRTMechanics || {};
  window.GymAnythingRTMechanics.orbital_docking_customs = {
    rootSelector: ".ivv-orbital-docking-customs",
    render: (state, helpers) => window.GymAnythingRTInteractionViiViii.render("orbital_docking_customs", state, helpers),
  };
})();
