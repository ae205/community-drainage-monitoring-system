// locationpicker.js — real map location picker using Leaflet + OpenStreetMap.
// Requires leaflet.css and leaflet.js to be loaded on the page before this file
// (added via CDN in report_form.html and admin_dashboard.html).

function createLocationPicker(containerId, opts = {}) {
  const container = document.getElementById(containerId);
  container.style.height = (opts.height || 320) + "px";
  container.style.borderRadius = "10px";
  container.style.overflow = "hidden";
  container.style.border = "2px solid #cbd5e1";

  // Default center: Abraka, Delta State, Nigeria
  const DEFAULT_CENTER = [5.7785, 6.0968];
  const center = opts.initial ? [opts.initial.lat, opts.initial.lng] : DEFAULT_CENTER;

  const map = L.map(container, { zoomControl: true }).setView(center, opts.initial ? 16 : 14);

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 19,
  }).addTo(map);

  // Ethiope East LGA approximate boundary, for local-government context.
  // Coordinates are a bounding extent (not a surveyed polygon), sourced from
  // published academic coordinates for the LGA: longitude 5.94-6.08 deg E,
  // latitude 5.62-5.78 deg N (Amadi & Olale, "The Use of Multi-Criteria
  // Decision Approach in Determining the Location for Solid Waste Disposal
  // Facility in Ethiope East, Nigeria"). Shown for orientation only — the
  // true administrative boundary is irregular, not rectangular.
  const LGA_BOUNDS = [
    [5.62, 5.94],
    [5.78, 6.08],
  ];
  const lgaOutline = L.rectangle(LGA_BOUNDS, {
    color: "#1d4ed8",
    weight: 2,
    dashArray: "6 6",
    fill: false,
    interactive: false,
  }).addTo(map);
  lgaOutline.bindTooltip("Ethiope East LGA (approximate extent)", {
    permanent: true,
    direction: "top",
    className: "lga-boundary-label",
    opacity: 0.85,
  });

  let marker = null;
  let selected = opts.initial || null;
  let userLocationMarker = null;

  function setMarker(lat, lng) {
    if (marker) map.removeLayer(marker);
    marker = L.marker([lat, lng]).addTo(map);
    selected = { lat: +lat.toFixed(6), lng: +lng.toFixed(6) };
  }

  if (selected) setMarker(selected.lat, selected.lng);

  if (!opts.readOnly) {
    map.on("click", (e) => {
      setMarker(e.latlng.lat, e.latlng.lng);
      if (opts.onSelect) opts.onSelect(selected);
    });
  }

  // Centre on the resident's actual location when creating a new report, so
  // they don't have to pan/search to find their own street. This only
  // re-centres the view — it never places the report marker automatically,
  // since the drainage problem being reported may not be at the resident's
  // exact current position. Falls back silently to the fixed Abraka centre
  // if geolocation is unavailable, denied, or times out.
  if (opts.useGeolocation && !opts.initial && !opts.readOnly && "geolocation" in navigator) {
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const { latitude, longitude } = pos.coords;
        map.setView([latitude, longitude], 16);
        if (userLocationMarker) map.removeLayer(userLocationMarker);
        userLocationMarker = L.circleMarker([latitude, longitude], {
          radius: 8,
          color: "#ffffff",
          weight: 2,
          fillColor: "#2563eb",
          fillOpacity: 1,
        }).addTo(map);
        userLocationMarker.bindTooltip("Your current location", { direction: "top" });
      },
      () => {
        // Permission denied, unavailable, or timed out — keep the default
        // Abraka-centred view. No error shown; this is a convenience only.
      },
      { enableHighAccuracy: true, timeout: 8000, maximumAge: 60000 }
    );
  }

  // Fix for map rendering blank/grey when its container was hidden or
  // sized after Leaflet initialised (common with dynamic pages).
  setTimeout(() => map.invalidateSize(), 200);

  return {
    getSelected: () => selected,
    setPoints: (points) => {
      if (!points || points.length === 0) return;
      points.forEach((p) => {
        L.circleMarker([p.lat, p.lng], {
          radius: 8,
          fillColor: p.color || "#dc2626",
          color: "#ffffff",
          weight: 2,
          fillOpacity: 0.85,
        }).addTo(map);
      });
      const bounds = L.latLngBounds(points.map((p) => [p.lat, p.lng]));
      map.fitBounds(bounds, { padding: [30, 30], maxZoom: 16 });
    },
  };
}
