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

# Initialize on import
init_db()
