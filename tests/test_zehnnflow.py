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
        def as_chat_engine(self, **kwargs):
            return type('CE', (), {'chat': staticmethod(lambda q, chat_history=None: 'answer')})()

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
    llms = types.ModuleType('llama_index.core.llms')
    llms.ChatMessage = lambda role, content: (role, content)
    llms.MessageRole = type('MR', (), {'USER': 'user', 'ASSISTANT': 'assistant'})
    monkeypatch.setitem(sys.modules, 'llama_index.core.llms', llms)

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

    class RejectingIMAP:
        def __init__(self, *a, **k):
            pass

        def login(self, *a):
            raise imaplib.IMAP4.error('bad creds')

    monkeypatch.setattr(zf.imaplib, 'IMAP4_SSL', RejectingIMAP)
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


def test_chat_creates_thread_and_persists(zf, client):
    r = client.post('/chat', data={'text_input': 'hello there'})
    assert r.status_code == 302 and '/chat?thread=' in r.headers['Location']
    page = client.get(r.headers['Location']).data
    assert b'hello there' in page and b'No data found' in page
    threads = zf.load_threads()
    assert len(threads) == 1 and threads[0]['title'] == 'hello there' and len(threads[0]['messages']) == 2
    assert client.post('/chat', data={'text_input': '  ', 'thread': threads[0]['id']}).status_code == 302
    assert len(zf.load_threads()[0]['messages']) == 2          # blank input is not stored


def test_threads_are_independent_and_receive_their_own_history(zf, client, monkeypatch):
    seen = []
    monkeypatch.setattr(zf.chat_engine, 'ask', lambda msg, history=(): seen.append((msg, [m['content'] for m in history])) or f're:{msg}')

    t1 = client.post('/chat', data={'text_input': 'first'}).headers['Location'].split('=')[1]
    client.post('/chat', data={'text_input': 'follow up', 'thread': t1})
    t2 = client.post('/chat/new').headers['Location'].split('=')[1]
    client.post('/chat', data={'text_input': 'other topic', 'thread': t2})

    assert seen[1] == ('follow up', ['first', 're:first'])      # same thread: context carried over
    assert seen[2] == ('other topic', [])                       # new thread: no leakage
    threads = {t['id']: t for t in zf.load_threads()}
    assert len(threads) == 2 and len(threads[t1]['messages']) == 4 and len(threads[t2]['messages']) == 2
    assert b'other topic' in client.get(f'/chat?thread={t2}').data
    assert b'follow up' not in client.get(f'/chat?thread={t2}').data


def test_new_chat_reuses_empty_thread_and_rename_delete_clear(zf, client):
    t = client.post('/chat/new').headers['Location'].split('=')[1]
    assert client.post('/chat/new').headers['Location'].endswith(t)      # no pile of blank threads
    assert len(zf.load_threads()) == 1

    client.post('/chat', data={'text_input': 'q', 'thread': t})
    client.post('/chat/rename', data={'thread': t, 'title': '  My   topic '})
    assert zf.load_threads()[0]['title'] == 'My topic'
    client.post('/chat/clear', data={'thread': t})
    assert zf.load_threads()[0]['messages'] == [] and zf.load_threads()[0]['title'] == 'New chat'
    client.post('/chat/delete', data={'thread': t})
    assert zf.load_threads() == []


def test_unknown_thread_id_starts_a_new_thread(zf, client):
    client.post('/chat', data={'text_input': 'hi', 'thread': 'does-not-exist'})
    assert len(zf.load_threads()) == 1


def test_legacy_flat_chat_history_is_migrated_with_a_stable_id(zf, client):
    zf.CHAT_FILE.write_text(zf.json.dumps([
        {'type': 'user', 'content': 'old question', 'at': '2026-01-01 10:00'},
        {'type': 'ai', 'content': 'old answer', 'at': '2026-01-01 10:00'},
        {'type': 'bogus', 'content': 'dropped'},
    ]))
    first = zf.load_threads()
    assert len(first) == 1 and first[0]['title'] == 'old question' and len(first[0]['messages']) == 2
    assert zf.load_threads()[0]['id'] == first[0]['id']                 # persisted, so links stay valid
    assert b'old answer' in client.get('/chat').data


def test_chat_messages_are_capped_per_thread_and_html_escaped(zf, client):
    tid = zf.append_chat_messages('', [zf.make_chat_message('ai', f'm{i}') for i in range(zf.MAX_CHAT_MESSAGES + 5)])
    assert len(zf.load_threads()[0]['messages']) == zf.MAX_CHAT_MESSAGES
    zf.save_threads([{**zf.load_threads()[0], 'messages': [{'type': 'ai', 'content': '<script>alert(1)</script> **ok**', 'at': ''}]}])
    page = client.get(f'/chat?thread={tid}').data
    assert b'<script>alert(1)</script>' not in page and b'<strong>ok</strong>' in page


