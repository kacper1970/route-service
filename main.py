import os
import pickle
import datetime
import requests
import smtplib
from email.message import EmailMessage
from flask import Flask, jsonify
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from jinja2 import Template
from fpdf import FPDF

# Konfiguracja Flask
app = Flask(__name__)

# Wymagane zmienne środowiskowe
GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID")
TOKEN_FILE = "token.pickle"
JS_APP_KEY = os.getenv("JS_APP_KEY")
JS_SENDER = os.getenv("JS_SENDER", "ENERTIA")
JS_VARIANT = os.getenv("JS_VARIANT", "PRO")
EMPLOYEE_NUMBERS = os.getenv("EMPLOYEE_NUMBERS", "").split(",")
EMAIL_RECIPIENT = os.getenv("EMAIL_RECIPIENT")

JUSTSEND_URL = "https://justsend.io/api/sender/singlemessage/send"

# Funkcja uzyskująca połączenie z Google Calendar
def get_calendar_service():
    if not os.path.exists(TOKEN_FILE):
        raise Exception("Brak tokena. Uwierzytelnij się przez /authorize w calendar-service.")

    with open(TOKEN_FILE, 'rb') as token:
        creds = pickle.load(token)

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_FILE, 'wb') as token:
            pickle.dump(creds, token)

    return build('calendar', 'v3', credentials=creds)

# Funkcja do pobierania wydarzeń z danego dnia
def get_events_for_today():
    service = get_calendar_service()
    now = datetime.datetime.utcnow()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat() + 'Z'
    end = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat() + 'Z'

    events_result = service.events().list(
        calendarId=GOOGLE_CALENDAR_ID,
        timeMin=start,
        timeMax=end,
        singleEvents=True,
        orderBy='startTime'
    ).execute()

    return events_result.get('items', [])

# Funkcja do generowania linku do Google Maps (optymalna trasa)
def generate_maps_link(addresses):
    base = "https://www.google.com/maps/dir/"
    return base + "/".join([addr.replace(" ", "+") for addr in addresses])

# Funkcja wysyłająca SMS
def send_sms(phone, message):
    payload = {
        "sender": JS_SENDER,
        "msisdn": phone,
        "bulkVariant": JS_VARIANT,
        "content": message
    }
    headers = {
        "App-Key": JS_APP_KEY,
        "Content-Type": "application/json"
    }
    return requests.post(JUSTSEND_URL, json=payload, headers=headers)

# Funkcja tworząca PDF z planem dnia
class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 12)
        self.cell(0, 10, 'Plan dnia – Wizyty ENERTIA', 0, 1, 'C')
        self.ln(10)

    def chapter_body(self, events):
        self.set_font('Arial', '', 11)
        for event in events:
            self.cell(0, 10, f"{event['start']['dateTime'][11:16]} – {event.get('summary', 'Brak tytułu')}", ln=True)
            location = event.get('location', 'Brak adresu')
            self.set_font('Arial', 'I', 10)
            self.cell(0, 10, f"Adres: {location}", ln=True)
            self.ln(5)

    def generate(self, events, filename):
        self.add_page()
        self.chapter_body(events)
        self.output(filename)

# Funkcja wysyłająca e-mail z PDF

def send_email_with_pdf(recipient, pdf_path, maps_link, sms_status):
    msg = EmailMessage()
    msg['Subject'] = '📍 Plan dnia – ENERTIA'
    msg['From'] = 'noreply@enertia.local'
    msg['To'] = recipient
    msg.set_content(f"Załączony plan dnia w PDF oraz link do trasy:

{maps_link}

Status wysyłki SMS:
{sms_status}")

    with open(pdf_path, 'rb') as f:
        file_data = f.read()
        msg.add_attachment(file_data, maintype='application', subtype='pdf', filename='plan_dnia.pdf')

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

        # Wysyłka SMS do pracowników
        summary = "Plan dnia ENERTIA:\n" + "\n".join([f"{e['start']['dateTime'][11:16]} – {e.get('location', '-')[:30]}" for e in events])
        summary += f"\nMapa: {maps_link}"

        sms_report = ""
        for number in EMPLOYEE_NUMBERS:
            resp = send_sms(number.strip(), summary)
            sms_report += f"{number.strip()}: {resp.status_code}\n"

        # Tworzenie PDF
        pdf = PDF()
        pdf_path = "/tmp/plan_dnia.pdf"
        pdf.generate(events, pdf_path)

        # Wysyłka e-mail
        send_email_with_pdf(EMAIL_RECIPIENT, pdf_path, maps_link, sms_report)

        return jsonify({"status": "OK", "message": "Plan dnia wygenerowany i wysłany."})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))

