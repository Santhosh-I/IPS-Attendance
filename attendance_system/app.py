from flask import Flask, render_template, request, redirect, url_for, jsonify
import sqlite3
from datetime import datetime

app = Flask(__name__)

DATABASE = "database.db"

# -------------------------
# Database Connection
# -------------------------
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

# -------------------------
# Initialize Database
# -------------------------
def init_db():
    conn = get_db()
    cursor = conn.cursor()

    # Create students table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            rfid_uid TEXT UNIQUE NOT NULL
        )
    ''')

    # Create attendance table
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

    # Add entry_number column if missing (migration for existing DBs)
    columns = [row[1] for row in cursor.execute("PRAGMA table_info(attendance)").fetchall()]
    if "entry_number" not in columns:
        cursor.execute("ALTER TABLE attendance ADD COLUMN entry_number INTEGER DEFAULT 1")

    # Insert sample student only if not exists
    cursor.execute(
        "SELECT * FROM students WHERE rfid_uid = ?",
        ("0000830245",)
    )

    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO students (name, rfid_uid) VALUES (?, ?)",
            ("Santhosh", "0000830245")
        )
        print("Sample Student Registered!")

    conn.commit()
    conn.close()

init_db()

# -------------------------
# TAP PAGE
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
            "SELECT * FROM students WHERE rfid_uid = ?", (uid,)
        ).fetchone()

        if not student:
            message = "Card Not Registered"
            status = "error"
        else:
            today = datetime.now().strftime("%Y-%m-%d")
            current_time = datetime.now().strftime("%H:%M:%S")

            # Get the latest attendance record for today
            latest = cursor.execute(
                "SELECT * FROM attendance WHERE student_id = ? AND date = ? ORDER BY id DESC LIMIT 1",
                (student["id"], today),
            ).fetchone()

            if not latest or (latest["in_time"] and latest["out_time"]):
                # No record yet or last record is complete → mark IN
                entry_num = (latest["entry_number"] + 1) if latest else 1
                cursor.execute(
                    "INSERT INTO attendance (student_id, date, in_time, entry_number) VALUES (?, ?, ?, ?)",
                    (student["id"], today, current_time, entry_num),
                )
                conn.commit()
                message = f"IN Time Marked for {student['name']} (Entry #{entry_num})"
                status = "in"
            elif latest["in_time"] and not latest["out_time"]:
                # Last record has IN but no OUT → mark OUT
                cursor.execute(
                    "UPDATE attendance SET out_time = ? WHERE id = ?",
                    (current_time, latest["id"]),
                )
                conn.commit()
                message = f"OUT Time Marked for {student['name']} (Entry #{latest['entry_number']})"
                status = "out"

        conn.close()

    return render_template("tap.html", message=message, status=status)

# -------------------------
# DASHBOARD PAGE
# -------------------------
@app.route("/dashboard")
def dashboard():
    conn = get_db()
    cursor = conn.cursor()

    records = cursor.execute('''
        SELECT students.name, attendance.date, attendance.in_time, attendance.out_time, attendance.entry_number
        FROM attendance
        JOIN students ON students.id = attendance.student_id
        ORDER BY attendance.date DESC, attendance.entry_number DESC
    ''').fetchall()

    conn.close()
    return render_template("dashboard.html", records=records)

if __name__ == "__main__":
    app.run(debug=True)