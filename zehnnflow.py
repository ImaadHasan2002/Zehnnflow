import argparse
import email
import imaplib
import json
import os
import smtplib
import tempfile
import threading
import time
import uuid
from datetime import datetime
from email.header import decode_header, make_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from getpass import getuser
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import requests
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request
from markdown2 import markdown
from markupsafe import escape

# Heavy / optional dependencies (llama_index, pymupdf, pywebview) are imported
# lazily inside the functions that need them, so importing this module (for a
# web deployment or tests) stays fast and does not require every extra.

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

# Loading environment variables
load_dotenv()

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
# Where user data lives. Defaults to the project folder; override with
# ZEHNNFLOW_HOME to keep data elsewhere (hosting, tests).
HOME_DIR = Path(os.getenv('ZEHNNFLOW_HOME') or BASE_DIR).resolve()
DATA_DIR = HOME_DIR / 'data'
NOTES_DIR = DATA_DIR / 'notes'
TASKS_FILE = HOME_DIR / 'tasks.json'
NOTES_FILE = HOME_DIR / 'notes.json'
TRACKS_FILE = HOME_DIR / 'tracks.json'

# Guards read-modify-write cycles on the JSON stores (waitress is multi-threaded).
STORE_LOCK = threading.RLock()

LLM_MODEL = os.getenv('ZEHNNFLOW_LLM_MODEL', 'llama3')
EMBED_MODEL = os.getenv('ZEHNNFLOW_EMBED_MODEL', 'BAAI/bge-base-en-v1.5')
# Only these file types are indexed; PDFs are indexed through their extracted
# .txt twin, so they are never embedded twice.
INDEXED_EXTENSIONS = ('.txt', '.md')

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

class EmailError(Exception):
    """An email problem with a message that is safe to show to the user."""

MISSING_CREDENTIALS_MESSAGE = (
    'Email is not set up yet. Add EMAIL_ADDRESS and GOOGLE_APP_PASSWORD '
    '(a Gmail app password) to your .env file, then restart ZehnnFlow.'
)

# Function to send an email
def send_email(to_email, subject, body):
    """Send a message through Gmail SMTP. Raises EmailError with a friendly message."""
    from_email, password = get_email_credentials()
    if not from_email or not password:
        raise EmailError(MISSING_CREDENTIALS_MESSAGE)

    msg = MIMEMultipart()
    msg['From'] = from_email
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    try:
        with smtplib.SMTP('smtp.gmail.com', 587, timeout=15) as server:
            server.starttls()
            server.login(from_email, password)
            server.sendmail(from_email, to_email, msg.as_string())
    except smtplib.SMTPAuthenticationError:
        raise EmailError('Gmail rejected the login. Check that you are using an app password, not your normal password.')
    except smtplib.SMTPRecipientsRefused:
        raise EmailError('The recipient address was refused. Check the "To" address.')
    except (smtplib.SMTPException, OSError) as e:
        print(f"Email sending error: {e}")
        raise EmailError('Could not reach Gmail to send the message. Check your connection and retry.')

# Function to login to email
def login_to_email():
    """Open an IMAP session. Raises EmailError with a friendly message."""
    email_address, app_password = get_email_credentials()
    if not email_address or not app_password:
        raise EmailError(MISSING_CREDENTIALS_MESSAGE)

    try:
        mail = imaplib.IMAP4_SSL('imap.gmail.com', 993, timeout=15)
        mail.login(email_address, app_password)
        return mail
    except imaplib.IMAP4.error:
        raise EmailError('Gmail rejected the login. Check that IMAP is enabled and that you are using an app password.')
    except OSError as e:
        print(f"Email login error: {e}")
        raise EmailError('Could not reach Gmail. Check your connection and retry.')

def decode_mime_header(value):
    """Decode an RFC 2047 header (all encoded words) to text; tolerate missing headers."""
    if not value:
        return ''
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return str(value)

