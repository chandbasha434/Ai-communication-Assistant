#!/usr/bin/env python3

import os
import requests
import json
import re
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import firebase_admin
from firebase_admin import firestore, credentials
from datetime import datetime, timezone
import random
from dotenv import load_dotenv
import smtplib
from email.message import EmailMessage
from email.utils import parseaddr
from sentence_transformers import SentenceTransformer
import chromadb
from chromadb.utils import embedding_functions

# Load environment variables from the .env file
load_dotenv()

# --- Flask and CORS setup ---
app = Flask(__name__, static_folder='static', static_url_path='/static')
CORS(app)

# --- Firebase Admin SDK Initialization ---
try:
    if not firebase_admin._apps:
        firebase_config_str = os.getenv('__firebase_config')
        if firebase_config_str:
            firebase_config = json.loads(firebase_config_str)
            cred = credentials.Certificate(firebase_config)
            firebase_admin.initialize_app(cred)
        else:
            raise FileNotFoundError("Firebase credentials not found.")

    db = firestore.client()
    app_id = os.getenv('__app_id', 'default-app-id')
    print("Firebase Admin SDK initialized successfully.")
except Exception as e:
    print(f"Error initializing Firebase Admin SDK: {e}")
    db = None
    app_id = 'default-app-id'

# --- Google Gemini API configuration ---
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-05-20:generateContent"
API_KEY = os.getenv("API_KEY", "")

# --- Email Sending Configuration ---
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER", "your-email@gmail.com")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "your-app-password")

def send_email_response(to_email, subject, body):
    """Sends an email using SMTP."""
    try:
        # Extract just the email address from the "To" string to prevent header errors.
        _, to_address = parseaddr(to_email)

        msg = EmailMessage()
        msg.set_content(body)
        msg['Subject'] = f"RE: {subject}"
        msg['From'] = SMTP_USER
        msg['To'] = to_address

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        print(f"Email sent to {to_email}")
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False

# --- RAG System Implementation with ChromaDB and Firestore ---
class RAGSystem:
    def __init__(self):
        self.chroma_client = chromadb.Client()
        self.embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
        self.collection = self.chroma_client.get_or_create_collection("knowledge_base", embedding_function=self.embedding_function)
        self.load_knowledge_base_from_firestore()

    def load_knowledge_base_from_firestore(self):
        try:
            self.chroma_client.delete_collection(name="knowledge_base")
        except:
            pass
        self.collection = self.chroma_client.get_or_create_collection("knowledge_base", embedding_function=self.embedding_function)

        knowledge_base_ref = db.collection(f"artifacts/{app_id}/knowledge_base")
        docs = knowledge_base_ref.stream()
        
        doc_contents = []
        doc_ids = []
        for doc in docs:
            data = doc.to_dict()
            doc_contents.append(data.get('content'))
            doc_ids.append(doc.id)
        
        if doc_contents:
            self.collection.add(
                documents=doc_contents,
                ids=doc_ids
            )
        print("Knowledge base loaded into ChromaDB from Firestore.")

    def retrieve_context(self, query):
        results = self.collection.query(
            query_texts=[query],
            n_results=1
        )
        if results and 'documents' in results and len(results['documents']) > 0 and len(results['documents'][0]) > 0:
            return results['documents'][0][0]
        return ""

rag_system = RAGSystem()

