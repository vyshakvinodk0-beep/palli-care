from werkzeug.security import generate_password_hash

def init_db():
    conn = get_db()

    conn.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        role TEXT
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS booking(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_name TEXT,
        service TEXT,
        caregiver TEXT
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