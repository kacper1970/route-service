import os
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
import datetime
import base64
import pickle
import smtplib
from email.message import EmailMessage
from flask import Flask, jsonify
from flask_cors import CORS
from googleapiclient.discovery import build
from reportlab.pdfgen import canvas
from io import BytesIO
import requests

app = Flask(__name__)
CORS(app)

# Obsługa tokena z GOOGLE_TOKEN_B64
if os.getenv("GOOGLE_TOKEN_B64"):
    token_bytes = base64.b64decode(os.environ["GOOGLE_TOKEN_B64"])
    with open("token.pickle", "wb") as f:
        f.write(token_bytes)

# Dane kalendarza i adresy
CALENDAR_ID = os.getenv("CALENDAR_ID")
START_ADDRESS = "Krolowej Elzbiety 1A, Swiebodzice"

# Funkcja do uzyskania połączenia z Google Calendar
def get_calendar_service():
    if not os.path.exists("token.pickle"):
        raise Exception("Brak tokena. Przejdź do /authorize")
    with open("token.pickle", "rb") as token:
        creds = pickle.load(token)
    return build("calendar", "v3", credentials=creds)

# Pobieranie wydarzeń z dzisiaj
def get_events_for_today():
    service = get_calendar_service()
    now = datetime.datetime.utcnow()
    start = now.replace(hour=0, minute=0, second=0).isoformat() + "Z"
    end = now.replace(hour=23, minute=59, second=59).isoformat() + "Z"

    events_result = service.events().list(
        calendarId=CALENDAR_ID,
        timeMin=start,
        timeMax=end,
        singleEvents=True,
        orderBy="startTime"
    ).execute()
    return events_result.get("items", [])

# Generowanie linku do Google Maps

def generate_maps_link(addresses):
    base = "https://www.google.com/maps/dir/"
    return base + "/".join([addr.replace(" ", "+") for addr in addresses])

# Generowanie PDF z listą wydarzeń
def generate_pdf(events):
    buffer = BytesIO()
    c = canvas.Canvas(buffer)
    c.setFont("Helvetica", 12)
    y = 800
    for event in events:
        start = event['start'].get('dateTime', '')
        location = event.get("location", "Brak adresu")
        summary = event.get("summary", "Brak opisu")
        c.drawString(50, y, f"{start} | {location} | {summary}")
        y -= 20
    c.save()
    buffer.seek(0)
    return buffer.read()

# Wysyłka SMS do pracowników
def send_sms_to_workers(message):
    url = "https://justsend.io/api/sender/singlemessage/send"
    headers = {
        "App-Key": os.getenv("JS_APP_KEY"),
        "Content-Type": "application/json"
    }

    status_report = []
    for var in ["WORKER_1", "WORKER_2"]:
        phone = os.getenv(var)
        if not phone:
            continue
        payload = {
            "sender": os.getenv("JS_SENDER", "ENERTIA"),
            "msisdn": phone,
            "bulkVariant": os.getenv("JS_VARIANT", "PRO"),
            "content": message
        }
        response = requests.post(url, headers=headers, json=payload)
        status = f"{phone}: {response.status_code}"
        status_report.append(status)
    return "\n".join(status_report)

# Wysyłka maila z załącznikiem
def send_email_with_pdf(recipient, pdf_path, maps_link, sms_status):
    msg = EmailMessage()
    msg['Subject'] = '📍 Plan dnia – ENERTIA'
    msg['From'] = 'noreply@enertia.local'
    msg['To'] = recipient
    msg.set_content(f"""
Załączony plan dnia w PDF oraz link do trasy:

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

@app.route("/")
def index():
    return "✅ Route service is running"

@app.route("/generate-route")
def generate_route():
    try:
        events = get_events_for_today()
        if not events:
            return jsonify({"message": "Brak wydarzeń na dziś."}), 200

        addresses = [START_ADDRESS]
        for event in events:
            location = event.get("location")
            if location:
                addresses.append(location)
        addresses.append(START_ADDRESS)

        maps_link = generate_maps_link(addresses)

        # SMS
        sms_message = "\n".join([f"{e['start'].get('dateTime', '')} - {e.get('location', 'Brak adresu')}" for e in events])
        sms_status = send_sms_to_workers(sms_message)

        # PDF
        pdf_data = generate_pdf(events)
        with open("plan_dnia.pdf", "wb") as f:
            f.write(pdf_data)

        # Mail
        send_email_with_pdf(os.getenv("MANAGER_EMAIL"), "plan_dnia.pdf", maps_link, sms_status)

        return jsonify({"status": "OK", "map": maps_link})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
