"""
Gmail SMTP email service.

Requires env vars in backend/.env:
  GMAIL_SENDER_EMAIL   - Gmail address to send from
  GMAIL_APP_PASSWORD   - Gmail App Password
"""

import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional
from app.logging_config import get_logger

log = get_logger(__name__)

GMAIL_HOST = "smtp.gmail.com"
GMAIL_PORT = 587


def _get_smtp_creds():
    email = os.getenv("GMAIL_SENDER_EMAIL")
    password = os.getenv("GMAIL_APP_PASSWORD")
    if not email or not password:
        raise EnvironmentError(
            "GMAIL_SENDER_EMAIL and GMAIL_APP_PASSWORD must be set in .env to send emails."
        )
    return email, password


def _send(to_email: str, subject: str, html_body: str, text_body: str) -> dict:
    sender_email, password = _get_smtp_creds()
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = to_email
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))
    with smtplib.SMTP(GMAIL_HOST, GMAIL_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(sender_email, password)
        server.sendmail(sender_email, to_email, msg.as_string())
    log.info("Email sent to %s: %s", to_email, subject)
    return {"status": "sent", "to": to_email, "subject": subject}


def send_recommendation_email(
    to_email: str,
    customer_name: str,
    recommended_product: str,
    rationale: str,
    confidence_pct: int,
    revenue_opportunity: int,
    sender_name: str = "Your Account Manager",
) -> dict:
    subject = f"A product recommendation for {customer_name}"
    html_body = f"""
    <html><body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
      <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; border-radius: 12px; margin-bottom: 24px;">
        <h1 style="color: white; margin: 0; font-size: 24px;">Product Recommendation</h1>
        <p style="color: rgba(255,255,255,0.85); margin: 8px 0 0 0;">Personalized for {customer_name}</p>
      </div>
      <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 20px; margin-bottom: 20px;">
        <p style="color: #64748b; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; margin: 0 0 8px 0;">Recommended Product</p>
        <h2 style="color: #1e293b; margin: 0; font-size: 22px;">{recommended_product}</h2>
        <div style="margin-top: 12px;">
          <span style="background: #dcfce7; color: #166534; padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: 600; margin-right: 8px;">{confidence_pct}% confidence</span>
          <span style="background: #dbeafe; color: #1e40af; padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: 600;">${revenue_opportunity:,}/yr potential</span>
        </div>
      </div>
      <div style="margin-bottom: 20px;">
        <p style="color: #374151; font-size: 14px; line-height: 1.6;">{rationale}</p>
      </div>
      <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 20px 0;" />
      <p style="color: #374151; font-size: 14px;">Best regards,<br /><strong>{sender_name}</strong></p>
    </body></html>
    """
    text_body = f"Product Recommendation for {customer_name}\n\nRecommended: {recommended_product}\nConfidence: {confidence_pct}%\nPotential: ${revenue_opportunity:,}/yr\n\nWhy: {rationale}\n\nBest regards,\n{sender_name}"
    return _send(to_email, subject, html_body, text_body)


def send_meeting_invite_email(
    to_email: str,
    customer_name: str,
    meeting_title: str,
    meeting_datetime: str,
    meet_link: str,
    agenda: Optional[str] = None,
    sender_name: str = "Your Account Manager",
) -> dict:
    subject = f"Meeting Invitation: {meeting_title}"
    agenda_html = f'<p style="color: #374151; font-size: 14px;"><strong>Agenda:</strong> {agenda}</p>' if agenda else ""
    html_body = f"""
    <html><body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
      <div style="background: linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%); padding: 30px; border-radius: 12px; margin-bottom: 24px;">
        <h1 style="color: white; margin: 0; font-size: 24px;">Meeting Invitation</h1>
        <p style="color: rgba(255,255,255,0.85); margin: 8px 0 0 0;">You're invited, {customer_name}</p>
      </div>
      <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 20px; margin-bottom: 20px;">
        <h2 style="color: #1e293b; margin: 0 0 12px 0;">{meeting_title}</h2>
        <p style="color: #374151;"><strong>Date &amp; Time:</strong> {meeting_datetime}</p>
        {agenda_html}
        <a href="{meet_link}" style="display: inline-block; background: #10b981; color: white; padding: 12px 24px; border-radius: 8px; text-decoration: none; font-weight: 600; margin-top: 16px;">Join Google Meet</a>
      </div>
      <p style="color: #374151; font-size: 14px;">Best regards,<br /><strong>{sender_name}</strong></p>
    </body></html>
    """
    text_body = f"Meeting: {meeting_title}\nFor: {customer_name}\nTime: {meeting_datetime}\nJoin: {meet_link}\n{('Agenda: ' + agenda) if agenda else ''}\nBest regards,\n{sender_name}"
    return _send(to_email, subject, html_body, text_body)
