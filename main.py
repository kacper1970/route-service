import os
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
import pickle
import datetime
import smtplib
import requests
import base64
from email.message import EmailMessage
from flask import Flask, jsonify
from flask_cors import CORS
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors

app = Flask(__name__)
CORS(app)

# Ścieżka do czcionki
FONT_PATH = os.path.join(os.path.dirname(__file__), "fonts", "DejaVuSans.ttf")
pdfmetrics.registerFont(TTFont("DejaVuSans", FONT_PATH))

# Zmienne środowiskowe
token_b64 = os.getenv("GOOGLE_TOKEN_B64")
calendar_id = os.getenv("GOOGLE_CALENDAR_ID")
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
    return service.events().list(
        calendarId=calendar_id,
        timeMin=start,
        timeMax=end,
        singleEvents=True,
        orderBy='startTime'
    ).execute().get('items', [])

def get_urgency(summary):
    if summary.startswith("🔴"):
        return "now"
    elif summary.startswith("🟠"):
        return "urgent"
    else:
        return "standard"

def get_urgency_color(urgency):
    return {
        "now": colors.red,
        "urgent": colors.orange,
        "standard": colors.green,
    }.get(urgency, colors.black)

def generate_maps_link(addresses):
    full_link = "https://www.google.com/maps/dir/" + "/".join(addr.replace(" ", "+") for addr in addresses)
    try:
        res = requests.get(f"http://tinyurl.com/api-create.php?url={full_link}", timeout=5)
        return res.text.strip()
    except:
        return full_link

def generate_pdf(events, filepath):
    c = canvas.Canvas(filepath, pagesize=A4)
    c.setFont("DejaVuSans", 12)
    width, height = A4
    y = height - 50

    c.setFont("DejaVuSans", 16)
    c.drawString(50, y, "🗓️ Plan dnia – ENERTIA")
    y -= 40

    for event in events:
        summary = event.get("summary", "")
        location = event.get("location", "BRAK ADRESU")
        phone = event.get("description", "").split("📞")[-1].splitlines()[0].strip() if "📞" in event.get("description", "") else "BRAK TELEFONU"
        start_time = event.get("start", {}).get("dateTime", "")[11:16]

        urgency = get_urgency(summary)
        urgency_color = get_urgency_color(urgency)

        # Typ wizyty
        c.setFillColor(urgency_color)
        c.setFont("DejaVuSans", 12)
        c.drawString(50, y, f"Typ wizyty: {urgency.upper()}")
        y -= 10

        # Belka pozioma
        c.setFillColor(urgency_color)
        c.rect(50, y, width - 100, 5, fill=True, stroke=False)
        y -= 20

        # Dane
        c.setFont("DejaVuSans", 12)
        c.setFillColor(colors.black)
        c.drawString(50, y, f"{start_time} – {summary}")
        y -= 20

        c.setFont("DejaVuSans", 10)
        c.setFillColor(colors.red if "BRAK" in location.upper() else colors.black)
        c.drawString(60, y, f"📍 {location}")
        y -= 15
        c.setFillColor(colors.red if "BRAK" in phone.upper() else colors.black)
        c.drawString(60, y, f"📞 {phone}")
        y -= 30

        if y < 100:
            c.showPage()
            y = height - 50

    c.save()

def send_sms_to_employees(message):
    phones = [EMPLOYEE_1, EMPLOYEE_2]
    results = []
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
        try:
            r = requests.post("https://justsend.io/api/sender/singlemessage/send", json=payload, headers=headers)
            results.append(f"{phone}: {r.status_code}")
        except:
            results.append(f"{phone}: ERR")
    return ", ".join(results)

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
        msg.add_attachment(f.read(), maintype='application', subtype='pdf',
                           filename=f"plan_dnia_{datetime.datetime.now().date()}.pdf")

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

        sms_body = "🛠️ Plan dnia ENERTIA:\n"
        for e in events:
            summary = e.get("summary", "")
            loc = e.get("location", "Brak")
            time = e.get("start", {}).get("dateTime", "")[11:16]
            sms_body += f"{time} – {summary} ({loc})\n"
        sms_body += f"📍 Trasa: {maps_link}"

        sms_status = send_sms_to_employees(sms_body)
        send_email_with_pdf(EMAIL_RECEIVER, pdf_path, maps_link, sms_status)

        return jsonify({"status": "Wysłano SMS i e-mail", "maps_link": maps_link})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
