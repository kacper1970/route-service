import os
import datetime
import pickle
import smtplib
from email.message import EmailMessage
from flask import Flask, jsonify, request
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import Flow
from flask_cors import CORS
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# Wymuszenie HTTPS OFF dla OAuth (do testów)
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

app = Flask(__name__)
CORS(app)

SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']
CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
REDIRECT_URI = "https://route-service.onrender.com/oauth2callback"
TOKEN_FILE = "token.pickle"

@app.route("/")
def index():
    return "✅ Route service is running"

@app.route("/authorize")
def authorize():
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "redirect_uris": [REDIRECT_URI],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token"
            }
        },
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
    return jsonify({"auth_url": auth_url})

@app.route("/oauth2callback")
def oauth2callback():
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "redirect_uris": [REDIRECT_URI],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token"
            }
        },
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    flow.fetch_token(authorization_response=request.url)
    creds = flow.credentials

    with open(TOKEN_FILE, 'wb') as token:
        pickle.dump(creds, token)

    return "✅ Token zapisany. Możesz korzystać z serwisu."

def get_calendar_service():
    if not os.path.exists(TOKEN_FILE):
        raise Exception("Brak tokena. Przejdź do /authorize")

    with open(TOKEN_FILE, 'rb') as token:
        creds = pickle.load(token)

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_FILE, 'wb') as token:
            pickle.dump(creds, token)

    return build('calendar', 'v3', credentials=creds)

def get_events_for_today():
    service = get_calendar_service()
    calendar_id = os.environ.get("GOOGLE_CALENDAR_ID")

    now = datetime.datetime.utcnow().replace(hour=0, minute=0, second=0)
    end = now + datetime.timedelta(days=1)

    events_result = service.events().list(
        calendarId=calendar_id,
        timeMin=now.isoformat() + 'Z',
        timeMax=end.isoformat() + 'Z',
        singleEvents=True,
        orderBy='startTime'
    ).execute()

    return events_result.get('items', [])

def generate_maps_link(addresses):
    base_url = "https://www.google.com/maps/dir/"
    return base_url + "/".join([addr.replace(" ", "+") for addr in addresses])

def generate_pdf(events):
    pdf_path = "/tmp/plan_dnia.pdf"
    c = canvas.Canvas(pdf_path, pagesize=A4)
    width, height = A4
    y = height - 50

    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, y, "Plan dnia – ENERTIA")
    y -= 30

    for event in events:
        summary = event.get("summary", "Brak tytułu")
        location = event.get("location", "Brak lokalizacji")
        start = event.get("start", {}).get("dateTime", "")
        start_time = start[11:16] if "T" in start else ""

        c.setFont("Helvetica", 12)
        c.drawString(50, y, f"🕒 {start_time} – {summary} @ {location}")
        y -= 20
        if y < 100:
            c.showPage()
            y = height - 50

    c.save()
    return pdf_path

def send_sms_to_employees(events, maps_link):
    # Tutaj możesz dodać logikę łączenia z JustSend
    # np. wysyłanie listy zadań z linkiem do mapy
    return "SMS wysłane (symulacja)"

def send_email_with_pdf(recipient, pdf_path, maps_link, sms_status):
    msg = EmailMessage()
    msg['Subject'] = '📍 Plan dnia – ENERTIA'
    msg['From'] = 'noreply@enertia.local'
    msg['To'] = recipient
    msg.set_content(f"""Załączony plan dnia w PDF oraz link do trasy:

{maps_link}

Status wysyłki SMS:
{sms_status}
""")

    with open(pdf_path, 'rb') as f:
        msg.add_attachment(f.read(), maintype='application', subtype='pdf', filename='plan_dnia.pdf')

    with smtplib.SMTP('smtp.gmail.com', 587) as smtp:
        smtp.starttls()
        smtp.login(os.getenv("EMAIL_LOGIN"), os.getenv("EMAIL_PASSWORD"))
        smtp.send_message(msg)

@app.route("/generate-route")
def generate_route():
    try:
        events = get_events_for_today()
        if not events:
            return jsonify({"message": "Brak wydarzeń na dziś."}), 200

        addresses = ["Królowej Elżbiety 1A, Świebodzice"]
        for event in events:
            location = event.get("location")
            if location:
                addresses.append(location)
        addresses.append("Królowej Elżbiety 1A, Świebodzice")

        maps_link = generate_maps_link(addresses)
        pdf_path = generate_pdf(events)
        sms_status = send_sms_to_employees(events, maps_link)

        send_email_with_pdf(
            recipient=os.getenv("EMAIL_RECIPIENT"),
            pdf_path=pdf_path,
            maps_link=maps_link,
            sms_status=sms_status
        )

        return jsonify({
            "status": "OK",
            "map_link": maps_link,
            "message": "Plan dnia został wysłany e-mailem oraz SMS-em."
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
