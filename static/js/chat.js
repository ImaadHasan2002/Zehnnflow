document.addEventListener('DOMContentLoaded', () => {
    const chatMessagesElement = document.getElementById('chat-messages');
    const rateInputElement = document.getElementById('speech-rate');
    const pitchInputElement = document.getElementById('speech-pitch');
    const stopSpeechButton = document.getElementById('stop-speech-btn');
    const ttsStatusElement = document.getElementById('tts-status');

    if (!chatMessagesElement || !rateInputElement || !pitchInputElement || !stopSpeechButton || !ttsStatusElement) {
        return;
    }

    const speechSupported = 'speechSynthesis' in window && 'SpeechSynthesisUtterance' in window;

    const updateStatus = (message, variant = '') => {
        ttsStatusElement.textContent = message;
        ttsStatusElement.classList.remove('error', 'success');
        if (variant) {
            ttsStatusElement.classList.add(variant);
        }
    };

    if (!speechSupported) {
        updateStatus('Read-aloud is not supported in this environment.', 'error');
        chatMessagesElement.querySelectorAll('.speak-btn').forEach((button) => {
            button.setAttribute('disabled', 'disabled');
        });
        stopSpeechButton.setAttribute('disabled', 'disabled');
        return;
    }

    const speakText = (text) => {
        if (!text.trim()) {
            updateStatus('This response has no readable text.', 'error');
            return;
        }

        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.rate = Number(rateInputElement.value || '1');
        utterance.pitch = Number(pitchInputElement.value || '1');
        utterance.onend = () => updateStatus('Read-aloud complete.', 'success');
        utterance.onerror = () => updateStatus('Speech playback failed.', 'error');
        window.speechSynthesis.speak(utterance);
        updateStatus('Reading response...');
    };

    chatMessagesElement.addEventListener('click', (event) => {
        const target = event.target;
        if (!(target instanceof HTMLButtonElement) || !target.classList.contains('speak-btn')) {
            return;
        }

        const messageElement = target.closest('.message');
        const messageBodyElement = messageElement?.querySelector('.message-body');
        if (!messageBodyElement) {
            updateStatus('Could not locate message body.', 'error');
            return;
        }

        speakText(messageBodyElement.textContent || '');
    });

    stopSpeechButton.addEventListener('click', () => {
        window.speechSynthesis.cancel();
        updateStatus('Read-aloud stopped.');
    });

    chatMessagesElement.scrollTop = chatMessagesElement.scrollHeight;
});
