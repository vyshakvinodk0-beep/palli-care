import sqlite3
import os
from werkzeug.security import generate_password_hash

DB_PATH = os.path.join('database', 'data.db')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    if not os.path.exists('database'):
        os.makedirs('database')
        
    conn = get_db()

    conn.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        role TEXT,
        status TEXT DEFAULT 'Available'
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS booking(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_name TEXT,
        service TEXT,
        caregiver TEXT,
        status TEXT DEFAULT 'Pending'
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS item_bookings(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER,
        caregiver TEXT,
        booking_date TEXT,
        status TEXT DEFAULT 'Pending'
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS tutorials(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        link TEXT
    )
    """)

    # ✅ create default admin only if not exists
    admin = conn.execute("SELECT * FROM users WHERE role='admin'").fetchone()

    if not admin:
        hashed_pw = generate_password_hash("admin123")
        conn.execute(
            "INSERT INTO users(username,password,role) VALUES ('admin',?,'admin')",
            (hashed_pw,)
        )

    conn.commit()
    conn.close()
    print("Database initialized successfully!")

if __name__ == "__main__":
    init_db()