/* =========================================================================
   AirWatch GeoSlovenija — mission control front-end behaviors
   - keyboard arrow keys scrub the day slider
   - numeric readouts tween from previous to new value
   - subtle parallax tilt on the map container
   - fade-in transition class applied when event changes
   ========================================================================= */
(function () {
  "use strict";

  // ---- 1. keyboard nav for the day slider -------------------------------
  function tryNudgeSlider(delta) {
    if (typeof $ === "undefined") return false;
    var $el = $("#day_index");
    if (!$el.length) return false;
    var inst = $el.data("ionRangeSlider");
    if (!inst) return false;
    var min = inst.options.min;
    var max = inst.options.max;
    var cur = inst.result.from;
    var next = Math.max(min, Math.min(max, cur + delta));
    if (next === cur) return true;
    inst.update({ from: next });
    if (window.Shiny && Shiny.setInputValue) {
      Shiny.setInputValue("day_index", next, { priority: "event" });
    }
    return true;
  }

  document.addEventListener("keydown", function (e) {
    var t = e.target;
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) {
      return;
    }
    if (e.key === "ArrowRight") {
      if (tryNudgeSlider(1)) e.preventDefault();
    } else if (e.key === "ArrowLeft") {
      if (tryNudgeSlider(-1)) e.preventDefault();
    }
  });

  // ---- 2. animated numeric counters on telemetry readouts ---------------
  var tracked = new WeakMap();

  function extractNumber(text) {
    var m = (text || "").match(/-?\d+(?:\.\d+)?/);
    return m ? parseFloat(m[0]) : null;
  }

  function tweenValue(el) {
    if (!el || !el.textContent) return;
    var text = el.textContent;
    var target = extractNumber(text);
    if (target === null) {
      tracked.delete(el);
      return;
    }
    var prev = tracked.get(el);
    if (prev === target) return;
    tracked.set(el, target);
    if (prev === undefined || prev === null) return; // skip on first render
    var match = text.match(/(.*?)(-?\d+(?:\.\d+)?)(.*)/);
    if (!match) return;
    var prefix = match[1];
    var suffix = match[3];
    var dur = 420;
    var t0 = performance.now();
    function frame(now) {
      var p = Math.min(1, (now - t0) / dur);
      var ease = 1 - Math.pow(1 - p, 3);
      var cur = prev + (target - prev) * ease;
      el.textContent = prefix + cur.toFixed(2) + suffix;
      if (p < 1) requestAnimationFrame(frame);
      else el.textContent = text;
    }
    requestAnimationFrame(frame);
  }

  function scanReadouts() {
    document.querySelectorAll(".aw-readout .value, .aw-region-detail .value-line .num").forEach(tweenValue);
  }

  // ---- 3. parallax — disabled in the calm design (kept as no-op) -------
  function attachParallax() {
    // Intentionally empty: the redesign favors steadiness over motion.
  }

  // ---- 4. fade-in on event change ---------------------------------------
  function bindEventFade() {
    document.addEventListener("change", function (e) {
      var t = e.target;
      if (!t || t.name !== "event_id") return;
      var panels = document.querySelectorAll(
        ".aw-map-wrap, .aw-telemetry, .aw-region-detail, .aw-trend-wrap, .aw-event-summary"
      );
      panels.forEach(function (p) {
        p.classList.remove("aw-fade-in");
        // restart animation
        void p.offsetWidth;
        p.classList.add("aw-fade-in");
      });
    });
  }

  // ---- 5. observe DOM for readout updates --------------------------------
  function attachObserver() {
    var mo = new MutationObserver(function () {
      scanReadouts();
    });
    mo.observe(document.body, { subtree: true, childList: true, characterData: true });
    scanReadouts();
  }

  function init() {
    attachParallax();
    bindEventFade();
    attachObserver();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
