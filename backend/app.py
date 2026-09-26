"""
app.py — Community Drainage Monitoring and Reporting System
Backend: Flask + SQLite. JWT auth via PyJWT, password hashing via Werkzeug.
Includes idempotent report submission (client_uuid) to support the offline
PWA sync queue: if a queued submission is retried after a flaky connection,
the server recognises the duplicate and returns the original report instead
of creating a second one.
"""
import os
import functools
import datetime
import jwt
from flask import Flask, request, jsonify, g, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from werkzeug.exceptions import HTTPException

from database import get_db, init_db, DB_PATH

BASE_DIR = os.path.dirname(__file__)
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
FRONTEND_DIR = os.path.join(os.path.dirname(BASE_DIR), "frontend")
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-for-drainage-reporting-system-2026")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}

os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10MB upload cap


# ---------------------------------------------------------------- error handlers
# Ensures every error returns JSON (not Flask's default HTML error page),
# which the frontend's fetch/JSON parsing depends on.
@app.errorhandler(413)
def file_too_large(e):
    return jsonify({"error": "That file is too large. Maximum upload size is 10MB per photo."}), 413


@app.errorhandler(HTTPException)
def handle_http_exception(e):
    return jsonify({"error": e.description or e.name}), e.code


@app.errorhandler(Exception)
def handle_unexpected_error(e):
    if isinstance(e, HTTPException):
        return handle_http_exception(e)
    app.logger.exception("Unhandled error")
    return jsonify({"error": f"Server error: {str(e)}"}), 500


if not os.path.exists(DB_PATH):
    init_db(reset=True)


def ensure_admin():
    conn = get_db()

    admin = conn.execute(
        "SELECT user_id FROM Users WHERE email = ?",
        ("admin@drainage.local",)
    ).fetchone()

    if not admin:
        password_hash = generate_password_hash("admin123")

        conn.execute(
            """
            INSERT INTO Users
            (full_name, email, phone, password_hash, role)
            VALUES (?, ?, ?, ?, 'admin')
            """,
            (
                "Admin Officer",
                "admin@drainage.local",
                "08000000000",
                password_hash,
            ),
        )

        conn.commit()

    conn.close()


ensure_admin()

# ---------------------------------------------------------------- helpers
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def make_token(user_id, role):
    payload = {
        "user_id": user_id,
        "role": role,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=24),
        "iat": datetime.datetime.utcnow(),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


def decode_token(token):
    return jwt.decode(token, SECRET_KEY, algorithms=["HS256"])


def login_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing or invalid Authorization header"}), 401
        token = auth_header.split(" ", 1)[1]
        try:
            payload = decode_token(token)
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token"}), 401
        g.user_id = payload["user_id"]
        g.role = payload["role"]
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if g.get("role") != "admin":
            return jsonify({"error": "Admin role required"}), 403
        return f(*args, **kwargs)
    return wrapper


def row_to_dict(row):
    return dict(row) if row else None


def notify(conn, user_id, report_id, message):
    conn.execute(
        "INSERT INTO Notifications (user_id, report_id, message) VALUES (?, ?, ?)",
        (user_id, report_id, message),
    )