def get_latest_emails(mail, count=5):
    """Return the most recent flagged emails, newest first. Raises EmailError on IMAP failure."""
    try:
        mail.select('INBOX', readonly=True)
        status, flagged_messages = mail.search(None, 'FLAGGED')
        if status != 'OK':
            raise EmailError('Gmail could not search your inbox.')

        flagged_ids = flagged_messages[0].split()
        emails = []
        for email_id in reversed(flagged_ids[-count:]):  # newest first
            status, msg = mail.fetch(email_id, '(RFC822)')
            if status != 'OK' or not msg or not msg[0]:
                continue
            email_message = email.message_from_bytes(msg[0][1])
            emails.append({
                'from': decode_mime_header(email_message['From']),
                'subject': decode_mime_header(email_message['Subject']) or '(no subject)',
                'body': extract_email_body(email_message),
                'is_important': True,
            })
        return emails
    except EmailError:
        raise
    except (imaplib.IMAP4.error, OSError) as e:
        print(f"Important email retrieval error: {e}")
        raise EmailError('Could not read your inbox right now. Retry in a moment.')

INBOX_CACHE_SECONDS = 60
_inbox_cache = {'at': 0.0, 'emails': None}
_inbox_lock = threading.Lock()

def fetch_inbox(force=False):
    """Return (emails, error_message), cached for INBOX_CACHE_SECONDS.

    Only successful fetches are cached, so an error is retried on the next visit.
    ``force=True`` (the Refresh button) bypasses the cache.
    """
    with _inbox_lock:
        fresh = time.monotonic() - _inbox_cache['at'] < INBOX_CACHE_SECONDS
        if not force and fresh and _inbox_cache['emails'] is not None:
            return _inbox_cache['emails'], None

        try:
            mail = login_to_email()
        except EmailError as e:
            return [], str(e)
        try:
            emails = get_latest_emails(mail)
        except EmailError as e:
            return [], str(e)
        finally:
            try:
                mail.logout()
            except Exception:
                pass

        _inbox_cache.update(at=time.monotonic(), emails=emails)
        return emails, None

# Helper function to extract email body
def extract_email_body(email_message):
    """Prefer the text/plain part; fall back to text/html. Uses the part's own charset."""
    def decode_part(part):
        payload = part.get_payload(decode=True)
        if payload is None:
            return ''
        return payload.decode(part.get_content_charset() or 'utf-8', errors='replace')

    try:
        parts = email_message.walk() if email_message.is_multipart() else [email_message]
        fallback = ''
        for part in parts:
            content_type = part.get_content_type()
            if part.get_content_disposition() == 'attachment':
                continue
            if content_type == 'text/plain':
                return decode_part(part)
            if content_type == 'text/html' and not fallback:
                fallback = decode_part(part)
        return fallback
    except Exception as e:
        print(f"Email body extraction error: {e}")
        return ''

# Route for handling email sending
@app.route('/email', methods=['GET', 'POST'])
def email_route():
    context = {}
    if request.method == 'POST':
        to_email = request.form.get('to_email', '').strip()
        subject = request.form.get('subject', '').strip()
        body = request.form.get('body', '')
        if not to_email or '@' not in to_email or not subject or not body.strip():
            context['send_error'] = 'Fill in a valid recipient, a subject and a message.'
        else:
            try:
                send_email(to_email, subject, body)
                context['success'] = True
            except EmailError as e:
                context['send_error'] = str(e)

    emails, inbox_error = fetch_inbox(force=request.args.get('refresh') == '1')
    return render_template('email.html', emails=emails, inbox_error=inbox_error, **context)

def ensure_app_directories():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    NOTES_DIR.mkdir(parents=True, exist_ok=True)

# PDF text extraction with error handling
def extract_text_from_pdfs(directory):
    """Extract each PDF to a sibling .txt file, skipping PDFs whose .txt is already current."""
    try:
        import pymupdf  # PyMuPDF >= 1.24.3 (the old `fitz` name is only an alias)
    except ImportError:
        print('PyMuPDF is not installed; skipping PDF extraction.')
        return

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for pdf_path in sorted(p for p in directory.rglob('*') if p.suffix.lower() == '.pdf'):
        txt_path = pdf_path.with_suffix('.txt')
        try:
            if txt_path.exists() and txt_path.stat().st_mtime >= pdf_path.stat().st_mtime:
                continue
            with pymupdf.open(pdf_path) as pdf_document:
                text = ''.join(page.get_text() for page in pdf_document)
            txt_path.write_text(text, encoding='utf-8')
            print(f"Extracted text from {pdf_path.name}")
        except Exception as e:
            print(f"Error processing {pdf_path.name}: {e}")

