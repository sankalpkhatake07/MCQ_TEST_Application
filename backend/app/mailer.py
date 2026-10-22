import smtplib
from email.message import EmailMessage

from . import config


def send_otp_email(to_email: str, code: str) -> None:
    if not config.ALLOW_SEND_EMAIL:
        print(f"[DEV OTP] {to_email}: {code}", flush=True)
        return
    msg = EmailMessage()
    msg["Subject"] = "Your ExamHub sign-in code"
    msg["From"] = config.FROM_EMAIL
    msg["To"] = to_email
    msg.set_content(f"Your ExamHub code is {code}\nIt expires in {config.OTP_TTL_MIN} minutes. If you did not ask for it, ignore this email.")
    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15) as smtp:
        smtp.starttls()
        smtp.login(config.SMTP_USER, config.SMTP_PASS)
        smtp.send_message(msg)
