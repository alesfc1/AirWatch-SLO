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
        ".aw-map-canvas, .aw-overlay-tl, .aw-overlay-tr, .aw-overlay-bl, .aw-overlay-br, .aw-trend-wrap, .aw-event-summary"
      );
      panels.forEach(function (p) {
        p.classList.remove("aw-fade-in");
        // restart animation
        void p.offsetWidth;
        p.classList.add("aw-fade-in");
      });
    });
  }

  // ---- 4b. auto-scroll through month ------------------------------------
  // The choropleth is updated via Plotly.restyle on each tick (see the
  // map_restyle custom message handler below), so the mapbox figure is not
  // torn down between frames. The pace below is for *reading* the data, not
  // for hitting frame-rate limits — keep it slow enough that the user can
  // absorb each day's pattern before the next one arrives.
  var STEP_MS = 1400;
  var play = { timer: null, playing: false, suppressNextChange: false };

  function getSliderInst() {
    if (typeof $ === "undefined") return null;
    var $el = $("#day_index");
    if (!$el.length) return null;
    return $el.data("ionRangeSlider") || null;
  }

  function setSliderValue(value) {
    var inst = getSliderInst();
    if (!inst) return null;
    var next = Math.max(inst.options.min, Math.min(inst.options.max, value));
    if (next === inst.result.from) return next;
    inst.update({ from: next });
    if (window.Shiny && Shiny.setInputValue) {
      Shiny.setInputValue("day_index", next, { priority: "event" });
    }
    return next;
  }

  function updatePlayButton() {
    var btn = document.getElementById("aw-play-toggle");
    if (!btn) return;
    var label = btn.querySelector(".play-label");
    if (play.playing) {
      btn.classList.add("is-playing");
      if (label) label.textContent = "Pavza";
      btn.setAttribute("aria-label", "Ustavi animacijo");
    } else {
      btn.classList.remove("is-playing");
      if (label) label.textContent = "Predvajaj";
      btn.setAttribute("aria-label", "Predvajaj animacijo skozi mesec");
    }
  }

  function stopPlay() {
    if (play.timer) {
      clearInterval(play.timer);
      play.timer = null;
    }
    play.playing = false;
    updatePlayButton();
  }

  function startPlay() {
    var inst = getSliderInst();
    if (!inst) return;
    // If we're at (or past) the end, restart from day 1.
    if (inst.result.from >= inst.options.max) {
      setSliderValue(inst.options.min);
    }
    play.playing = true;
    updatePlayButton();
    if (play.timer) clearInterval(play.timer);
    play.timer = setInterval(function () {
      var i = getSliderInst();
      if (!i) { stopPlay(); return; }
      var cur = i.result.from;
      if (cur >= i.options.max) { stopPlay(); return; }
      setSliderValue(cur + 1);
    }, STEP_MS);
  }

  function togglePlay() {
    if (play.playing) stopPlay();
    else startPlay();
  }

  function bindPlayButton() {
    document.addEventListener("click", function (e) {
      var btn = e.target.closest && e.target.closest("#aw-play-toggle");
      if (!btn) return;
      e.preventDefault();
      togglePlay();
    });
  }

  // Pause auto-play when the user manually grabs the slider.
  function bindManualSliderInterrupt() {
    function pauseFromUser(e) {
      var stage = e.target.closest && e.target.closest(".aw-slider-stage");
      if (!stage) return;
      if (play.playing) stopPlay();
    }
    document.addEventListener("mousedown", pauseFromUser, true);
    document.addEventListener("touchstart", pauseFromUser, { passive: true, capture: true });
  }

  // When the user picks a different event card, rewind to day 1 and auto-play.
  function bindAutoPlayOnEventChange() {
    document.addEventListener("change", function (e) {
      var t = e.target;
      if (!t || t.name !== "event_id") return;
      stopPlay();
      // Wait for the server to push the updated slider bounds, then start.
      setTimeout(function () {
        setSliderValue(1);
        setTimeout(startPlay, 420);
      }, 360);
    });
  }

  // Kick off on first load — small delay so the user can orient before motion.
  function autoStartOnFirstLoad() {
    function tryStart(retries) {
      var inst = getSliderInst();
      if (inst && document.getElementById("aw-play-toggle")) {
        setSliderValue(1);
        startPlay();
        return;
      }
      if (retries > 0) setTimeout(function () { tryStart(retries - 1); }, 250);
    }
    setTimeout(function () { tryStart(20); }, 1200);
  }

  // ---- 5. observe DOM for readout updates --------------------------------
  function attachObserver() {
    var mo = new MutationObserver(function () {
      scanReadouts();
    });
    mo.observe(document.body, { subtree: true, childList: true, characterData: true });
    scanReadouts();
  }

  // ---- 5b. client-side Plotly.restyle for the map -----------------------
  // The server pushes only the day's z / locations / customdata as a custom
  // message — we apply it with Plotly.restyle so the mapbox layer, geojson,
  // and colorbar all stay mounted between frames. The two choropleth traces
  // (index 0 = with-value, index 1 = without-value) are always present.
  function findPlotlyEl() {
    var container = document.getElementById("map_plot");
    if (!container) return null;
    if (container.classList && container.classList.contains("js-plotly-plot")) {
      return container;
    }
    return container.querySelector(".js-plotly-plot");
  }

  function applyMapRestyle(msg) {
    if (!msg || !window.Plotly) return false;
    var el = findPlotlyEl();
    if (!el) return false;
    var wv = msg.with_value || { locations: [], z: [], customdata: [] };
    var nv = msg.without_value || { locations: [], customdata: [] };
    try {
      window.Plotly.restyle(el, {
        locations: [wv.locations || []],
        z: [wv.z || []],
        customdata: [wv.customdata || []],
      }, [0]);
      window.Plotly.restyle(el, {
        locations: [nv.locations || []],
        z: [(nv.locations || []).map(function () { return 0; })],
        customdata: [nv.customdata || []],
      }, [1]);
      return true;
    } catch (err) {
      return false;
    }
  }

  function bindMapRestyle() {
    if (!window.Shiny || !Shiny.addCustomMessageHandler) {
      // Shiny not ready yet — retry shortly.
      setTimeout(bindMapRestyle, 200);
      return;
    }
    Shiny.addCustomMessageHandler("map_restyle", function (msg) {
      // Plotly may not be mounted yet on first paint; retry a few times.
      if (applyMapRestyle(msg)) return;
      var attempts = 0;
      var t = setInterval(function () {
        attempts += 1;
        if (applyMapRestyle(msg) || attempts > 20) clearInterval(t);
      }, 120);
    });
  }

  // ---- 5c. client-side Plotly.relayout for the trend chart --------------
  // The trend figure is cached server-side per (event, pollutant, region,
  // mode) and shipped only when one of those changes. The day slider's
  // dotted "selected day" marker is sent here as a tiny custom message
  // and applied with Plotly.relayout — so slider drags never re-render
  // the whole figure.
  function findTrendPlotlyEl() {
    var container = document.getElementById("trend_plot");
    if (!container) return null;
    if (container.classList && container.classList.contains("js-plotly-plot")) {
      return container;
    }
    return container.querySelector(".js-plotly-plot");
  }

  function applyTrendDayMarker(msg) {
    if (!window.Plotly) return false;
    var el = findTrendPlotlyEl();
    if (!el || !el.layout) return false;
    var baseCount =
      (el.layout.meta && typeof el.layout.meta.base_shape_count === "number")
        ? el.layout.meta.base_shape_count
        : (el.layout.shapes ? el.layout.shapes.length : 0);
    var shapes = (el.layout.shapes || []).slice(0, baseCount);
    if (msg && msg.date) {
      shapes.push({
        type: "line",
        x0: msg.date,
        x1: msg.date,
        yref: "paper",
        y0: 0,
        y1: 1,
        line: { color: "#63e0ff", dash: "dot", width: 1.6 },
      });
    }
    try {
      window.Plotly.relayout(el, { shapes: shapes });
      return true;
    } catch (err) {
      return false;
    }
  }

  function bindTrendDayMarker() {
    if (!window.Shiny || !Shiny.addCustomMessageHandler) {
      setTimeout(bindTrendDayMarker, 200);
      return;
    }
    Shiny.addCustomMessageHandler("trend_day_marker", function (msg) {
      if (applyTrendDayMarker(msg)) return;
      var attempts = 0;
      var t = setInterval(function () {
        attempts += 1;
        if (applyTrendDayMarker(msg) || attempts > 20) clearInterval(t);
      }, 120);
    });
  }

  function init() {
    attachParallax();
    bindEventFade();
    attachObserver();
    bindPlayButton();
    bindManualSliderInterrupt();
    bindAutoPlayOnEventChange();
    bindMapRestyle();
    bindTrendDayMarker();
    autoStartOnFirstLoad();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
