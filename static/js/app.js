document.addEventListener('DOMContentLoaded', function () {
    const clockElement = document.getElementById('clock');
    const todoListElement = document.getElementById('todo-list');
    const todoInputElement = document.getElementById('todo-input');
    const addBtnElement = document.getElementById('add-btn');
    const awardVisual = document.getElementById('award-visual');

    function updateClock() {
        const now = new Date();
        const hours = String(now.getHours()).padStart(2, '0');
        const minutes = String(now.getMinutes()).padStart(2, '0');
        clockElement.textContent = `${hours}:${minutes}`;
    }

    setInterval(updateClock, 1000);
    updateClock();

    function showAward() {
        awardVisual.classList.remove('hidden');
        setTimeout(() => awardVisual.classList.add('hidden'), 1000);
    }

    function addTodoItem() {
        const todoText = todoInputElement.value.trim();
        if (todoText === '') return;

        $.post('/add_task', { task: todoText }, function(data) {
            if (data.success) {
                const li = document.createElement('li');
                li.textContent = todoText;
                li.dataset.index = todoListElement.children.length;

                const toggleBtn = document.createElement('button');
                toggleBtn.textContent = 'Complete Task';
                toggleBtn.className = 'toggle-btn';  // Ensure class name is added here
                toggleBtn.style.backgroundColor = 'black';
                toggleBtn.style.color = 'white';
                toggleBtn.style.borderRadius = '25px';

                li.appendChild(toggleBtn);
                todoListElement.appendChild(li);
                todoInputElement.value = '';
            }
        });
    }

    addBtnElement.addEventListener('click', addTodoItem);
    todoInputElement.addEventListener('keypress', function (e) {
        if (e.key === 'Enter') {
            e.preventDefault(); // Prevent form submission
            addTodoItem();
        }
    });

    todoListElement.addEventListener('click', function(e) {
        if (e.target.classList.contains('toggle-btn')) {
            const li = e.target.parentElement;
            const index = li.dataset.index;

            $.post('/toggle_task', { index: index }, function(data) {
                if (data.success) {
                    li.classList.toggle('completed');
                    if (li.classList.contains('completed')) {
                        showAward();
                    }
                }
            });
        }
    });
});
