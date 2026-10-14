"""Attendance Tracker: Flask + Firebase Firestore (Python port of the C++ program).

Firestore layout:
  students/{id}        -> {name}
  attendance/{date}    -> {studentId: "P" | "A" | "L" | "E"}
"""
import json
import os
import re

import firebase_admin
from firebase_admin import credentials, firestore
from flask import Flask, Response, jsonify, request, send_file

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
PASSWORD = os.environ.get("APP_PASSWORD")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@app.before_request
def require_password():
    if not PASSWORD:
        return None
    auth = request.authorization
    if auth and auth.password == PASSWORD:
        return None
    return Response("Login required", 401,
                    {"WWW-Authenticate": 'Basic realm="Attendance Tracker"'})


@app.get("/")
def index():
    return app.send_static_file("index.html")


def sort_key(s):
    return (0, int(s["id"]), "") if s["id"].isdigit() else (1, 0, s["id"])


def load_all():
    students = [{"id": d.id, "name": d.to_dict().get("name", "")}
                for d in db.collection("students").stream()]
    students.sort(key=sort_key)
    records = {d.id: d.to_dict() for d in db.collection("attendance").stream()}
    return students, records


@app.get("/api/data")
def get_data():
    students, records = load_all()
    return jsonify(students=students, records=records)


@app.get("/api/export.xlsx")
def export_xlsx():
    students, records = load_all()
    return send_file(build_workbook(students, records), as_attachment=True,
                     download_name="attendance.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def replace_collection(name, new_docs):
    """Make the collection exactly equal to new_docs ({doc_id: data})."""
    ref = db.collection(name)
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

    replace_collection("students", student_docs)
    replace_collection("attendance", record_docs)
    return jsonify(ok=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=True)
