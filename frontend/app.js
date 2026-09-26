// app.js — shared utilities for the Community Drainage Monitoring and Reporting System frontend
// Now includes: service worker registration, offline/online detection, and
// automatic syncing of reports queued in IndexedDB while offline.

const API_BASE = "";

function getAuth() {
  const raw = localStorage.getItem("cdmrs_auth");
  return raw ? JSON.parse(raw) : null;
}

function setAuth(token, user) {
  localStorage.setItem("cdmrs_auth", JSON.stringify({ token, user }));
}

function clearAuth() {
  localStorage.removeItem("cdmrs_auth");
}

function requireAuth(requiredRole) {
  const auth = getAuth();
  if (!auth) {
    window.location.href = "login.html";
    return null;
  }
  if (requiredRole && auth.user.role !== requiredRole) {
    window.location.href = auth.user.role === "admin" ? "admin_dashboard.html" : "resident_dashboard.html";
    return null;
  }
  return auth;
}

async function api(path, options = {}) {
  const auth = getAuth();
  const headers = options.headers || {};
  if (auth && !options.noAuth) {
    headers["Authorization"] = "Bearer " + auth.token;
  }
  if (options.json) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.json);
  }
  const res = await fetch(API_BASE + path, { ...options, headers });
  let data = null;
  try { data = await res.json(); } catch (e) { /* no body */ }
  if (!res.ok) {
    const err = new Error((data && data.error) || "Request failed");
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

function logout() {
  clearAuth();
  window.location.href = "index.html";
}

function showError(elId, message) {
  const el = document.getElementById(elId);
  el.textContent = message;
  el.style.display = "block";
}

function hideError(elId) {
  document.getElementById(elId).style.display = "none";
}

function statusLabel(status) {
  const map = { submitted: "Submitted", acknowledged: "Acknowledged", in_progress: "In Progress", resolved: "Resolved", rejected: "Rejected" };
  return map[status] || status;
}

function categoryLabel(cat) {
  const map = { blocked: "Blocked Drain", collapsed: "Collapsed / Damaged", overflow: "Overflow", illegal_dumping: "Illegal Dumping", other: "Other" };
  return map[cat] || cat;
}

function timeAgo(dateStr) {
  // Server timestamps are SQLite format ("2026-08-03 06:51:00", no timezone,
  // implicitly UTC). Locally-queued pending-report timestamps are already
  // full ISO 8601 (from `new Date().toISOString()`). Handle both correctly
  // instead of assuming one format.
  const isISO = /T.*Z$/.test(dateStr);
  const d = isISO ? new Date(dateStr) : new Date(dateStr.replace(" ", "T") + "Z");
  const diffMs = Date.now() - d.getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return mins + "m ago";
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return hrs + "h ago";
  const days = Math.floor(hrs / 24);
  return days + "d ago";
}

// ============================================================ PWA / OFFLINE

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch((e) => console.warn("SW registration failed:", e));
  });
}

let syncInFlight = false;

async function trySyncPending() {
  if (syncInFlight || !navigator.onLine) return;
  const auth = getAuth();
  if (!auth) return;

  syncInFlight = true;
  try {
    const pending = await getAllPending();
    for (const item of pending) {
      try {
        const fd = new FormData();
        fd.append("category", item.category);
        fd.append("severity", item.severity);
        fd.append("description", item.description);
        fd.append("landmark", item.landmark || "");
        fd.append("community_ward", item.community_ward || "");
        fd.append("latitude", item.latitude);
        fd.append("longitude", item.longitude);
        fd.append("client_uuid", item.client_uuid);
        for (const photo of item.photos) fd.append("photos", photo);

        const res = await fetch("/api/reports", {
          method: "POST",
          headers: { Authorization: "Bearer " + auth.token },
          body: fd,
        });
        if (res.ok) {
          await deletePending(item.client_uuid);
        }
      } catch (e) {
        // Still offline or request failed — leave it queued, try again later.
        break;
      }
    }
  } finally {
    syncInFlight = false;
    updateOfflineIndicator();
    window.dispatchEvent(new CustomEvent("offline-sync-complete"));
  }
}

window.addEventListener("online", trySyncPending);
window.addEventListener("offline", () => updateOfflineIndicator());

async function updateOfflineIndicator() {
  const el = document.getElementById("offlineIndicator");
  if (!el) return;
  const pendingCount = await countPending().catch(() => 0);

  if (!navigator.onLine) {
    el.style.display = "inline-flex";
    el.style.background = "#fef3c7";
    el.style.color = "#92400e";
    el.textContent = pendingCount > 0
      ? `📴 Offline — ${pendingCount} report${pendingCount > 1 ? "s" : ""} waiting to sync`
      : "📴 Offline";
  } else if (pendingCount > 0) {
    el.style.display = "inline-flex";
    el.style.background = "#dbeafe";
    el.style.color = "#1e40af";
    el.textContent = `🔄 Syncing ${pendingCount} report${pendingCount > 1 ? "s" : ""}...`;
  } else {
    el.style.display = "none";
  }
}

function renderNav(active) {
  const auth = getAuth();
  const el = document.getElementById("navbar");
  if (!el) return;

  const offlinePill = `<span id="offlineIndicator" style="display:none; align-items:center; padding:3px 10px; border-radius:999px; font-size:12px; font-weight:600; margin-right:10px;"></span>`;

  if (!auth) {
    el.innerHTML = `
      <a class="brand" href="index.html">🚰 Drainage Watch</a>
      <div class="links">
        ${offlinePill}
        <a href="login.html" class="${active === 'login' ? 'active' : ''}">Log In</a>
        <a href="register.html" class="${active === 'register' ? 'active' : ''}">Register</a>
      </div>`;
    updateOfflineIndicator();
    return;
  }

  const isAdmin = auth.user.role === "admin";
  const links = isAdmin ? [
    ["admin_dashboard.html", "dashboard", "Dashboard"],
    ["manage_reports.html", "manage", "Manage Reports"],
    ["statistics.html", "stats", "Statistics"],
  ] : [
    ["resident_dashboard.html", "dashboard", "Dashboard"],
    ["report_form.html", "report", "Report an Issue"],
    ["my_reports.html", "myreports", "My Reports"],
    ["notifications.html", "notifications", "Notifications"],
    ["profile.html", "profile", "Profile"],
  ];

  el.innerHTML = `
    <a class="brand" href="${isAdmin ? 'admin_dashboard.html' : 'resident_dashboard.html'}">🚰 Drainage Watch</a>
    <div class="links">
      ${offlinePill}
      ${links.map(([href, key, label]) => `<a href="${href}" class="${active === key ? 'active' : ''}">${label}</a>`).join("")}
      <a href="#" onclick="logout(); return false;">Log Out (${auth.user.full_name.split(' ')[0]})</a>
    </div>`;

  updateOfflineIndicator();
  trySyncPending();
}
