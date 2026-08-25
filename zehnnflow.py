import os
import json
import uuid
import imaplib
import email
import smtplib
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from datetime import datetime
from getpass import getuser
from email.header import decode_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import fitz
import requests
import webview
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request
from markdown2 import markdown

# Llama Index Imports
from llama_index.core import VectorStoreIndex, Settings
from llama_index.core.readers import SimpleDirectoryReader
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.llms.ollama import Ollama

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

# Loading environment variables
load_dotenv()

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / 'data'
NOTES_DIR = DATA_DIR / 'notes'
TASKS_FILE = BASE_DIR / 'tasks.json'
NOTES_FILE = BASE_DIR / 'notes.json'
TRACKS_FILE = BASE_DIR / 'tracks.json'

DEFAULT_FOCUS_TRACKS = [
    {
        'title': 'Lo-fi radio',
        'url': 'https://www.youtube.com/watch?v=jfKfPfyJRdk',
    },
    {
        'title': 'Nature ambience',
        'url': 'https://www.youtube.com/watch?v=DWcJFNfaw9c',
    },
    {
        'title': 'Deep focus mix',
        'url': 'https://www.youtube.com/watch?v=lTRiuFIWV54',
    },
]

def get_email_credentials():
    email_address = os.getenv('email') or os.getenv('EMAIL_ADDRESS') or ''
    app_password = os.getenv('google') or os.getenv('GOOGLE_APP_PASSWORD') or ''
    return email_address, app_password

# Function to send an email
def send_email(to_email, subject, body):
    try:
        from_email, password = get_email_credentials()
        if not from_email or not password:
            print('Missing email credentials in environment variables.')
            return False

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
        email_address, app_password = get_email_credentials()
        if not email_address or not app_password:
            print('Missing email credentials in environment variables.')
            return None

        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        mail.login(email_address, app_password)
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

def ensure_app_directories():
    DATA_DIR.mkdir(exist_ok=True)
    NOTES_DIR.mkdir(exist_ok=True)

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
def load_tasks():
    try:
        if TASKS_FILE.exists():
            with TASKS_FILE.open('r', encoding='utf-8') as file:
                return json.load(file)
        return []
    except Exception as e:
        print(f"Task loading error: {e}")
        return []

def save_tasks(tasks):
    try:
        with TASKS_FILE.open('w', encoding='utf-8') as file:
            json.dump(tasks, file, indent=2)
    except Exception as e:
        print(f"Task saving error: {e}")

def load_notes():
    try:
        if NOTES_FILE.exists():
            with NOTES_FILE.open('r', encoding='utf-8') as file:
                notes = json.load(file)
                if isinstance(notes, list):
                    return notes
        return []
    except Exception as e:
        print(f"Note loading error: {e}")
        return []

def save_notes(notes):
    try:
        with NOTES_FILE.open('w', encoding='utf-8') as file:
            json.dump(notes, file, indent=2)
    except Exception as e:
        print(f"Note saving error: {e}")

def create_note_record(title, content):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
    cleaned_title = title.strip() or f'Note {timestamp}'
    return {
        'id': uuid.uuid4().hex,
        'title': cleaned_title,
        'content': content.strip(),
        'updated_at': timestamp,
    }

def sync_note_to_dataset(note):
    try:
        ensure_app_directories()
        note_path = NOTES_DIR / f"note_{note['id']}.txt"
        note_text = (
            f"Title: {note['title']}\n"
            f"Updated at: {note['updated_at']}\n\n"
            f"{note['content']}\n"
        )
        note_path.write_text(note_text, encoding='utf-8')
    except Exception as e:
        print(f"Note sync error: {e}")

def remove_note_from_dataset(note_id):
    try:
        note_path = NOTES_DIR / f'note_{note_id}.txt'
        if note_path.exists():
            note_path.unlink()
    except Exception as e:
        print(f"Note removal error: {e}")

