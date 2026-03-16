from flask import Flask, render_template, request, redirect, session, flash, send_from_directory
import sqlite3
import os
import pickle
from datetime import timedelta
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "palliative"

# ✅ SESSION TIMEOUT (5 minutes)
app.permanent_session_lifetime = timedelta(minutes=5)


# ✅ DISABLE BACK BUTTON CACHE (VERY IMPORTANT FOR LOGOUT SECURITY)
@app.after_request
def add_header(response):
    response.cache_control.no_store = True
    response.cache_control.no_cache = True
    response.cache_control.must_revalidate = True
    response.cache_control.max_age = 0
    return response


# ---------------- LOAD ML MODELS ----------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
symptom_model = pickle.load(open(os.path.join(BASE_DIR, "model.pkl"), "rb"))
chatbot_model = pickle.load(open(os.path.join(BASE_DIR, "chatbot_model.pkl"), "rb"))
vectorizer = pickle.load(open(os.path.join(BASE_DIR, "vectorizer.pkl"), "rb"))

DB_DIR = os.path.join(BASE_DIR, "database")
original_db = os.path.join(DB_DIR, "data.db")

# Vercel's environment is read-only, so we must use /tmp/ for an operational SQLite DB
if os.environ.get("VERCEL") or os.environ.get("VERCEL_URL"):
    DB = "/tmp/data.db"
    import shutil
    if not os.path.exists(DB) and os.path.exists(original_db):
        shutil.copy(original_db, DB)
else:
    DB = original_db
    if not os.path.exists(DB_DIR):
        os.makedirs(DB_DIR)


# ---------------- DB CONNECTION ----------------
from flask import g

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB, timeout=20)
        g.db.row_factory = sqlite3.Row
        # Enable WAL mode for better concurrency
        g.db.execute("PRAGMA journal_mode=WAL")
    return g.db

@app.teardown_appcontext
def close_db(error):
    if hasattr(g, 'db'):
        g.db.close()


