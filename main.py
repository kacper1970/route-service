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
import re

app = Flask(__name__)
CORS(app)

# Zmienne
token_b64 = os.getenv("GOOGLE_TOKEN_B64")
calendar_id = os.getenv("GOOGLE_CALENDAR_ID")

JUSTSEND_URL = "https://justsend.io/api/sender/singlemessage/send"
APP_KEY = os.getenv("JS_APP_KEY")
SENDER = os.getenv("JS_SENDER", "WEB")
VARIANT = os.getenv("JS_VARIANT", "PRO")

EMAIL_LOGIN = os.getenv("EMAIL_LOGIN")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")

EMPLOYEE_1 = os.getenv("EMPLOYEE_1")
EMPLOYEE_2 = os.getenv("EMPLOYEE_2")

BASE_ADDRESS = "Królowej Elżbiety 1A, Świebodzice"

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
    events = service.events().list(
        calendarId=calendar_id,
        timeMin=start,
        timeMax=end,
        singleEvents=True,
        orderBy='startTime'
    ).execute().get('items', [])
    return events

def generate_maps_link(addresses):
    waypoints = "/".join([addr.replace(" ", "+") for addr in addresses])
    response = requests.get(f"https://tinyurl.com/api-create.php?url=https://www.google.com/maps/dir/{waypoints}")
    return response.text

def extract_phone(description):
    if not description:
        return None
    match = re.search(r'Tel: *(\+?\d+)', description)
    if match:
        return match.group(1)
    return None

def get_color_and_label(summary):
    if summary.startswith("🟢"):
        return colors.green, "STANDARD"
    elif summary.startswith("🟠"):
        return colors.orange, "PILNA"
    elif summary.startswith("🔴"):
        return colors.red, "NATYCHMIASTOWA"
    return colors.gray, "NIEZNANA"

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
        description = event.get("description", "")
        start_time = event.get("start", {}).get("dateTime", "")[11:16]
        phone = extract_phone(description)

        color, label = get_color_and_label(summary)

        # Typ wizyty
        c.setFont("DejaVuSans", 10)
        c.setFillColor(color)
        c.drawString(50, y, f"🔹 Typ wizyty: {label}")
        y -= 10

        # Kolorowa pozioma belka
        c.setFillColor(color)
        c.rect(45, y - 2, 500, 4, fill=1, stroke=0)
        y -= 10

        # Treść zgłoszenia
        c.setFont("DejaVuSans", 12)
        c.setFillColor(colors.black)
        c.drawString(50, y, f"{start_time} – {summary}")
        y -= 20

        c.setFont("DejaVuSans", 10)
        if location:
            c.drawString(60, y, f"📍 {location}")
        else:
            c.setFillColor(colors.red)
            c.drawString(60, y, "❌ Brak lokalizacji")
        y -= 15

        if phone:
            c.setFillColor(colors.black)
            c.drawString(60, y, f"📞 {phone}")
        else:
            c.setFillColor(colors.red)
            c.drawString(60, y, "❌ Brak telefonu")
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
    msg.set_content(f"""
Załączony plan dnia w PDF oraz link do trasy:
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
            if loc:
                addresses.append(loc)
        addresses.append(BASE_ADDRESS)

        maps_link = generate_maps_link(addresses)
        pdf_path = "/tmp/plan_dnia.pdf"
        generate_pdf(events, pdf_path)

        sms_content = "🛠️ Plan dnia ENERTIA:\n"
        for e in events:
            summary = e.get("summary", "")
            location = e.get("location", "")
            time = e.get("start", {}).get("dateTime", "")[11:16]
            sms_content += f"{time} – {summary} ({location})\n"
        sms_content += f"📍 Trasa: {maps_link}"

        sms_status = send_sms_to_employees(sms_content)
        send_email_with_pdf(EMAIL_RECEIVER, pdf_path, maps_link, sms_status)

        return jsonify({"status": "Wysłano SMS i e-mail", "maps_link": maps_link})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