def export_notes_markdown(notes):
    if not notes:
        return '# ZehnnFlow Notes\n\nNo notes available.\n'

    sections = ['# ZehnnFlow Notes', '']
    for note in notes:
        sections.append(f"## {note['title']}")
        sections.append(f"_Updated: {note['updated_at']}_")
        sections.append('')
        sections.append(note['content'])
        sections.append('')
    return '\n'.join(sections)

def load_focus_tracks():
    try:
        if TRACKS_FILE.exists():
            with TRACKS_FILE.open('r', encoding='utf-8') as file:
                tracks = json.load(file)
                if isinstance(tracks, list):
                    valid_tracks = [
                        track for track in tracks
                        if isinstance(track, dict) and track.get('url') and track.get('title')
                    ]
                    if valid_tracks:
                        return valid_tracks
    except Exception as e:
        print(f"Track loading error: {e}")
    return DEFAULT_FOCUS_TRACKS

def save_focus_tracks(tracks):
    try:
        with TRACKS_FILE.open('w', encoding='utf-8') as file:
            json.dump(tracks, file, indent=2)
    except Exception as e:
        print(f"Track saving error: {e}")

def get_youtube_embed_url(raw_url):
    parsed_url = urlparse(raw_url)
    host = parsed_url.netloc.lower()
    path = parsed_url.path

    if 'youtu.be' in host:
        video_id = path.strip('/').split('/')[0]
    elif 'youtube.com' in host:
        if path.startswith('/shorts/'):
            video_id = path.split('/shorts/')[1].split('/')[0]
        elif path.startswith('/embed/'):
            video_id = path.split('/embed/')[1].split('/')[0]
        else:
            video_id = parse_qs(parsed_url.query).get('v', [''])[0]
    else:
        return ''

    if not video_id:
        return ''

    return f'https://www.youtube.com/embed/{video_id}'

def resolve_track_metadata(track_url):
    embed_url = get_youtube_embed_url(track_url)
    if yt_dlp is None:
        return {
            'title': 'Custom track',
            'source_url': track_url,
            'embed_url': embed_url,
            'duration': '',
            'uploader': '',
            'stream_url': '',
        }

    ydl_options = {
        'quiet': True,
        'skip_download': True,
        'noplaylist': True,
    }

    with yt_dlp.YoutubeDL(ydl_options) as ydl:
        info = ydl.extract_info(track_url, download=False)
        if 'entries' in info and info['entries']:
            info = info['entries'][0]

        duration = info.get('duration')
        return {
            'title': info.get('title') or 'Custom track',
            'source_url': info.get('webpage_url') or track_url,
            'embed_url': get_youtube_embed_url(info.get('webpage_url') or track_url),
            'duration': f'{duration // 60}:{duration % 60:02d}' if isinstance(duration, int) else '',
            'uploader': info.get('uploader') or '',
            'stream_url': info.get('url') or '',
        }

def sync_all_notes_to_dataset():
    notes_data = load_notes()
    for note in notes_data:
        if note.get('id') and note.get('content'):
            sync_note_to_dataset(note)

# Home route
@app.route('/')
def home():
    username = getuser()
    greeting = get_greeting()
    quote = get_quote()
    tasks = load_tasks()
    notes = load_notes()
    pending_tasks = len(tasks)
    return render_template(
        'index.html',
        username=username,
        greeting=greeting,
        quote=quote,
        tasks=tasks,
        pending_tasks=pending_tasks,
        note_count=len(notes),
    )

# Task routes
@app.route('/add_task', methods=['POST'])
def add_task():
    try:
        task = request.form.get('task', '').strip()
        if not task:
            return jsonify(success=False, error='Task cannot be empty.')

        tasks = load_tasks()
        tasks.append({'text': task, 'completed': False})
        save_tasks(tasks)
        return jsonify(success=True, index=len(tasks) - 1)
    except Exception as e:
        print(f"Add task error: {e}")
        return jsonify(success=False, error='Unable to add task right now.')