def test_export_import_roundtrip_merges_without_duplicates(zf, client, tmp_path):
    import io
    task_id = add(client, 'keep me')
    client.post('/toggle_task', data={'id': add(client, 'done')})
    client.post('/notes/add', json={'title': 'N', 'content': 'body'})
    zf.append_chat_messages('', [zf.make_chat_message('user', 'q'), zf.make_chat_message('ai', 'a')])
    backup = client.get('/export').data

    # importing onto the same install adds nothing
    r = client.post('/import', data={'backup_file': (io.BytesIO(backup), 'b.json')}).json
    assert r['success'] and sum(r['added'].values()) == 0

    # importing onto a fresh install restores everything, including the notes dataset files
    zf.TASKS_FILE.unlink(); zf.NOTES_FILE.unlink(); zf.CHAT_FILE.unlink()
    for f in zf.NOTES_DIR.glob('note_*.txt'):
        f.unlink()
    r = client.post('/import', data={'backup_file': (io.BytesIO(backup), 'b.json')}).json
    assert r['added']['tasks'] == 2 and r['added']['notes'] == 1 and r['added']['chat_messages'] == 2
    assert any(t['id'] == task_id for t in zf.load_tasks())
    assert len(list(zf.NOTES_DIR.glob('note_*.txt'))) == 1
    assert len(zf.load_threads()) == 1 and len(zf.load_threads()[0]['messages']) == 2


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
    assert r['added'] == {'tasks': 1, 'notes': 1, 'tracks': 1, 'chat_messages': 1}   # v1 flat history -> one thread


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


class Clock:
    """Stand-in for the time module: manual monotonic clock, recorded sleeps."""
    def __init__(self):
        self.now = 1000.0
        self.slept = []
    def monotonic(self):
        return self.now
    def sleep(self, seconds):
        self.slept.append(seconds)


@pytest.fixture
def clock(zf, monkeypatch):
    c = Clock()
    monkeypatch.setattr(zf, 'time', c)
    monkeypatch.setattr(zf, '_sleep', c.sleep)
    return c


def test_retries_transient_errors_with_exponential_backoff(zf, clock):
    attempts = []

    def flaky():
        attempts.append(1)
        if len(attempts) < 3:
            raise zf.TransientEmailError('blip')
        return 'ok'

    assert zf.call_with_retries(flaky) == 'ok'
    assert len(attempts) == 3 and clock.slept == [1.0, 2.0]


def test_gives_up_after_max_attempts_and_never_retries_permanent_errors(zf, clock):
    n = []
    def always():
        n.append(1)
        raise zf.TransientEmailError('down')
    with pytest.raises(zf.TransientEmailError):
        zf.call_with_retries(always)
    assert len(n) == 3 and clock.slept == [1.0, 2.0]       # no sleep after the last attempt

    n.clear()
    def bad_password():
        n.append(1)
        raise zf.EmailError('rejected')
    with pytest.raises(zf.EmailError):
        zf.call_with_retries(bad_password)
    assert len(n) == 1


def test_smtp_error_classification(zf):
    smtplib = zf.smtplib
    assert zf.is_transient_smtp_error(smtplib.SMTPServerDisconnected())
    assert zf.is_transient_smtp_error(TimeoutError())
    assert zf.is_transient_smtp_error(smtplib.SMTPResponseException(451, b'try later'))
    # SMTPException subclasses OSError, so these must NOT count as transient
    assert not zf.is_transient_smtp_error(smtplib.SMTPAuthenticationError(535, b'bad'))
    assert not zf.is_transient_smtp_error(smtplib.SMTPRecipientsRefused({}))
    assert not zf.is_transient_smtp_error(smtplib.SMTPResponseException(550, b'no'))


def test_send_retries_connect_but_never_resends(zf, clock, monkeypatch):
    monkeypatch.setenv('EMAIL_ADDRESS', 'me@example.com')
    monkeypatch.setenv('GOOGLE_APP_PASSWORD', 'pw')
    connects, sends = [], []

    class FakeSMTP:
        def __init__(self, *a, **k):
            connects.append(1)
            if len(connects) < 3:
                raise OSError('timed out')
        def starttls(self): pass
        def login(self, *a): pass
        def sendmail(self, *a): sends.append(1)
        def quit(self): pass
        def close(self): pass

    monkeypatch.setattr(zf.smtplib, 'SMTP', FakeSMTP)
    zf.send_email('you@example.com', 's', 'b')
    assert len(connects) == 3 and len(sends) == 1 and clock.slept == [1.0, 2.0]

    # a drop *during* sendmail is ambiguous: must not retry (could double-send)
    connects.clear(); sends.clear()
    class DropsMidSend(FakeSMTP):
        def __init__(self, *a, **k): connects.append(1)
        def sendmail(self, *a):
            sends.append(1)
            raise zf.smtplib.SMTPServerDisconnected('gone')
    monkeypatch.setattr(zf.smtplib, 'SMTP', DropsMidSend)
    with pytest.raises(zf.EmailError, match='Sent folder'):
        zf.send_email('you@example.com', 's', 'b')
    assert len(sends) == 1


