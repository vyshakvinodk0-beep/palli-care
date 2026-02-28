import pandas as pd
from sklearn.tree import DecisionTreeClassifier
import pickle

# ---------------- SAMPLE DATASET ----------------
data = {
    "pain":        [1,2,3,4,5,2,3,4,5,1],
    "fatigue":     [1,2,3,4,5,2,3,4,5,1],
    "nausea":      [1,1,2,3,4,2,3,4,5,1],
    "depression":  [1,2,2,3,4,2,3,4,5,1],
    "appetite":    [1,2,3,3,4,2,3,4,5,1],
    "severity": [
        "Mild","Mild","Moderate","Moderate","Severe",
        "Mild","Moderate","Moderate","Severe","Mild"
    ]
}

# ---------------- CREATE DATAFRAME ----------------
df = pd.DataFrame(data)

X = df.drop("severity", axis=1)
y = df["severity"]

# ---------------- TRAIN MODEL ----------------
model = DecisionTreeClassifier()
model.fit(X, y)

# ---------------- SAVE MODEL ----------------
pickle.dump(model, open("model.pkl", "wb"))

print("Model trained & saved successfully ✅")