from flask import Flask, render_template, request, redirect, url_for, jsonify
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, date, time
import os

app = Flask(__name__)

DATABASE_URL = "postgresql://postgres.xuirqkdtrvkhjirrnmla:ipsattendance0000830245@aws-1-ap-south-1.pooler.supabase.com:6543/postgres"

@app.template_filter('to12hr')
def to12hr_filter(value):
    if not value:
        return '-'
    if isinstance(value, time):
        return value.strftime('%I:%M:%S %p')
    try:
        t = datetime.strptime(str(value), '%H:%M:%S')
        return t.strftime('%I:%M:%S %p')
    except ValueError:
        return str(value)

def _time_str(value):
    """Convert time/datetime.time to string for JSON responses."""
    if value is None:
        return '-'
    if isinstance(value, time):
        return value.strftime('%H:%M:%S')
    return str(value)

def _date_str(value):
    """Convert date/datetime.date to string for JSON responses."""
    if value is None:
        return ''
    if isinstance(value, date):
        return value.strftime('%Y-%m-%d')
    return str(value)

# -------------------------
# Database Connection
# -------------------------
def get_db():
    return psycopg2.connect(
        DATABASE_URL,
        cursor_factory=RealDictCursor
    )

# -------------------------
# Initialize Database
# -------------------------
def init_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS students (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            roll_number TEXT,
            rfid_uid TEXT UNIQUE NOT NULL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            id SERIAL PRIMARY KEY,
            student_id INTEGER REFERENCES students(id),
            date DATE,
            in_time TIME,
            out_time TIME,
            entry_number INTEGER DEFAULT 1
        )
    ''')

    conn.commit()
    conn.close()

init_db()

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

        cursor.execute(
            "SELECT * FROM students WHERE rfid_uid = %s",
            (uid,)
        )
        student = cursor.fetchone()

        if not student:
            message = "ID Not Registered"
            status = "error"
        else:
            today = datetime.now().strftime("%Y-%m-%d")
            current_time = datetime.now().strftime("%H:%M:%S")

            cursor.execute(
                "SELECT * FROM attendance WHERE student_id = %s AND date = %s ORDER BY id DESC LIMIT 1",
                (student["id"], today),
            )
            latest = cursor.fetchone()

            if not latest or (latest["in_time"] and latest["out_time"]):
                entry_num = (latest["entry_number"] + 1) if latest else 1

                cursor.execute(
                    "INSERT INTO attendance (student_id, date, in_time, entry_number) VALUES (%s, %s, %s, %s)",
                    (student["id"], today, current_time, entry_num),
                )
                message = f"IN Time Marked (Entry #{entry_num})"
                status = "in"
            else:
                cursor.execute(
                    "UPDATE attendance SET out_time = %s WHERE id = %s",
                    (current_time, latest["id"]),
                )
                message = "OUT Time Marked"
                status = "out"

            conn.commit()

        conn.close()

    return render_template("index.html", message=message, status=status)

@app.route("/dashboard")
def dashboard():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT students.name, attendance.date,
               attendance.entry_number, attendance.in_time, attendance.out_time
        FROM attendance
        JOIN students ON students.id = attendance.student_id
        ORDER BY attendance.date DESC, attendance.id DESC
    ''')
    records = cursor.fetchall()

    conn.close()
    return render_template("dashboard.html", records=records)

@app.route("/history")
def history():
    return render_template("history.html")

@app.route("/api/attendance/<date>")
def attendance_by_date(date):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT students.name, students.roll_number,
               attendance.in_time, attendance.out_time,
               attendance.entry_number
        FROM attendance
        JOIN students ON students.id = attendance.student_id
        WHERE attendance.date = %s
    ''', (date,))
    records = cursor.fetchall()

    conn.close()

    data = []
    for r in records:
        data.append({
            "name": r["name"],
            "roll_number": r["roll_number"] or "-",
            "in_time": _time_str(r["in_time"]),
            "out_time": _time_str(r["out_time"]),
            "entry_number": r["entry_number"]
        })

    return jsonify(data)

@app.route("/api/attendance-dates")
def attendance_dates():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT DISTINCT date FROM attendance ORDER BY date"
    )
    dates = cursor.fetchall()

    conn.close()
    return jsonify([_date_str(d["date"]) for d in dates])

@app.route("/verify-admin", methods=["POST"])
def verify_admin():
    password = request.form.get("password", "")
    if password == "ips@2026":
        return redirect("/add-member")
    return redirect("/dashboard")

@app.route("/add-member", methods=["GET", "POST"])
def add_member():
    message = ""
    status = ""

    if request.method == "POST":
        name = request.form["name"].strip()
        roll_number = request.form.get("roll_number", "").strip()
        rfid_uid = request.form["rfid_uid"].strip()

        conn = get_db()
        cursor = conn.cursor()

        try:
            cursor.execute(
                "INSERT INTO students (name, roll_number, rfid_uid) VALUES (%s, %s, %s)",
                (name, roll_number, rfid_uid),
            )
            conn.commit()
            message = f"{name} added successfully!"
            status = "in"
        except psycopg2.IntegrityError:
            conn.rollback()
            message = "This RFID UID is already registered!"
            status = "error"
        finally:
            conn.close()

    return render_template("add_member.html", message=message, status=status)

@app.route("/members")
def members():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM students ORDER BY name")
    students = cursor.fetchall()
    conn.close()
    return render_template("members.html", students=students)

@app.route("/edit-member/<int:id>", methods=["GET", "POST"])
def edit_member(id):
    conn = get_db()
    cursor = conn.cursor()
    message = ""
    status = ""

    if request.method == "POST":
        name = request.form["name"].strip()
        roll_number = request.form.get("roll_number", "").strip()

        cursor.execute(
            "UPDATE students SET name = %s, roll_number = %s WHERE id = %s",
            (name, roll_number, id),
        )
        conn.commit()
        message = "Updated successfully!"
        status = "in"

    cursor.execute("SELECT * FROM students WHERE id = %s", (id,))
    student = cursor.fetchone()
    conn.close()

    if not student:
        return redirect("/members")

    return render_template("edit_member.html", student=student, message=message, status=status)

@app.route("/delete-member/<int:id>", methods=["POST"])
def delete_member(id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM attendance WHERE student_id = %s", (id,))
    cursor.execute("DELETE FROM students WHERE id = %s", (id,))
    conn.commit()
    conn.close()
    return redirect("/members")

# Local testing
if __name__ == "__main__":
    app.run(debug=True)