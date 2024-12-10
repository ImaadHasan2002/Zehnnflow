import os
import imaplib
import email
import webview
from email.header import decode_header
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from flask import Flask, render_template, request, jsonify
from getpass import getuser
from datetime import datetime
from waitress import serve
from dotenv import load_dotenv
from markdown2 import markdown
import fitz
import requests
import time
import json

# Llama Index Imports
from llama_index.core import VectorStoreIndex, Settings
from llama_index.core.readers import SimpleDirectoryReader
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.llms.ollama import Ollama

# Loading environment variables
load_dotenv()

app = Flask(__name__)

# Function to send an email
def send_email(to_email, subject, body):
    try:
        from_email = os.getenv('email')
        password = os.getenv('google')

        msg = MIMEMultipart()
        msg['From'] = from_email
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(from_email, password)
            server.sendmail(from_email, to_email, msg.as_string())
        
        return True
    except Exception as e:
        print(f"Email sending error: {e}")
        return False

# Route for handling email sending
@app.route('/email', methods=['GET', 'POST'])
def email_route():
    try:
        if request.method == 'POST':
            to_email = request.form['to_email']
            subject = request.form['subject']
            body = request.form['body']
            
            if send_email(to_email, subject, body):
                mail = login_to_email()
                emails = get_latest_emails(mail)
                return render_template('email.html', emails=emails, success=True)
            else:
                return render_template('email.html', error=True)
        
        mail = login_to_email()
        emails = get_latest_emails(mail)
        return render_template('email.html', emails=emails)
    except Exception as e:
        print(f"Email route error: {e}")
        return render_template('email.html', error=True)

# Function to login to email
def login_to_email():
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        mail.login(os.getenv('email'), os.getenv('google'))
        return mail
    except Exception as e:
        print(f"Email login error: {e}")
        return None

# Function to get the latest emails
def get_latest_emails(mail, count=5):
    try:
        if not mail:
            return []
        
        # Specifically search for ONLY flagged (important) emails
        mail.select('INBOX')
        status, flagged_messages = mail.search(None, 'FLAGGED')
        flagged_messages = flagged_messages[0].split()
        
        # If no flagged messages, return empty list
        if not flagged_messages:
            return []

        # Get the last 5 flagged email IDs
        latest_flagged_ids = flagged_messages[-count:] if len(flagged_messages) >= count else flagged_messages

        emails = []
        for email_id in reversed(latest_flagged_ids):  # reversed to get most recent first
            status, msg = mail.fetch(email_id, '(RFC822)')
            raw_email = msg[0][1]
            email_message = email.message_from_bytes(raw_email)
            
            # Decode subject
            subject, encoding = decode_header(email_message['Subject'])[0]
            subject = subject.decode(encoding or 'utf-8') if isinstance(subject, bytes) else subject
            
            # Decode sender
            from_email, encoding = decode_header(email_message['From'])[0]
            from_email = from_email.decode(encoding or 'utf-8') if isinstance(from_email, bytes) else from_email
            
            # Extract body
            body = extract_email_body(email_message)
            
            emails.append({
                'from': from_email, 
                'subject': subject, 
                'body': body,
                'is_important': True  # All emails here are important
            })

        return emails
    except Exception as e:
        print(f"Important email retrieval error: {e}")
        return []

# Helper function to extract email body
def extract_email_body(email_message):
    try:
        body = ""
        if email_message.is_multipart():
            for part in email_message.walk():
                content_type = part.get_content_type()
                if content_type in ['text/plain', 'text/html']:
                    try:
                        body = part.get_payload(decode=True).decode('utf-8')
                        break
                    except Exception as e:
                        print(f"Body decoding error: {e}")
        else:
            try:
                body = email_message.get_payload(decode=True).decode('utf-8')
            except Exception as e:
                print(f"Body decoding error: {e}")
        
        return body
    except Exception as e:
        print(f"Email body extraction error: {e}")
        return ""

# PDF text extraction with error handling
def extract_text_from_pdfs(directory):
    try:
        if not os.path.exists(directory):
            os.makedirs(directory)
            print(f"Created directory: {directory}")
            return

        for filename in os.listdir(directory):
            if filename.endswith('.pdf'):
                try:
                    pdf_path = os.path.join(directory, filename)
                    txt_path = os.path.join(directory, filename.replace('.pdf', '.txt'))
                    
                    with fitz.open(pdf_path) as pdf_document:
                        text = ""
                        for page_num in range(len(pdf_document)):
                            page = pdf_document.load_page(page_num)
                            text += page.get_text()
                    
                    with open(txt_path, 'w', encoding='utf-8') as txt_file:
                        txt_file.write(text)
                    
                    print(f"Extracted text from {filename}")
                except Exception as e:
                    print(f"Error processing {filename}: {e}")
    except Exception as e:
        print(f"PDF extraction error: {e}")

