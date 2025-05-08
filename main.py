import os
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
import datetime
import pickle
import smtplib
from email.message import EmailMessage
from flask import Flask, jsonify, request
from flask_cors import CORS
from googleapiclient.discovery import build
import google.auth.transport.requests




app = Flask(__name__)
CORS(app)

SCOPES = ['https://www.googleapis.com/auth/calendar']
TOKEN_FILE = 'token.pickle'
CALENDAR_ID = os.getenv("CALENDAR_ID")
START_END_ADDRESS = "Królowej Elżbiety 1A, Świebodzice"

@app.route("/")
def index():
    return "✅ Route service is running"

def get_calendar_service():
    if not os.path.exists(TOKEN_FILE):
        raise Exception("Brak tokena. Przejdź do /authorize")

    with open(TOKEN_FILE, 'rb') as token:
        creds = pickle.load(token)

    if creds.expired and creds.refresh_token:
        creds.refresh(google.auth.transport.requests.Request())
        with open(TOKEN_FILE, 'wb') as token:
            pickle.dump(creds, token)

    return build('calendar', 'v3', credentials=creds)

def get_events_for_today():
    service = get_calendar_service()
    now = datetime.datetime.utcnow()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat() + 'Z'
    end = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat() + 'Z'

    events_result = service.events().list(
        calendarId=CALENDAR_ID,
        timeMin=start,
        timeMax=end,
        singleEvents=True,
        orderBy='startTime'
    ).execute()

    return events_result.get('items', [])

def generate_maps_link(addresses):
    base = "https://www.google.com/maps/dir/"
    return base + "/".join([addr.replace(" ", "+") for addr in addresses])

def generate_daily_pdf(events):
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt="Plan dnia – ENERTIA", ln=True, align='C')
    pdf.ln(10)

    for event in events:
        start = event['start'].get('dateTime', event['start'].get('date'))
        location = event.get("location", "Brak lokalizacji")
        summary = event.get("summary", "Brak opisu")
        pdf.cell(200, 10, txt=f"{start} – {summary} – {location}", ln=True)

    file_path = "/tmp/plan_dnia.pdf"
    pdf.output(file_path)
    return file_path

def send_sms(phone, message):
    import requests

    JUSTSEND_URL = "https://justsend.io/api/sender/singlemessage/send"
    payload = {
        "sender": os.getenv("JS_SENDER", "ENERTIA"),
        "msisdn": phone,
        "bulkVariant": os.getenv("JS_VARIANT", "PRO"),
        "content": message
    }
    headers = {
        "App-Key": os.getenv("JS_APP_KEY"),
        "Content-Type": "application/json"
    }

    response = requests.post(JUSTSEND_URL, json=payload, headers=headers)
    return f"{phone}: {response.status_code}"

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

        addresses = [START_END_ADDRESS]
        for event in events:
            location = event.get("location")
            if location:
                addresses.append(location)
        addresses.append(START_END_ADDRESS)

        maps_link = generate_maps_link(addresses)
        pdf_path = generate_daily_pdf(events)

        sms_message = f"🛠️ Plan dnia ENERTIA\n{datetime.datetime.now().strftime('%Y-%m-%d')}\n\nTrasa: {maps_link}"
        sms_status = []

        employee1 = os.getenv("EMPLOYEE1_PHONE")
        employee2 = os.getenv("EMPLOYEE2_PHONE")

        if employee1:
            sms_status.append(send_sms(employee1, sms_message))
        if employee2:
            sms_status.append(send_sms(employee2, sms_message))

        send_email_with_pdf(os.getenv("EMAIL_REPORT"), pdf_path, maps_link, "\n".join(sms_status))

        return jsonify({
            "status": "OK",
            "maps_link": maps_link,
            "sms_status": sms_status
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
