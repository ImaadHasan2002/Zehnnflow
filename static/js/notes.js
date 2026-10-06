document.addEventListener('DOMContentLoaded', () => {
    const noteFormElement = document.getElementById('note-form');
    const noteTitleElement = document.getElementById('note-title');
    const noteContentElement = document.getElementById('note-content');
    const notesListElement = document.getElementById('notes-list');
    const notesStatusElement = document.getElementById('notes-status');
    const importFormElement = document.getElementById('import-notes-form');
    const searchElement = document.getElementById('notes-search');

    if (!noteFormElement || !notesListElement || !notesStatusElement || !importFormElement) {
        return;
    }

    const showStatus = (message, variant = '') => {
        notesStatusElement.textContent = message;
        notesStatusElement.classList.remove('hidden', 'error', 'success');
        if (variant) {
            notesStatusElement.classList.add(variant);
        }
        window.setTimeout(() => notesStatusElement.classList.add('hidden'), 3200);
    };

    const removeEmptyState = () => {
        const emptyState = notesListElement.querySelector('#empty-notes');
        if (emptyState) {
            emptyState.remove();
        }
    };

    const ensureEmptyState = () => {
        const notes = notesListElement.querySelectorAll('.note-card');
        if (notes.length > 0 || notesListElement.querySelector('#empty-notes')) {
            return;
        }

        const emptyState = document.createElement('p');
        emptyState.id = 'empty-notes';
        emptyState.className = 'empty-state';
        emptyState.textContent = 'No notes yet. Add your first one above.';
        notesListElement.appendChild(emptyState);
    };

    const createNoteElement = (note) => {
        const noteCard = document.createElement('article');
        noteCard.className = 'note-card';
        noteCard.dataset.noteId = note.id;

        const noteHead = document.createElement('div');
        noteHead.className = 'note-head';

        const titleElement = document.createElement('h3');
        titleElement.textContent = note.title;

        const actions = document.createElement('span');
        actions.className = 'note-actions';

        const editButton = document.createElement('button');
        editButton.type = 'button';
        editButton.className = 'secondary-btn edit-note-btn';
        editButton.textContent = 'Edit';

        const deleteButton = document.createElement('button');
        deleteButton.type = 'button';
        deleteButton.className = 'danger-btn delete-note-btn';
        deleteButton.textContent = 'Delete';

        actions.append(editButton, deleteButton);
        noteHead.append(titleElement, actions);

        const metaElement = document.createElement('p');
        metaElement.className = 'note-meta';
        metaElement.textContent = `Updated ${note.updated_at}`;

        const contentElement = document.createElement('p');
        contentElement.className = 'note-content';
        contentElement.textContent = note.content;

        noteCard.append(noteHead, metaElement, contentElement);
        return noteCard;
    };

    const applySearch = () => {
        const query = (searchElement ? searchElement.value : '').trim().toLowerCase();
        notesListElement.querySelectorAll('.note-card').forEach((card) => {
            const haystack = card.textContent.toLowerCase();
            card.classList.toggle('hidden', query !== '' && !haystack.includes(query));
        });
    };

    if (searchElement) {
        searchElement.addEventListener('input', applySearch);
    }

    const startEditing = (noteCard) => {
        if (noteCard.querySelector('.note-edit-form')) {
            return;
        }
        const titleElement = noteCard.querySelector('h3');
        const contentElement = noteCard.querySelector('.note-content');
        const originalTitle = titleElement.textContent;
        const originalContent = contentElement.textContent;

        const form = document.createElement('form');
        form.className = 'note-edit-form form-stack';

        const titleInput = document.createElement('input');
        titleInput.type = 'text';
        titleInput.value = originalTitle;
        titleInput.setAttribute('aria-label', 'Note title');

        const contentInput = document.createElement('textarea');
        contentInput.value = originalContent;
        contentInput.required = true;
        contentInput.setAttribute('aria-label', 'Note content');

        const saveButton = document.createElement('button');
        saveButton.type = 'submit';
        saveButton.textContent = 'Save changes';

        const cancelButton = document.createElement('button');
        cancelButton.type = 'button';
        cancelButton.className = 'secondary-btn';
        cancelButton.textContent = 'Cancel';

        form.append(titleInput, contentInput, saveButton, cancelButton);

        const restore = () => {
            form.remove();
            noteCard.querySelector('.note-head').classList.remove('hidden');
            noteCard.querySelector('.note-meta').classList.remove('hidden');
            contentElement.classList.remove('hidden');
        };

        noteCard.querySelector('.note-head').classList.add('hidden');
        noteCard.querySelector('.note-meta').classList.add('hidden');
        contentElement.classList.add('hidden');
        noteCard.append(form);
        contentInput.focus();

        cancelButton.addEventListener('click', restore);
        form.addEventListener('submit', async (event) => {
            event.preventDefault();
            const content = contentInput.value.trim();
            if (!content) {
                showStatus('Note content cannot be empty.', 'error');
                return;
            }
            try {
                const response = await fetch('/notes/update', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        note_id: noteCard.dataset.noteId || '',
                        title: titleInput.value.trim(),
                        content,
                    }),
                });
                const data = await response.json();
                if (!data.success) {
                    showStatus(data.error || 'Unable to save note.', 'error');
                    return;
                }
                titleElement.textContent = data.note.title;
                contentElement.textContent = data.note.content;
                noteCard.querySelector('.note-meta').textContent = `Updated ${data.note.updated_at}`;
                restore();
                applySearch();
                showStatus('Note updated and re-indexed.', 'success');
            } catch (_error) {
                showStatus('Network issue while saving note.', 'error');
            }
        });
    };

    noteFormElement.addEventListener('submit', async (event) => {
        event.preventDefault();
        const title = noteTitleElement.value.trim();
        const content = noteContentElement.value.trim();

        if (!content) {
            showStatus('Note content cannot be empty.', 'error');
            return;
        }

        try {
            const response = await fetch('/notes/add', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ title, content }),
            });
            const data = await response.json();
            if (!data.success) {
                showStatus(data.error || 'Unable to save note.', 'error');
                return;
            }

            removeEmptyState();
            notesListElement.prepend(createNoteElement(data.note));
            noteFormElement.reset();
            showStatus('Note saved and indexed for chat.', 'success');
        } catch (_error) {
            showStatus('Network issue while saving note.', 'error');
        }
    });

    notesListElement.addEventListener('click', async (event) => {
        const target = event.target;
        if (!(target instanceof HTMLButtonElement)) {
            return;
        }

        const noteCard = target.closest('.note-card');
        if (!noteCard) {
            return;
        }

        if (target.classList.contains('edit-note-btn')) {
            startEditing(noteCard);
            return;
        }
        if (!target.classList.contains('delete-note-btn')) {
            return;
        }

        const noteId = noteCard.dataset.noteId || '';
        try {
            const response = await fetch('/notes/delete', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ note_id: noteId }),
            });
            const data = await response.json();
            if (!data.success) {
                showStatus(data.error || 'Unable to delete note.', 'error');
                return;
            }

            noteCard.remove();
            ensureEmptyState();
            showStatus('Note deleted.', 'success');
        } catch (_error) {
            showStatus('Network issue while deleting note.', 'error');
        }
    });

    importFormElement.addEventListener('submit', async (event) => {
        event.preventDefault();
        const formData = new FormData(importFormElement);
        if (!formData.get('notes_file')) {
            showStatus('Choose a file before importing.', 'error');
            return;
        }

        try {
            const response = await fetch('/notes/import', {
                method: 'POST',
                body: formData,
            });
            const data = await response.json();
            if (!data.success) {
                showStatus(data.error || 'Unable to import note.', 'error');
                return;
            }

            removeEmptyState();
            notesListElement.prepend(createNoteElement(data.note));
            importFormElement.reset();
            showStatus('Note imported and indexed.', 'success');
        } catch (_error) {
            showStatus('Network issue while importing note.', 'error');
        }
    });
});