# Task management
TASKS_FILE = 'tasks.json'

def load_tasks():
    try:
        if os.path.exists(TASKS_FILE):
            with open(TASKS_FILE, 'r') as f:
                return json.load(f)
        return []
    except Exception as e:
        print(f"Task loading error: {e}")
        return []

def save_tasks(tasks):
    try:
        with open(TASKS_FILE, 'w') as f:
            json.dump(tasks, f)
    except Exception as e:
        print(f"Task saving error: {e}")

# Home route
@app.route('/')
def home():
    username = getuser()
    greeting = get_greeting()
    quote = get_quote()
    tasks = load_tasks()
    return render_template('index.html', username=username, greeting=greeting, quote=quote, tasks=tasks)

# Task routes
@app.route('/add_task', methods=['POST'])
def add_task():
    try:
        task = request.form['task']
        tasks = load_tasks()
        tasks.append({'text': task, 'completed': False})
        save_tasks(tasks)
        return jsonify(success=True)
    except Exception as e:
        print(f"Add task error: {e}")
        return jsonify(success=False)

@app.route('/toggle_task', methods=['POST'])
def toggle_task():
    try:
        index = int(request.form['index'])
        tasks = load_tasks()
        tasks[index]['completed'] = not tasks[index]['completed']
        
        if tasks[index]['completed']:
            del tasks[index]
        
        save_tasks(tasks)
        return jsonify(success=True)
    except Exception as e:
        print(f"Toggle task error: {e}")
        return jsonify(success=False)

# Chat route with robust error handling
@app.route('/chat', methods=['GET', 'POST'])
def chat():
    try:
        if request.method == 'POST':
            messages = []
            user_message = request.form['text_input']
            messages.append({'type': 'user', 'content': user_message})
            username = getuser()
            
            # Check if documents exist
            if not os.path.exists("data") or not os.listdir("data"):
                return render_template('chat.html', 
                                       messages=[{'type': 'ai', 'content': 'No documents found in the data directory.'}], 
                                       username=username)

            try:
                documents = SimpleDirectoryReader("data").load_data()
            except Exception as e:
                print(f"Document loading error: {e}")
                return render_template('chat.html', 
                                       messages=[{'type': 'ai', 'content': f'Error loading documents: {e}'}], 
                                       username=username)

            # Fallback if no documents
            if not documents:
                return render_template('chat.html', 
                                       messages=[{'type': 'ai', 'content': 'No readable documents found.'}], 
                                       username=username)

            # Configure settings
            Settings.embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-base-en-v1.5")
            Settings.llm = Ollama(model="llama3", request_timeout=360.0)

            # Create index and query
            index = VectorStoreIndex.from_documents(documents)
            query_engine = index.as_query_engine()
            
            response = query_engine.query(f"""Process the following user input using the context documents:
                                          User query: {user_message}
                                          Provide a clear, concise response in markdown format.""")
            
            ai_response = markdown(str(response))
            messages.append({'type': 'ai', 'content': ai_response})
            return render_template('chat.html', messages=messages, username=username)
        
        else:
            username = getuser()
            return render_template('chat.html', messages=[], username=username)
    
    except Exception as e:
        # Log the error and provide a user-friendly message
        print(f"Chat error: {e}")
        return render_template('chat.html', 
                               messages=[{'type': 'ai', 'content': f'An error occurred: {str(e)}'}], 
                               username=getuser())

# Utility functions
def get_greeting():
    now = datetime.now()
    if now.hour < 12:
        return "Good morning"
    elif 12 <= now.hour < 18:
        return "Good afternoon"
    else:
        return "Good evening"

def get_quote():
    try:
        response = requests.get('https://zenquotes.io/api/random')
        if response.status_code == 200:
            quote_data = response.json()[0]
            return f"\"{quote_data['q']}\" - {quote_data['a']}"
        else:
            return "Could not retrieve a quote at this time."
    except Exception as e:
        print(f"Quote retrieval error: {e}")
        return "Unable to fetch quote"

# Main execution
if __name__ == '__main__':
    # Ensure data directory exists and extract PDFs
    if not os.path.exists("data"):
        os.makedirs("data")
    extract_text_from_pdfs("data")

    # Create webview window
    webview.create_window("ZehnnFlow", app, width=1000, height=800)
    webview.start()