@app.route('/toggle_task', methods=['POST'])
def toggle_task():
    try:
        index = int(request.form['index'])
        tasks = load_tasks()
        if index < 0 or index >= len(tasks):
            return jsonify(success=False, error='Task index out of range.')

        tasks[index]['completed'] = not tasks[index]['completed']
        if tasks[index]['completed']:
            del tasks[index]

        save_tasks(tasks)
        return jsonify(success=True)
    except Exception as e:
        print(f"Toggle task error: {e}")
        return jsonify(success=False, error='Unable to update task.')

@app.route('/notes')
def notes():
    notes_data = load_notes()
    notes_sorted = sorted(notes_data, key=lambda item: item.get('updated_at', ''), reverse=True)
    return render_template('notes.html', notes=notes_sorted)

@app.route('/notes/add', methods=['POST'])
def add_note():
    try:
        payload = request.get_json(silent=True) or {}
        title = payload.get('title', '')
        content = payload.get('content', '').strip()

        if not content:
            return jsonify(success=False, error='Note content cannot be empty.')

        note = create_note_record(title, content)
        notes_data = load_notes()
        notes_data.append(note)
        save_notes(notes_data)
        sync_note_to_dataset(note)
        return jsonify(success=True, note=note)
    except Exception as e:
        print(f"Note add error: {e}")
        return jsonify(success=False, error='Unable to save note.')

@app.route('/notes/delete', methods=['POST'])
def delete_note():
    try:
        payload = request.get_json(silent=True) or {}
        note_id = payload.get('note_id', '')
        if not note_id:
            return jsonify(success=False, error='Invalid note id.')

        notes_data = load_notes()
        remaining_notes = [note for note in notes_data if note.get('id') != note_id]
        if len(remaining_notes) == len(notes_data):
            return jsonify(success=False, error='Note not found.')

        save_notes(remaining_notes)
        remove_note_from_dataset(note_id)
        return jsonify(success=True)
    except Exception as e:
        print(f"Note delete error: {e}")
        return jsonify(success=False, error='Unable to delete note.')

@app.route('/notes/import', methods=['POST'])
def import_note():
    try:
        uploaded_file = request.files.get('notes_file')
        if uploaded_file is None or uploaded_file.filename == '':
            return jsonify(success=False, error='Choose a markdown or text file to import.')

        raw_content = uploaded_file.read().decode('utf-8', errors='ignore').strip()
        if not raw_content:
            return jsonify(success=False, error='Imported file is empty.')

        inferred_title = Path(uploaded_file.filename).stem.replace('_', ' ').strip()
        note = create_note_record(inferred_title, raw_content)
        notes_data = load_notes()
        notes_data.append(note)
        save_notes(notes_data)
        sync_note_to_dataset(note)
        return jsonify(success=True, note=note)
    except Exception as e:
        print(f"Note import error: {e}")
        return jsonify(success=False, error='Unable to import note.')

@app.route('/notes/export')
def export_notes():
    notes_data = load_notes()
    markdown_export = export_notes_markdown(notes_data)
    return Response(
        markdown_export,
        mimetype='text/markdown',
        headers={'Content-Disposition': 'attachment; filename=zehnnflow-notes.md'},
    )

@app.route('/focus')
def focus():
    return render_template('focus.html', tracks=load_focus_tracks(), yt_dlp_ready=yt_dlp is not None)

@app.route('/focus/add_track', methods=['POST'])
def add_focus_track():
    try:
        payload = request.get_json(silent=True) or {}
        title = payload.get('title', '').strip()
        url = payload.get('url', '').strip()

        if not title or not url:
            return jsonify(success=False, error='Track title and URL are required.')

        tracks = load_focus_tracks()
        track_exists = any(track.get('url') == url for track in tracks)
        if track_exists:
            return jsonify(success=False, error='That track is already in your quick list.')

        track = {'title': title, 'url': url}
        tracks.append(track)
        save_focus_tracks(tracks)
        return jsonify(success=True, track=track)
    except Exception as e:
        print(f"Track add error: {e}")
        return jsonify(success=False, error='Unable to save track.')