# JSON stores (tasks, notes, tracks)
def read_json_list(path, label):
    try:
        if path.exists():
            with path.open('r', encoding='utf-8') as file:
                data = json.load(file)
            if isinstance(data, list):
                return data
            print(f"{label} file is not a list; ignoring it.")
    except json.JSONDecodeError as e:
        # Keep the unreadable file so the user's data is not silently overwritten.
        backup = path.with_suffix(path.suffix + '.corrupt')
        try:
            os.replace(path, backup)
        except OSError:
            pass
        print(f"{label} file is corrupt ({e}); moved to {backup.name}")
    except Exception as e:
        print(f"{label} loading error: {e}")
    return []

def write_json_atomic(path, data, label):
    """Write via a temp file + rename so a crash can never leave a half-written file."""
    tmp_name = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            'w', encoding='utf-8', dir=path.parent, prefix=path.name, suffix='.tmp', delete=False
        ) as tmp:
            tmp_name = tmp.name
            json.dump(data, tmp, indent=2)
        os.replace(tmp_name, path)
        return True
    except Exception as e:
        print(f"{label} saving error: {e}")
        if tmp_name and os.path.exists(tmp_name):
            os.unlink(tmp_name)
        return False

# Task management
def load_tasks():
    return read_json_list(TASKS_FILE, 'Task')

def save_tasks(tasks):
    return write_json_atomic(TASKS_FILE, tasks, 'Task')

def load_notes():
    return read_json_list(NOTES_FILE, 'Note')

def save_notes(notes):
    return write_json_atomic(NOTES_FILE, notes, 'Note')

def create_note_record(title, content):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
    cleaned_title = title.strip() or f'Note {timestamp}'
    return {
        'id': uuid.uuid4().hex,
        'title': cleaned_title,
        'content': content.strip(),
        'updated_at': timestamp,
    }

def render_note_text(note):
    return (
        f"Title: {note['title']}\n"
        f"Updated at: {note['updated_at']}\n\n"
        f"{note['content']}\n"
    )

def sync_note_to_dataset(note):
    """Write a note's text twin; leaves the file (and its mtime) alone if unchanged."""
    try:
        ensure_app_directories()
        note_path = NOTES_DIR / f"note_{note['id']}.txt"
        note_text = render_note_text(note)
        if note_path.exists() and note_path.read_text(encoding='utf-8') == note_text:
            return
        note_path.write_text(note_text, encoding='utf-8')
    except Exception as e:
        print(f"Note sync error: {e}")

def append_note(note):
    """Persist a note to notes.json and its dataset twin; True on success."""
    with STORE_LOCK:
        notes_data = load_notes()
        notes_data.append(note)
        if not save_notes(notes_data):
            return False
        sync_note_to_dataset(note)
    return True

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
    valid_tracks = [
        track for track in read_json_list(TRACKS_FILE, 'Track')
        if isinstance(track, dict) and track.get('url') and track.get('title')
    ]
    # Copy the defaults so callers can append without mutating the module constant.
    return valid_tracks or [dict(track) for track in DEFAULT_FOCUS_TRACKS]

def save_focus_tracks(tracks):
    return write_json_atomic(TRACKS_FILE, tracks, 'Track')

YOUTUBE_HOSTS = ('youtube.com', 'youtu.be', 'youtube-nocookie.com')

def host_matches(host, domain):
    return host == domain or host.endswith('.' + domain)

def get_youtube_embed_url(raw_url):
    parsed_url = urlparse(raw_url)
    host = (parsed_url.hostname or '').lower()
    path = parsed_url.path

    if not any(host_matches(host, domain) for domain in YOUTUBE_HOSTS):
        return ''

    if host_matches(host, 'youtu.be'):
        video_id = path.strip('/').split('/')[0]
    else:
        for prefix in ('/shorts/', '/embed/', '/live/'):
            if path.startswith(prefix):
                video_id = path[len(prefix):].split('/')[0]
                break
        else:
            video_id = parse_qs(parsed_url.query).get('v', [''])[0]

    if not video_id:
        return ''

    return f'https://www.youtube.com/embed/{video_id}'

