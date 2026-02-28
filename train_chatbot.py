import pickle
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

# ---------------- TRAINING DATA ----------------

training_data = [

    # 🔹 GREETING
    ("hi", "greeting"),
    ("hello", "greeting"),
    ("hey", "greeting"),
    ("good morning", "greeting"),
    ("good evening", "greeting"),

    # 🔹 BOOKING
    ("book service", "booking"),
    ("i want to book", "booking"),
    ("need to book a service", "booking"),
    ("book caregiver visit", "booking"),

    # 🔹 AMBULANCE
    ("need ambulance", "ambulance"),
    ("call ambulance", "ambulance"),
    ("emergency ambulance", "ambulance"),
    ("ambulance service", "ambulance"),

    # 🔹 AI PREDICTION
    ("check symptoms", "prediction"),
    ("symptom prediction", "prediction"),
    ("predict patient condition", "prediction"),
    ("ai prediction", "prediction"),

    # 🔹 VIEW BOOKINGS
    ("show my bookings", "view_bookings"),
    ("my bookings", "view_bookings"),
    ("view my bookings", "view_bookings"),
    ("booking history", "view_bookings"),

    # 🔹 DASHBOARD
    ("go to dashboard", "dashboard"),
    ("open dashboard", "dashboard"),
    ("my dashboard", "dashboard"),

    # 🔹 PAIN HELP
    ("patient has pain", "pain_help"),
    ("pain management", "pain_help"),
    ("severe pain what to do", "pain_help"),

    # 🔹 FEVER HELP
    ("patient has fever", "fever_help"),
    ("fever what to do", "fever_help"),
    ("high temperature", "fever_help"),
    ("how to treat fever", "fever_help"),

    # 🔹 DIET HELP
    ("what food to give", "diet_help"),
    ("patient diet", "diet_help"),
    ("nutrition for patient", "diet_help"),
    ("what to feed patient", "diet_help"),

    # 🔹 FATIGUE HELP
    ("patient is tired", "fatigue_help"),
    ("fatigue management", "fatigue_help"),
    ("very weak patient", "fatigue_help"),

]

# ---------------- SPLIT DATA ----------------

texts = [x[0] for x in training_data]
labels = [x[1] for x in training_data]

# ---------------- VECTORIZER ----------------

vectorizer = TfidfVectorizer()
X = vectorizer.fit_transform(texts)

# ---------------- MODEL ----------------

model = LogisticRegression()
model.fit(X, labels)

# ---------------- SAVE FILES ----------------

pickle.dump(model, open("chatbot_model.pkl", "wb"))
pickle.dump(vectorizer, open("vectorizer.pkl", "wb"))

print("✅ Chatbot model trained successfully!")