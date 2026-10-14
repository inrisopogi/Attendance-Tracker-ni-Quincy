"""Attendance Tracker: Flask + Firebase Firestore (Python port of the C++ program).

Firestore layout (one private space per login):
  users/{username}/students/{id}      -> {name}
  users/{username}/attendance/{date}  -> {studentId: "P" | "A" | "L" | "E"}
"""
import hmac
import json
import os
import re

import firebase_admin
from firebase_admin import credentials, firestore
from flask import Flask, Response, g, jsonify, request, send_file

from export_xlsx import build_workbook
from import_xlsx import parse_spreadsheet

app = Flask(__name__, static_folder="static", static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024


def init_db():
    raw = os.environ.get("FIREBASE_CREDENTIALS")  # service-account JSON text
    if raw:
        cred = credentials.Certificate(json.loads(raw))
    elif os.path.exists("serviceAccountKey.json"):  # local development
        cred = credentials.Certificate("serviceAccountKey.json")
    else:  # e.g. Google Cloud Run's built-in service account
        cred = credentials.ApplicationDefault()
    firebase_admin.initialize_app(cred)
    return firestore.client()


db = init_db()
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
NAME_RE = re.compile(r"^[a-z0-9_.-]{1,40}$")


def load_users():
    """USERS="juan:pass1,maria:pass2" -> {"juan": "pass1", "maria": "pass2"}"""
    users = {}
    for pair in os.environ.get("USERS", "").split(","):
        if ":" in pair:
            name, pw = pair.split(":", 1)
            name, pw = name.strip().lower(), pw.strip()
            if NAME_RE.match(name) and pw:
                users[name] = pw
    return users


USERS = load_users()
SHARED_PASSWORD = os.environ.get("APP_PASSWORD")  # optional: one shared login


@app.before_request
def require_login():
    if not USERS and not SHARED_PASSWORD:
        g.user = "local"  # no login configured (local testing only)
        return None
    auth = request.authorization
    if auth and auth.username:
        name, pw = auth.username.strip().lower(), auth.password or ""
        if USERS:
            expected = USERS.get(name)
            if expected and hmac.compare_digest(expected.encode(), pw.encode()):
                g.user = name
                return None
        elif hmac.compare_digest(SHARED_PASSWORD.encode(), pw.encode()):
            g.user = "shared"
            return None
    return Response("Login required", 401,
                    {"WWW-Authenticate": 'Basic realm="Attendance Tracker"'})


def user_doc():
    """Each user's data lives under users/{username}/..., private to that login."""
    return db.collection("users").document(g.user)


@app.get("/")
def index():
    return app.send_static_file("index.html")


def sort_key(s):
    return (0, int(s["id"]), "") if s["id"].isdigit() else (1, 0, s["id"])


def load_all():
    students = [{"id": d.id, "name": d.to_dict().get("name", "")}
                for d in user_doc().collection("students").stream()]
    students.sort(key=sort_key)
    records = {d.id: d.to_dict() for d in user_doc().collection("attendance").stream()}
    return students, records


@app.get("/api/data")
def get_data():
    students, records = load_all()
    return jsonify(students=students, records=records, user=g.user)


@app.get("/api/export.xlsx")
def export_xlsx():
    students, records = load_all()
    return send_file(build_workbook(students, records), as_attachment=True,
                     download_name="attendance.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def replace_collection(ref, new_docs):
    """Make the collection exactly equal to new_docs ({doc_id: data})."""
    old_ids = {d.id for d in ref.list_documents()}
    ops = [("set", k, v) for k, v in new_docs.items()]
    ops += [("delete", k, None) for k in old_ids - new_docs.keys()]
    for i in range(0, len(ops), 400):  # Firestore batches hold max 500 writes
        batch = db.batch()
        for op, k, v in ops[i:i + 400]:
            batch.set(ref.document(k), v) if op == "set" else batch.delete(ref.document(k))
        batch.commit()


@app.post("/api/parse-import")
def parse_import():
    f = request.files.get("file")
    if not f:
        return jsonify(error="No file received."), 400
    try:
        return jsonify(parse_spreadsheet(f.read(), f.filename or ""))
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except Exception:
        return jsonify(error="Could not read that file. Please use .xlsx or .csv."), 400


@app.put("/api/data")
def put_data():
    body = request.get_json(silent=True) or {}
    students, records = body.get("students"), body.get("records")
    if not isinstance(students, list) or not isinstance(records, dict):
        return jsonify(error="bad payload"), 400

    student_docs = {}
    for s in students:
        sid, name = str(s.get("id", "")).strip(), str(s.get("name", "")).strip()
        if not sid or not name or "/" in sid or sid in (".", ".."):
            return jsonify(error=f"invalid student: {sid!r}"), 400
        student_docs[sid] = {"name": name}

    record_docs = {}
    for day, marks in records.items():
        if not DATE_RE.match(day) or not isinstance(marks, dict):
            return jsonify(error=f"invalid date: {day!r}"), 400
        clean = {k: v for k, v in marks.items() if k in student_docs and v in "PALE" and len(v) == 1}
        if clean:
            record_docs[day] = clean

    replace_collection(user_doc().collection("students"), student_docs)
    replace_collection(user_doc().collection("attendance"), record_docs)
    return jsonify(ok=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=True)
