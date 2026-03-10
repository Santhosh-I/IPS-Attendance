"""
Advisor Email Notification Module for IPS Attendance System.

Checks attendance at scheduled times (8:15 AM and 1:15 PM IST) and sends
email notifications to class advisors listing present students from their class.
"""

import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import psycopg2
from psycopg2.extras import RealDictCursor

# IST timezone (UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))

# ---------------------
# Configuration
# ---------------------

# SMTP settings — configure via environment variables
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")       # sender email
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")  # app password

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres.xuirqkdtrvkhjirrnmla:ipsattendance0000830245@aws-1-ap-south-1.pooler.supabase.com:6543/postgres",
)

# ---------------------
# IPS Tech Community — 17 Second-Year Members
# ---------------------
# Each entry: student name (must match the `students.name` column exactly),
#             department, class advisor name, advisor email.

TEST_EMAIL = "tayanithaans2196@gmail.com"  # ← change to real advisor emails when going live

MONITORED_MEMBERS = [
    # ----- AI & DS - A (Advisor: Saranya U) -----
    {"name": "Kavinila L",          "roll_number": "24UAD149", "department": "AI&DS-A",      "advisor": "Saranya U",       "advisor_email": TEST_EMAIL},
    {"name": "Ansih Karthic V S",   "roll_number": "24UAD110", "department": "AI&DS-A",      "advisor": "Saranya U",       "advisor_email": TEST_EMAIL},
    {"name": "Joshpin Kayalvizhi A","roll_number": "24UAD145", "department": "AI&DS-A",      "advisor": "Saranya U",       "advisor_email": TEST_EMAIL},
    {"name": "Joe Daniel A",        "roll_number": "24UAD144", "department": "AI&DS-A",      "advisor": "Saranya U",       "advisor_email": TEST_EMAIL},
    {"name": "Akilan C K",          "roll_number": "24UAD105", "department": "AI&DS-A",      "advisor": "Saranya U",       "advisor_email": TEST_EMAIL},
    {"name": "Joshua Melvin K",     "roll_number": "24UAD146", "department": "AI&DS-A",      "advisor": "Saranya U",       "advisor_email": TEST_EMAIL},
    {"name": "Arunaw Rishe",        "roll_number": "24UAD114", "department": "AI&DS-A",      "advisor": "Saranya U",       "advisor_email": TEST_EMAIL},

    # ----- AI & DS - B (Advisor: Preethi R) -----
    {"name": "Srishanth P M",       "roll_number": "24UAD245", "department": "AI&DS-B",      "advisor": "Preethi R",       "advisor_email": TEST_EMAIL},
    {"name": "Mourish Antony C",    "roll_number": "24UAD201", "department": "AI&DS-B",      "advisor": "Preethi R",       "advisor_email": TEST_EMAIL},
    {"name": "Vinu Karthick D",     "roll_number": "24UAD262", "department": "AI&DS-B",      "advisor": "Preethi R",       "advisor_email": TEST_EMAIL},
    {"name": "Santhosh",            "roll_number": "24UAD233",  "department": "AI&DS-B",      "advisor": "Preethi R",       "advisor_email": TEST_EMAIL},

    # ----- CSE - A (Advisor: Vivekanandhan V) -----
    {"name": "Boomathi P",          "roll_number": "24UCS119", "department": "CSE-A",        "advisor": "Vivekanandhan V", "advisor_email": TEST_EMAIL},
    {"name": "Jeremiah Jefry G",    "roll_number": "24UCS143", "department": "CSE-A",        "advisor": "Vivekanandhan V", "advisor_email": TEST_EMAIL},

    # ----- CSE - B (Advisor: Sakthivel) -----
    {"name": "Samikssha",           "roll_number": "24UCS229", "department": "CSE-B",        "advisor": "Sakthivel", "advisor_email": TEST_EMAIL},

    # ----- IT (Advisor: Kamala V) -----
    {"name": "Harini M",            "roll_number": "24UIT120", "department": "IT",           "advisor": "Kamala V",        "advisor_email": TEST_EMAIL},

    # ----- CYS (Advisor: Kamalakannan R) -----
    {"name": "Tayanithaa N S",      "roll_number": "24UCY158", "department": "CYS",          "advisor": "Kamalakannan R",  "advisor_email": TEST_EMAIL},
    {"name": "Mirdula R",           "roll_number": "24UCY127", "department": "CYS",          "advisor": "Kamalakannan R",  "advisor_email": TEST_EMAIL},
]

