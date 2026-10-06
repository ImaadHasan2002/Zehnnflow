document.addEventListener('DOMContentLoaded', () => {
    const clockElement = document.getElementById('clock');
    const todoFormElement = document.getElementById('todo-form');
    const todoListElement = document.getElementById('todo-list');
    const todoInputElement = document.getElementById('todo-input');
    const statusElement = document.getElementById('task-status');
    const awardVisual = document.getElementById('award-visual');

    if (!clockElement || !todoFormElement || !todoListElement || !todoInputElement || !statusElement) {
        return;
    }

    const renderClock = () => {
        const now = new Date();
        const hours = String(now.getHours()).padStart(2, '0');
        const minutes = String(now.getMinutes()).padStart(2, '0');
        const seconds = String(now.getSeconds()).padStart(2, '0');
        clockElement.textContent = `${hours}:${minutes}:${seconds}`;
    };

    const renderStatus = (message, variant = '') => {
        statusElement.textContent = message;
        statusElement.classList.remove('hidden', 'error', 'success');
        if (variant) {
            statusElement.classList.add(variant);
        }
        window.setTimeout(() => statusElement.classList.add('hidden'), 2600);
    };

    const showAward = () => {
        if (!awardVisual) {
            return;
        }
        awardVisual.classList.remove('hidden');
        window.setTimeout(() => awardVisual.classList.add('hidden'), 1300);
    };

    const ensureEmptyState = () => {
        const taskItems = todoListElement.querySelectorAll('.task-item');
        const existingEmpty = todoListElement.querySelector('.task-empty');

        if (taskItems.length === 0 && !existingEmpty) {
            const emptyItem = document.createElement('li');
            emptyItem.className = 'task-empty';
            emptyItem.textContent = 'No tasks yet. Start with one small win.';
            todoListElement.appendChild(emptyItem);
        } else if (taskItems.length > 0 && existingEmpty) {
            existingEmpty.remove();
        }
    };

    const reindexTasks = () => {
        const taskItems = todoListElement.querySelectorAll('.task-item');
        taskItems.forEach((item, index) => {
            item.dataset.index = String(index);
        });
    };

    const buildTaskElement = (taskText, taskIndex) => {
        const item = document.createElement('li');
        item.className = 'task-item';
        item.dataset.index = String(taskIndex);

        const textElement = document.createElement('span');
        textElement.className = 'task-text';
        textElement.textContent = taskText;

        const completeButton = document.createElement('button');
        completeButton.type = 'button';
        completeButton.className = 'toggle-btn';
        completeButton.textContent = 'Complete';

        item.append(textElement, completeButton);
        return item;
    };

    renderClock();
    window.setInterval(renderClock, 1000);
    ensureEmptyState();

    todoFormElement.addEventListener('submit', async (event) => {
        event.preventDefault();
        const taskText = todoInputElement.value.trim();
        if (!taskText) {
            renderStatus('Task cannot be empty.', 'error');
            return;
        }

        try {
            const response = await fetch('/add_task', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
                },
                body: new URLSearchParams({ task: taskText }),
            });
            const data = await response.json();
            if (!data.success) {
                renderStatus(data.error || 'Unable to add task.', 'error');
                return;
            }

            const taskItem = buildTaskElement(taskText, data.index);
            todoListElement.appendChild(taskItem);
            todoInputElement.value = '';
            ensureEmptyState();
            renderStatus('Task added.', 'success');
        } catch (_error) {
            renderStatus('Network issue while adding task.', 'error');
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
            try {
                const response = await fetch('/update_task', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
                    },
                    body: new URLSearchParams({ index: taskItem.dataset.index || '', text: newText }),
                });
                const data = await response.json();
                if (!data.success) {
                    renderStatus(data.error || 'Unable to update task.', 'error');
                    return;
                }
                target.textContent = data.text;
                renderStatus('Task updated.', 'success');
            } catch (_error) {
                renderStatus('Network issue while updating task.', 'error');
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

    todoListElement.addEventListener('click', async (event) => {
        const target = event.target;
        if (!(target instanceof HTMLButtonElement) || !target.classList.contains('toggle-btn')) {
            return;
        }

        const taskItem = target.closest('.task-item');
        if (!taskItem) {
            return;
        }

        const index = taskItem.dataset.index || '';
        try {
            const response = await fetch('/toggle_task', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
                },
                body: new URLSearchParams({ index }),
            });
            const data = await response.json();
            if (!data.success) {
                renderStatus(data.error || 'Unable to complete task.', 'error');
                return;
            }

            taskItem.remove();
            reindexTasks();
            ensureEmptyState();
            showAward();
        } catch (_error) {
            renderStatus('Network issue while updating task.', 'error');
        }
    });
});