def get_embed_provider(raw_url):
    """Return (provider, player_url) for a supported link, or ('', '') if unsupported."""
    parsed_url = urlparse(raw_url)
    if parsed_url.scheme not in ('http', 'https'):
        return '', ''

    host = (parsed_url.hostname or '').lower()
    youtube_embed = get_youtube_embed_url(raw_url)
    if youtube_embed:
        return 'youtube', f'{youtube_embed}?autoplay=1&rel=0'

    if host_matches(host, 'soundcloud.com'):
        return 'soundcloud', f'https://w.soundcloud.com/player/?url={quote(raw_url, safe="")}&auto_play=true'

    if host_matches(host, 'spotify.com') and parsed_url.path.strip('/'):
        return 'spotify', f'https://open.spotify.com/embed/{parsed_url.path.strip("/")}'

    return '', ''

def resolve_track_metadata(track_url):
    """Build track info. Metadata (title, duration) is best-effort and never blocks playback."""
    provider, player_url = get_embed_provider(track_url)
    track = {
        'title': 'Custom track',
        'provider': provider,
        'source_url': track_url,
        'embed_url': get_youtube_embed_url(track_url) or player_url,
        'player_url': player_url,
        'duration': '',
        'uploader': '',
        'stream_url': '',
    }
    if yt_dlp is None or not provider:
        return track

    ydl_options = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'noplaylist': True,
        'socket_timeout': 10,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_options) as ydl:
            info = ydl.extract_info(track_url, download=False)
        if info and info.get('entries'):
            info = info['entries'][0]
        if not info:
            return track

        duration = info.get('duration')
        track.update({
            'title': info.get('title') or track['title'],
            'duration': f'{int(duration) // 60}:{int(duration) % 60:02d}' if isinstance(duration, (int, float)) else '',
            'uploader': info.get('uploader') or '',
            'stream_url': info.get('url') or '',
        })
    except Exception as e:
        # Network issue, private video, rate limit...: the embed can still play.
        print(f"Track metadata lookup failed, falling back to plain embed: {e}")
    return track

def sync_all_notes_to_dataset():
    """Make data/notes mirror notes.json exactly: add/update missing files, drop orphans.

    notes.json is the source of truth, so a reset, a copy to another machine or a
    hand-deleted file always converges to the same indexed content.
    """
    ensure_app_directories()
    with STORE_LOCK:
        notes_data = [note for note in load_notes() if isinstance(note, dict) and note.get('id') and note.get('content')]
    expected = {f"note_{note['id']}.txt" for note in notes_data}
    for note in notes_data:
        sync_note_to_dataset(note)
    for stale_path in NOTES_DIR.glob('note_*.txt'):
        if stale_path.name not in expected:
            try:
                stale_path.unlink()
            except OSError as e:
                print(f"Stale note removal error: {e}")

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

        with STORE_LOCK:
            tasks = load_tasks()
            tasks.append({'text': task, 'completed': False})
            if not save_tasks(tasks):
                return jsonify(success=False, error='Unable to add task right now.')
        return jsonify(success=True, index=len(tasks) - 1)
    except Exception as e:
        print(f"Add task error: {e}")
        return jsonify(success=False, error='Unable to add task right now.')

@app.route('/toggle_task', methods=['POST'])
def toggle_task():
    try:
        index = int(request.form['index'])
        with STORE_LOCK:
            tasks = load_tasks()
            if index < 0 or index >= len(tasks):
                return jsonify(success=False, error='Task index out of range.')

            tasks[index]['completed'] = not tasks[index]['completed']
            if tasks[index]['completed']:
                del tasks[index]

            if not save_tasks(tasks):
                return jsonify(success=False, error='Unable to update task.')
        return jsonify(success=True)
    except Exception as e:
        print(f"Toggle task error: {e}")
        return jsonify(success=False, error='Unable to update task.')

@app.route('/update_task', methods=['POST'])
def update_task():
    try:
        index = int(request.form['index'])
        text = request.form.get('text', '').strip()
        if not text:
            return jsonify(success=False, error='Task cannot be empty.')

        with STORE_LOCK:
            tasks = load_tasks()
            if index < 0 or index >= len(tasks):
                return jsonify(success=False, error='Task index out of range.')
            tasks[index]['text'] = text
            if not save_tasks(tasks):
                return jsonify(success=False, error='Unable to update task.')
        return jsonify(success=True, text=text)
    except Exception as e:
        print(f"Update task error: {e}")
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
        if not append_note(note):
            return jsonify(success=False, error='Unable to save note.')
        return jsonify(success=True, note=note)
    except Exception as e:
        print(f"Note add error: {e}")
        return jsonify(success=False, error='Unable to save note.')

