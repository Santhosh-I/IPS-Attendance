from flask import Flask, render_template, request, redirect, url_for, jsonify
import sqlite3
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
import os

app = Flask(__name__, template_folder="../templates")

DATABASE = "/tmp/database.db"   # Vercel writable temp folder

# -------------------------
# Database
# -------------------------
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            roll_number TEXT,
            rfid_uid TEXT UNIQUE NOT NULL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            date TEXT,
            in_time TEXT,
            out_time TEXT,
            entry_number INTEGER DEFAULT 1,
            FOREIGN KEY(student_id) REFERENCES students(id)
        )
    ''')

    conn.commit()
    conn.close()

init_db()

# -------------------------
# Google Sheets Config
# -------------------------
SHEET_ID = os.environ.get("SHEET_ID")
CREDS_JSON = os.environ.get("GOOGLE_CREDS_JSON")

def get_sheet():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    creds = Credentials.from_service_account_info(
        eval(GOOGLE_CREDS_JSON),
        scopes=scopes
    )

    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SHEET_ID)
    return sh.sheet1

def sync_to_sheets():
    try:
        ws = get_sheet()
        conn = get_db()
        cursor = conn.cursor()

        records = cursor.execute('''
            SELECT students.name, students.roll_number,
                   attendance.date, attendance.in_time,
                   attendance.out_time, attendance.entry_number
            FROM attendance
            JOIN students ON students.id = attendance.student_id
        ''').fetchall()

        conn.close()

        rows = [["Date", "Name", "Roll No", "Entry #", "In Time", "Out Time"]]

        for r in records:
            rows.append([
                r["date"],
                r["name"],
                r["roll_number"] or "-",
                r["entry_number"],
                r["in_time"],
                r["out_time"] or "-"
            ])

        ws.clear()
        ws.update(rows)

    except Exception as e:
        print("Sheet Sync Error:", e)

# -------------------------
# Routes
# -------------------------
@app.route("/", methods=["GET", "POST"])
def tap():
    message = ""
    status = ""

    if request.method == "POST":
        uid = request.form["rfid"].strip()
        conn = get_db()
        cursor = conn.cursor()

        student = cursor.execute(
            "SELECT * FROM students WHERE rfid_uid = ?",
            (uid,)
        ).fetchone()

        if not student:
            message = "ID Not Registered"
            status = "error"
        else:
            today = datetime.now().strftime("%Y-%m-%d")
            current_time = datetime.now().strftime("%H:%M:%S")

            latest = cursor.execute(
                "SELECT * FROM attendance WHERE student_id = ? AND date = ? ORDER BY id DESC LIMIT 1",
                (student["id"], today),
            ).fetchone()

            if not latest or (latest["in_time"] and latest["out_time"]):
                entry_num = (latest["entry_number"] + 1) if latest else 1
                cursor.execute(
                    "INSERT INTO attendance (student_id, date, in_time, entry_number) VALUES (?, ?, ?, ?)",
                    (student["id"], today, current_time, entry_num),
                )
                message = f"IN Time Marked (Entry #{entry_num})"
                status = "in"
            else:
                cursor.execute(
                    "UPDATE attendance SET out_time = ? WHERE id = ?",
                    (current_time, latest["id"]),
                )
                message = "OUT Time Marked"
                status = "out"

            conn.commit()
            sync_to_sheets()

        conn.close()

    return render_template("index.html", message=message, status=status)

@app.route("/api/attendance/<date>")
def attendance_by_date(date):
    conn = get_db()
    cursor = conn.cursor()

    records = cursor.execute('''
        SELECT students.name, students.roll_number,
               attendance.in_time, attendance.out_time,
               attendance.entry_number
        FROM attendance
        JOIN students ON students.id = attendance.student_id
        WHERE attendance.date = ?
    ''', (date,)).fetchall()

    conn.close()

    return jsonify([
        {
            "name": r["name"],
            "roll_number": r["roll_number"] or "-",
            "in_time": r["in_time"],
            "out_time": r["out_time"] or "-",
            "entry_number": r["entry_number"]
        }
        for r in records
    ])

# Required by Vercel
def handler(request, context):
    return app(request.environ, start_response)