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

  // ---- 5b. map renderer — two paths -------------------------------------
  // FULL render (`map_figure`): the server ships the entire Plotly figure
  // JSON only when something structural changes — event / pollutant /
  // mode / region / scope / context-layer toggles. We call Plotly.react so
  // the basemap tiles, viewport and unchanged traces stay in place. This
  // path is NOT hit on day-slider ticks.
  //
  // LIGHT day update (`map_restyle`): the server ships only the per-day
  // z / locations / customdata for the two NUTS3 choropleth traces. We
  // apply it with Plotly.restyle, which touches just trace 0 (regions with
  // data) and trace 1 (no-data grey). Basemap, GeoJSON, layout, zoom,
  // selected-region highlight, event marker and context overlays stay
  // mounted and unaffected — that is what makes the Play/Pause animation
  // feel cinematic instead of like a full page reload.
  //
  // mapbox.uirevision="map-keep-view" pins pan/zoom across full rebuilds
  // so the user's view doesn't snap back. Plotly.react has the same
  // signature as newPlot and handles the first mount; if it throws (very
  // rare, on drastic figure-shape changes), we fall back to a full newPlot.
  var pendingMapMsg = null;
  // Last restyle payload — replayed after a full rebuild so trace 0/1 stay
  // in sync with the current day (otherwise a freshly built figure could
  // briefly show its bake-in defaults before the next day-snapshot arrives).
  var pendingRestyleMsg = null;

  function applyMapFigure(msg) {
    if (!msg) return false;
    if (!window.Plotly) return false;
    var el = document.getElementById("map_plot");
    if (!el) return false;
    var data = msg.data || [];
    var layout = msg.layout || {};
    var config = { responsive: true, displayModeBar: false };
    try {
      window.Plotly.react(el, data, layout, config);
      return true;
    } catch (err) {
      try {
        window.Plotly.newPlot(el, data, layout, config);
        return true;
      } catch (err2) {
        return false;
      }
    }
  }

  function drainPendingMap() {
    if (!pendingMapMsg) return true;
    if (applyMapFigure(pendingMapMsg)) {
      pendingMapMsg = null;
      // After a full rebuild, re-apply the last day-snapshot if we have
      // one, so trace 0/1 reflect the current slider value.
      if (pendingRestyleMsg) applyMapRestyle(pendingRestyleMsg);
      return true;
    }
    return false;
  }

  // Apply a day-only restyle to the two choropleth traces (indices 0 and 1).
  // The figure must already be mounted by a prior map_figure message — we
  // verify that by checking `el.data.length >= 2`. If not yet mounted, the
  // caller will retry for a short window.
  function applyMapRestyle(msg) {
    if (!msg) return false;
    if (!window.Plotly) return false;
    var el = document.getElementById("map_plot");
    if (!el || !el.data || el.data.length < 2) return false;
    var v = msg.values || {};
    var n = msg.nodata || {};
    // Plotly.restyle wraps array-typed attrs once per trace; passing
    // [arr] sets `data[0].<attr> = arr` rather than spreading element-wise.
    try {
      window.Plotly.restyle(
        el,
        {
          z: [v.z || []],
          locations: [v.locations || []],
          customdata: [v.customdata || []],
        },
        [0]
      );
      window.Plotly.restyle(
        el,
        {
          z: [n.z || []],
          locations: [n.locations || []],
          customdata: [n.customdata || []],
        },
        [1]
      );
      return true;
    } catch (err) {
      return false;
    }
  }

  function bindMapRestyle() {
    if (!window.Shiny || !Shiny.addCustomMessageHandler) {
      setTimeout(bindMapRestyle, 200);
      return;
    }
    Shiny.addCustomMessageHandler("map_figure", function (msg) {
      // Stash the latest payload — the renderer always uses the freshest one.
      pendingMapMsg = msg;
      if (applyMapFigure(msg)) {
        pendingMapMsg = null;
        if (pendingRestyleMsg) applyMapRestyle(pendingRestyleMsg);
        return;
      }
      // Plotly / #map_plot may not be mounted yet; retry briefly.
      var attempts = 0;
      var t = setInterval(function () {
        attempts += 1;
        if (drainPendingMap() || attempts > 40) clearInterval(t);
      }, 120);
    });
    Shiny.addCustomMessageHandler("map_restyle", function (msg) {
      // Remember the latest snapshot so we can replay it after a full
      // rebuild (see applyMapFigure success path).
      pendingRestyleMsg = msg;
      if (applyMapRestyle(msg)) return;
      // Map may not be mounted yet on first paint — retry briefly. Once
      // the full figure arrives we'll also replay this payload, so this
      // retry loop is only insurance for the case where map_restyle
      // arrives before any map_figure (which shouldn't normally happen).
      var attempts = 0;
      var t = setInterval(function () {
        attempts += 1;
        if (applyMapRestyle(msg) || attempts > 40) clearInterval(t);
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
        line: { color: "#0a4f8a", dash: "dot", width: 2.6 },
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

  // ---- 5d. precise placement of the "Dan dogodka" marker ----------------
  // The server emits the marker with an approximate `left:` and a
  // data-frac attribute (= (event_day_index - 1) / (max_day - 1)). The
  // CSS approximation can drift a few percent off the handle's actual
  // center because ionRangeSlider's handle moves over (slider_width -
  // handle_width), not the full track. We read the real geometry of
  // .irs-line + .irs-handle once the slider has mounted and pin the
  // marker exactly under the handle position that corresponds to the
  // event's day_index.
  function positionEventMarker(marker) {
    if (!marker) return;
    var stage = marker.closest && marker.closest(".aw-slider-stage");
    if (!stage) return;
    var line = stage.querySelector(".irs-line");
    if (!line) return;
    var fracAttr = marker.getAttribute("data-frac");
    var frac = parseFloat(fracAttr);
    if (isNaN(frac)) return;
    frac = Math.max(0, Math.min(1, frac));
    var handleEl =
      stage.querySelector(".irs-handle.from") ||
      stage.querySelector(".irs-handle.single") ||
      stage.querySelector(".irs-handle");
    var handleW = handleEl ? handleEl.getBoundingClientRect().width : 18;
    if (!handleW || handleW < 4) handleW = 18;
    var lineRect = line.getBoundingClientRect();
    var stageRect = stage.getBoundingClientRect();
    if (!lineRect.width) return;
    var lineLeftInStage = lineRect.left - stageRect.left;
    var centerX =
      lineLeftInStage + handleW / 2 + (lineRect.width - handleW) * frac;
    marker.style.left = centerX + "px";
  }

  function positionAllEventMarkers() {
    document.querySelectorAll(".aw-event-marker[data-frac]").forEach(
      positionEventMarker
    );
  }

  function bindEventMarkerPlacement() {
    // Re-place on resize (slider width changes with the layout).
    window.addEventListener("resize", positionAllEventMarkers);

    // Re-place when Shiny swaps the marker (event change) or the slider
    // rebuilds (max_day change). A MutationObserver scoped to slider
    // stages catches both without per-message wiring.
    var mo = new MutationObserver(function () {
      positionAllEventMarkers();
    });
    mo.observe(document.body, { subtree: true, childList: true });

    // Initial paint — the slider needs a tick to mount; retry briefly.
    var attempts = 0;
    var t = setInterval(function () {
      attempts += 1;
      positionAllEventMarkers();
      if (attempts > 20) clearInterval(t);
    }, 120);
  }

  // ---- Mirror the scope radio into <body data-scope> so CSS can switch
  // visibility of Regije-only vs Občine-only DOM pieces.
  function applyScope(value) {
    var v = value === "obcine" ? "obcine" : "regije";
    document.body.dataset.scope = v;
  }
  function bindScopeMirror() {
    var initial = document.querySelector(
      'input[type="radio"][name="scope"]:checked'
    );
    applyScope(initial ? initial.value : "regije");
    document.addEventListener("change", function (e) {
      var t = e.target;
      if (
        t && t.tagName === "INPUT" && t.type === "radio" &&
        t.name === "scope"
      ) {
        applyScope(t.value);
      }
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
    bindEventMarkerPlacement();
    bindScopeMirror();
    autoStartOnFirstLoad();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