@app.route('/focus/resolve', methods=['POST'])
def resolve_focus_track():
    try:
        payload = request.get_json(silent=True) or {}
        track_url = payload.get('url', '').strip()
        if not track_url:
            return jsonify(success=False, error='Track URL is required.')

        track = resolve_track_metadata(track_url)
        if not track.get('embed_url'):
            return jsonify(
                success=False,
                error='Use a YouTube URL for now so the built-in player can load it.',
            )
        return jsonify(success=True, track=track)
    except Exception as e:
        print(f"Track resolve error: {e}")
        return jsonify(success=False, error='Could not load track metadata.')

# Chat route with robust error handling
@app.route('/chat', methods=['GET', 'POST'])
def chat():
    try:
        if request.method == 'POST':
            messages = []
            user_message = request.form.get('text_input', '').strip()
            if not user_message:
                return render_template(
                    'chat.html',
                    messages=[{'type': 'ai', 'content': 'Type a message to start the conversation.'}],
                    username=getuser(),
                )

            messages.append({'type': 'user', 'content': user_message})
            username = getuser()

            ensure_app_directories()

            # Check if documents exist
            if not DATA_DIR.exists() or not any(DATA_DIR.iterdir()):
                return render_template(
                    'chat.html',
                    messages=[
                        {
                            'type': 'ai',
                            'content': 'No data found. Add files to `data/` or create notes from the Notes tab.',
                        }
                    ],
                    username=username,
                )

            try:
                documents = SimpleDirectoryReader(str(DATA_DIR)).load_data()
            except Exception as e:
                print(f"Document loading error: {e}")
                return render_template(
                    'chat.html',
                    messages=[{'type': 'ai', 'content': f'Error loading documents: {e}'}],
                    username=username,
                )

            # Fallback if no documents
            if not documents:
                return render_template(
                    'chat.html',
                    messages=[{'type': 'ai', 'content': 'No readable documents found.'}],
                    username=username,
                )

            # Configure settings
            Settings.embed_model = HuggingFaceEmbedding(model_name='BAAI/bge-base-en-v1.5')
            Settings.llm = Ollama(model='llama3', request_timeout=360.0)

            # Create index and query
            index = VectorStoreIndex.from_documents(documents)
            query_engine = index.as_query_engine()

            response = query_engine.query(
                f"""Process the following user input using the context documents:
                User query: {user_message}
                Provide a clear, concise response in markdown format."""
            )

            ai_response = markdown(str(response))
            messages.append({'type': 'ai', 'content': ai_response})
            return render_template('chat.html', messages=messages, username=username)

        username = getuser()
        return render_template('chat.html', messages=[], username=username)

    except Exception as e:
        # Log the error and provide a user-friendly message
        print(f"Chat error: {e}")
        return render_template(
            'chat.html',
            messages=[{'type': 'ai', 'content': f'An error occurred: {str(e)}'}],
            username=getuser(),
        )

# Utility functions
def get_greeting():
    now = datetime.now()
    if now.hour < 12:
        return 'Good morning'
    elif 12 <= now.hour < 18:
        return 'Good afternoon'
    return 'Good evening'

def get_quote():
    try:
        response = requests.get('https://zenquotes.io/api/random', timeout=8)
        if response.status_code == 200:
            quote_data = response.json()[0]
            return f"\"{quote_data['q']}\" - {quote_data['a']}"
        return 'Could not retrieve a quote at this time.'
    except Exception as e:
        print(f"Quote retrieval error: {e}")
        return 'Unable to fetch quote'

# Main execution
if __name__ == '__main__':
    # Ensure data and notes directories exist and refresh searchable data.
    ensure_app_directories()
    extract_text_from_pdfs(str(DATA_DIR))
    sync_all_notes_to_dataset()

    # Create webview window
    webview.create_window('ZehnnFlow', app, width=1100, height=820)
    webview.start()