# ---------------------------------------------------------------- FR1/FR2: auth
@app.route("/api/auth/register", methods=["POST"])
def register():
    data = request.get_json(force=True)
    full_name = (data.get("full_name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    phone = (data.get("phone") or "").strip()
    password = data.get("password") or ""

    if not full_name or not email or not password:
        return jsonify({"error": "full_name, email, and password are required"}), 400
    if len(password) < 6:
        return jsonify({"error": "password must be at least 6 characters"}), 400

    conn = get_db()
    existing = conn.execute("SELECT user_id FROM Users WHERE email = ?", (email,)).fetchone()
    if existing:
        conn.close()
        return jsonify({"error": "An account with this email already exists"}), 409

    password_hash = generate_password_hash(password)
    cur = conn.execute(
        "INSERT INTO Users (full_name, email, phone, password_hash, role) VALUES (?, ?, ?, ?, 'resident')",
        (full_name, email, phone, password_hash),
    )
    conn.commit()
    user_id = cur.lastrowid
    conn.close()

    token = make_token(user_id, "resident")
    return jsonify({"token": token, "user": {"user_id": user_id, "full_name": full_name, "role": "resident"}}), 201


@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    conn = get_db()
    user = conn.execute("SELECT * FROM Users WHERE email = ?", (email,)).fetchone()
    conn.close()

    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Invalid email or password"}), 401

    token = make_token(user["user_id"], user["role"])
    return jsonify({
        "token": token,
        "user": {"user_id": user["user_id"], "full_name": user["full_name"], "role": user["role"]},
    })


# ---------------------------------------------------------------- FR3/FR4/FR5: submit report
@app.route("/api/reports", methods=["POST"])
@login_required
def create_report():
    """Multipart form: category, description, severity, latitude, longitude,
    landmark, community_ward, client_uuid (optional, for offline-sync dedupe),
    photos (one or more files)."""
    form = request.form
    category = form.get("category")
    description = form.get("description")
    severity = form.get("severity")
    latitude = form.get("latitude")
    longitude = form.get("longitude")
    landmark = form.get("landmark", "")
    ward = form.get("community_ward", "")
    client_uuid = form.get("client_uuid", "")

    # Idempotency check: if this exact client-generated submission was already
    # received (e.g. a retried sync from the offline queue), return the
    # existing report instead of creating a duplicate.
    if client_uuid:
        conn = get_db()
        existing = conn.execute(
            "SELECT report_id, status FROM Reports WHERE client_uuid = ? AND user_id = ?",
            (client_uuid, g.user_id),
        ).fetchone()
        if existing:
            conn.close()
            return jsonify({"report_id": existing["report_id"], "status": existing["status"], "deduped": True}), 200
        conn.close()

    if category not in ("blocked", "collapsed", "overflow", "illegal_dumping", "other"):
        return jsonify({"error": "invalid category"}), 400
    if severity not in ("low", "medium", "high"):
        return jsonify({"error": "invalid severity"}), 400
    if not description:
        return jsonify({"error": "description is required"}), 400
    try:
        lat, lng = float(latitude), float(longitude)
    except (TypeError, ValueError):
        return jsonify({"error": "a valid latitude/longitude location pin is required"}), 400

    files = request.files.getlist("photos")
    saved_files = []
    for f in files:
        if f and f.filename and allowed_file(f.filename):
            fname = f"{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_{secure_filename(f.filename)}"
            f.save(os.path.join(UPLOAD_DIR, fname))
            saved_files.append(fname)
    if not saved_files:
        return jsonify({"error": "at least one photo is required"}), 400

    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO Locations (latitude, longitude, landmark, community_ward) VALUES (?, ?, ?, ?)",
            (lat, lng, landmark, ward),
        )
        location_id = cur.lastrowid

        cur = conn.execute(
            "INSERT INTO Reports (user_id, location_id, category, description, severity, status, client_uuid) "
            "VALUES (?, ?, ?, ?, ?, 'submitted', ?)",
            (g.user_id, location_id, category, description, severity, client_uuid or None),
        )
        report_id = cur.lastrowid

        for fname in saved_files:
            conn.execute(
                "INSERT INTO Images (report_id, file_path) VALUES (?, ?)", (report_id, fname)
            )

        conn.execute(
            "INSERT INTO Status_History (report_id, old_status, new_status, changed_by, note) "
            "VALUES (?, NULL, 'submitted', ?, 'Report submitted by resident')",
            (report_id, g.user_id),
        )

        admins = conn.execute("SELECT user_id FROM Users WHERE role = 'admin'").fetchall()
        for a in admins:
            notify(conn, a["user_id"], report_id, f"New drainage report #{report_id} submitted")

        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({"error": f"submission failed: {e}"}), 500

    conn.close()
    return jsonify({"report_id": report_id, "status": "submitted", "deduped": False}), 201


# ---------------------------------------------------------------- FR6: resident's own reports
@app.route("/api/reports/mine", methods=["GET"])
@login_required
def my_reports():
    conn = get_db()
    rows = conn.execute(
        """SELECT r.report_id, r.category, r.description, r.severity, r.status,
                  r.created_at, r.resolved_at, l.latitude, l.longitude, l.landmark
           FROM Reports r JOIN Locations l ON r.location_id = l.location_id
           WHERE r.user_id = ? ORDER BY r.created_at DESC""",
        (g.user_id,),
    ).fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in rows])


# ---------------------------------------------------------------- report detail
@app.route("/api/reports/<int:report_id>", methods=["GET"])
@login_required
def report_detail(report_id):
    conn = get_db()
    report = conn.execute(
        """SELECT r.*, l.latitude, l.longitude, l.landmark, l.community_ward, u.full_name AS reporter_name
           FROM Reports r
           JOIN Locations l ON r.location_id = l.location_id
           JOIN Users u ON r.user_id = u.user_id
           WHERE r.report_id = ?""",
        (report_id,),
    ).fetchone()
    if not report:
        conn.close()
        return jsonify({"error": "report not found"}), 404
    if g.role != "admin" and report["user_id"] != g.user_id:
        conn.close()
        return jsonify({"error": "forbidden"}), 403

    images = conn.execute("SELECT image_id, file_path FROM Images WHERE report_id = ?", (report_id,)).fetchall()
    history = conn.execute(
        """SELECT h.old_status, h.new_status, h.note, h.changed_at, u.full_name AS changed_by_name
           FROM Status_History h JOIN Users u ON h.changed_by = u.user_id
           WHERE h.report_id = ? ORDER BY h.changed_at ASC""",
        (report_id,),
    ).fetchall()
    conn.close()

    result = row_to_dict(report)
    result["images"] = [row_to_dict(i) for i in images]
    result["history"] = [row_to_dict(h) for h in history]
    return jsonify(result)


