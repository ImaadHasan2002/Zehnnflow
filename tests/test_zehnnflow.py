import imaplib
import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def zf(tmp_path, monkeypatch):
    monkeypatch.setenv('ZEHNNFLOW_HOME', str(tmp_path))
    for var in ('email', 'EMAIL_ADDRESS', 'google', 'GOOGLE_APP_PASSWORD'):
        monkeypatch.delenv(var, raising=False)
    sys.modules.pop('zehnnflow', None)
    module = importlib.import_module('zehnnflow')
    monkeypatch.setattr(module, 'load_dotenv', lambda *a, **k: None, raising=False)
    module.app.config['TESTING'] = True
    yield module
    sys.modules.pop('zehnnflow', None)


@pytest.fixture
def client(zf):
    return zf.app.test_client()


def test_import_is_lightweight_and_web_capable(zf):
    # Importing must not pull in heavy / desktop-only deps.
    for name in ('webview', 'llama_index', 'fitz'):
        assert name not in sys.modules


def test_requirements_has_no_fitz_package():
    lines = Path(__file__).resolve().parent.parent.joinpath('requirements.txt').read_text().splitlines()
    names = [l.split('=')[0].split('>')[0].split('<')[0].strip().lower() for l in lines if l.strip()]
    assert 'fitz' not in names and 'imaplib2' not in names
    assert 'pymupdf' in names


def test_main_web_mode_does_not_need_webview(zf, monkeypatch):
    calls = []
    monkeypatch.setattr(zf, 'run_web', lambda host, port: calls.append((host, port)))
    monkeypatch.setattr(zf, 'run_desktop', lambda: calls.append('desktop'))
    zf.main(['--web', '--port', '8123'])
    assert calls == [('127.0.0.1', 8123)]
    zf.main([])
    assert calls[-1] == 'desktop'
    assert zf.DATA_DIR.exists()


def test_tasks_roundtrip_and_corrupt_file_is_preserved(zf, client):
    assert client.post('/add_task', data={'task': 'write tests'}).json['success']
    assert zf.load_tasks() == [{'text': 'write tests', 'completed': False}]
    assert client.post('/toggle_task', data={'index': '0'}).json['success']
    assert zf.load_tasks() == []

    zf.TASKS_FILE.write_text('{not json')
    assert zf.load_tasks() == []
    assert zf.TASKS_FILE.with_suffix('.json.corrupt').exists()


def test_notes_sync_reconciles_dataset(zf, client):
    note_id = client.post('/notes/add', json={'title': 'A', 'content': 'alpha'}).json['note']['id']
    client.post('/notes/add', json={'title': 'B', 'content': 'beta'})
    files = sorted(p.name for p in zf.NOTES_DIR.glob('note_*.txt'))
    assert len(files) == 2

    # Simulate a reset/copy to another machine: orphan file + missing file.
    (zf.NOTES_DIR / 'note_orphan.txt').write_text('stale')
    (zf.NOTES_DIR / f'note_{note_id}.txt').unlink()
    zf.sync_all_notes_to_dataset()
    assert sorted(p.name for p in zf.NOTES_DIR.glob('note_*.txt')) == files

    # Unchanged notes are not rewritten (keeps the index fingerprint stable).
    before = {p: p.stat().st_mtime_ns for p in zf.NOTES_DIR.glob('note_*.txt')}
    zf.sync_all_notes_to_dataset()
    assert before == {p: p.stat().st_mtime_ns for p in zf.NOTES_DIR.glob('note_*.txt')}

    assert client.post('/notes/delete', json={'note_id': note_id}).json['success']
    assert not (zf.NOTES_DIR / f'note_{note_id}.txt').exists()


def test_pdf_extraction_is_incremental(zf):
    pymupdf = pytest.importorskip('pymupdf')
    zf.ensure_app_directories()
    pdf_path = zf.DATA_DIR / 'doc.pdf'
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), 'hello pdf world')
    doc.save(pdf_path)
    doc.close()

    zf.extract_text_from_pdfs(zf.DATA_DIR)
    txt = zf.DATA_DIR / 'doc.txt'
    assert 'hello pdf world' in txt.read_text()
    mtime = txt.stat().st_mtime_ns
    zf.extract_text_from_pdfs(zf.DATA_DIR)
    assert txt.stat().st_mtime_ns == mtime


