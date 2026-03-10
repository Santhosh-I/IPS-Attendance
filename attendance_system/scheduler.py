"""
Scheduler for IPS Attendance Advisor Notifications.

Runs continuously and triggers advisor email notifications at:
  - 8:15 AM IST
  - 1:15 PM IST

Usage:
    python scheduler.py

Environment variables (required for sending emails):
    SMTP_HOST      — SMTP server hostname (default: smtp.gmail.com)
    SMTP_PORT      — SMTP server port     (default: 587)
    SMTP_USER      — Sender email address
    SMTP_PASSWORD  — Sender email app password (not your regular password)

For Gmail, generate an App Password:
    Google Account → Security → 2-Step Verification → App Passwords
"""

import schedule
import time
from datetime import datetime, timezone, timedelta
from advisor_notifier import run_notification_check

# IST timezone
IST = timezone(timedelta(hours=5, minutes=30))


def job():
    """Wrapper that runs the notification check."""
    run_notification_check()


# Schedule at 8:15 AM and 1:15 PM IST
# Note: `schedule` uses the system clock. If the server is in UTC,
# convert IST times to UTC (8:15 IST = 2:45 UTC, 1:15 PM IST = 7:45 UTC).
# Adjust below if your server is NOT in IST.
schedule.every().day.at("10:50").do(job)
schedule.every().day.at("13:15").do(job)

if __name__ == "__main__":
    print("IPS Attendance — Advisor Notification Scheduler started.")
    print("Scheduled checks at 08:15 and 13:15 (server local time).")
    print("Press Ctrl+C to stop.\n")

    # Run the event loop
    while True:
        schedule.run_pending()
        time.sleep(30)
