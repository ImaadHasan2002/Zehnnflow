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


def add(client, text):
    return client.post('/add_task', data={'task': text}).json['task']['id']


def test_tasks_complete_archive_restore_clear(zf, client):
    a, b = add(client, 'a'), add(client, 'b')
    assert client.post('/toggle_task', data={'id': a}).json['completed'] is True
    payload = client.get('/tasks').json
    assert [t['id'] for t in payload['open']] == [b]
    assert [t['id'] for t in payload['completed']] == [a]
    assert payload['completed'][0]['completed_at']

    assert client.post('/toggle_task', data={'id': a}).json['completed'] is False   # restore
    assert [t['id'] for t in client.get('/tasks').json['open']] == [b, a]

    client.post('/toggle_task', data={'id': a})
    assert client.post('/clear_completed').json['removed'] == 1
    assert [t['id'] for t in zf.load_tasks()] == [b]


def test_task_ids_prevent_wrong_task_from_two_windows(zf, client):
    a, _, c = add(client, 'a'), add(client, 'b'), add(client, 'c')
    client.post('/toggle_task', data={'id': a})            # window 1 completes "a"
    client.post('/toggle_task', data={'id': c})            # window 2 (stale) completes "c"
    assert [t['text'] for t in zf.load_tasks() if not t['completed']] == ['b']
    assert not client.post('/toggle_task', data={'id': 'gone'}).json['success']


def test_reorder_tasks(zf, client):
    a, b, c = add(client, 'a'), add(client, 'b'), add(client, 'c')
    client.post('/toggle_task', data={'id': b})
    assert client.post('/reorder_tasks', json={'ids': [c, a]}).json['success']
    assert [t['id'] for t in client.get('/tasks').json['open']] == [c, a]
    assert [t['id'] for t in client.get('/tasks').json['completed']] == [b]   # archive untouched
    # stale or malformed orders are rejected, not applied
    assert not client.post('/reorder_tasks', json={'ids': [c]}).json['success']
    assert not client.post('/reorder_tasks', json={'ids': [c, a, b]}).json['success']
    assert not client.post('/reorder_tasks', json={'ids': [c, c]}).json['success']
    assert not client.post('/reorder_tasks', json={}).json['success']
    assert [t['id'] for t in client.get('/tasks').json['open']] == [c, a]


def test_legacy_tasks_without_ids_are_migrated_once(zf):
    zf.TASKS_FILE.write_text('[{"text": "old task", "completed": false}, {"nope": 1}]')
    first = zf.load_tasks()
    assert len(first) == 1 and first[0]['id']
    assert zf.load_tasks()[0]['id'] == first[0]['id']          # persisted, stable
    assert zf.json.loads(zf.TASKS_FILE.read_text())[0]['id'] == first[0]['id']


def test_corrupt_tasks_file_is_preserved(zf):
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
    response = client.post('/chat', data={'text_input': 'hi'}, follow_redirects=True)
    assert b'No data found' in response.data
    assert 'llama_index' not in sys.modules


def test_chat_index_cached_until_files_change(zf, client, monkeypatch):
    built = []
    engine = zf.ChatEngine()

    class FakeIndex:
        def as_query_engine(self, llm):
            return type('QE', (), {'query': staticmethod(lambda q: 'answer')})()

    monkeypatch.setattr(engine, '_get_models', lambda: ('llm', 'embed'))
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


def test_update_task(zf, client):
    task_id = add(client, 'old')
    assert client.post('/update_task', data={'id': task_id, 'text': ' new '}).json['text'] == 'new'
    assert zf.load_tasks()[0]['text'] == 'new'
    assert not client.post('/update_task', data={'id': task_id, 'text': '  '}).json['success']
    assert not client.post('/update_task', data={'id': 'x', 'text': 'x'}).json['success']


def test_update_note_resyncs_dataset(zf, client):
    note_id = client.post('/notes/add', json={'title': 'A', 'content': 'alpha'}).json['note']['id']
    data = client.post('/notes/update', json={'note_id': note_id, 'title': 'A2', 'content': 'gamma'}).json
    assert data['success'] and data['note']['title'] == 'A2'
    assert 'gamma' in (zf.NOTES_DIR / f'note_{note_id}.txt').read_text()
    assert zf.load_notes()[0]['content'] == 'gamma'
    assert not client.post('/notes/update', json={'note_id': note_id, 'content': ' '}).json['success']
    assert not client.post('/notes/update', json={'note_id': 'nope', 'content': 'x'}).json['success']


def test_inbox_cached_then_refreshed(zf, client, monkeypatch):
    calls = []

    class FakeMail:
        def logout(self):
            pass

    monkeypatch.setattr(zf, 'login_to_email', lambda: FakeMail())
    monkeypatch.setattr(zf, 'get_latest_emails', lambda mail: calls.append(1) or [])
    zf.fetch_inbox()
    zf.fetch_inbox()
    assert len(calls) == 1          # second visit served from cache
    client.get('/email?refresh=1')
    assert len(calls) == 2          # refresh bypasses it


def test_inbox_errors_are_not_cached(zf, monkeypatch):
    attempts = []

    def fail():
        attempts.append(1)
        raise zf.EmailError('boom')

    monkeypatch.setattr(zf, 'login_to_email', fail)
    assert zf.fetch_inbox() == ([], 'boom')
    zf.fetch_inbox()
    assert len(attempts) == 2


