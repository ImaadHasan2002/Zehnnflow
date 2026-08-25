document.addEventListener('DOMContentLoaded', () => {
    const resolveTrackFormElement = document.getElementById('resolve-track-form');
    const trackUrlInputElement = document.getElementById('track-url-input');
    const trackStatusElement = document.getElementById('track-status');
    const quickTrackGridElement = document.getElementById('quick-track-grid');
    const trackTitleElement = document.getElementById('track-title');
    const trackMetaElement = document.getElementById('track-meta');
    const playerElement = document.getElementById('focus-player');
    const saveTrackFormElement = document.getElementById('save-track-form');
    const saveTrackTitleElement = document.getElementById('save-track-title');
    const saveTrackUrlElement = document.getElementById('save-track-url');
    const timerDisplayElement = document.getElementById('timer-display');
    const startTimerButton = document.getElementById('start-timer-btn');
    const pauseTimerButton = document.getElementById('pause-timer-btn');
    const resetTimerButton = document.getElementById('reset-timer-btn');

    if (
        !resolveTrackFormElement
        || !trackUrlInputElement
        || !trackStatusElement
        || !quickTrackGridElement
        || !trackTitleElement
        || !trackMetaElement
        || !playerElement
        || !saveTrackFormElement
        || !saveTrackTitleElement
        || !saveTrackUrlElement
        || !timerDisplayElement
        || !startTimerButton
        || !pauseTimerButton
        || !resetTimerButton
    ) {
        return;
    }

    let timerSeconds = 25 * 60;
    let timerIntervalId = null;
    const defaultSeconds = timerSeconds;

    const setTrackStatus = (message, variant = '') => {
        trackStatusElement.textContent = message;
        trackStatusElement.classList.remove('error', 'success');
        if (variant) {
            trackStatusElement.classList.add(variant);
        }
    };

    const renderTimer = () => {
        const minutes = Math.floor(timerSeconds / 60);
        const seconds = timerSeconds % 60;
        timerDisplayElement.textContent = `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
    };

    const stopTimer = () => {
        if (timerIntervalId !== null) {
            window.clearInterval(timerIntervalId);
            timerIntervalId = null;
        }
    };

    const startTimer = () => {
        if (timerIntervalId !== null) {
            return;
        }

        timerIntervalId = window.setInterval(() => {
            if (timerSeconds <= 0) {
                stopTimer();
                setTrackStatus('Session complete. Great work.', 'success');
                return;
            }
            timerSeconds -= 1;
            renderTimer();
        }, 1000);
    };

    const loadTrack = async (url, titleHint = '') => {
        if (!url) {
            setTrackStatus('Please paste a valid YouTube URL.', 'error');
            return;
        }

        setTrackStatus('Loading track metadata...');
        try {
            const response = await fetch('/focus/resolve', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ url }),
            });
            const data = await response.json();
            if (!data.success) {
                setTrackStatus(data.error || 'Unable to load track.', 'error');
                return;
            }

            const track = data.track;
            playerElement.classList.remove('hidden');
            playerElement.src = `${track.embed_url}?autoplay=1&rel=0`;
            trackTitleElement.textContent = track.title || titleHint || 'Focus track';

            const metaParts = [];
            if (track.uploader) {
                metaParts.push(track.uploader);
            }
            if (track.duration) {
                metaParts.push(track.duration);
            }
            trackMetaElement.textContent = metaParts.length ? metaParts.join(' • ') : 'Now playing in embedded mode.';
            setTrackStatus('Track ready.', 'success');
        } catch (_error) {
            setTrackStatus('Network issue while loading track.', 'error');
        }
    };

    resolveTrackFormElement.addEventListener('submit', async (event) => {
        event.preventDefault();
        const url = trackUrlInputElement.value.trim();
        await loadTrack(url);
    });

    quickTrackGridElement.addEventListener('click', async (event) => {
        const target = event.target;
        if (!(target instanceof HTMLButtonElement) || !target.classList.contains('quick-track-btn')) {
            return;
        }
        const trackUrl = target.dataset.trackUrl || '';
        const trackTitle = target.dataset.trackTitle || '';
        trackUrlInputElement.value = trackUrl;
        await loadTrack(trackUrl, trackTitle);
    });

    saveTrackFormElement.addEventListener('submit', async (event) => {
        event.preventDefault();
        const title = saveTrackTitleElement.value.trim();
        const url = saveTrackUrlElement.value.trim();
        if (!title || !url) {
            setTrackStatus('Track title and URL are required.', 'error');
            return;
        }

        try {
            const response = await fetch('/focus/add_track', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ title, url }),
            });
            const data = await response.json();
            if (!data.success) {
                setTrackStatus(data.error || 'Unable to save track.', 'error');
                return;
            }

            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'quick-track-btn';
            button.dataset.trackUrl = data.track.url;
            button.dataset.trackTitle = data.track.title;
            button.textContent = data.track.title;
            quickTrackGridElement.appendChild(button);

            saveTrackFormElement.reset();
            setTrackStatus('Track saved to quick list.', 'success');
        } catch (_error) {
            setTrackStatus('Network issue while saving track.', 'error');
        }
    });

    document.querySelectorAll('.timer-preset-btn').forEach((button) => {
        button.addEventListener('click', () => {
            const minutes = Number(button.dataset.minutes || '25');
            timerSeconds = minutes * 60;
            stopTimer();
            renderTimer();
            setTrackStatus(`Timer set to ${minutes} minutes.`);
        });
    });

    startTimerButton.addEventListener('click', () => {
        startTimer();
        setTrackStatus('Focus timer started.');
    });

    pauseTimerButton.addEventListener('click', () => {
        stopTimer();
        setTrackStatus('Focus timer paused.');
    });

    resetTimerButton.addEventListener('click', () => {
        stopTimer();
        timerSeconds = defaultSeconds;
        renderTimer();
        setTrackStatus('Focus timer reset to 25 minutes.');
    });

    renderTimer();
});