def get_db():
    """Open a new database connection."""
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def get_present_monitored_students(today_str: str) -> list[dict]:
    """
    Query attendance for today and return only the monitored members
    who have at least one IN record.
    """
    conn = get_db()
    cursor = conn.cursor()

    # Get distinct student names present today
    cursor.execute(
        """
        SELECT DISTINCT s.name
        FROM attendance a
        JOIN students s ON s.id = a.student_id
        WHERE a.date = %s AND a.in_time IS NOT NULL
        """,
        (today_str,),
    )
    present_names = {row["name"] for row in cursor.fetchall()}
    conn.close()

    # Filter monitored members who are present
    return [m for m in MONITORED_MEMBERS if m["name"] in present_names]


def group_by_advisor(members: list[dict]) -> dict:
    """
    Group members by (advisor_email + department) so each department
    always gets its own email — even during testing when all emails are the same.
    Returns: { "email|dept": { "advisor": str, "department": str, "email": str, "students": [str] } }
    """
    grouped = defaultdict(lambda: {"advisor": "", "department": "", "email": "", "students": []})
    for m in members:
        key = f"{m['advisor_email']}|{m['department']}"
        grouped[key]["advisor"] = m["advisor"]
        grouped[key]["department"] = m["department"]
        grouped[key]["email"] = m["advisor_email"]
        grouped[key]["students"].append({"name": m["name"], "roll_number": m.get("roll_number", "")})
    return grouped


def build_email_body(advisor_name: str, department: str, students: list[dict], today_str: str, check_time: str) -> str:
    """Build a plain-text email body listing present students with roll numbers."""
    lines = []
    for i, s in enumerate(students, 1):
        roll = s["roll_number"] if s["roll_number"] else "N/A"
        lines.append(f"  {i}. {s['name']}  (Roll No: {roll})")
    student_list = "\n".join(lines)

    return (
        f"Dear {advisor_name},\n\n"
        f"This is to inform you that the following student(s) from the "
        f"{department} department (IPS Tech Community — 2nd Year) have been "
        f"recorded as PRESENT in the attendance system today "
        f"({today_str}, checked at {check_time} IST):\n\n"
        f"{student_list}\n\n"
        f"Total present: {len(students)}\n\n"
        f"Regards,\n"
        f"IPS Attendance System\n\n"
        f"---\n"
        f"NOTE: This is a system-generated automatic message. "
        f"Please do not reply to this email."
    )


def send_email(to_addr: str, subject: str, body: str) -> None:
    """Send a single email via SMTP."""
    if not SMTP_USER or not SMTP_PASSWORD:
        print(f"[SKIP] SMTP credentials not configured. Would send to {to_addr}:")
        print(f"  Subject: {subject}")
        print(f"  Body preview: {body[:120]}...")
        return

    msg = MIMEMultipart()
    msg["From"] = SMTP_USER
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_USER, to_addr, msg.as_string())

    print(f"[SENT] Email to {to_addr} — {subject}")


def run_notification_check():
    """
    Main entry point: query today's attendance, group present monitored
    students by advisor, and send one email per advisor.
    """
    now = datetime.now(IST)
    today_str = now.strftime("%Y-%m-%d")
    check_time = now.strftime("%I:%M %p")

    print(f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] Running advisor notification check...")

    present = get_present_monitored_students(today_str)

    if not present:
        print("  No monitored students present today. No emails to send.")
        return

    grouped = group_by_advisor(present)

    for _, info in grouped.items():
        subject = (
            f"IPS Attendance — {info['department']} Students Present Today ({today_str})"
        )
        body = build_email_body(
            advisor_name=info["advisor"],
            department=info["department"],
            students=info["students"],
            today_str=today_str,
            check_time=check_time,
        )
        try:
            send_email(info["email"], subject, body)
        except Exception as e:
            print(f"[ERROR] Failed to send email to {info['email']}: {e}")

    print(f"  Done. Notified {len(grouped)} advisor(s) about {len(present)} student(s).")


def run_test_email():
    """
    Force-send a test email using all MONITORED_MEMBERS as if they are present.
    Use this to verify SMTP is working without needing real attendance data.
    """
    now = datetime.now(IST)
    today_str = now.strftime("%Y-%m-%d")
    check_time = now.strftime("%I:%M %p")

    print(f"[TEST MODE] Simulating all {len(MONITORED_MEMBERS)} monitored members as present...")

    grouped = group_by_advisor(MONITORED_MEMBERS)

    for _, info in grouped.items():
        subject = (
            f"[TEST] IPS Attendance — {info['department']} Students Present Today ({today_str})"
        )
        body = build_email_body(
            advisor_name=info["advisor"],
            department=info["department"],
            students=info["students"],
            today_str=today_str,
            check_time=check_time,
        )
        try:
            send_email(info["email"], subject, body)
        except Exception as e:
            print(f"[ERROR] Failed to send test email to {info['email']}: {e}")

    print(f"[TEST MODE] Done. Sent {len(grouped)} test email(s).")


# Allow direct execution for testing
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        run_test_email()
    else:
        run_notification_check()
