from flask import Flask, render_template, request, redirect, session, flash, send_from_directory
from datetime import timedelta
import sqlite3
import os
import pickle

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
symptom_model = pickle.load(open("model.pkl", "rb"))
chatbot_model = pickle.load(open("chatbot_model.pkl", "rb"))
vectorizer = pickle.load(open("vectorizer.pkl", "rb"))

DB = "database/data.db"


# ---------------- DB CONNECTION ----------------
def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------- DB INIT ----------------
def init_db():
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
        caregiver TEXT
    )
    """)

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
        status TEXT DEFAULT 'Active'
    )
    """)

    admin = conn.execute("SELECT * FROM users WHERE role='admin'").fetchone()
    if not admin:
        conn.execute(
            "INSERT INTO users(username,password,role) VALUES ('admin','admin','admin')"
        )

    items_count = conn.execute("SELECT COUNT(*) FROM medical_items").fetchone()[0]
    if items_count == 0:
        initial_items = [
            ("Oxygen Cylinder", 5, "Available"),
            ("Wheelchair", 2, "Limited"),
            ("Hospital Bed", 1, "Limited"),
            ("Syringe Kit", 0, "Out of Stock")
        ]
        for name, qty, sts in initial_items:
            conn.execute("INSERT INTO medical_items(item_name, quantity, status) VALUES (?,?,?)", (name, qty, sts))

    conn.commit()
    conn.close()


# ---------------- HOME ----------------
@app.route("/")
def home():
    return render_template("landing.html")

# ---------------- PWA ROUTES ----------------
@app.route('/sw.js')
def serve_sw():
    return send_from_directory('static', 'sw.js')

@app.route('/manifest.json')
def serve_manifest():
    return send_from_directory('static', 'manifest.json')


# ---------------- SIGNUP ----------------
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        try:
            conn = get_db()
            conn.execute(
                "INSERT INTO users(username,password,role) VALUES (?,?,?)",
                (request.form["username"], request.form["password"], request.form["role"])
            )
            conn.commit()
            conn.close()

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
        conn.close()

        if not user:
            flash("Invalid username ❌", "danger")
            return redirect("/login")

        if user["password"] != password:
            flash("Wrong password ❌", "danger")
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
            conn.close()
            flash("Username not found ❌", "danger")
            return redirect("/forgot_password")

        conn.execute("UPDATE users SET password=? WHERE username=?", (new_password, username))
        conn.commit()
        conn.close()

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
    conn.close()

    return render_template("admin_dashboard.html", users=users, bookings=bookings)

import json
from flask import jsonify

# ---------------- API CHECK SOS (Admin Only) ----------------
@app.route("/api/check_sos")
def check_sos():
    if session.get("role") != "admin":
        return jsonify({"status": "error"})
        
    conn = get_db()
    active_sos = conn.execute("SELECT * FROM emergencies WHERE status='Active' ORDER BY id DESC").fetchall()
    conn.close()
    
    if active_sos:
        return jsonify({"status": "active", "emergencies": [dict(e) for e in active_sos]})
    return jsonify({"status": "clear"})

# ---------------- RESOLVE SOS (Admin Only) ----------------
@app.route("/resolve_sos/<int:id>", methods=["POST"])
def resolve_sos(id):
    if session.get("role") != "admin":
        return redirect("/login")
        
    conn = get_db()
    conn.execute("UPDATE emergencies SET status='Resolved' WHERE id=?", (id,))
    conn.commit()
    conn.close()
    
    flash("Emergency marked as resolved ✅", "success")
    return redirect("/admin_dashboard")

# ---------------- MANAGE USERS (Admin Only) ----------------
@app.route("/manage_users")
def manage_users():
    if session.get("role") != "admin":
        return redirect("/login")

    conn = get_db()
    users = conn.execute("SELECT id, username, role FROM users WHERE role != 'admin'").fetchall()
    conn.close()

    return render_template("admin_manage_users.html", users=users)

# 🗑️ ---------------- DELETE USER (Admin Only) ----------------
@app.route("/delete_user/<int:id>")
def delete_user(id):
    if session.get("role") != "admin":
        return redirect("/login")

    conn = get_db()
    conn.execute("DELETE FROM users WHERE id=?", (id,))
    conn.commit()
    conn.close()

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
        conn.close()
        
        flash("User updated successfully ✅", "success")
        return redirect("/manage_users")
        
    user = conn.execute("SELECT * FROM users WHERE id=?", (id,)).fetchone()
    conn.close()
    
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
    conn.close()

    recent_logs = list(reversed(recent_logs))
    
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
        chart_bp=chart_bp
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
    conn.close()
    
    flash("Daily stats successfully logged! 📝", "success")
    return redirect("/caregiver_dashboard")

from datetime import datetime

# ---------------- TRIGGER EMERGENCY SOS ----------------
@app.route("/trigger_sos", methods=["POST"])
def trigger_sos():
    if session.get("role") != "caregiver":
        return redirect("/login")
        
    conn = get_db()
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("INSERT INTO emergencies (caregiver, time, status) VALUES (?, ?, 'Active')", (session["user"], current_time))
    conn.commit()
    conn.close()
    
    flash("EMERGENCY SOS TRIGGERED! Admin has been notified. 🚨", "danger")
    return redirect("/caregiver_dashboard")


