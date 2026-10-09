"""
Google Calendar API meeting scheduler.

Requires env vars in backend/.env:
  GOOGLE_SERVICE_ACCOUNT_JSON  - Path to service account JSON credentials file
  GOOGLE_SERVICE_ACCOUNT_KEY   - OR inline JSON string of service account credentials
  GOOGLE_CALENDAR_ID           - Calendar ID (defaults to 'primary')
  GOOGLE_MEET_ORGANIZER_EMAIL  - Email of the calendar owner (for domain delegation)

Falls back gracefully if unconfigured: returns meeting details without creating a real event.
"""

import os
import json
from datetime import datetime, timedelta
from typing import Optional
from app.logging_config import get_logger

log = get_logger(__name__)


def _get_google_service():
    try:
        from googleapiclient.discovery import build
        from google.oauth2 import service_account
    except ImportError:
        log.warning("google-api-python-client not installed. Install: pip install google-api-python-client google-auth")
        return None

    key_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    key_inline = os.getenv("GOOGLE_SERVICE_ACCOUNT_KEY")
    organizer = os.getenv("GOOGLE_MEET_ORGANIZER_EMAIL")

    if not organizer:
        return None

    try:
        scopes = ["https://www.googleapis.com/auth/calendar"]
        if key_path and os.path.exists(key_path):
            creds = service_account.Credentials.from_service_account_file(key_path, scopes=scopes)
        elif key_inline:
            info = json.loads(key_inline)
            creds = service_account.Credentials.from_service_account_info(info, scopes=scopes)
        else:
            return None
        delegated = creds.with_subject(organizer)
        return build("calendar", "v3", credentials=delegated)
    except Exception as e:
        log.error("Failed to build Google Calendar service: %s", e)
        return None


def schedule_meeting(
    title: str,
    start_datetime_utc: str,
    attendee_email: str,
    duration_minutes: int = 30,
    agenda: Optional[str] = None,
    customer_name: Optional[str] = None,
) -> dict:
    calendar_id = os.getenv("GOOGLE_CALENDAR_ID", "primary")
    try:
        start_dt = datetime.fromisoformat(start_datetime_utc.replace("Z", "+00:00"))
    except Exception:
        start_dt = datetime.utcnow() + timedelta(days=1)
    end_dt = start_dt + timedelta(minutes=duration_minutes)
    description = agenda or f"Meeting regarding product discussion with {customer_name or attendee_email}."

    service = _get_google_service()
    if service is None:
        return {
            "status": "fallback",
            "meet_link": None,
            "event_id": None,
            "event_link": None,
            "meeting_datetime_utc": start_datetime_utc,
            "duration_minutes": duration_minutes,
            "title": title,
            "attendee_email": attendee_email,
            "fallback_message": (
                "Google Calendar API is not configured. "
                "Set GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_SERVICE_ACCOUNT_KEY, "
                "GOOGLE_CALENDAR_ID, and GOOGLE_MEET_ORGANIZER_EMAIL in .env."
            ),
        }

    event_body = {
        "summary": title,
        "description": description,
        "start": {"dateTime": start_dt.isoformat(), "timeZone": "UTC"},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": "UTC"},
        "attendees": [{"email": attendee_email}],
        "conferenceData": {
            "createRequest": {
                "requestId": f"upsell-{attendee_email}-{int(start_dt.timestamp())}",
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        },
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "email", "minutes": 24 * 60},
                {"method": "popup", "minutes": 15},
            ],
        },
    }
    try:
        created = service.events().insert(
            calendarId=calendar_id,
            body=event_body,
            conferenceDataVersion=1,
            sendUpdates="all",
        ).execute()
        meet_link = None
        for ep in created.get("conferenceData", {}).get("entryPoints", []):
            if ep.get("entryPointType") == "video":
                meet_link = ep.get("uri")
                break
        log.info("Google Meet event created: %s", created.get("id"))
        return {
            "status": "created",
            "meet_link": meet_link,
            "event_id": created.get("id"),
            "event_link": created.get("htmlLink"),
            "meeting_datetime_utc": start_datetime_utc,
            "duration_minutes": duration_minutes,
            "title": title,
            "attendee_email": attendee_email,
        }
    except Exception as e:
        log.error("Failed to create calendar event: %s", e)
        return {
            "status": "fallback",
            "meet_link": None,
            "event_id": None,
            "event_link": None,
            "meeting_datetime_utc": start_datetime_utc,
            "duration_minutes": duration_minutes,
            "title": title,
            "attendee_email": attendee_email,
            "fallback_message": f"Calendar event creation failed: {str(e)}",
        }


def is_available() -> bool:
    return _get_google_service() is not None
