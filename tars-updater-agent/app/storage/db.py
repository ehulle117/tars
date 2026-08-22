import sqlite3
import os
import logging

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("DB_PATH", "state.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reported_cves (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cve_id TEXT NOT NULL,
            target TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(cve_id, target)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reported_updates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            version TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(name, type, version)
        )
    ''')
    # Full finding history, kept independent of the reported_* dedup tables above
    # so past scan results remain queryable even after they've been emailed once.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS vulnerability_findings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cve_id TEXT NOT NULL,
            target TEXT NOT NULL,
            pkg_name TEXT,
            installed_version TEXT,
            fixed_version TEXT,
            title TEXT,
            first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(cve_id, target)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS update_findings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            version TEXT NOT NULL,
            first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(name, type, version)
        )
    ''')
    conn.commit()
    conn.close()

def has_cve_been_reported(cve_id, target):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM reported_cves WHERE cve_id = ? AND target = ?', (cve_id, target))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def mark_cve_reported(cve_id, target):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO reported_cves (cve_id, target) VALUES (?, ?)', (cve_id, target))
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()

def has_update_been_reported(name, item_type, version):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM reported_updates WHERE name = ? AND type = ? AND version = ?', (name, item_type, version))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def mark_update_reported(name, item_type, version):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO reported_updates (name, type, version) VALUES (?, ?, ?)', (name, item_type, version))
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()

def record_vulnerability_finding(vuln):
    """Persist a full vulnerability record, independent of email dedup state."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO vulnerability_findings (cve_id, target, pkg_name, installed_version, fixed_version, title)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(cve_id, target) DO UPDATE SET
            pkg_name=excluded.pkg_name,
            installed_version=excluded.installed_version,
            fixed_version=excluded.fixed_version,
            title=excluded.title,
            last_seen=CURRENT_TIMESTAMP
    ''', (
        vuln.get("cve_id"), vuln.get("target"), vuln.get("pkg_name"),
        vuln.get("installed_version"), vuln.get("fixed_version"), vuln.get("title"),
    ))
    conn.commit()
    conn.close()

def record_update_finding(item):
    """Persist a full update record, independent of email dedup state."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO update_findings (name, type, version)
        VALUES (?, ?, ?)
        ON CONFLICT(name, type, version) DO UPDATE SET last_seen=CURRENT_TIMESTAMP
    ''', (item.get("name"), item.get("type"), item.get("version")))
    conn.commit()
    conn.close()

def get_vulnerability_findings(limit=100):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM vulnerability_findings ORDER BY last_seen DESC LIMIT ?', (limit,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def get_update_findings(limit=100):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM update_findings ORDER BY last_seen DESC LIMIT ?', (limit,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

# Initialize on import
init_db()
