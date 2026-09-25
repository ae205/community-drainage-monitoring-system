"""
database.py — Schema for the Community Drainage Monitoring and Reporting System.
Mirrors the data dictionary in Chapter Three (Tables 3.3-3.8) exactly:
Users, Locations, Reports, Images, Status_History, Notifications.
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "database.db")

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS Users (
    user_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name       VARCHAR(100) NOT NULL,
    email           VARCHAR(150) NOT NULL UNIQUE,
    phone           VARCHAR(20),
    password_hash   VARCHAR(255) NOT NULL,
    role            VARCHAR(10) NOT NULL DEFAULT 'resident' CHECK (role IN ('resident','admin')),
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS Locations (
    location_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    latitude        DECIMAL(9,6) NOT NULL,
    longitude       DECIMAL(9,6) NOT NULL,
    landmark        VARCHAR(255),
    community_ward  VARCHAR(100)
);

CREATE TABLE IF NOT EXISTS Reports (
    report_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             INTEGER NOT NULL REFERENCES Users(user_id),
    location_id         INTEGER NOT NULL REFERENCES Locations(location_id),
    assigned_officer_id INTEGER REFERENCES Users(user_id),
    category            VARCHAR(20) NOT NULL CHECK (category IN ('blocked','collapsed','overflow','illegal_dumping','other')),
    description         TEXT NOT NULL,
    severity            VARCHAR(10) NOT NULL CHECK (severity IN ('low','medium','high')),
    status              VARCHAR(20) NOT NULL DEFAULT 'submitted'
                         CHECK (status IN ('submitted','acknowledged','in_progress','resolved','rejected')),
    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at         TIMESTAMP,
    client_uuid         VARCHAR(64)
);

CREATE TABLE IF NOT EXISTS Images (
    image_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id     INTEGER NOT NULL REFERENCES Reports(report_id),
    file_path     VARCHAR(255) NOT NULL,
    uploaded_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS Status_History (
    history_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id     INTEGER NOT NULL REFERENCES Reports(report_id),
    old_status    VARCHAR(20),
    new_status    VARCHAR(20) NOT NULL,
    changed_by    INTEGER NOT NULL REFERENCES Users(user_id),
    note          TEXT,
    changed_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS Notifications (
    notification_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           INTEGER NOT NULL REFERENCES Users(user_id),
    report_id         INTEGER NOT NULL REFERENCES Reports(report_id),
    message           VARCHAR(255) NOT NULL,
    is_read           BOOLEAN NOT NULL DEFAULT 0,
    created_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(reset=False):
    if reset and os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = get_db()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    print(f"Database initialised at {DB_PATH}")


if __name__ == "__main__":
    init_db(reset=True)