# ---------------- NURSE DASHBOARD ----------------
@app.route("/nurse_dashboard")
def nurse_dashboard():
    if session.get("role") != "nurse":
        return redirect("/login")

    conn = get_db()
    # List all patients who have bookings
    assigned_bookings = conn.execute("SELECT * FROM booking").fetchall()
    
    # Get nurse status
    status = conn.execute("SELECT status FROM users WHERE username=?", (session["user"],)).fetchone()[0]
    conn.close()

    return render_template("nurse_dashboard.html", bookings=assigned_bookings, status=status)

# ---------------- NURSE PATIENT VIEW (Clinical History) ----------------
@app.route("/nurse_patient_view/<int:id>")
def nurse_patient_view(id):
    if session.get("role") != "nurse":
        return redirect("/login")

    conn = get_db()
    booking = conn.execute("SELECT * FROM booking WHERE id=?", (id,)).fetchone()
    
    # Get logs from the caregiver of this patient
    logs = conn.execute("SELECT * FROM patient_logs WHERE caregiver=? ORDER BY id DESC", (booking['caregiver'],)).fetchall()
    
    # Get clinical notes already written
    notes = conn.execute("SELECT * FROM clinical_notes WHERE booking_id=? ORDER BY id DESC", (id,)).fetchall()
    conn.close()

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
    conn.close()

    flash("Clinical note added 🏥", "success")
    return redirect(f"/nurse_patient_view/{booking_id}")

# ---------------- TOGGLE NURSE STATUS ----------------
@app.route("/toggle_status")
def toggle_status():
    if session.get("role") != "nurse":
        return redirect("/login")

    conn = get_db()
    current = conn.execute("SELECT status FROM users WHERE username=?", (session["user"],)).fetchone()[0]
    new_status = "Busy" if current == "Available" else "Available"
    
    conn.execute("UPDATE users SET status=? WHERE username=?", (new_status, session["user"]))
    conn.commit()
    conn.close()

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
    conn.close()

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
            "INSERT INTO booking(patient_name, service, caregiver) VALUES (?, ?, ?)",
            (patient, service, session["user"])
        )
        conn.commit()
        conn.close()

        flash("Booking successful ✅", "success")
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
    conn.close()

    return render_template("view_bookings.html", bookings=data)

# ---------------- VIEW ALL BOOKINGS (Admin/Nurse) ----------------
@app.route("/view_all_bookings")
def view_all_bookings():
    if session.get("role") not in ["admin", "nurse"]:
        return redirect("/login")
        
    conn = get_db()
    data = conn.execute("SELECT * FROM booking").fetchall()
    conn.close()
    
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
    conn.close()

    flash("Booking deleted 🗑️", "success")
    return redirect("/view_bookings")


# ---------------- MEDICAL ITEMS ----------------
@app.route("/medical_items")
def medical_items():

    if "user" not in session:
        return redirect("/login")

    conn = get_db()
    items = conn.execute("SELECT * FROM medical_items").fetchall()
    conn.close()

    return render_template("medical_items.html", items=items)

# ---------------- UPDATE MEDICAL ITEM ----------------
@app.route("/update_item/<int:id>", methods=["GET", "POST"])
def update_item(id):
    if session.get("role") != "admin":
        return redirect("/medical_items")

    if request.method == "POST":
        quantity = request.form["quantity"]
        status = request.form["status"]
        
        conn = get_db()
        conn.execute("UPDATE medical_items SET quantity=?, status=? WHERE id=?", (quantity, status, id))
        conn.commit()
        conn.close()
        
        flash("Medical item updated successfully ✅", "success")
        return redirect("/medical_items")
        
    conn = get_db()
    item = conn.execute("SELECT * FROM medical_items WHERE id=?", (id,)).fetchone()
    conn.close()
    
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
    conn.close()

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
    conn.close()

    flash("Booking removed by admin 🗑️", "success")
    return redirect("/view_all_bookings")


# ---------------- AMBULANCE ----------------
@app.route("/ambulance")
def ambulance():

    if "user" not in session:
        return redirect("/login")

    ambulances = [
        {"vehicle_no": "KL07AB1234", "driver": "Ramesh", "phone": "9876543210", "status": "Available"},
        {"vehicle_no": "KL07CD5678", "driver": "Suresh", "phone": "9876501234", "status": "Busy"}
    ]

    return render_template("ambulance.html", ambulances=ambulances)


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

        else:
            reply = """I can help you with:

• Book a service  
• View ambulance  
• Check symptom severity  
• View medical equipment  
• Watch caregiving tutorials  
• My bookings 💙
"""

    return render_template("chatbot.html", reply=reply, user_msg=user_msg)


# ---------------- MAIN ----------------
if __name__ == "__main__":

    if not os.path.exists("database"):
        os.makedirs("database")

    init_db()
    app.run(debug=True)