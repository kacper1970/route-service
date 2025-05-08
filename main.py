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
from reportlab.lib.colors import HexColor

app = Flask(__name__)
CORS(app)

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

COLORS = {
    "standard": HexColor("#4CAF50"),  # Zielony
    "urgent": HexColor("#FF9800"),    # Pomarańczowy
    "now": HexColor("#F44336")        # Czerwony
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
    full_url = f"https://www.google.com/maps/dir/{waypoints}"
    response = requests.get(f"https://tinyurl.com/api-create.php?url={full_url}")
    return response.text.strip() if response.ok else full_url

def parse_urgency_from_summary(summary):
    summary = summary.lower()
    if "now" in summary:
        return "now"
    elif "piln" in summary or "urgent" in summary:
        return "urgent"
    return "standard"

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
        summary = event.get("summary", "Brak opisu")
        location = event.get("location", "")
        start = event.get("start", {}).get("dateTime", "")
        start_time = start[11:16] if start else "??:??"
        description = event.get("description", "")
        urgency = parse_urgency_from_summary(summary)

        color = COLORS.get(urgency, HexColor("#000000"))

        # Belka
        c.setFillColor(color)
        c.rect(40, y - 5, 5, 60, fill=1, stroke=0)

        c.setFillColor(color)
        c.setFont("DejaVuSans", 10)
        c.drawString(50, y, f"Typ wizyty: {urgency.upper()}")
        y -= 15

        c.setFillColor(HexColor("#000000"))
        c.setFont("DejaVuSans", 12)
        c.drawString(50, y, f"{start_time} – {summary}")
        y -= 18

        phone_line = next((l for l in description.splitlines() if "Telefon:" in l), "")
        address_line = location if location else "Brak adresu"
        problem_line = next((l for l in description.splitlines() if "Problem:" in l), "")

        c.setFont("DejaVuSans", 10)

        if "Brak" in address_line or address_line.strip() == "":
            c.setFillColor(COLORS["now"])
        else:
            c.setFillColor(HexColor("#000000"))
        c.drawString(60, y, f"📍 Adres: {address_line}")
        y -= 14

        if phone_line:
            c.setFillColor(HexColor("#000000"))
            c.drawString(60, y, f"📞 {phone_line}")
            y -= 14

        if problem_line:
            c.setFillColor(HexColor("#000000"))
            c.drawString(60, y, f"🛠️ {problem_line}")
            y -= 20
        else:
            y -= 10

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
            location = event.get("location")
            if location:
                addresses.append(location)
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
