# route-service/main.py

import os
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
import pickle
import datetime
import smtplib
from email.message import EmailMessage
from flask import Flask, jsonify
from flask_cors import CORS
import requests
import base64
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors

app = Flask(__name__)
CORS(app)

# Zmienne środowiskowe
token_b64 = os.getenv("GOOGLE_TOKEN_B64")
calendar_id = os.getenv("GOOGLE_CALENDAR_ID")
EMAIL_LOGIN = os.getenv("EMAIL_LOGIN")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")
EMPLOYEE_1 = os.getenv("EMPLOYEE_1")
EMPLOYEE_2 = os.getenv("EMPLOYEE_2")
JUSTSEND_URL = "https://justsend.io/api/sender/singlemessage/send"
APP_KEY = os.getenv("JS_APP_KEY")
SENDER = os.getenv("JS_SENDER", "WEB")
VARIANT = os.getenv("JS_VARIANT", "PRO")
BASE_ADDRESS = "Królowej Elżbiety 1A, Świebodzice"

# Kolory pilności
URGENCY_COLORS = {
    "standard": colors.green,
    "urgent": colors.orange,
    "now": colors.red
}

@app.route("/")
def home():
    return "✅ Route service is running"

def get_calendar_service():
    if not token_b64:
        raise Exception("Brak tokena. Przejdź do /authorize")
    token_bytes = base64.b64decode(token_b64)
    creds = pickle.loads(token_bytes)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build('calendar', 'v3', credentials=creds)

def get_events_for_today():
    service = get_calendar_service()
    now = datetime.datetime.utcnow()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat() + 'Z'
    end = now.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat() + 'Z'
    return service.events().list(
        calendarId=calendar_id,
        timeMin=start,
        timeMax=end,
        singleEvents=True,
        orderBy='startTime'
    ).execute().get('items', [])

def generate_maps_link(addresses):
    waypoints = "/".join([addr.replace(" ", "+") for addr in addresses])
    full_url = f"https://www.google.com/maps/dir/{waypoints}"
    try:
        r = requests.get(f"https://tinyurl.com/api-create.php?url={full_url}")
        return r.text if r.status_code == 200 else full_url
    except Exception:
        return full_url

def generate_pdf(events, filepath):
    font_path = os.path.join(os.path.dirname(__file__), "fonts", "DejaVuSans.ttf")
    pdfmetrics.registerFont(TTFont("DejaVuSans", font_path))
    c = canvas.Canvas(filepath, pagesize=A4)
    width, height = A4
    y = height - 50

    c.setFont("DejaVuSans", 16)
    c.drawString(50, y, "🗓️ Plan dnia – ENERTIA")
    y -= 40

    for event in events:
        summary = event.get("summary", "")
        location = event.get("location", "")
        start_time = event.get("start", {}).get("dateTime", "")[11:16]
        urgency = "standard"
        phone = "Brak numeru"

        if "🔥" in summary:
            urgency = "now"
        elif "⚠️" in summary:
            urgency = "urgent"

        if "📞" in event.get("description", ""):
            for line in event["description"].splitlines():
                if "📞" in line:
                    phone = line.replace("📞 Telefon:", "").strip()

        # Kolor belki
        urgency_color = URGENCY_COLORS.get(urgency, colors.black)

        # Typ wizyty
        urgency_label = {
            "standard": "Wizyta standardowa",
            "urgent": "Wizyta pilna",
            "now": "Wizyta natychmiastowa"
        }[urgency]

        # Pasek koloru (poziomy pod nagłówkiem)
        c.setFillColor(urgency_color)
        c.rect(45, y - 5, width - 90, 5, fill=1)
        y -= 15

        # Typ wizyty (tekst)
        c.setFont("DejaVuSans", 10)
        c.setFillColor(urgency_color)
        c.drawString(50, y, urgency_label)
        y -= 15

        # Szczegóły
        c.setFillColor(colors.black)
        c.setFont("DejaVuSans", 12)
        c.drawString(50, y, f"{start_time} – {summary}")
        y -= 20

        c.setFont("DejaVuSans", 10)
        if not location or "Brak" in location:
            c.setFillColor(colors.red)
        c.drawString(60, y, f"📍 {location or 'Brak lokalizacji'}")
        y -= 15

        if not phone or "Brak" in phone:
            c.setFillColor(colors.red)
        else:
            c.setFillColor(colors.black)
        c.drawString(60, y, f"📞 {phone}")
        y -= 30

        if y < 100:
            c.showPage()
            y = height - 50

    c.save()

def send_sms_to_employees(message):
    phones = [EMPLOYEE_1, EMPLOYEE_2]
    status = []
    for phone in phones:
        payload = {
            "sender": SENDER,
            "msisdn": phone,
            "bulkVariant": VARIANT,
            "content": message
        }
        headers = {
            "App-Key": APP_KEY,
            "Content-Type": "application/json"
        }
        response = requests.post(JUSTSEND_URL, json=payload, headers=headers)
        status.append(f"{phone}: {response.status_code}")
    return ", ".join(status)

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
        file_data = f.read()
        filename = f"plan_dnia_{datetime.datetime.now().strftime('%Y-%m-%d')}.pdf"
        msg.add_attachment(file_data, maintype='application', subtype='pdf', filename=filename)

    with smtplib.SMTP('smtp.gmail.com', 587) as smtp:
        smtp.starttls()
        smtp.login(EMAIL_LOGIN, EMAIL_PASSWORD)
        smtp.send_message(msg)

@app.route("/generate-route")
def generate_route():
    try:
        events = get_events_for_today()
        if not events:
            return jsonify({"message": "Brak wydarzeń na dziś."}), 200

        addresses = [BASE_ADDRESS]
        for event in events:
            loc = event.get("location")
            if loc: addresses.append(loc)
        addresses.append(BASE_ADDRESS)

        maps_link = generate_maps_link(addresses)
        pdf_path = "/tmp/plan_dnia.pdf"
        generate_pdf(events, pdf_path)

        sms_text = "🛠️ Plan dnia ENERTIA:\n"
        for e in events:
            summary = e.get("summary", "")
            loc = e.get("location", "")
            hour = e.get("start", {}).get("dateTime", "")[11:16]
            sms_text += f"{hour} – {summary} ({loc})\n"
        sms_text += f"📍 Trasa: {maps_link}"

        sms_status = send_sms_to_employees(sms_text)
        send_email_with_pdf(EMAIL_RECEIVER, pdf_path, maps_link, sms_status)

        return jsonify({"status": "Wysłano SMS i e-mail", "maps_link": maps_link})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