@app.route('/notes/update', methods=['POST'])
def update_note():
    try:
        payload = request.get_json(silent=True) or {}
        note_id = payload.get('note_id', '')
        title = str(payload.get('title', '')).strip()
        content = str(payload.get('content', '')).strip()
        if not note_id:
            return jsonify(success=False, error='Invalid note id.')
        if not content:
            return jsonify(success=False, error='Note content cannot be empty.')

        with STORE_LOCK:
            notes_data = load_notes()
            note = next((item for item in notes_data if item.get('id') == note_id), None)
            if note is None:
                return jsonify(success=False, error='Note not found.')

            note['title'] = title or note.get('title') or 'Untitled note'
            note['content'] = content
            note['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M')
            if not save_notes(notes_data):
                return jsonify(success=False, error='Unable to save note.')
            sync_note_to_dataset(note)
        return jsonify(success=True, note=note)
    except Exception as e:
        print(f"Note update error: {e}")
        return jsonify(success=False, error='Unable to save note.')

@app.route('/notes/delete', methods=['POST'])
def delete_note():
    try:
        payload = request.get_json(silent=True) or {}
        note_id = payload.get('note_id', '')
        if not note_id:
            return jsonify(success=False, error='Invalid note id.')

        with STORE_LOCK:
            notes_data = load_notes()
            remaining_notes = [note for note in notes_data if note.get('id') != note_id]
            if len(remaining_notes) == len(notes_data):
                return jsonify(success=False, error='Note not found.')

            if not save_notes(remaining_notes):
                return jsonify(success=False, error='Unable to delete note.')
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
        if not append_note(note):
            return jsonify(success=False, error='Unable to import note.')
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