def test_chat_empty_state_and_no_global_settings(zf, client):
    response = client.post('/chat', data={'text_input': 'hi'})
    assert b'No data found' in response.data
    assert 'llama_index' not in sys.modules


def test_chat_index_cached_until_files_change(zf, client, monkeypatch):
    built = []
    engine = zf.ChatEngine()

    class FakeIndex:
        def as_query_engine(self, llm):
            return type('QE', (), {'query': staticmethod(lambda q: 'answer')})()

    monkeypatch.setattr(engine, '_get_models', lambda: ('llm', 'embed'))
    fake_modules = {}
    import types
    core = types.ModuleType('llama_index.core')
    core.VectorStoreIndex = type('VSI', (), {
        'from_documents': staticmethod(lambda docs, embed_model: built.append(len(docs)) or FakeIndex())
    })
    readers = types.ModuleType('llama_index.core.readers')
    readers.SimpleDirectoryReader = lambda *a, **k: type('R', (), {'load_data': lambda self: ['doc']})()
    monkeypatch.setitem(sys.modules, 'llama_index', types.ModuleType('llama_index'))
    monkeypatch.setitem(sys.modules, 'llama_index.core', core)
    monkeypatch.setitem(sys.modules, 'llama_index.core.readers', readers)

    zf.ensure_app_directories()
    (zf.DATA_DIR / 'a.txt').write_text('one')
    assert engine.ask('q') == 'answer'
    engine.ask('q')
    assert built == [1]  # second question reused the cached index

    (zf.DATA_DIR / 'b.md').write_text('two')
    engine.ask('q')
    assert len(built) == 2  # new file => rebuilt


def test_email_states(zf, client, monkeypatch):
    page = client.get('/email')
    assert b'Email is not set up yet' in page.data

    monkeypatch.setenv('EMAIL_ADDRESS', 'me@example.com')
    monkeypatch.setenv('GOOGLE_APP_PASSWORD', 'secret')

    class BadIMAP:
        def __init__(self, *a, **k):
            raise imaplib.IMAP4.error('bad creds')

    monkeypatch.setattr(zf.imaplib, 'IMAP4_SSL', BadIMAP)
    assert b'Gmail rejected the login' in client.get('/email').data

    page = client.post('/email', data={'to_email': 'nope', 'subject': 's', 'body': 'b'})
    assert b'valid recipient' in page.data


def test_email_header_and_body_decoding(zf):
    import email as email_pkg
    assert zf.decode_mime_header(None) == ''
    assert zf.decode_mime_header('=?utf-8?q?caf=C3=A9?= <a@b.c>') == 'café <a@b.c>'
    msg = email_pkg.message_from_bytes(
        b'Content-Type: text/plain; charset=latin-1\r\nContent-Transfer-Encoding: 8bit\r\n\r\ncaf\xe9'
    )
    assert zf.extract_email_body(msg) == 'café'


@pytest.mark.parametrize('url,provider', [
    ('https://www.youtube.com/watch?v=abc', 'youtube'),
    ('https://music.youtube.com/watch?v=abc', 'youtube'),
    ('https://youtu.be/abc', 'youtube'),
    ('https://www.youtube.com/live/abc', 'youtube'),
    ('https://soundcloud.com/a/b', 'soundcloud'),
    ('https://open.spotify.com/playlist/xyz', 'spotify'),
    ('https://evil-youtube.com/watch?v=abc', ''),
    ('javascript:alert(1)', ''),
    ('not a url', ''),
])
def test_embed_provider(zf, url, provider):
    assert zf.get_embed_provider(url)[0] == provider


def test_focus_resolve_falls_back_when_metadata_fails(zf, client, monkeypatch):
    class Boom:
        def YoutubeDL(self, *a, **k):
            raise RuntimeError('network down')

    monkeypatch.setattr(zf, 'yt_dlp', Boom())
    data = client.post('/focus/resolve', json={'url': 'https://youtu.be/abc'}).json
    assert data['success'] and data['track']['player_url'].startswith('https://www.youtube.com/embed/abc')
    assert not client.post('/focus/resolve', json={'url': 'https://example.com/x'}).json['success']


def test_default_tracks_not_mutated(zf, client):
    before = len(zf.DEFAULT_FOCUS_TRACKS)
    assert client.post('/focus/add_track', json={'title': 'x', 'url': 'https://youtu.be/zzz'}).json['success']
    assert len(zf.DEFAULT_FOCUS_TRACKS) == before
