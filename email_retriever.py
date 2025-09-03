#!/usr/bin/env python3

# This script fetches and processes support emails from an IMAP server.
# It runs in a continuous loop to provide dynamic, real-time-like behavior.

import firebase_admin
from firebase_admin import firestore
from firebase_admin import credentials
from datetime import datetime, timezone
import os
import imaplib
import email
from email.header import decode_header
from email.utils import parseaddr # Added for safe email header parsing
import requests
import json
import re # Added for robust JSON parsing
from dotenv import load_dotenv
import time

# Load environment variables
load_dotenv()

# --- Firebase Admin SDK Initialization ---
try:
    if not firebase_admin._apps:
        firebase_config = os.getenv('__firebase_config', '{}')
        if firebase_config:
            cred_dict = json.loads(firebase_config)
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initializeApp()
    db = firestore.client()
    app_id = os.getenv('__app_id', 'default-app-id')
    user_id = 'example-user-id'
    print("Firebase Admin SDK initialized successfully.")
except Exception as e:
    print(f"Error initializing Firebase Admin SDK: {e}")
    db = None
    app_id = 'default-app-id'
    user_id = 'example-user-id'

# --- Google Gemini API configuration ---
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-05-20:generateContent"
API_KEY = os.getenv("API_KEY", "")

# --- Email Retrieval Configuration ---
IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.gmail.com")
IMAP_PORT = int(os.getenv("IMAP_PORT", 993))
IMAP_USER = os.getenv("IMAP_USER", "your-email@gmail.com")
IMAP_PASSWORD = os.getenv("IMAP_PASSWORD", "your-app-password")

# --- Helper Functions (re-used from app.py) ---
def analyze_and_extract_email_info(email_body):
    """
    Uses the Gemini API to analyze the email and extract structured information for support tickets.
    """
    try:
        prompt = f"""
        Analyze the following customer support email and extract key information into a JSON object.
        Provide a concise, 1-2 sentence summary of the customer's request.
        Determine the sentiment and priority of the email.
        
        Strictly follow this JSON structure:
        {{
          "customer_name": "string (customer's name, e.g., Jane Doe, or 'Unknown')",
          "request_summary": "a short summary of the customer's issue or request",
          "sentiment": "positive" | "negative" | "neutral",
          "priority": "urgent" | "not urgent" (based on keywords like 'immediately', 'critical', 'cannot access'),
          "contact_details": "string or 'N/A' if not found"
        }}
        
        Email: {email_body}
        
        JSON:
        """
        headers = { 'Content-Type': 'application/json' }
        payload = { "contents": [{ "parts": [{"text": prompt}] }] }
        response = requests.post(f"{GEMINI_API_URL}?key={API_KEY}", headers=headers, data=json.dumps(payload))
        response.raise_for_status()
        
        extracted_text = response.json()['candidates'][0]['content']['parts'][0]['text']
        
        # --- MODIFICATION START ---
        # Use regex to find the first JSON object in the text.
        json_match = re.search(r'\{.*\}', extracted_text, re.DOTALL)
        if json_match:
            json_string = json_match.group(0)
            extracted_json = json.loads(json_string)
            return extracted_json
        else:
            print(f"No JSON object found in AI output. Raw output: '{extracted_text}'")
            return {
                "customer_name": "N/A",
                "request_summary": "Failed to generate summary.",
                "sentiment": "neutral",
                "priority": "not urgent",
                "contact_details": "N/A"
            }
        # --- MODIFICATION END ---
    except json.JSONDecodeError as e:
        print(f"JSON parsing failed: {e}. Raw AI output: '{extracted_text}'")
        return {
            "customer_name": "N/A",
            "request_summary": "Failed to generate summary.",
            "sentiment": "neutral",
            "priority": "not urgent",
            "contact_details": "N/A"
        }
    except Exception as e:
        print(f"Extraction API request failed: {e}")
        return {
            "customer_name": "N/A",
            "request_summary": "Failed to generate summary.",
            "sentiment": "neutral",
            "priority": "not urgent",
            "contact_details": "N/A"
        }

def retrieve_context(query):
    # In the full application, this would use a vector DB. For this retriever, a simple mock is fine.
    query = query.lower()
    retrieved_info = []
    MOCK_KNOWLEDGE_BASE = {
        "password_reset": "To reset your password, please go to the login page and click 'Forgot Password'. Follow the on-screen instructions.",
        "billing_issue": "We recommend checking your credit card details or contacting your bank for a declined transaction. You can also try a different payment method.",
        "general_inquiry": "Our support team is happy to help with any questions you may have. Please provide more details about your issue."
    }

    if "password" in query or "log in" in query or "access" in query:
        retrieved_info.append(MOCK_KNOWLEDGE_BASE["password_reset"])
    if "billing" in query or "credit card" in query or "declined" in query:
        retrieved_info.append(MOCK_KNOWLEDGE_BASE["billing_issue"])

    return " ".join(retrieved_info) if retrieved_info else MOCK_KNOWLEDGE_BASE["general_inquiry"]


