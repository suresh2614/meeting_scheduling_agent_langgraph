# Jupyter Notebook Cell 1: Install and Import Dependencies
# !pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client python-dotenv
 
import os
import json
from datetime import datetime, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from dotenv import load_dotenv
from typing import List
 
# Load environment variables
load_dotenv()
SERVICE_ACCOUNT_FILE = r"C:\Users\ssharmaz200\Meeting_scheduler_agent_langgraph_v1(August 9th)\langraph-agno\Backend\service_account_key.json"
SCOPES = ['https://www.googleapis.com/auth/calendar']
 
 
SMTP_EMAIL = "manicharanakarapu123@gmail.com"
SMTP_PASSWORD = "ilkp wekr jeeq gnml"
 
def authenticate_google_service_account():
    """Authenticate using service account"""
    credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    service = build('calendar', 'v3', credentials=credentials)
    return service
 
def send_calendar_notification_smtp(event_details, attendee_emails):
    """Send email notifications using SMTP"""
    subject = f"Meeting Invite: {event_details['summary']}"
    password = event_details.get('password', 'PWC@1234')
   
    html_body = f"""
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: Arial, sans-serif; background-color: #f2f4f5; }}
            .container {{ max-width: 600px; margin: 0 auto; background: white; padding: 20px; }}
            .header {{ background-color: #ffe8d3; padding: 20px; text-align: center; }}
            .content {{ padding: 20px; }}
            .details {{ background-color: #f9f9f9; padding: 15px; margin: 10px 0; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>Meeting Invite: {event_details['summary']}</h1>
            </div>
            <div class="content">
                <p>Dear Attendee,</p>
                <p>{event_details['description']}</p>
               
                <div class="details">
                    <h3>Meeting Details:</h3>
                    <p><strong>Date & Time:</strong> {event_details['start_time']}</p>
                    <p><strong>Duration:</strong> {event_details['duration']}</p>
                    <p><strong>Location:</strong> {event_details['location']}</p>
                    <p><strong>Meeting Link:</strong> <a href="{event_details['event_link']}">Join Meeting</a></p>
                    <p><strong>Password:</strong> {password}</p>
                </div>
               
                <p>Please mark your calendar and join the meeting at the scheduled time.</p>
            </div>
        </div>
    </body>
    </html>
    """    
   
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
       
        for email in attendee_emails:
            msg = MIMEMultipart('related')
            msg['From'] = SMTP_EMAIL
            msg['To'] = email
            msg['Subject'] = subject
           
            msg.attach(MIMEText(html_body, 'html'))
            server.send_message(msg)
            print(f"Email sent to {email}")
           
        server.quit()
        return True
       
    except Exception as e:
        print(f"Failed to send emails: {e}")
        return False
 
def create_calendar_event(
    title: str,
    date: str,
    time: str,
    duration_hours: int,
    attendee_emails: List[str],
    location: str = "Online",
    description: str = "Meeting scheduled by AI Assistant"
) -> str:
    """
    Create a calendar event and send invitations
   
    Args:
        title: Meeting title
        date: Date in YYYY-MM-DD format
        time: Time in HH:MM format (24-hour) or HH:MM AM/PM format
        duration_hours: Meeting duration in hours
        attendee_emails: List of attendee email addresses
        location: Meeting location (default: "Online")
        description: Meeting description
   
    Returns:
        JSON string with event creation status
    """
    try:
        print(f"Creating event: {title}")
        print(f"Date: {date}, Time: {time}, Duration: {duration_hours}h")
        print(f"Attendees: {attendee_emails}")
       
        # Parse date and time
        datetime_str = f"{date} {time}"
        try:
            start_time = datetime.strptime(datetime_str, '%Y-%m-%d %H:%M')
        except ValueError:
            start_time = datetime.strptime(datetime_str, '%Y-%m-%d %I:%M %p')
       
        end_time = start_time + timedelta(hours=duration_hours)
       
        print("Authenticating with Google Calendar...")
        service = authenticate_google_service_account()
        print("Authentication successful!")
       
        # Create event object
        event = {
            'summary': title,
            'location': location,
            'description': description,
            'start': {
                'dateTime': start_time.isoformat(),
                'timeZone': 'Asia/Kolkata'
            },
            'end': {
                'dateTime': end_time.isoformat(),
                'timeZone': 'Asia/Kolkata'
            },
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'email', 'minutes': 24 * 60},  
                    {'method': 'popup', 'minutes': 10},  
                ],
            },
        }
       
        # Create the event
        print("Creating calendar event...")
        created_event = service.events().insert(
            calendarId='primary',
            body=event,
            sendNotifications=True
        ).execute()
       
        print(f"Event created successfully! ID: {created_event.get('id')}")
       
        # Send email notifications
        email_sent = False
        if attendee_emails:
            print("Sending email notifications...")
            event_details = {
                'summary': title,
                'start_time': start_time.strftime('%B %d, %Y at %I:%M %p IST'),
                'duration': f"{duration_hours} hour(s)",
                'location': location,
                'description': description,
                'event_link': created_event.get('htmlLink', '#'),
                'date': date,
                'password': 'PWC@1234'
            }
            email_sent = send_calendar_notification_smtp(event_details, attendee_emails)
       
        result = {
            "status": "success",
            "message": f"Calendar event '{title}' created successfully!",
            "event_link": created_event.get('htmlLink'),
            "event_id": created_event.get('id'),
            "attendees_notified": len(attendee_emails) if attendee_emails else 0,
            "emails_sent": email_sent,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat()
        }
       
        return json.dumps(result, indent=2)
       
    except Exception as e:
        print(f"ERROR: {str(e)}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
       
        return json.dumps({
            "status": "error",
            "message": f"Failed to create calendar event: {str(e)}",
            "error_type": str(type(e))
        }, indent=2)
 
 
 
def test_authentication():
    try:
        service = authenticate_google_service_account()
        calendars = service.calendarList().list().execute()
        print("Authentication successful!")
        print(f"Found {len(calendars.get('items', []))} calendars")
        return True
    except Exception as e:
        print(f"Authentication failed: {e}")
        return False
 
def test_email_connection():
    """Test SMTP email connection"""
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.quit()
        print("Email authentication successful!")
        return True
    except Exception as e:
        print(f"Email authentication failed: {e}")
        return False
 
 