def test_send_does_not_retry_bad_password(zf, clock, monkeypatch):
    monkeypatch.setenv('EMAIL_ADDRESS', 'me@example.com')
    monkeypatch.setenv('GOOGLE_APP_PASSWORD', 'pw')
    logins = []

    class BadLogin:
        def __init__(self, *a, **k): pass
        def starttls(self): pass
        def login(self, *a):
            logins.append(1)
            raise zf.smtplib.SMTPAuthenticationError(535, b'nope')
        def close(self): pass

    monkeypatch.setattr(zf.smtplib, 'SMTP', BadLogin)
    with pytest.raises(zf.EmailError, match='app password'):
        zf.send_email('you@example.com', 's', 'b')
    assert len(logins) == 1 and clock.slept == []


def test_inbox_cooldown_grows_then_refresh_bypasses_and_success_resets(zf, clock, monkeypatch):
    fetches = []
    outcome = {'fail': True}

    def fake_once():
        fetches.append(1)
        if outcome['fail']:
            raise zf.TransientEmailError('down')
        return ['mail']

    monkeypatch.setattr(zf, 'fetch_inbox_once', fake_once)

    assert zf.fetch_inbox() == ([], 'down')
    assert len(fetches) == 3                       # 3 attempts inside one call
    clock.now += 5                                 # within the 15s cooldown: fail fast, no network
    assert zf.fetch_inbox() == ([], 'down') and len(fetches) == 3
    clock.now += 11                                # cooldown over -> tries again (and cooldown doubles to 30s)
    zf.fetch_inbox()
    assert len(fetches) == 6
    clock.now += 20
    zf.fetch_inbox()
    assert len(fetches) == 6                       # still cooling down (30s)
    zf.fetch_inbox(force=True)                     # Refresh link ignores the cooldown
    assert len(fetches) == 9

    outcome['fail'] = False
    assert zf.fetch_inbox(force=True) == (['mail'], None)
    assert zf.fetch_inbox() == (['mail'], None)    # cached again
    assert zf._inbox_cache['failures'] == 0


def test_inbox_cooldown_is_capped(zf, clock, monkeypatch):
    monkeypatch.setattr(zf, 'fetch_inbox_once', lambda: (_ for _ in ()).throw(zf.EmailError('rejected')))
    for _ in range(12):
        zf.fetch_inbox(force=True)
    wait = zf._inbox_cache['retry_after'] - clock.now
    assert wait == zf.INBOX_COOLDOWN_MAX


def test_missing_credentials_never_trigger_a_cooldown(zf, clock):
    for _ in range(3):
        assert zf.fetch_inbox()[1] == zf.MISSING_CREDENTIALS_MESSAGE
    assert zf._inbox_cache['failures'] == 0 and zf._inbox_cache['error'] is None


def test_import_merges_threads_by_id_without_duplicating_messages(zf, client):
    import io
    tid = zf.append_chat_messages('', [zf.make_chat_message('user', 'q'), zf.make_chat_message('ai', 'a')])
    backup = client.get('/export').data
    zf.append_chat_messages(tid, [zf.make_chat_message('user', 'later')])        # local changes after the backup
    r = client.post('/import', data={'backup_file': (io.BytesIO(backup), 'b.json')}).json
    assert r['added']['chat_messages'] == 0
    assert len(zf.load_threads()) == 1 and len(zf.load_threads()[0]['messages']) == 3

    other = {'app': 'zehnnflow', 'version': 2, 'chat_threads': [
        {'id': tid, 'messages': [{'type': 'user', 'content': 'from laptop', 'at': '2030-01-01 00:00'}]},
        {'id': 'new-thread', 'title': 'Elsewhere', 'messages': [{'type': 'user', 'content': 'hi', 'at': ''}]},
    ]}
    r = client.post('/import', data={'backup_file': (io.BytesIO(zf.json.dumps(other).encode()), 'b.json')}).json
    assert r['added']['chat_messages'] == 2
    threads = {t['id']: t for t in zf.load_threads()}
    assert threads['new-thread']['title'] == 'Elsewhere' and len(threads[tid]['messages']) == 4