UNSUPPORTED_TRACK_MESSAGE = (
    'That link is not supported. Paste a full https:// YouTube, SoundCloud or Spotify link.'
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
        if not get_embed_provider(url)[0]:
            return jsonify(success=False, error=UNSUPPORTED_TRACK_MESSAGE)

        with STORE_LOCK:
            tracks = load_focus_tracks()
            track_exists = any(track.get('url') == url for track in tracks)
            if track_exists:
                return jsonify(success=False, error='That track is already in your quick list.')

            track = {'title': title, 'url': url}
            tracks.append(track)
            if not save_focus_tracks(tracks):
                return jsonify(success=False, error='Unable to save track.')
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

        if not get_embed_provider(track_url)[0]:
            return jsonify(success=False, error=UNSUPPORTED_TRACK_MESSAGE)

        return jsonify(success=True, track=resolve_track_metadata(track_url))
    except Exception as e:
        print(f"Track resolve error: {e}")
        return jsonify(success=False, error='Could not load track metadata.')

class ChatUnavailable(Exception):
    """The chat cannot answer yet; the message is safe to show to the user."""

class ChatEngine:
    """Owns the LLM, embedding model and vector index for the whole process.

    * Models are created once, on first use, and passed explicitly to llama_index
      instead of mutating the global ``Settings`` singleton, so concurrent
      requests cannot race on shared state.
    * The index is cached and only rebuilt when the indexed files change.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._llm = None
        self._embed_model = None
        self._index = None
        self._fingerprint = None

    def _get_models(self):
        if self._llm is None or self._embed_model is None:
            from llama_index.embeddings.huggingface import HuggingFaceEmbedding
            from llama_index.llms.ollama import Ollama

            self._embed_model = HuggingFaceEmbedding(model_name=EMBED_MODEL)
            self._llm = Ollama(model=LLM_MODEL, request_timeout=360.0)
        return self._llm, self._embed_model

    @staticmethod
    def dataset_fingerprint():
        """A cheap signature (path, size, mtime) of every indexable file."""
        if not DATA_DIR.exists():
            return ()
        return tuple(sorted(
            (path.relative_to(DATA_DIR).as_posix(), path.stat().st_size, path.stat().st_mtime_ns)
            for path in DATA_DIR.rglob('*')
            if path.is_file() and path.suffix.lower() in INDEXED_EXTENSIONS
        ))

    def prepare_dataset(self):
        """Bring derived files (PDF text, note text) up to date before indexing."""
        ensure_app_directories()
        extract_text_from_pdfs(DATA_DIR)
        sync_all_notes_to_dataset()

    def get_index(self):
        with self._lock:
            self.prepare_dataset()
            fingerprint = self.dataset_fingerprint()
            if not fingerprint:
                self._index, self._fingerprint = None, None
                raise ChatUnavailable(
                    'No data found. Add .txt, .md or .pdf files to `data/` or create notes from the Notes tab.'
                )
            if self._index is not None and fingerprint == self._fingerprint:
                return self._index

            from llama_index.core import VectorStoreIndex
            from llama_index.core.readers import SimpleDirectoryReader

            try:
                documents = SimpleDirectoryReader(
                    str(DATA_DIR), recursive=True, required_exts=list(INDEXED_EXTENSIONS)
                ).load_data()
            except Exception as e:
                print(f"Document loading error: {e}")
                raise ChatUnavailable('Could not read the files in `data/`. Check the server log for details.')
            if not documents:
                raise ChatUnavailable('No readable documents found.')

            _, embed_model = self._get_models()
            self._index = VectorStoreIndex.from_documents(documents, embed_model=embed_model)
            self._fingerprint = fingerprint
            return self._index

    def ask(self, user_message):
        index = self.get_index()
        llm, _ = self._get_models()
        query_engine = index.as_query_engine(llm=llm)
        response = query_engine.query(
            f"""Process the following user input using the context documents:
            User query: {user_message}
            Provide a clear, concise response in markdown format."""
        )
        return str(response)

chat_engine = ChatEngine()

# Chat route
@app.route('/chat', methods=['GET', 'POST'])
def chat():
    username = getuser()
    if request.method != 'POST':
        return render_template('chat.html', messages=[], username=username)

    user_message = request.form.get('text_input', '').strip()
    if not user_message:
        return render_template(
            'chat.html',
            messages=[{'type': 'ai', 'content': 'Type a message to start the conversation.'}],
            username=username,
        )

    messages = [{'type': 'user', 'content': user_message}]
    try:
        messages.append({'type': 'ai', 'content': markdown(chat_engine.ask(user_message))})
    except ChatUnavailable as e:
        messages.append({'type': 'ai', 'content': str(escape(e))})
    except Exception as e:
        print(f"Chat error: {e}")
        messages.append({
            'type': 'ai',
            'content': 'The assistant could not answer. Make sure Ollama is running with the '
                       f'`{escape(LLM_MODEL)}` model pulled, then try again.',
        })
    return render_template('chat.html', messages=messages, username=username)

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

def run_desktop():
    """Open the app in a native pywebview window (the default experience)."""
    try:
        import webview
    except ImportError:
        print('pywebview is not installed; falling back to web mode. Install it for the desktop window.')
        return run_web()

    webview.create_window('ZehnnFlow', app, width=1100, height=820)
    webview.start()

def run_web(host='127.0.0.1', port=5000):
    """Serve the app over HTTP with waitress (falls back to Flask's dev server)."""
    print(f'ZehnnFlow running at http://{host}:{port}')
    try:
        from waitress import serve
    except ImportError:
        app.run(host=host, port=port)
    else:
        serve(app, host=host, port=port)

def main(argv=None):
    parser = argparse.ArgumentParser(description='ZehnnFlow productivity suite')
    parser.add_argument('--web', action='store_true', help='serve over HTTP instead of opening a desktop window')
    parser.add_argument('--host', default='127.0.0.1', help='web mode: interface to bind (default 127.0.0.1)')
    parser.add_argument('--port', type=int, default=5000, help='web mode: port to listen on (default 5000)')
    args = parser.parse_args(argv)

    # Startup stays light: only create folders. PDF extraction, note syncing and
    # indexing happen lazily on the first chat request.
    ensure_app_directories()
    if args.web:
        run_web(args.host, args.port)
    else:
        run_desktop()

if __name__ == '__main__':
    main()