# ---------------------------------------------------------------- FR9: admin - all reports
@app.route("/api/reports", methods=["GET"])
@login_required
@admin_required
def all_reports():
    status = request.args.get("status")
    category = request.args.get("category")
    query = """SELECT r.report_id, r.category, r.description, r.severity, r.status,
                      r.created_at, r.resolved_at, l.latitude, l.longitude, l.landmark,
                      u.full_name AS reporter_name
               FROM Reports r
               JOIN Locations l ON r.location_id = l.location_id
               JOIN Users u ON r.user_id = u.user_id
               WHERE 1=1"""
    params = []
    if status:
        query += " AND r.status = ?"
        params.append(status)
    if category:
        query += " AND r.category = ?"
        params.append(category)
    query += " ORDER BY r.created_at DESC"

    conn = get_db()
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in rows])


# ---------------------------------------------------------------- FR10: admin - update status
VALID_TRANSITIONS = {
    "submitted": {"acknowledged", "rejected"},
    "acknowledged": {"in_progress", "rejected"},
    "in_progress": {"resolved", "rejected"},
    "resolved": set(),
    "rejected": set(),
}


@app.route("/api/reports/<int:report_id>/status", methods=["PATCH"])
@login_required
@admin_required
def update_status(report_id):
    data = request.get_json(force=True)
    new_status = data.get("status")
    note = data.get("note", "")

    conn = get_db()
    report = conn.execute("SELECT * FROM Reports WHERE report_id = ?", (report_id,)).fetchone()
    if not report:
        conn.close()
        return jsonify({"error": "report not found"}), 404

    old_status = report["status"]
    if new_status not in VALID_TRANSITIONS.get(old_status, set()):
        conn.close()
        return jsonify({"error": f"cannot transition from {old_status} to {new_status}"}), 400

    try:
        if new_status == "resolved":
            conn.execute(
                "UPDATE Reports SET status = ?, assigned_officer_id = ?, resolved_at = CURRENT_TIMESTAMP WHERE report_id = ?",
                (new_status, g.user_id, report_id),
            )
        else:
            conn.execute(
                "UPDATE Reports SET status = ?, assigned_officer_id = ? WHERE report_id = ?",
                (new_status, g.user_id, report_id),
            )
        conn.execute(
            "INSERT INTO Status_History (report_id, old_status, new_status, changed_by, note) VALUES (?, ?, ?, ?, ?)",
            (report_id, old_status, new_status, g.user_id, note),
        )
        status_messages = {
            "acknowledged": f"Your report #{report_id} has been acknowledged",
            "in_progress": f"Work has started on your report #{report_id}",
            "resolved": f"Your report #{report_id} has been resolved",
            "rejected": f"Your report #{report_id} was rejected: {note}",
        }
        notify(conn, report["user_id"], report_id, status_messages.get(new_status, f"Report #{report_id} updated"))
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({"error": str(e)}), 500

    conn.close()
    return jsonify({"report_id": report_id, "status": new_status})


# ---------------------------------------------------------------- FR8: notifications
@app.route("/api/notifications", methods=["GET"])
@login_required
def get_notifications():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM Notifications WHERE user_id = ? ORDER BY created_at DESC", (g.user_id,)
    ).fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in rows])


@app.route("/api/notifications/<int:notification_id>/read", methods=["PATCH"])
@login_required
def mark_notification_read(notification_id):
    conn = get_db()
    conn.execute(
        "UPDATE Notifications SET is_read = 1 WHERE notification_id = ? AND user_id = ?",
        (notification_id, g.user_id),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ---------------------------------------------------------------- FR11: statistics
@app.route("/api/statistics", methods=["GET"])
@login_required
@admin_required
def statistics():
    conn = get_db()
    by_category = conn.execute("SELECT category, COUNT(*) as count FROM Reports GROUP BY category").fetchall()
    by_status = conn.execute("SELECT status, COUNT(*) as count FROM Reports GROUP BY status").fetchall()
    by_ward = conn.execute(
        """SELECT l.community_ward, COUNT(*) as count FROM Reports r
           JOIN Locations l ON r.location_id = l.location_id
           WHERE l.community_ward IS NOT NULL AND l.community_ward != ''
           GROUP BY l.community_ward"""
    ).fetchall()
    total = conn.execute("SELECT COUNT(*) as count FROM Reports").fetchone()["count"]
    avg_resolution = conn.execute(
        """SELECT AVG(julianday(resolved_at) - julianday(created_at)) as avg_days
           FROM Reports WHERE resolved_at IS NOT NULL"""
    ).fetchone()["avg_days"]
    conn.close()
    return jsonify({
        "total_reports": total,
        "by_category": [row_to_dict(r) for r in by_category],
        "by_status": [row_to_dict(r) for r in by_status],
        "by_ward": [row_to_dict(r) for r in by_ward],
        "avg_resolution_days": round(avg_resolution, 2) if avg_resolution else None,
    })


# ---------------------------------------------------------------- static file serving
@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)


@app.route("/")
@app.route("/<path:page>")
def serve_frontend(page="index.html"):
    if not page.endswith((".html", ".js", ".css", ".json")):
        page = "index.html"
    full_path = os.path.join(FRONTEND_DIR, page)
    if os.path.exists(full_path):
        return send_from_directory(FRONTEND_DIR, page)
    return send_from_directory(FRONTEND_DIR, "index.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(host="0.0.0.0", port=port, debug=False)
