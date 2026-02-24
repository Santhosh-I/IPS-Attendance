from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file
import sqlite3
from datetime import datetime
import json
import os
import io

app = Flask(__name__)

# Use /tmp for serverless (Vercel), local path otherwise
if os.environ.get("VERCEL"):
    DATABASE = "/tmp/database.db"
else:
    DATABASE = os.path.join(os.path.dirname(__file__), "database.db")

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
def get_sheet():
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        print("gspread/google-auth not installed, skipping sheets sync")
        return None

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    # On Vercel: use env vars; locally: use credentials.json file
    creds_json = os.environ.get("GOOGLE_CREDS_JSON")
    sheet_id = os.environ.get("SHEET_ID", "1lUsXnIVtTca18X43AtJsfV6MrJCihuXA1Q3Ddv9k9bs")

    if creds_json:
        creds_data = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_data, scopes=scopes)
    else:
        creds_file = os.path.join(os.path.dirname(__file__), "credentials.json")
        if not os.path.exists(creds_file):
            print("No credentials found, skipping sheets sync")
            return None
        creds = Credentials.from_service_account_file(creds_file, scopes=scopes)

    gc = gspread.authorize(creds)
    sh = gc.open_by_key(sheet_id)
    return sh.sheet1

def sync_to_sheets():
    try:
        ws = get_sheet()
        if ws is None:
            return

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

@app.route("/dashboard")
def dashboard():
    conn = get_db()
    cursor = conn.cursor()

    records = cursor.execute('''
        SELECT students.name, attendance.date,
               attendance.entry_number, attendance.in_time, attendance.out_time
        FROM attendance
        JOIN students ON students.id = attendance.student_id
        ORDER BY attendance.date DESC, attendance.id DESC
    ''').fetchall()

    conn.close()
    return render_template("dashboard.html", records=records)

@app.route("/history")
def history():
    return render_template("history.html")

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

    data = []
    for r in records:
        data.append({
            "name": r["name"],
            "roll_number": r["roll_number"] or "-",
            "in_time": r["in_time"],
            "out_time": r["out_time"] or "-",
            "entry_number": r["entry_number"]
        })

    return jsonify(data)

@app.route("/api/attendance-dates")
def attendance_dates():
    conn = get_db()
    cursor = conn.cursor()

    dates = cursor.execute(
        "SELECT DISTINCT date FROM attendance ORDER BY date"
    ).fetchall()

    conn.close()
    return jsonify([d["date"] for d in dates])

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
                "INSERT INTO students (name, roll_number, rfid_uid) VALUES (?, ?, ?)",
                (name, roll_number, rfid_uid),
            )
            conn.commit()
            message = f"{name} added successfully!"
            status = "in"
        except sqlite3.IntegrityError:
            message = "This RFID UID is already registered!"
            status = "error"
        finally:
            conn.close()

    return render_template("add_member.html", message=message, status=status)

@app.route("/members")
def members():
    conn = get_db()
    cursor = conn.cursor()
    students = cursor.execute("SELECT * FROM students ORDER BY name").fetchall()
    conn.close()
    return render_template("members.html", students=students)

@app.route("/download-members")
def download_members():
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

    conn = get_db()
    cursor = conn.cursor()
    students = cursor.execute("SELECT name, roll_number, rfid_uid FROM students ORDER BY name").fetchall()
    conn.close()

    wb = Workbook()
    ws = wb.active
    ws.title = "Members"

    # Header styling
    header_font = Font(bold=True, color="FFFFFF", size=12)
    header_fill = PatternFill(start_color="1a1a2e", end_color="1a1a2e", fill_type="solid")
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin")
    )

    headers = ["S.No", "Name", "Roll Number", "RFID UID"]
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
        cell.border = thin_border

    for i, s in enumerate(students, 1):
        ws.cell(row=i + 1, column=1, value=i).border = thin_border
        ws.cell(row=i + 1, column=2, value=s["name"]).border = thin_border
        ws.cell(row=i + 1, column=3, value=s["roll_number"] or "-").border = thin_border
        ws.cell(row=i + 1, column=4, value=s["rfid_uid"]).border = thin_border

    ws.column_dimensions["A"].width = 8
    ws.column_dimensions["B"].width = 25
    ws.column_dimensions["C"].width = 18
    ws.column_dimensions["D"].width = 22

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="members.xlsx"
    )

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
            "UPDATE students SET name = ?, roll_number = ? WHERE id = ?",
            (name, roll_number, id),
        )
        conn.commit()
        message = "Updated successfully!"
        status = "in"

    student = cursor.execute("SELECT * FROM students WHERE id = ?", (id,)).fetchone()
    conn.close()

    if not student:
        return redirect("/members")

    return render_template("edit_member.html", student=student, message=message, status=status)

@app.route("/delete-member/<int:id>", methods=["POST"])
def delete_member(id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM attendance WHERE student_id = ?", (id,))
    cursor.execute("DELETE FROM students WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return redirect("/members")

# Local testing
if __name__ == "__main__":
    app.run(debug=True)