def test_chat_history_persists_and_clears(zf, client):
    r = client.post('/chat', data={'text_input': 'hello'})
    assert r.status_code == 302                       # post/redirect/get
    page = client.get('/chat').data
    assert b'hello' in page and b'No data found' in page
    assert len(zf.load_chat_history()) == 2
    assert client.post('/chat', data={'text_input': '  '}).status_code == 302
    assert len(zf.load_chat_history()) == 2           # blank input is not stored
    client.post('/chat/clear')
    assert zf.load_chat_history() == []


def test_chat_history_is_capped_and_html_escaped(zf, client):
    zf.append_chat_messages([zf.make_chat_message('ai', f'm{i}') for i in range(zf.MAX_CHAT_MESSAGES + 5)])
    assert len(zf.load_chat_history()) == zf.MAX_CHAT_MESSAGES
    zf.write_json_atomic(zf.CHAT_FILE, [{'type': 'ai', 'content': '<script>alert(1)</script> **ok**'}], 'x')
    page = client.get('/chat').data
    assert b'<script>alert(1)</script>' not in page and b'<strong>ok</strong>' in page


def test_export_import_roundtrip_merges_without_duplicates(zf, client, tmp_path):
    import io
    task_id = add(client, 'keep me')
    client.post('/toggle_task', data={'id': add(client, 'done')})
    client.post('/notes/add', json={'title': 'N', 'content': 'body'})
    zf.append_chat_messages([zf.make_chat_message('user', 'q'), zf.make_chat_message('ai', 'a')])
    backup = client.get('/export').data

    # importing onto the same install adds nothing
    r = client.post('/import', data={'backup_file': (io.BytesIO(backup), 'b.json')}).json
    assert r['success'] and sum(r['added'].values()) == 0

    # importing onto a fresh install restores everything, including the notes dataset files
    zf.TASKS_FILE.unlink(); zf.NOTES_FILE.unlink(); zf.CHAT_FILE.unlink()
    for f in zf.NOTES_DIR.glob('note_*.txt'):
        f.unlink()
    r = client.post('/import', data={'backup_file': (io.BytesIO(backup), 'b.json')}).json
    assert r['added']['tasks'] == 2 and r['added']['notes'] == 1 and r['added']['chat_history'] == 2
    assert any(t['id'] == task_id for t in zf.load_tasks())
    assert len(list(zf.NOTES_DIR.glob('note_*.txt'))) == 1


def test_import_rejects_bad_files_and_sanitizes(zf, client):
    import io
    def send(raw):
        return client.post('/import', data={'backup_file': (io.BytesIO(raw), 'b.json')}).json
    assert not send(b'not json')['success']
    assert not send(b'[1,2]')['success']
    assert not send(b'{"app": "other", "version": 1}')['success']
    assert not send(b'{"app": "zehnnflow", "version": 99}')['success']
    assert not client.post('/import').json['success']

    evil = {
        'app': 'zehnnflow', 'version': 1,
        'tasks': ['str', {'text': 5}, {'text': 'ok', 'id': 'dup'}, {'text': 'again', 'id': 'dup'}],
        'notes': [{'content': ''}, {'content': 'n', 'title': 123}],
        'tracks': [{'title': 'x', 'url': 'javascript:alert(1)'}, {'title': 'ok', 'url': 'https://youtu.be/q'}],
        'chat_history': [{'type': 'system', 'content': 'x'}, {'type': 'ai', 'content': '<b>hi</b>'}],
    }
    r = send(zf.json.dumps(evil).encode())
    assert r['added'] == {'tasks': 1, 'notes': 1, 'tracks': 1, 'chat_history': 1}


def test_quote_is_not_fetched_on_page_load_and_is_cached(zf, client, monkeypatch):
    calls = []

    class Resp:
        def raise_for_status(self): pass
        def json(self): return [{'q': 'Be here', 'a': 'Someone'}]

    monkeypatch.setattr(zf.requests, 'get', lambda *a, **k: calls.append(1) or Resp())
    page = client.get('/').data
    assert calls == [] and b"data-needs-fetch='1'" in page          # page render never hits the network
    assert client.get('/quote').json['quote'] == '"Be here" - Someone'
    client.get('/quote')
    assert len(calls) == 1                                          # cached
    assert b'Be here' in client.get('/').data


def test_quote_failure_backs_off(zf, client, monkeypatch):
    calls = []
    monkeypatch.setattr(zf.requests, 'get', lambda *a, **k: calls.append(1) or (_ for _ in ()).throw(OSError('offline')))
    assert not client.get('/quote').json['success']
    client.get('/quote')
    assert len(calls) == 1                                          # no retry storm while offline


def test_stale_complete_click_is_idempotent(zf, client):
    task_id = add(client, 'a')
    assert client.post('/toggle_task', data={'id': task_id, 'completed': '1'}).json['completed'] is True
    # a second window that still shows the task as open clicks Complete again
    assert client.post('/toggle_task', data={'id': task_id, 'completed': '1'}).json['completed'] is True
    assert zf.load_tasks()[0]['completed'] is True
    assert client.post('/toggle_task', data={'id': task_id, 'completed': '0'}).json['completed'] is False
    assert client.post('/toggle_task', data={'id': task_id, 'completed': '0'}).json['completed'] is False


def test_desktop_mode_falls_back_to_web_when_no_gui_toolkit(zf, monkeypatch):
    import types
    fake = types.ModuleType('webview')
    fake.create_window = lambda *a, **k: None
    def boom():
        raise RuntimeError('You must have either QT or GTK')
    fake.start = boom
    monkeypatch.setitem(sys.modules, 'webview', fake)
    served = []
    monkeypatch.setattr(zf, 'run_web', lambda *a, **k: served.append(1))
    zf.run_desktop()
    assert served == [1]
