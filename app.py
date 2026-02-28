from flask import Flask, render_template, request, redirect, session, flash
import sqlite3
import os
import pickle

app = Flask(__name__)
app.secret_key = "palliative"

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

    conn.execute("""
    CREATE TABLE IF NOT EXISTS medical_items(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_name TEXT,
        quantity INTEGER,
        status TEXT
    )
    """)

    admin = conn.execute("SELECT * FROM users WHERE role='admin'").fetchone()
    if not admin:
        conn.execute("INSERT INTO users(username,password,role) VALUES ('admin','admin','admin')")

    items = conn.execute("SELECT * FROM medical_items").fetchall()
    if not items:
        conn.execute("INSERT INTO medical_items VALUES (NULL,'Oxygen Cylinder',5,'Available')")
        conn.execute("INSERT INTO medical_items VALUES (NULL,'Wheelchair',2,'Limited')")
        conn.execute("INSERT INTO medical_items VALUES (NULL,'Hospital Bed',1,'Limited')")
        conn.execute("INSERT INTO medical_items VALUES (NULL,'Syringe Kit',0,'Out of Stock')")

    conn.commit()
    conn.close()


# ---------------- HOME ----------------
@app.route("/")
def home():
    return render_template("landing.html")


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
        user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        conn.close()

        if not user:
            flash("Invalid username ❌", "danger")
            return redirect("/login")

        if user["password"] != password:
            flash("Wrong password ❌", "danger")
            return redirect("/login")

        session.clear()
        session["user"] = user["username"]
        session["role"] = user["role"]

        flash("Login successful ✅", "success")
        return redirect(f"/{user['role']}_dashboard")

    return render_template("login.html")


# ---------------- FORGOT PASSWORD ----------------
@app.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():

    if request.method == "POST":

        username = request.form["username"]
        new_password = request.form["password"]

        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()

        if not user:
            flash("Username not found ❌", "danger")
            return redirect("/forgot_password")

        conn.execute("UPDATE users SET password=? WHERE username=?", (new_password, username))
        conn.commit()
        conn.close()

        flash("Password updated successfully ✅ Please login", "success")
        return redirect("/login")

    return render_template("forgot_password.html")


# ---------------- LOGOUT ----------------
@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully ✅", "success")
    return redirect("/login")


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
    conn.close()

    return render_template("caregiver_dashboard.html", total_bookings=total)


# ---------------- NURSE DASHBOARD ----------------
@app.route("/nurse_dashboard")
def nurse_dashboard():
    if session.get("role") != "nurse":
        return redirect("/login")

    return render_template("nurse_dashboard.html")


# ---------------- TUTORIALS (NEW) ----------------
@app.route("/tutorials")
def tutorials():

    if "user" not in session:
        return redirect("/login")

    videos = [
        {
            "title": "How to use Oxygen Cylinder",
            "link": "https://www.youtube.com/embed/AlWjFyvlDFw?si=0CahnA8HsxvOQrCk"
        },
        {
            "title": "Hospital Bed Adjustment",
            "link": "https://www.youtube.com/embed/uQH3SigM2bg?si=IGZrQRaMJ-6qh2ih"
        },
        {
            "title": "Bedsore Prevention",
            "link": "https://www.youtube.com/embed/_4bL-qIvSas?si=ZjuQuoToFLJsPgCI"
        },
        {
            "title": "changing of urine pad",
            "link": "https://www.youtube.com/embed/Z1i0dGq0M3g"
        }
    ]

    return render_template("tutorials.html", videos=videos)


# ---------------- BOOKING ----------------
@app.route("/booking", methods=["GET", "POST"])
def booking():
    if session.get("role") != "caregiver":
        return redirect("/login")

    if request.method == "POST":
        conn = get_db()
        conn.execute(
            "INSERT INTO booking(patient_name, service, caregiver) VALUES (?,?,?)",
            (request.form["patient"], request.form["service"], session["user"])
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


# ---------------- MEDICAL ITEMS ----------------
@app.route("/medical_items")
def medical_items():
    if "user" not in session:
        return redirect("/login")

    conn = get_db()
    items = conn.execute("SELECT * FROM medical_items").fetchall()
    conn.close()

    return render_template("medical_items.html", items=items)


# ---------------- UPDATE EQUIPMENT ----------------
@app.route("/update_item/<int:id>", methods=["GET", "POST"])
def update_item(id):

    if session.get("role") != "admin":
        return redirect("/login")

    conn = get_db()

    if request.method == "POST":

        quantity = int(request.form["quantity"])

        status = "Available"
        if quantity == 0:
            status = "Out of Stock"
        elif quantity <= 2:
            status = "Limited"

        conn.execute(
            "UPDATE medical_items SET quantity=?, status=? WHERE id=?",
            (quantity, status, id)
        )
        conn.commit()
        conn.close()

        flash("Item updated ✅", "success")
        return redirect("/medical_items")

    item = conn.execute("SELECT * FROM medical_items WHERE id=?", (id,)).fetchone()
    conn.close()

    return render_template("update_item.html", item=item)


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