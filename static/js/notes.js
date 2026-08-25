document.addEventListener('DOMContentLoaded', () => {
    const noteFormElement = document.getElementById('note-form');
    const noteTitleElement = document.getElementById('note-title');
    const noteContentElement = document.getElementById('note-content');
    const notesListElement = document.getElementById('notes-list');
    const notesStatusElement = document.getElementById('notes-status');
    const importFormElement = document.getElementById('import-notes-form');

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

        const deleteButton = document.createElement('button');
        deleteButton.type = 'button';
        deleteButton.className = 'danger-btn delete-note-btn';
        deleteButton.textContent = 'Delete';

        noteHead.append(titleElement, deleteButton);

        const metaElement = document.createElement('p');
        metaElement.className = 'note-meta';
        metaElement.textContent = `Updated ${note.updated_at}`;

        const contentElement = document.createElement('p');
        contentElement.className = 'note-content';
        contentElement.textContent = note.content;

        noteCard.append(noteHead, metaElement, contentElement);
        return noteCard;
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
        if (!(target instanceof HTMLButtonElement) || !target.classList.contains('delete-note-btn')) {
            return;
        }

        const noteCard = target.closest('.note-card');
        if (!noteCard) {
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