# --- Helper Functions ---
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
        
        Your entire response MUST be the JSON object. Do not include any other text, markdown, or explanation.
        """
        
        headers = { 'Content-Type': 'application/json' }
        payload = { "contents": [{ "parts": [{"text": prompt}] }] }
        
        response = requests.post(f"{GEMINI_API_URL}?key={API_KEY}", headers=headers, data=json.dumps(payload))
        response.raise_for_status()
        result = response.json()
        
        extracted_text = result['candidates'][0]['content']['parts'][0]['text']
        
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

def generate_ai_response(email_body, sentiment):
    """
    Generates an AI-powered draft response using the Gemini API and RAG.
    """
    try:
        retrieved_context = rag_system.retrieve_context(email_body)
        
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

# --- API Endpoints ---
@app.route('/')
def serve_index():
    return send_from_directory('.', 'index.html')

@app.route('/seed_emails', methods=['POST'])
def seed_emails():
    """
    Endpoint to seed the database with mock emails.
    """
    if db is None:
        return jsonify({"status": "error", "message": "Database not initialized."}), 500
    
    user_id = 'example-user-id'
    collection_ref = db.collection(f"artifacts/{app_id}/users/{user_id}/emails")
    
    try:
        existing_docs = collection_ref.limit(1).get()
        if len(existing_docs) > 0:
            return jsonify({"status": "error", "message": "Database already seeded."}), 409

        # --- USING THE FULL SPREADSHEET DATA ---
        MOCK_EMAILS = [
            {
                "sender": "eve@startup.io",
                "subject": "Help required with account verification",
                "body": "Do you support integration with third-party APIs? Specifically, I'm looking for CRM integration options.",
                "timestamp": datetime(2025, 8, 19, 0, 58, 9),
            },
            {
                "sender": "diana@client.co",
                "subject": "General query about subscription",
                "body": "Hi team, I am unable to log into my account since yesterday. Could you please help me resolve this issue?",
                "timestamp": datetime(2025, 8, 25, 0, 58, 9),
            },
            {
                "sender": "eve@startup.io",
                "subject": "Immediate support needed for billing error",
                "body": "Hello, I wanted to understand the pricing tiers better. Could you share a detailed breakdown?",
                "timestamp": datetime(2025, 8, 20, 12, 58, 9),
            },
            {
                "sender": "alice@example.com",
                "subject": "Urgent request: system access blocked",
                "body": "Hi team, I am unable to log into my account since yesterday. Could you please help me resolve this issue?",
                "timestamp": datetime(2025, 8, 21, 21, 58, 9),
            },
            {
                "sender": "eve@startup.io",
                "subject": "Question: integration with API",
                "body": "Despite multiple attempts, I cannot reset my password. The reset link doesn't seem to work.",
                "timestamp": datetime(2025, 8, 20, 4, 58, 9),
            },
            {
                "sender": "alice@example.com",
                "subject": "Critical help needed for downtime",
                "body": "Hi team, I am unable to log into my account since yesterday. Could you please help me resolve this issue?",
                "timestamp": datetime(2025, 8, 18, 0, 58, 9),
            },
            {
                "sender": "diana@client.co",
                "subject": "Help required with account verification",
                "body": "There is a billing error where I was charged twice. This needs immediate correction.",
                "timestamp": datetime(2025, 8, 20, 19, 58, 9),
            },
            {
                "sender": "alice@example.com",
                "subject": "Support needed for login issue",
                "body": "I am facing issues with verifying my account. The verification email never arrived. Can you assist?",
                "timestamp": datetime(2025, 8, 23, 6, 58, 9),
            },
            {
                "sender": "alice@example.com",
                "subject": "General query about subscription",
                "body": "Our servers are down, and we need immediate support. This is highly critical.",
                "timestamp": datetime(2025, 8, 26, 2, 58, 9),
            },
            {
                "sender": "eve@startup.io",
                "subject": "Help required with account verification",
                "body": "Do you support integration with third-party APIs? Specifically, I'm looking for CRM integration options.",
                "timestamp": datetime(2025, 8, 21, 13, 58, 9),
            },
            {
                "sender": "diana@client.co",
                "subject": "Support needed for login issue",
                "body": "Hi team, I am unable to log into my account since yesterday. Could you please help me resolve this issue?",
                "timestamp": datetime(2025, 8, 26, 13, 58, 9),
            },
            {
                "sender": "alice@example.com",
                "subject": "Help required with account verification",
                "body": "Do you support integration with third-party APIs? Specifically, I'm looking for CRM integration options.",
                "timestamp": datetime(2025, 8, 24, 5, 58, 9),
            },
            {
                "sender": "eve@startup.io",
                "subject": "Critical help needed for downtime",
                "body": "Our servers are down, and we need immediate support. This is highly critical.",
                "timestamp": datetime(2025, 8, 21, 19, 58, 9),
            },
            {
                "sender": "alice@example.com",
                "subject": "Query about product pricing",
                "body": "There is a billing error where I was charged twice. This needs immediate correction.",
                "timestamp": datetime(2025, 8, 24, 13, 58, 9),
            },
            {
                "sender": "diana@client.co",
                "subject": "General query about subscription",
                "body": "I am facing issues with verifying my account. The verification email never arrived. Can you assist?",
                "timestamp": datetime(2025, 8, 26, 1, 58, 9),
            },
            {
                "sender": "alice@example.com",
                "subject": "Immediate support needed for billing error",
                "body": "Despite multiple attempts, I cannot reset my password. The reset link doesn't seem to work.",
                "timestamp": datetime(2025, 8, 19, 7, 58, 9),
            },
            {
                "sender": "charlie@partner.org",
                "subject": "Help required with account verification",
                "body": "This is urgent -- our system is completely inaccessible, and this is affecting our operations.",
                "timestamp": datetime(2025, 8, 18, 0, 58, 9),
            },
            {
                "sender": "diana@client.co",
                "subject": "Request for refund process clarification",
                "body": "Could you clarify the steps involved in requesting a refund? I submitted one last week but have no update.",
                "timestamp": datetime(2025, 8, 22, 17, 58, 9),
            },
            {
                "sender": "eve@startup.io",
                "subject": "Query about product pricing",
                "body": "Our servers are down, and we need immediate support. This is highly critical.",
                "timestamp": datetime(2025, 8, 22, 9, 58, 9),
            },
            {
                "sender": "bob@customer.com",
                "subject": "Urgent request: system access blocked",
                "body": "Despite multiple attempts, I cannot reset my password. The reset link doesn't seem to work.",
                "timestamp": datetime(2025, 8, 22, 13, 58, 9),
            }
        ]

        for email in MOCK_EMAILS:
            extracted_info = analyze_and_extract_email_info(email["body"])
            ai_response = generate_ai_response(email["body"], extracted_info['sentiment'])
            
            doc_data = {
                "sender": email["sender"],
                "subject": email["subject"],
                "body": email["body"],
                "timestamp": email["timestamp"],
                "status": "pending",
                "extractedInfo": extracted_info,
                "aiResponse": ai_response
            }
            collection_ref.add(doc_data)
        
        KNOWLEDGE_BASE_DOCS = [
            {"content": "Our service supports a wide range of third-party CRM integrations, including Salesforce, HubSpot, and Zoho. You can find detailed documentation in our API guide."},
            {"content": "For password reset issues, please ensure you are using the correct email address. If the link is not working, try clearing your browser's cache or using an incognito window."},
            {"content": "We offer several pricing tiers. The Basic plan is free, the Pro plan is $25/month, and the Enterprise plan is custom-priced. Please visit our website for a complete breakdown of features."},
            {"content": "For billing inquiries or errors, please contact our billing team at billing@example.com or call us at 1-800-555-1234. We'll be happy to assist you."},
            {"content": "If you are experiencing a system outage or downtime, our technical team is on standby. Please provide a detailed description of the issue and your account ID so we can escalate it immediately."}
        ]
        
        knowledge_base_ref = db.collection(f"artifacts/{app_id}/knowledge_base")
        for doc in KNOWLEDGE_BASE_DOCS:
            knowledge_base_ref.add(doc)
        
        rag_system.load_knowledge_base_from_firestore()

        print("Database seeded with mock emails and knowledge base.")
        return jsonify({"status": "success", "message": "Database seeded with mock emails and knowledge base."})
    except Exception as e:
        print(f"Failed to seed database: {e}")
        return jsonify({"status": "error", "message": "Failed to seed database."}), 500


@app.route('/fetch_emails', methods=['GET'])
def fetch_emails():
    """
    Fetches emails from Firestore and sends them to the frontend, sorted by priority.
    """
    if db is None:
        return jsonify({"status": "error", "message": "Database not initialized."}), 500
    
    user_id = 'example-user-id'
    
    try:
        emails_ref = db.collection(f"artifacts/{app_id}/users/{user_id}/emails")
        docs = emails_ref.stream()
        emails_list = []
        for doc in docs:
            email_data = doc.to_dict()
            email_data['id'] = doc.id
            if 'timestamp' in email_data and not isinstance(email_data['timestamp'], str):
                email_data['timestamp'] = email_data['timestamp'].isoformat()
            emails_list.append(email_data)
        
        def sort_key(email):
            priority_order = {'urgent': 2, 'not urgent': 1}
            priority_score = priority_order.get(email.get('extractedInfo', {}).get('priority', 'not urgent'), 0)
            timestamp_value = datetime.fromisoformat(email['timestamp']).timestamp()
            return (priority_score, -timestamp_value)

        emails_list.sort(key=sort_key, reverse=True)
            
        return jsonify(emails_list)
    except Exception as e:
        print(f"Error fetching emails from Firestore: {e}")
        return jsonify({"status": "error", "message": "Failed to fetch emails."}), 500


@app.route('/generate_response', methods=['POST'])
def generate_response_api():
    """
    Generates an AI response on demand.
    """
    try:
        data = request.json
        email_body = data.get("email_body", "")
        # First, extract info to get sentiment for context in response generation
        extracted_info = analyze_and_extract_email_info(email_body)
        response_text = generate_ai_response(email_body, extracted_info['sentiment'])
        return jsonify({"status": "success", "ai_response": response_text})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
        

@app.route('/update_email_status', methods=['POST'])
def update_email_status():
    """
    Sends the email response and updates the status of an email in Firestore.
    """
    if db is None:
        return jsonify({"status": "error", "message": "Database not initialized."}), 500

    try:
        data = request.json
        email_id = data.get("email_id")
        final_response = data.get("final_response")
        user_id = 'example-user-id'
        
        doc_ref = db.collection(f"artifacts/{app_id}/users/{user_id}/emails").document(email_id)
        email_doc = doc_ref.get().to_dict()
        
        if not email_doc:
            return jsonify({"status": "error", "message": "Email not found."}), 404

        success = send_email_response(email_doc['sender'], email_doc['subject'], final_response)
        
        if success:
            doc_ref.update({"status": "resolved", "finalResponse": final_response})
            return jsonify({"status": "success", "message": "Email status updated and response sent."})
        else:
            return jsonify({"status": "error", "message": "Failed to send email."}), 500
            
    except Exception as e:
        print(f"Failed to update email status or send email: {e}")
        return jsonify({"status": "error", "message": "Failed to update email status."}), 500


@app.route('/update_knowledge_base', methods=['POST'])
def update_knowledge_base_api():
    """Updates the RAG knowledge base from the frontend."""
    if db is None:
        return jsonify({"status": "error", "message": "Database not initialized."}), 500
    
    try:
        data = request.json
        doc_id = data.get("id")
        content = data.get("content")
        
        if not doc_id or not content:
            return jsonify({"status": "error", "message": "Missing document ID or content."}), 400
        
        doc_ref = db.collection(f"artifacts/{app_id}/knowledge_base").document(doc_id)
        doc_ref.set({"content": content})
        
        rag_system.load_knowledge_base_from_firestore()
        
        return jsonify({"status": "success", "message": "Knowledge base updated successfully."})
    except Exception as e:
        print(f"Failed to update knowledge base: {e}")
        return jsonify({"status": "error", "message": "Failed to update knowledge base."}), 500


# --- Main block to run the Flask app ---
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))