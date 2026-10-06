document.addEventListener('DOMContentLoaded', () => {
    const clockElement = document.getElementById('clock');
    const todoFormElement = document.getElementById('todo-form');
    const todoListElement = document.getElementById('todo-list');
    const todoInputElement = document.getElementById('todo-input');
    const statusElement = document.getElementById('task-status');
    const awardVisual = document.getElementById('award-visual');
    const completedSection = document.getElementById('completed-section');
    const completedListElement = document.getElementById('completed-list');
    const completedCountElement = document.getElementById('completed-count');
    const clearCompletedButton = document.getElementById('clear-completed-btn');
    const openCountElement = document.getElementById('open-count');
    const quoteElement = document.getElementById('quote-text');
    const importFormElement = document.getElementById('import-data-form');
    const dataStatusElement = document.getElementById('data-status');

    if (!clockElement || !todoFormElement || !todoListElement || !todoInputElement || !statusElement) {
        return;
    }

    const postForm = async (url, fields) => {
        const response = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8' },
            body: new URLSearchParams(fields),
        });
        return response.json();
    };

    const showMessage = (element, message, variant = '') => {
        element.textContent = message;
        element.classList.remove('hidden', 'error', 'success');
        if (variant) {
            element.classList.add(variant);
        }
        window.setTimeout(() => element.classList.add('hidden'), 2600);
    };
    const renderStatus = (message, variant = '') => showMessage(statusElement, message, variant);

    const renderClock = () => {
        const now = new Date();
        const hours = String(now.getHours()).padStart(2, '0');
        const minutes = String(now.getMinutes()).padStart(2, '0');
        const seconds = String(now.getSeconds()).padStart(2, '0');
        clockElement.textContent = `${hours}:${minutes}:${seconds}`;
    };

    const showAward = () => {
        if (!awardVisual) {
            return;
        }
        awardVisual.classList.remove('hidden');
        window.setTimeout(() => awardVisual.classList.add('hidden'), 1300);
    };

    // --- Rendering: the server is the source of truth; every change re-renders from /tasks ---
    const makeButton = (className, label, text) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = className;
        button.textContent = text;
        if (label) {
            button.setAttribute('aria-label', label);
        }
        return button;
    };

    const buildTaskElement = (task, completed) => {
        const item = document.createElement('li');
        item.className = completed ? 'task-item completed' : 'task-item';
        item.dataset.id = task.id;

        const textElement = document.createElement('span');
        textElement.className = 'task-text';
        textElement.textContent = task.text;

        const actions = document.createElement('span');
        actions.className = 'task-actions';
        if (completed) {
            actions.append(makeButton('secondary-btn restore-btn', '', 'Restore'));
        } else {
            actions.append(
                makeButton('secondary-btn move-up-btn', 'Move up', '↑'),
                makeButton('secondary-btn move-down-btn', 'Move down', '↓'),
                makeButton('toggle-btn', '', 'Complete'),
            );
        }
        item.append(textElement, actions);
        return item;
    };

    const renderTasks = (data) => {
        todoListElement.replaceChildren(...data.open.map((task) => buildTaskElement(task, false)));
        if (data.open.length === 0) {
            const emptyItem = document.createElement('li');
            emptyItem.className = 'task-empty';
            emptyItem.textContent = 'No tasks yet. Start with one small win.';
            todoListElement.appendChild(emptyItem);
        }
        if (openCountElement) {
            openCountElement.textContent = String(data.open.length);
        }
        if (completedListElement && completedSection && completedCountElement) {
            completedListElement.replaceChildren(...data.completed.map((task) => buildTaskElement(task, true)));
            completedCountElement.textContent = String(data.completed.length);
            completedSection.hidden = data.completed.length === 0;
        }
    };

    const refreshTasks = async () => {
        try {
            const response = await fetch('/tasks');
            const data = await response.json();
            if (data.success) {
                renderTasks(data);
            }
        } catch (_error) {
            renderStatus('Could not refresh tasks.', 'error');
        }
    };

    // Run an action against the server, report errors, then re-render from the server's state.
    const mutate = async (action, failureMessage) => {
        try {
            const data = await action();
            if (!data.success) {
                renderStatus(data.error || failureMessage, 'error');
            }
            await refreshTasks();
            return data;
        } catch (_error) {
            renderStatus('Network issue. Please try again.', 'error');
            return { success: false };
        }
    };

    renderClock();
    window.setInterval(renderClock, 1000);

    if (quoteElement && quoteElement.dataset.needsFetch === '1') {
        fetch('/quote')
            .then((response) => response.json())
            .then((data) => { quoteElement.textContent = data.quote; })
            .catch(() => { quoteElement.textContent = 'Unable to fetch quote'; });
    }

    todoFormElement.addEventListener('submit', async (event) => {
        event.preventDefault();
        const taskText = todoInputElement.value.trim();
        if (!taskText) {
            renderStatus('Task cannot be empty.', 'error');
            return;
        }

        const data = await mutate(() => postForm('/add_task', { task: taskText }), 'Unable to add task.');
        if (data.success) {
            todoInputElement.value = '';
            renderStatus('Task added.', 'success');
        }
    });

    todoListElement.addEventListener('dblclick', (event) => {
        const target = event.target;
        if (!(target instanceof HTMLElement) || !target.classList.contains('task-text')) {
            return;
        }
        const taskItem = target.closest('.task-item');
        if (!taskItem || taskItem.querySelector('.task-edit-input')) {
            return;
        }

        const originalText = target.textContent;
        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'task-edit-input';
        input.value = originalText;
        input.setAttribute('aria-label', 'Edit task');
        target.classList.add('hidden');
        target.after(input);
        input.focus();
        input.select();

        let finished = false;
        const finish = async (save) => {
            if (finished) {
                return;
            }
            finished = true;
            const newText = input.value.trim();
            input.remove();
            target.classList.remove('hidden');
            if (!save || !newText || newText === originalText) {
                return;
            }
            const data = await mutate(
                () => postForm('/update_task', { id: taskItem.dataset.id || '', text: newText }),
                'Unable to update task.',
            );
            if (data.success) {
                renderStatus('Task updated.', 'success');
            }
        };

        input.addEventListener('keydown', (keyEvent) => {
            if (keyEvent.key === 'Enter') {
                keyEvent.preventDefault();
                finish(true);
            } else if (keyEvent.key === 'Escape') {
                finish(false);
            }
        });
        input.addEventListener('blur', () => finish(true));
    });

    const moveTask = async (taskItem, direction) => {
        const ids = Array.from(todoListElement.querySelectorAll('.task-item')).map((item) => item.dataset.id);
        const from = ids.indexOf(taskItem.dataset.id);
        const to = from + direction;
        if (from < 0 || to < 0 || to >= ids.length) {
            return;
        }
        [ids[from], ids[to]] = [ids[to], ids[from]];
        await mutate(async () => {
            const response = await fetch('/reorder_tasks', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ids }),
            });
            return response.json();
        }, 'Unable to reorder tasks.');
    };

    const handleTaskClick = async (event) => {
        const target = event.target;
        if (!(target instanceof HTMLButtonElement)) {
            return;
        }
        const taskItem = target.closest('.task-item');
        if (!taskItem) {
            return;
        }

        if (target.classList.contains('move-up-btn')) {
            await moveTask(taskItem, -1);
        } else if (target.classList.contains('move-down-btn')) {
            await moveTask(taskItem, 1);
        } else if (target.classList.contains('toggle-btn')) {
            const data = await mutate(() => postForm('/toggle_task', { id: taskItem.dataset.id || '', completed: '1' }), 'Unable to complete task.');
            if (data.success) {
                showAward();
            }
        } else if (target.classList.contains('restore-btn')) {
            await mutate(() => postForm('/toggle_task', { id: taskItem.dataset.id || '', completed: '0' }), 'Unable to restore task.');
        }
    };
    todoListElement.addEventListener('click', handleTaskClick);
    if (completedListElement) {
        completedListElement.addEventListener('click', handleTaskClick);
    }

    if (clearCompletedButton) {
        clearCompletedButton.addEventListener('click', async () => {
            if (!window.confirm('Permanently remove all completed tasks?')) {
                return;
            }
            await mutate(() => postForm('/clear_completed', {}), 'Unable to clear completed tasks.');
        });
    }

    if (importFormElement && dataStatusElement) {
        importFormElement.addEventListener('submit', async (event) => {
            event.preventDefault();
            try {
                const response = await fetch('/import', { method: 'POST', body: new FormData(importFormElement) });
                const data = await response.json();
                if (!data.success) {
                    showMessage(dataStatusElement, data.error || 'Unable to import backup.', 'error');
                    return;
                }
                const added = data.added;
                showMessage(
                    dataStatusElement,
                    `Imported ${added.tasks} tasks, ${added.notes} notes, ${added.tracks} tracks, ${added.chat_history} chat messages.`,
                    'success',
                );
                importFormElement.reset();
                await refreshTasks();
            } catch (_error) {
                showMessage(dataStatusElement, 'Network issue while importing.', 'error');
            }
        });
    }
});