def generate_ai_response(email_body, sentiment):
    """
    Generates an AI-powered draft response using the Gemini API and RAG.
    """
    try:
        retrieved_context = retrieve_context(email_body)

        empathetic_opening = ""
        if sentiment == 'negative':
            empathetic_opening = "I'm so sorry to hear about the issue you're facing. "

        prompt = f"""
        You are an AI-powered customer support assistant. Draft a professional, polite, and helpful response to the customer email.
        **Instructions:**
        - Maintain a professional and friendly tone.
        - Start with an empathetic acknowledgement if the sentiment is negative.
        - Use the provided knowledge base context to generate a relevant answer.
        - If the context doesn't contain the answer, state that you will investigate. Do not fabricate information.

        **Customer Email:**
        {email_body}

        **Knowledge Base Context:**
        {retrieved_context}

        **Draft Response:**
        """
        headers = { 'Content-Type': 'application/json' }
        payload = { "contents": [{ "parts": [{"text": prompt}] }] }
        response = requests.post(f"{GEMINI_API_URL}?key={API_KEY}", headers=headers, data=json.dumps(payload))
        response.raise_for_status()
        result = response.json()
        generated_text = result['candidates'][0]['content']['parts'][0]['text']
        return generated_text
    except Exception as e:
        print(f"Generation API request failed: {e}")
        return "AI is unable to generate a response at this time. Please try again later."


def fetch_emails_from_server():
    """Fetches emails from the IMAP server."""
    emails_list = []
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        mail.login(IMAP_USER, IMAP_PASSWORD)
        mail.select("inbox")

        status, messages = mail.search(None, '(UNSEEN)')
        message_ids = messages[0].split()

        for msg_id in message_ids:
            status, data = mail.fetch(msg_id, "(RFC822)")
            raw_email = data[0][1]
            msg = email.message_from_bytes(raw_email)

            sender_name, sender_email = decode_header(msg.get("From"))[0]
            if isinstance(sender_name, bytes):
                sender_name = sender_name.decode()

            subject = decode_header(msg.get("Subject"))[0][0]
            if isinstance(subject, bytes):
                subject = subject.decode()

            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    content_disposition = str(part.get("Content-Disposition"))
                    if content_type == "text/plain" and "attachment" not in content_disposition:
                        body = part.get_payload(decode=True).decode()
                        break
            else:
                body = msg.get_payload(decode=True).decode()

            emails_list.append({
                "sender": f"{sender_name} <{sender_email}>",
                "subject": subject,
                "body": body,
                "timestamp": datetime.now(timezone.utc),
                "status": "pending"
            })

            mail.store(msg_id, '+FLAGS', '\\Seen')

    except Exception as e:
        print(f"Failed to fetch emails from server: {e}")
    finally:
        if 'mail' in locals():
            mail.logout()

    return emails_list

def email_retriever(request):
    """
    Fetches emails, processes them with AI, and saves them to Firestore.
    """
    if db is None:
        return {"status": "error", "message": "Database not initialized."}, 500

    new_emails = fetch_emails_from_server()
    if not new_emails:
        return {"status": "success", "message": "No new emails to process."}

    new_emails_count = 0

    for email_data in new_emails:
        subject = email_data["subject"].lower()

        # --- UPDATED FILTERING LOGIC ---
        if any(keyword in subject for keyword in ["support", "query", "request", "help", "critical", "urgent"]):

            extracted_info = analyze_and_extract_email_info(email_data["body"])
            ai_response = generate_ai_response(email_data["body"], extracted_info['sentiment'])

            doc_data = {
                "sender": email_data["sender"],
                "subject": email_data["subject"],
                "body": email_data["body"],
                "timestamp": datetime.now(timezone.utc),
                "status": "pending",
                "extractedInfo": extracted_info,
                "aiResponse": ai_response
            }

            try:
                collection_ref = db.collection(f"artifacts/{app_id}/users/{user_id}/emails")
                collection_ref.add(doc_data)
                new_emails_count += 1
                print(f"Added email from {email_data['sender']} to Firestore.")
            except Exception as e:
                print(f"Failed to add document to Firestore: {e}")

    return {"status": "success", "message": f"Processed {new_emails_count} new emails."}


def main():
    """Main function to run the email retriever continuously."""
    # This is a key part of the dynamic behavior.
    # In a real-world app, this would be a scheduled Cloud Function.
    while True:
        print("Checking for new emails...")
        # The request argument is not used in this local version, so we pass None.
        email_retriever(None)
        print("Sleeping for 5 seconds...")
        time.sleep(5)

if __name__ == "__main__":
    # We check for an environment variable to decide whether to run the Flask app or the retriever.
    # In a production environment, they would be separate services.
    if os.getenv("FLASK_RUNNING"):
        app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
    else:
        main()