# ---------------- DB INIT ----------------
def init_db():
    # Use a separate connection for initialization as it might run outside app context
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row # Ensure row_factory is set for init_db as well
    conn.execute("PRAGMA journal_mode=WAL")

    conn.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        role TEXT,
        status TEXT DEFAULT 'Available'
    )
    """)
    
    # Check if 'status' column exists (Migration for existing DBs)
    cursor = conn.execute("PRAGMA table_info(users)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'status' not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN status TEXT DEFAULT 'Available'")

    conn.execute("""
    CREATE TABLE IF NOT EXISTS booking(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_name TEXT,
        service TEXT,
        caregiver TEXT,
        status TEXT DEFAULT 'Pending'
    )
    """)

    # Migration for existing booking table
    cursor = conn.execute("PRAGMA table_info(booking)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'status' not in columns:
        conn.execute("ALTER TABLE booking ADD COLUMN status TEXT DEFAULT 'Approved'") # Existing ones approved

    conn.execute("""
    CREATE TABLE IF NOT EXISTS patient_logs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        caregiver TEXT,
        date TEXT,
        comfort_score INTEGER,
        mood TEXT,
        sleep TEXT,
        tasks_completed TEXT,
        heart_rate INTEGER,
        o2_saturation INTEGER,
        bp_systolic INTEGER
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS clinical_notes(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        booking_id INTEGER,
        nurse TEXT,
        note TEXT,
        date TEXT
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS medical_items(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_name TEXT,
        quantity INTEGER,
        status TEXT
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS emergencies(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        caregiver TEXT,
        time TEXT,
        status TEXT DEFAULT 'Active',
        admin_message TEXT
    )
    """)
    
    # Check if 'admin_message' column exists
    cursor = conn.execute("PRAGMA table_info(emergencies)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'admin_message' not in columns:
        conn.execute("ALTER TABLE emergencies ADD COLUMN admin_message TEXT")


    # ✅ Create default admin if not exists
    admin = conn.execute("SELECT * FROM users WHERE role='admin'").fetchone()
    if not admin:
        hashed_pw = generate_password_hash("admin123")
        conn.execute(
            "INSERT INTO users(username,password,role) VALUES ('admin',?,'admin')",
            (hashed_pw,)
        )

    conn.execute("""
    CREATE TABLE IF NOT EXISTS ambulances(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vehicle_no TEXT,
        driver TEXT,
        phone TEXT,
        status TEXT DEFAULT 'Available'
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS item_bookings(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER,
        caregiver TEXT,
        booking_date TEXT,
        status TEXT DEFAULT 'In Use', -- 'In Use', 'Finished'
        FOREIGN KEY(item_id) REFERENCES medical_items(id)
    )
    """)

    amb_count = conn.execute("SELECT COUNT(*) FROM ambulances").fetchone()[0]
    if amb_count == 0:
        initial_ambs = [
            ("KL07AB1234", "Ramesh", "9876543210", "Available"),
            ("KL07CD5678", "Suresh", "9876501234", "Busy"),
            ("KL07EF9012", "Mohan", "9876512345", "Available")
        ]
        for v, d, p, s in initial_ambs:
            conn.execute("INSERT INTO ambulances(vehicle_no, driver, phone, status) VALUES (?,?,?,?)", (v, d, p, s))

    conn.commit()
    conn.close()

init_db()

# ---------------- HOME ----------------
@app.route("/")
def home():
    return render_template("landing.html")

# ---------------- PWA ROUTES ----------------
@app.route('/sw.js')
def serve_sw():
    response = send_from_directory(app.static_folder, 'sw.js')
    response.headers['Content-Type'] = 'application/javascript'
    response.headers['Service-Worker-Allowed'] = '/'
    return response

@app.route('/manifest.json')
def serve_manifest():
    response = send_from_directory(app.static_folder, 'manifest.json')
    response.headers['Content-Type'] = 'application/manifest+json'
    return response


# ---------------- SIGNUP ----------------
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        try:
            conn = get_db()
            hashed_password = generate_password_hash(request.form["password"])
            conn.execute(
                "INSERT INTO users(username,password,role) VALUES (?,?,?)",
                (request.form["username"], hashed_password, request.form["role"])
            )
            conn.commit()

            flash("Account created successfully ✅ Please login", "success")
            return redirect("/login")

        except:
            flash("Username already exists ❌", "danger")

    return render_template("signup.html")


# ---------------- LOGIN ----------------
@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        username = request.form["username"]
        password = request.form["password"]

        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE username=?", (username,)
        ).fetchone()

        if not user or not check_password_hash(user["password"], password):
            flash("Invalid credentials ❌", "danger")
            return redirect("/login")

        session.clear()
        session.permanent = True

        session["user"] = user["username"]
        session["role"] = user["role"]

        flash("Login successful ✅", "success")
        return redirect(f"/{user['role']}_dashboard")

    return render_template("login.html")


# ---------------- LOGOUT ----------------
@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully ✅", "success")
    return redirect("/login")


# ---------------- FORGOT PASSWORD ----------------
@app.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():

    if request.method == "POST":

        username = request.form["username"]
        new_password = request.form["new_password"]

        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE username=?", (username,)
        ).fetchone()

        if not user:
            flash("Username not found ❌", "danger")
            return redirect("/forgot_password")

        hashed_password = generate_password_hash(new_password)
        conn.execute("UPDATE users SET password=? WHERE username=?", (hashed_password, username))
        conn.commit()

        flash("Password reset successfully ✅ Please login", "success")
        return redirect("/login")

    return render_template("forgot_password.html")


# ---------------- ADMIN DASHBOARD ----------------
@app.route("/admin_dashboard")
def admin_dashboard():
    if session.get("role") != "admin":
        return redirect("/login")

    conn = get_db()
    users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    bookings = conn.execute("SELECT COUNT(*) FROM booking").fetchone()[0]
    pending_services = conn.execute("SELECT COUNT(*) FROM booking WHERE status='Pending'").fetchone()[0]
    pending_items = conn.execute("SELECT COUNT(*) FROM item_bookings WHERE status='Pending'").fetchone()[0]
    
    return render_template("admin_dashboard.html", 
                           users=users, 
                           bookings=bookings,
                           pending_services=pending_services, 
                           pending_items=pending_items)

from flask import jsonify
from datetime import datetime

# ---------------- API CHECK SOS (Admin Only) ----------------
@app.route("/api/check_sos")
def check_sos():
    if session.get("role") != "admin":
        return jsonify({"status": "error"})
        
    conn = get_db()
    active_sos = conn.execute("SELECT * FROM emergencies WHERE status='Active' ORDER BY id DESC").fetchall()
    
    if active_sos:
        return jsonify({"status": "active", "emergencies": [dict(e) for e in active_sos]})
    return jsonify({"status": "clear"})

# ---------------- RESOLVE SOS (Admin Only) ----------------
@app.route("/resolve_sos/<int:id>", methods=["POST"])
def resolve_sos(id):
    if session.get("role") != "admin":
        return redirect("/login")
        
    admin_message = request.form.get("admin_message", "")
    
    conn = get_db()
    conn.execute("UPDATE emergencies SET status='Resolved', admin_message=? WHERE id=?", (admin_message, id))
    conn.commit()
    
    flash("Emergency marked as resolved and message sent to Caregiver ✅", "success")
    return redirect("/admin_dashboard")

# ---------------- TRIGGER EMERGENCY SOS ----------------
@app.route("/trigger_sos", methods=["POST"])
def trigger_sos():
    if session.get("role") != "caregiver":
        return redirect("/login")
        
    conn = get_db()
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("INSERT INTO emergencies (caregiver, time, status) VALUES (?, ?, 'Active')", (session["user"], current_time))
    conn.commit()
    
    flash("EMERGENCY SOS TRIGGERED! Admin has been notified. 🚨", "danger")
    return redirect("/caregiver_dashboard")

# ---------------- CAREGIVER CHECK SOS STATUS ----------------
@app.route("/api/check_sos_status")
def check_sos_status():
    if session.get("role") != "caregiver":
        return jsonify({"status": "error"})
        
    conn = get_db()
    last_resolved = conn.execute(
        "SELECT * FROM emergencies WHERE caregiver=? AND status='Resolved' AND admin_message IS NOT NULL AND admin_message != '' ORDER BY id DESC LIMIT 1",
        (session["user"],)
    ).fetchone()
    
    if last_resolved:
        return jsonify({"has_message": True, "message": last_resolved["admin_message"]})
    
    return jsonify({"has_message": False})

# ---------------- CAREGIVER DISMISS SOS MESSAGE ----------------
@app.route("/api/dismiss_sos_message", methods=["POST"])
def dismiss_sos_message():
    if session.get("role") != "caregiver":
        return jsonify({"status": "error"})
        
    conn = get_db()
    conn.execute(
        "UPDATE emergencies SET admin_message = NULL WHERE caregiver=? AND status='Resolved'",
        (session["user"],)
    )
    conn.commit()
    return jsonify({"status": "success"})

# ---------------- MANAGE USERS (Admin Only) ----------------
@app.route("/manage_users")
def manage_users():
    if session.get("role") != "admin":
        return redirect("/login")

    conn = get_db()
    users = conn.execute("SELECT id, username, role FROM users WHERE role != 'admin'").fetchall()

    return render_template("admin_manage_users.html", users=users)

# 🗑️ ---------------- DELETE USER (Admin Only) ----------------
@app.route("/delete_user/<int:id>")
def delete_user(id):
    if session.get("role") != "admin":
        return redirect("/login")

    conn = get_db()
    conn.execute("DELETE FROM users WHERE id=?", (id,))
    conn.commit()

    flash("User deleted successfully 🗑️", "success")
    return redirect("/manage_users")

# ---------------- EDIT USER (Admin Only) ----------------
@app.route("/edit_user/<int:id>", methods=["GET", "POST"])
def edit_user(id):
    if session.get("role") != "admin":
        return redirect("/login")

    conn = get_db()
    if request.method == "POST":
        username = request.form["username"]
        role = request.form["role"]
        conn.execute("UPDATE users SET username=?, role=? WHERE id=?", (username, role, id))
        conn.commit()
        
        flash("User updated successfully ✅", "success")
        return redirect("/manage_users")
        
    user = conn.execute("SELECT * FROM users WHERE id=?", (id,)).fetchone()
    
    return render_template("edit_user.html", user=user)


# ---------------- CAREGIVER DASHBOARD ----------------
@app.route("/caregiver_dashboard")
def caregiver_dashboard():
    if session.get("role") != "caregiver":
        return redirect("/login")

    conn = get_db()
    total = conn.execute(
        "SELECT COUNT(*) FROM booking WHERE caregiver=?",
        (session["user"],)
    ).fetchone()[0]

    latest_log = conn.execute(
        "SELECT * FROM patient_logs WHERE caregiver=? ORDER BY id DESC LIMIT 1",
        (session["user"],)
    ).fetchone()
    
    recent_logs = conn.execute(
        "SELECT * FROM patient_logs WHERE caregiver=? ORDER BY id DESC LIMIT 7",
        (session["user"],)
    ).fetchall()

    recent_logs = list(reversed(recent_logs))
    
    active_items = conn.execute("""
        SELECT ib.id, mi.item_name, ib.booking_date, ib.status 
        FROM item_bookings ib 
        JOIN medical_items mi ON ib.item_id = mi.id
        WHERE ib.caregiver = ? AND ib.status IN ('In Use', 'Pending')
    """, (session["user"],)).fetchall()
    
    mood_icons = {"Happy": "😊", "Neutral": "😐", "Sad": "😔", "Anxious": "😟", "In Pain": "😫"}
    sleep_icons = {"Sound": "💤", "Restless": "🛏️", "Interrupted": "🕰️", "Minimal": "😵"}
    
    mood_val = latest_log['mood'] if latest_log else 'Neutral'
    sleep_val = latest_log['sleep'] if latest_log else 'Sound'
    
    stats = {
        'comfort_score': latest_log['comfort_score'] if latest_log else 55,
        'mood': mood_val,
        'mood_icon': mood_icons.get(mood_val, "🌞"),
        'sleep': sleep_val,
        'sleep_icon': sleep_icons.get(sleep_val, "💤"),
        'tasks': latest_log['tasks_completed'] if latest_log else '4/5'
    }

    import json
    chart_labels = json.dumps([f"Day {i+1}" for i in range(len(recent_logs))] if recent_logs else ['Day 1', 'Day 2', 'Day 3', 'Day 4', 'Day 5', 'Day 6', 'Day 7'])
    chart_hr = json.dumps([l['heart_rate'] for l in recent_logs] if recent_logs else [72, 75, 78, 74, 80, 77, 75])
    chart_o2 = json.dumps([l['o2_saturation'] for l in recent_logs] if recent_logs else [98, 97, 98, 96, 95, 96, 98])
    chart_bp = json.dumps([l['bp_systolic'] for l in recent_logs] if recent_logs else [120, 118, 122, 125, 120, 115, 118])

    return render_template("caregiver_dashboard.html", 
        total_bookings=total, 
        stats=stats,
        chart_labels=chart_labels,
        chart_hr=chart_hr,
        chart_o2=chart_o2,
        chart_bp=chart_bp,
        active_items=active_items
    )

from datetime import date

@app.route("/update_stats", methods=["POST"])
def update_stats():
    if session.get("role") != "caregiver":
        return redirect("/login")
        
    comfort = request.form.get("comfort_score", 55)
    mood = request.form.get("mood", "Neutral")
    sleep = request.form.get("sleep", "Sound")
    tasks = request.form.get("tasks", "0/5")
    hr = request.form.get("heart_rate", 75)
    o2 = request.form.get("o2", 98)
    bp = request.form.get("bp", 120)
    
    today = str(date.today())
    
    conn = get_db()
    conn.execute("""
        INSERT INTO patient_logs (caregiver, date, comfort_score, mood, sleep, tasks_completed, heart_rate, o2_saturation, bp_systolic)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (session["user"], today, comfort, mood, sleep, tasks, hr, o2, bp))
    conn.commit()
    
    flash("Daily stats successfully logged! 📝", "success")
    return redirect("/caregiver_dashboard")


# ---------------- NURSE DASHBOARD ----------------
@app.route("/nurse_dashboard")
def nurse_dashboard():
    if session.get("role") != "nurse":
        return redirect("/login")

    conn = get_db()
    assigned_bookings = conn.execute("SELECT * FROM booking WHERE status='Approved'").fetchall()
    status = conn.execute("SELECT status FROM users WHERE username=?", (session["user"],)).fetchone()[0]

    return render_template("nurse_dashboard.html", bookings=assigned_bookings, status=status)

# ---------------- NURSE PATIENT VIEW (Clinical History) ----------------
@app.route("/nurse_patient_view/<int:id>")
def nurse_patient_view(id):
    if session.get("role") != "nurse":
        return redirect("/login")

    conn = get_db()
    booking = conn.execute("SELECT * FROM booking WHERE id=?", (id,)).fetchone()
    logs = conn.execute("SELECT * FROM patient_logs WHERE caregiver=? ORDER BY id DESC", (booking['caregiver'],)).fetchall()
    notes = conn.execute("SELECT * FROM clinical_notes WHERE booking_id=? ORDER BY id DESC", (id,)).fetchall()

    # Prepare data for Chart.js
    import json
    chart_labels = json.dumps([log['date'] for log in reversed(logs)])
    chart_hr = json.dumps([log['heart_rate'] for log in reversed(logs)])
    chart_o2 = json.dumps([log['o2_saturation'] for log in reversed(logs)])
    chart_bp = json.dumps([log['bp_systolic'] for log in reversed(logs)])

    return render_template("nurse_patient_view.html", 
                           booking=booking, 
                           logs=logs, 
                           notes=notes,
                           chart_labels=chart_labels,
                           chart_hr=chart_hr,
                           chart_o2=chart_o2,
                           chart_bp=chart_bp)

# ---------------- ADD CLINICAL NOTE (Nurse Only) ----------------
@app.route("/add_clinical_note", methods=["POST"])
def add_clinical_note():
    if session.get("role") != "nurse":
        return redirect("/login")

    booking_id = request.form["booking_id"]
    note_text = request.form["note"]
    today = str(date.today())

    conn = get_db()
    conn.execute("INSERT INTO clinical_notes(booking_id, nurse, note, date) VALUES (?, ?, ?, ?)",
                 (booking_id, session["user"], note_text, today))
    conn.commit()

    flash("Clinical note added 🏥", "success")
    return redirect(f"/nurse_patient_view/{booking_id}")

# ---------------- TOGGLE NURSE STATUS ----------------
@app.route("/toggle_status")
def toggle_status():
    if session.get("role") != "nurse":
        return redirect("/login")

    conn = get_db()
    user = conn.execute("SELECT status FROM users WHERE username=?", (session["user"],)).fetchone()
    if not user:
        return redirect("/login")
        
    current = user[0]
    new_status = "Busy" if current == "Available" else "Available"
    
    conn.execute("UPDATE users SET status=? WHERE username=?", (new_status, session["user"]))
    conn.commit()
    # Flash and redirect

    flash(f"Status updated to: {new_status} ✅", "info")
    return redirect("/nurse_dashboard")


# ---------------- NURSE AVAILABILITY ----------------
@app.route("/nurse_availability")
def nurse_availability():

    if "user" not in session:
        return redirect("/login")

    conn = get_db()
    nurses = conn.execute(
        "SELECT username, status FROM users WHERE role='nurse'"
    ).fetchall()

    return render_template("nurse_availability.html", nurses=nurses)


# ---------------- BOOKING ----------------
@app.route("/booking", methods=["GET", "POST"])
def booking():

    if session.get("role") != "caregiver":
        return redirect("/login")

    if request.method == "POST":

        patient = request.form["patient"]
        service = request.form["service"]

        conn = get_db()
        conn.execute(
            "INSERT INTO booking(patient_name, service, caregiver, status) VALUES (?, ?, ?, 'Pending')",
            (patient, service, session["user"])
        )
        conn.commit()

        flash("Booking request sent! Waiting for Admin approval ⏳", "success")
        return redirect("/caregiver_dashboard")

    return render_template("booking.html")


# ---------------- VIEW BOOKINGS ----------------
@app.route("/view_bookings")
def view_bookings():

    if session.get("role") != "caregiver":
        return redirect("/login")

    conn = get_db()
    data = conn.execute(
        "SELECT * FROM booking WHERE caregiver=?",
        (session["user"],)
    ).fetchall()

    return render_template("view_bookings.html", bookings=data)

# ---------------- VIEW ALL BOOKINGS (Admin/Nurse) ----------------
@app.route("/view_all_bookings")
def view_all_bookings():
    if session.get("role") not in ["admin", "nurse"]:
        return redirect("/login")
        
    conn = get_db()
    data = conn.execute("SELECT * FROM booking").fetchall()
    
    return render_template("admin_view_bookings.html", bookings=data)


# 🗑️ ---------------- DELETE BOOKING ----------------
@app.route("/delete_booking/<int:id>")
def delete_booking(id):

    if session.get("role") != "caregiver":
        return redirect("/login")

    conn = get_db()
    conn.execute("""
        DELETE FROM booking
        WHERE id=? AND caregiver=?
    """, (id, session["user"]))

    conn.commit()

    flash("Booking deleted 🗑️", "success")
    return redirect("/view_bookings")


# ---------------- ITEM BOOKING (Caregiver Only) ----------------
@app.route("/book_item/<int:id>", methods=["POST"])
def book_item(id):
    if session.get("role") != "caregiver":
        return redirect("/login")

    conn = get_db()
    item = conn.execute("SELECT * FROM medical_items WHERE id=?", (id,)).fetchone()
    
    if not item or item["quantity"] <= 0:
        flash("Sorry, this item is currently unavailable ❌", "danger")
        return redirect("/medical_items")

    # Decrease quantity
    conn.execute("UPDATE medical_items SET quantity = quantity - 1 WHERE id=?", (id,))
    
    # Update status if quantity becomes 0
    if item["quantity"] - 1 == 0:
        conn.execute("UPDATE medical_items SET status = 'Out of Stock' WHERE id=?", (id,))

    # Create booking record with Pending status
    booking_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    conn.execute(
        "INSERT INTO item_bookings(item_id, caregiver, booking_date, status) VALUES (?, ?, ?, 'Pending')",
        (id, session["user"], booking_date)
    )
    conn.commit()

    flash(f"Request for {item['item_name']} sent! Waiting for admin approval ⏳", "success")
    return redirect("/medical_items")

# ---------------- FINISH ITEM USAGE (Caregiver Only) ----------------
@app.route("/finish_item/<int:id>", methods=["POST"])
def finish_item(id):
    if session.get("role") != "caregiver":
        return redirect("/login")

    conn = get_db()
    booking = conn.execute("SELECT * FROM item_bookings WHERE id=? AND caregiver=?", (id, session["user"])).fetchone()
    
    if not booking:
        return redirect("/caregiver_dashboard")

    # Update booking status
    conn.execute("UPDATE item_bookings SET status = 'Finished' WHERE id=?", (id,))
    
    # Increase inventory quantity
    conn.execute("UPDATE medical_items SET quantity = quantity + 1 WHERE id=?", (booking["item_id"],))
    
    # Update inventory status if it was Out of Stock
    item = conn.execute("SELECT * FROM medical_items WHERE id=?", (booking["item_id"],)).fetchone()
    if item["status"] == "Out of Stock":
        conn.execute("UPDATE medical_items SET status = 'Available' WHERE id=?", (booking["item_id"],))

    conn.commit()

    flash("Item usage marked as finished. Return to pool confirmed ✅", "success")
    return redirect("/caregiver_dashboard")

# ---------------- ADMIN APPROVALS ----------------
@app.route("/admin_approvals")
def admin_approvals():
    if session.get("role") != "admin":
        return redirect("/login")

    conn = get_db()
    services = conn.execute("SELECT * FROM booking WHERE status='Pending'").fetchall()
    items = conn.execute("""
        SELECT ib.*, mi.item_name 
        FROM item_bookings ib 
        JOIN medical_items mi ON ib.item_id = mi.id 
        WHERE ib.status='Pending'
    """).fetchall()

    return render_template("admin_approvals.html", services=services, items=items)

@app.route("/approve_service/<int:id>")
def approve_service(id):
    if session.get("role") != "admin":
        return redirect("/login")
    
    conn = get_db()
    conn.execute("UPDATE booking SET status='Approved' WHERE id=?", (id,))
    conn.commit()
    flash("Service booking approved ✅", "success")
    return redirect("/admin_approvals")

@app.route("/reject_service/<int:id>")
def reject_service(id):
    if session.get("role") != "admin":
        return redirect("/login")
    
    conn = get_db()
    conn.execute("UPDATE booking SET status='Rejected' WHERE id=?", (id,))
    conn.commit()
    flash("Service booking rejected ❌", "danger")
    return redirect("/admin_approvals")

@app.route("/approve_item/<int:id>")
def approve_item(id):
    if session.get("role") != "admin":
        return redirect("/login")
    
    conn = get_db()
    conn.execute("UPDATE item_bookings SET status='In Use' WHERE id=?", (id,))
    conn.commit()
    flash("Equipment booking approved ✅", "success")
    return redirect("/admin_approvals")

@app.route("/reject_item/<int:id>")
def reject_item(id):
    if session.get("role") != "admin":
        return redirect("/login")
    
    conn = get_db()
    booking = conn.execute("SELECT * FROM item_bookings WHERE id=?", (id,)).fetchone()
    if booking:
        # Return quantity to inventory
        conn.execute("UPDATE medical_items SET quantity = quantity + 1 WHERE id=?", (booking["item_id"],))
        
        # Update inventory status if it was Out of Stock
        item = conn.execute("SELECT * FROM medical_items WHERE id=?", (booking["item_id"],)).fetchone()
        if item and item["status"] == "Out of Stock":
            conn.execute("UPDATE medical_items SET status = 'Available' WHERE id=?", (booking["item_id"],))
            
        conn.execute("UPDATE item_bookings SET status='Rejected' WHERE id=?", (id,))
        conn.commit()
    
    flash("Equipment booking rejected and item returned to pool ❌", "danger")
    return redirect("/admin_approvals")

# ---------------- MEDICAL ITEMS ----------------
@app.route("/medical_items")
def medical_items():

    if "user" not in session:
        return redirect("/login")

    conn = get_db()
    items = conn.execute("SELECT * FROM medical_items").fetchall()

    return render_template("medical_items.html", items=items)

# ---------------- UPDATE MEDICAL ITEM ----------------
@app.route("/update_item/<int:id>", methods=["GET", "POST"])
def update_item(id):
    if session.get("role") != "admin":
        return redirect("/medical_items")

    conn = get_db()
    if request.method == "POST":
        quantity = request.form["quantity"]
        status = request.form["status"]
        
        conn.execute("UPDATE medical_items SET quantity=?, status=? WHERE id=?", (quantity, status, id))
        conn.commit()
        
        flash("Medical item updated successfully ✅", "success")
        return redirect("/medical_items")
        
    item = conn.execute("SELECT * FROM medical_items WHERE id=?", (id,)).fetchone()
    
    return render_template("update_item.html", item=item)

# ---------------- ADD MEDICAL ITEM (Admin Only) ----------------
@app.route("/add_item", methods=["POST"])
def add_item():
    if session.get("role") != "admin":
        return redirect("/medical_items")

    name = request.form["item_name"]
    qty = request.form["quantity"]
    status = request.form["status"]

    conn = get_db()
    conn.execute("INSERT INTO medical_items(item_name, quantity, status) VALUES (?,?,?)", (name, qty, status))
    conn.commit()

    flash("New equipment added 📦", "success")
    return redirect("/medical_items")

# ---------------- ADMIN DELETE BOOKING ----------------
@app.route("/admin_delete_booking/<int:id>")
def admin_delete_booking(id):
    if session.get("role") != "admin":
        return redirect("/login")

    conn = get_db()
    conn.execute("DELETE FROM booking WHERE id=?", (id,))
    conn.commit()

    flash("Booking removed by admin 🗑️", "success")
    return redirect("/view_all_bookings")


# ---------------- AMBULANCE ----------------
@app.route("/ambulance")
def ambulance():

    if "user" not in session:
        return redirect("/login")

    conn = get_db()
    ambulances = conn.execute("SELECT * FROM ambulances").fetchall()

    return render_template("ambulance.html", ambulances=ambulances)

# ---------------- MANAGE AMBULANCES (Admin Only) ----------------
@app.route("/manage_ambulances")
def manage_ambulances():
    if session.get("role") != "admin":
        return redirect("/login")

    conn = get_db()
    ambulances = conn.execute("SELECT * FROM ambulances").fetchall()

    return render_template("admin_manage_ambulances.html", ambulances=ambulances)

# ---------------- UPDATE AMBULANCE (Admin Only) ----------------
@app.route("/update_ambulance/<int:id>", methods=["POST"])
def update_ambulance(id):
    if session.get("role") != "admin":
        return redirect("/login")

    status = request.form.get("status")
    driver = request.form.get("driver")
    phone = request.form.get("phone")

    conn = get_db()
    conn.execute("UPDATE ambulances SET status=?, driver=?, phone=? WHERE id=?", (status, driver, phone, id))
    conn.commit()

    flash("Ambulance stats updated successfully ✅", "success")
    return redirect("/manage_ambulances")

# ---------------- ADD AMBULANCE (Admin Only) ----------------
@app.route("/add_ambulance", methods=["POST"])
def add_ambulance():
    if session.get("role") != "admin":
        return redirect("/login")

    vehicle_no = request.form.get("vehicle_no")
    driver = request.form.get("driver")
    phone = request.form.get("phone")
    status = request.form.get("status", "Available")

    conn = get_db()
    conn.execute("INSERT INTO ambulances(vehicle_no, driver, phone, status) VALUES (?,?,?,?)", (vehicle_no, driver, phone, status))
    conn.commit()
    conn.close()

    flash("New ambulance added successfully ✅", "success")
    return redirect("/manage_ambulances")


# ---------------- TUTORIALS ----------------
@app.route("/tutorials")
def tutorials():

    if "user" not in session:
        return redirect("/login")

    videos = [
        {"title": "How to use Oxygen Cylinder", "link": "https://www.youtube.com/embed/AlWjFyvlDFw"},
        {"title": "Hospital Bed Adjustment", "link": "https://www.youtube.com/embed/uQH3SigM2bg"},
        {"title": "Bedsore Prevention", "link": "https://www.youtube.com/embed/_4bL-qIvSas"},
        {"title": "Changing of urine pad", "link": "https://www.youtube.com/embed/Z1i0dGq0M3g"}
    ]

    return render_template("tutorials.html", videos=videos)


# ---------------- AI SYMPTOMS ----------------
@app.route("/symptoms", methods=["GET", "POST"])
def symptoms():

    if "user" not in session:
        return redirect("/login")

    if request.method == "POST":

        values = [
            int(request.form["pain"]),
            int(request.form["fatigue"]),
            int(request.form["nausea"]),
            int(request.form["depression"]),
            int(request.form["appetite"])
        ]

        result = symptom_model.predict([values])[0]

        return render_template("result.html", result=result)

    return render_template("symptoms.html")


# ---------------- AI CHATBOT ----------------
@app.route("/chatbot", methods=["GET", "POST"])
def chatbot():

    if "user" not in session:
        return redirect("/login")

    reply = ""
    user_msg = ""

    if request.method == "POST":

        user_msg = request.form["msg"]
        msg = user_msg.lower()

        X = vectorizer.transform([msg])
        intent = chatbot_model.predict(X)[0]

        if intent == "booking":
            return redirect("/booking")

        elif intent == "ambulance":
            return redirect("/ambulance")

        elif intent == "prediction":
            return redirect("/symptoms")

        elif intent == "view_bookings":
            return redirect("/view_bookings")

        elif "equipment" in msg:
            return redirect("/medical_items")

        elif "tutorial" in msg or "video" in msg:
            return redirect("/tutorials")

        elif intent == "dashboard":
            return redirect(f"/{session['role']}_dashboard")

        elif "hello" in msg or "hi" in msg:
            reply = f"Hello {session['user']} 💙 How can I assist you today?"

        # --- Rule-based Medical Queries ---
        elif "fever" in msg or "temperature" in msg:
            reply = "🌡️ For a fever, ensure the patient is well-hydrated. Apply a cool, damp cloth to their forehead. If the temperature exceeds 101°F (38.3°C) or persists, please contact a doctor or trigger an SOS."
            
        elif "pain" in msg or "ache" in msg:
            reply = "💊 For pain management, ensure the patient is in a comfortable position. Administer prescribed pain relief medication as directed. If the pain is severe, sudden, or unmanageable, contact emergencies immediately."
            
        elif "breath" in msg or "breathing" in msg or "wheez" in msg:
            reply = "🫁 If experiencing breathing difficulty, elevate the patient's head and loosen any tight clothing. If they are on oxygen therapy, check the flow rate. If it worsens, trigger an SOS or call an ambulance immediately!"
            
        elif "nausea" in msg or "vomit" in msg:
            reply = "🤢 For nausea, offer small, frequent sips of clear fluids like water or ginger tea. Avoid heavy, greasy, or strong-smelling foods. Administer prescribed anti-nausea medication if available."
            
        elif "fatigue" in msg or "tired" in msg or "weak" in msg:
            reply = "🛌 Fatigue is common in palliative care. Ensure the patient gets plenty of undisturbed rest. Keep essential items within their easy reach to minimize physical exertion."
            
        elif "bedsore" in msg or "ulcer" in msg or "skin break" in msg:
            reply = "🧴 To prevent or manage bedsores, gently reposition the patient every 2 hours. Keep their skin clean and dry, and use pressure-relieving cushions. Inform a nurse if you notice red spots or broken skin."
            
        elif "emergency" in msg or "unconscious" in msg or "collapse" in msg:
            reply = "🚨 THIS IS AN EMERGENCY! If the patient is unresponsive, immediately call an ambulance from the Ambulance tab and trigger the SOS from your dashboard. Begin CPR if you are trained and it is aligned with the patient's care plan."
            
        elif "eat" in msg or "appetite" in msg or "food" in msg:
            reply = "🍲 A loss of appetite is normal. Offer small, high-calorie, nutritious meals whenever they feel hungry. Do not force them to eat. Nutrition shakes can also be a helpful alternative."

        else:
            reply = """I can help you with:

• Book a service  
• View ambulance  
• Check symptom severity  
• View medical equipment  
• Watch caregiving tutorials  
• My bookings 💙
• Basic medical advice (e.g., pain, fever, nausea, bedsores)
"""

    return render_template("chatbot.html", reply=reply, user_msg=user_msg)


# ---------------- MAIN ----------------
if __name__ == "__main__":
    app.run(debug=True)