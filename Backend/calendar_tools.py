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
SERVICE_ACCOUNT_FILE = r"C:\Users\ssharmaz200\meeting_scheduling_langgraph_v2\langraph-agno\Backend\service_account_key.json"
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
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body{{
                font-family: Arial, sans-serif !important;
                margin: 0;
                padding: 0;
                background-color: #f2f4f5;
                -webkit-text-size-adjust: 100%;
                -ms-text-size-adjust: 100%;
            }}

            /* Mobile-first responsive design */
            @media screen and (max-width: 600px) {{
                .container {{
                    margin: 16px !important;
                    border-radius: 12px !important;
                }}
                
                .header-section {{
                    flex-direction: column !important;
                }}
                
                .header-content {{
                    width: 100% !important;
                    padding: 24px !important;
                }}
                
                .header-image {{
                    width: 100% !important;
                }}
                
                .header-image img {{
                    height: 200px !important;
                }}
                
                .main-title {{
                    font-size: 24px !important;
                }}
                
                .content-padding {{
                    padding: 24px !important;
                }}
                
                .session-details {{
                    flex-direction: column !important;
                    gap: 16px !important;
                }}
                
                .detail-item {{
                    margin-right: 0 !important;
                    margin-bottom: 16px;
                }}
                
                .detail-item:last-child {{
                    margin-bottom: 0;
                }}
                
                .cta-section {{
                    padding: 32px 16px !important;
                }}
                
                .cta-button {{
                    font-size: 16px !important;
                    padding: 12px 24px !important;
                }}
                
                .footer-padding {{
                    padding: 24px 16px !important;
                }}
            }}

            /* Tablet adjustments */
            @media screen and (min-width: 601px) and (max-width: 768px) {{
                .container {{
                    margin: 32px 16px !important;
                }}
                
                .header-content {{
                    padding: 28px !important;
                }}
                
                .content-padding {{
                    padding: 32px !important;
                }}
            }}

            /* Ensure images are responsive */
            img {{
                max-width: 100%;
                height: auto;
                display: block;
            }}

            /* Fix for Outlook */
            table {{
                border-collapse: collapse;
                mso-table-lspace: 0pt;
                mso-table-rspace: 0pt;
            }}
        </style>
    </head>
    <body style="background-color: #f2f4f5; font-family: Arial, sans-serif; margin: 0; padding: 0;">
 
    <div style="display: flex; justify-content: center; align-items: center; padding: 64px 16px;">
        <div class="container" style="width: 100%; max-width: 768px; background-color: white; border-radius: 16px; box-shadow: 0 10px 15px rgba(0, 0, 0, 0.1); border: 1px solid #e4e7eb; overflow: hidden;">
           
            <!-- Header Section -->
            <div class="header-section" style="display: flex; flex-direction: row;">
                <div class="header-content" style="width: 50%; background-color: #ffe8d3; padding: 32px; display: flex; flex-direction: column; justify-content: center;">
                    <div style="display: inline-block;">
                        <div style="background-color: #ffcda8; display: inline-block; padding: 4px 8px;">
                            <h2 style="color: #000000; font-size: 24px; font-weight: 500; margin: 0; line-height: 1.2;">Meeting Invite</h2>
                        </div>
                    </div>
                    <h1 class="main-title" style="color: #000000; font-size: 32px; font-weight: bold; margin: 16px 0 0 0;">{event_details['summary']}</h1>
                    <div style="margin-top: 24px;">
                        <span style="background-color: white; border: 1px solid #e4e7eb; padding: 8px 16px; color: #000000; font-size: 16px;">2025-08-06</span>
                    </div>
                </div>
                <div class="header-image" style="width: 50%;">
                    <img src="https://storage.googleapis.com/uxpilot-auth.appspot.com/673050c327-bff99ad16b571543fd76.png" alt="Meeting Banner" style="width: 100%; height: 256px; object-fit: cover; display: block;">
                </div>
            </div>
 
            <!-- Content Section -->
            <div class="content-padding" style="padding: 40px;">
                <div>
                    <p style="color: #000000; font-size: 14px; margin: 0 0 16px 0;">Dear Attendee,</p>
                    <p style="color: #000000; font-size: 14px; line-height: 1.5; margin: 0 0 32px 0;">You have been added to the upcoming meeting: {event_details['summary']}<br>{event_details['description']}</p>
                </div>
 
                <!-- Session Details -->
                <div>
                    <h3 style="color: #000000; font-size: 16px; font-weight: 600; margin: 0 0 16px 0;">Session Details</h3>
                    <div style="background-color: #f2f4f5; padding: 24px; border-radius: 8px;">
                        <div class="session-details" style="display: flex; justify-content: space-between; gap: 16px;">
                           
                            <!-- Time -->
                            <div class="detail-item" style="flex: 1; display: flex; align-items: center; gap: 12px; min-width: 0; margin-right: 12px;">
                                <div style="width: 56px; height: 56px; background-color: white; border-radius: 6px; box-shadow: 0 1px 2px rgba(0, 0, 0, 0.1); display: flex; align-items: center; justify-content: center; flex-shrink: 0;">
                                    <img src="https://api.iconify.design/material-symbols:calendar-today-outline.svg?color=%23ffcda8&width=24&height=24" alt="Calendar" style="width: 24px; height: 24px; display: block;" />
                                </div>
                                <span style="color: #000000; font-size: 12px; word-wrap: break-word; overflow-wrap: break-word; min-width: 0; flex: 1;"> {event_details['start_time']} ({event_details['duration']})</span>
                            </div>
 
                            <!-- Location -->
                            <div class="detail-item" style="flex: 1; display: flex; align-items: center; gap: 12px; min-width: 0; margin-right: 12px;">
                                <div style="width: 56px; height: 56px; background-color: white; border-radius: 6px; box-shadow: 0 1px 2px rgba(0, 0, 0, 0.1); display: flex; align-items: center; justify-content: center; flex-shrink: 0;">
                                    <img src="https://api.iconify.design/material-symbols:location-on-outline.svg?color=%23ffcda8&width=24&height=24" alt="Location" style="width: 24px; height: 24px; display: block;" />
                                </div>
                                <span style="color: #000000; font-size: 12px; line-height: 1.5; word-wrap: break-word; overflow-wrap: break-word; min-width: 0; flex: 1;"> {event_details['location']}</span>
                            </div>
 
                            <!-- Meeting Link -->
                            <div class="detail-item" style="flex: 1; display: flex; align-items: center; gap: 12px; min-width: 0;">
                                <div style="width: 56px; height: 56px; background-color: white; border-radius: 6px; box-shadow: 0 1px 2px rgba(0, 0, 0, 0.1); display: flex; align-items: center; justify-content: center; flex-shrink: 0;">
                                    <img src="https://api.iconify.design/material-symbols:link.svg?color=%23ffcda8&width=24&height=24" alt="Join Link" style="width: 24px; height: 24px; display: block;" />
                                </div>
                                <div style="min-width: 0; flex: 1;">
                                    <a href="{event_details['event_link']}" style="color: #085297; font-size: 12px; font-weight: 600; text-decoration: none; word-wrap: break-word;">Join here</a>
                                    <p style="color: #000000; font-size: 12px; margin: 4px 0 0 0; word-wrap: break-word;">Password - PWC#1234</p>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
 
                <!-- CTA Button -->
                <div style="margin-top: 32px;">
                    <div class="cta-section" style="background-color: #e4e7eb; padding: 48px; border-radius: 8px; text-align: center;">
                        <a href="{event_details['event_link']}" class="cta-button" style="background-color: #ffe8d3; color: #085297; font-size: 20px; font-weight: 600; padding: 12px 48px; border-radius: 8px; box-shadow: 0 4px 4px rgba(0, 0, 0, 0.25); text-decoration: none; display: inline-block;">View in Outlook Calendar</a>
                        <p style="color: #666666; font-size: 12px; margin: 12px 0 0 0; font-style: italic;">Note: This feature is currently disabled for the demo version</p>
                    </div>
                </div>
            </div>
 
            <!-- Footer -->
            <div class="footer-padding" style="text-align: center; padding: 32px; border-top: 1px solid #e4e7eb;">
                <div>
                    <p style="font-weight: bold; color: #000000; font-size: 16px; margin: 0;">PWC AI Assistant</p>
                    <p style="color: #000000; font-size: 14px; margin: 8px 0 0 0;">This meeting was scheduled automatically by your intelligent calendar assistant</p>
                </div>
                <div style="margin-top: 32px;">
                    <p style="color: rgba(0,0,0,0.70); font-size: 14px; margin: 0;">© 2025 PricewaterhouseCoopers. All rights reserved.</p>
                    <p style="color: #000000; font-size: 14px; margin: 4px 0 0 0;">Building trust and delivering sustained outcomes</p>
                </div>
            </div>
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
 
 