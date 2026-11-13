// Location pin for the chat page (src/app/main.py). Runs as a gr.HTML js_on_load script, where Gradio provides
// `element` (this component's root), `props` (props.value is the component's value) and `trigger`.
//
// The value is "" (no pin), "lat, lon (±N m)" from the device's location, or "lat, lon (map pin)" once the user taps
// the map or drags the pin. main.location_note() turns it into a note for the model, which passes lat/lon to the
// filing tools. "Use my location" needs a secure context (https or localhost); elsewhere the user can still tap the
// map. Leaflet is loaded by the component's `head`.
(function () {
  "use strict";
  const SHEFFIELD = [53.3811, -1.4701];
  const BBOX = { west: -1.80, south: 53.30, east: -1.32, north: 53.50 }; // geocode.SHEFFIELD_BBOX
  const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/"; // same basemap as /dashboard
  const TILES = [ESRI + "World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
                 ESRI + "World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}"];
  const CANVAS_MAX_ZOOM = 16; // Esri canvas tiles stop here; Leaflet upscales beyond it.

  const $ = sel => element.querySelector(sel);
  const status = $(".lp-status"), useBtn = $(".lp-use"), clearBtn = $(".lp-clear"), mapEl = $(".lp-map");
  let hint = "";

  if (!window.isSecureContext || !navigator.geolocation) {
    useBtn.disabled = true;
    hint = window.isSecureContext ? "(This browser can't share its location.)"
                                  : "(Sharing your location needs the https:// address.)";
  }

  const inSheffield = (lat, lon) => lat >= BBOX.south && lat <= BBOX.north && lon >= BBOX.west && lon <= BBOX.east;

  function start() {
    const map = L.map(mapEl, { scrollWheelZoom: false, maxZoom: 19 }).setView(SHEFFIELD, 12);
    TILES.forEach((url, n) => L.tileLayer(url, {
      maxZoom: 19, maxNativeZoom: CANVAS_MAX_ZOOM,
      attribution: n ? "" : "Powered by Esri | Tiles &copy; Esri, HERE, Garmin, &copy; OpenStreetMap contributors",
    }).addTo(map));

    let marker = null, pin = null;

    function show(message) {
      status.textContent = message || (pin
        ? `Pin at ${pin.lat.toFixed(5)}, ${pin.lon.toFixed(5)}` +
          (pin.accuracy_m ? ` (accurate to about ${Math.round(pin.accuracy_m)} m)` : "") +
          ". Drag it to the exact spot if needed."
        : "No pin yet. Tap the map where the problem is" + (useBtn.disabled ? "." : ", or use your location.") +
          (hint ? " " + hint : ""));
      clearBtn.disabled = !pin;
    }

    function publish() {
      props.value = !pin ? "" : `${pin.lat.toFixed(6)}, ${pin.lon.toFixed(6)} ` +
        (pin.source === "device" ? `(±${pin.accuracy_m ?? 0} m)` : "(map pin)");
      trigger("change");
    }

    function set(latlng, source, accuracy) {
      if (!inSheffield(latlng.lat, latlng.lng)) {
        show("That's outside Sheffield, so this service can't report it. Tap a point in Sheffield instead.");
        return;
      }
      if (!marker) {
        marker = L.marker(latlng, { draggable: true, autoPan: true, title: "Problem location", alt: "Problem location pin" })
          .addTo(map);
        marker.on("dragend", () => set(marker.getLatLng(), "map"));
      } else {
        marker.setLatLng(latlng);
      }
      pin = { lat: +latlng.lat.toFixed(6), lon: +latlng.lng.toFixed(6), source };
      if (accuracy != null) pin.accuracy_m = Math.round(accuracy);
      show();
      publish();
    }

    map.on("click", e => set(e.latlng, "map"));

    useBtn.addEventListener("click", () => {
      show("Finding your location…");
      navigator.geolocation.getCurrentPosition(pos => {
        const ll = L.latLng(pos.coords.latitude, pos.coords.longitude);
        if (!inSheffield(ll.lat, ll.lng)) {
          show("You seem to be outside Sheffield. Tap the map where the problem is instead.");
          return;
        }
        set(ll, "device", pos.coords.accuracy);
        map.setView(ll, 17);
      }, err => {
        show(err.code === err.PERMISSION_DENIED
          ? "Location sharing is turned off for this site. Tap the map where the problem is instead."
          : "Couldn't find your location. Tap the map where the problem is instead.");
      }, { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 });
    });

    clearBtn.addEventListener("click", () => {
      if (marker) { map.removeLayer(marker); marker = null; }
      pin = null;
      show();
      publish();
    });

    show();
    // Gradio may lay the page out after this runs; make Leaflet re-measure its container.
    new ResizeObserver(() => map.invalidateSize()).observe(mapEl);
  }

  (function waitForLeaflet(tries) {
    if (window.L) start();
    else if (tries > 0) setTimeout(() => waitForLeaflet(tries - 1), 100);
    else status.textContent = "The map couldn't load. Describe where the problem is in the chat instead.";
  })(100);
})();
