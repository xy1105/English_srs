/**
 * Handles JavaScript interactions for the practice_session.html page.
 * Includes showing the answer, handling quality button clicks via keyboard,
 * playing audio, and confirm quit.
 */
document.addEventListener('DOMContentLoaded', function() {
    const showAnswerBtn = document.getElementById('showAnswerBtn');
    const answerSection = document.getElementById('answerSection');
    const reviewForm = document.getElementById('reviewForm'); // Get the form itself

    // --- Function to Show Answer ---
    function showAnswer() {
         if (answerSection && showAnswerBtn && !answerSection.classList.contains('visible')) {
            console.debug("Showing answer section.");
            answerSection.classList.add('visible');
            showAnswerBtn.classList.add('hidden'); // Hide button using CSS

            // Focus the first quality button for keyboard navigation/submission
            const firstQualityButton = answerSection.querySelector('button[name="quality"]');
            if (firstQualityButton) {
                 setTimeout(() => firstQualityButton.focus(), 100);
            }
         }
    }

    // --- Event Listener for Show Answer Button ---
    if (showAnswerBtn) {
        showAnswerBtn.addEventListener('click', showAnswer);
    } else {
        console.debug("Show Answer button not found.");
    }

    // --- Keyboard Shortcuts ---
    document.addEventListener('keydown', function(event) {
        // Ignore shortcuts if user is typing in an input/textarea
        const isInputFocused = document.activeElement.tagName === 'INPUT' || document.activeElement.tagName === 'TEXTAREA';
        if (isInputFocused) return;

        const isAnswerVisible = answerSection && answerSection.classList.contains('visible');

        // --- Spacebar to Show Answer ---
        if (event.code === 'Space' && !isAnswerVisible && showAnswerBtn && !showAnswerBtn.classList.contains('hidden')) {
             console.debug("Spacebar pressed to show answer.");
             event.preventDefault(); // Prevent default spacebar action (scrolling)
             showAnswer();
             return; // Stop further processing for this keydown
        }

        // --- Number Keys (1-4) for Quality Rating ---
        if (isAnswerVisible && reviewForm) {
            const qualityMap = {
                 'Digit1': 'again', 'Numpad1': 'again',
                 'Digit2': 'hard',  'Numpad2': 'hard',
                 'Digit3': 'good',  'Numpad3': 'good',
                 'Digit4': 'easy',  'Numpad4': 'easy'
            };
            const qualityValue = qualityMap[event.code];

            if (qualityValue) {
                console.debug(`Quality key '${event.code}' pressed for value '${qualityValue}'`);
                event.preventDefault();

                const button = reviewForm.querySelector(`button[name="quality"][value="${qualityValue}"]`);
                if (button) {
                    button.classList.add('active'); // Add bootstrap's active state briefly
                    setTimeout(() => button.classList.remove('active'), 150);
                    button.focus();
                    setTimeout(() => button.click(), 50); // Submit the form
                } else {
                     console.warn(`Button for quality value '${qualityValue}' not found.`);
                }
            }
        }
    });

    // --- Audio Play Initialization ---
    // Relies on the global `playAudio` function defined in script.js
    document.querySelectorAll('.btn-play-audio').forEach(button => {
        const onclickAttr = button.getAttribute('onclick');
        if (!onclickAttr || !onclickAttr.includes('playAudio')) {
            console.warn("Practice Session: Audio button found without expected inline onclick.", button);
        }
    });

    // --- Initialize Tooltips (for quality buttons) ---
    // Uses global function if available
    if (typeof initializeBootstrapTooltips === 'function') {
        initializeBootstrapTooltips();
        console.debug("Practice session tooltips initialized.");
    } else {
        console.warn("Global function 'initializeBootstrapTooltips' not found for practice page.");
    }

    console.debug("Practice session script initialized.");

}); // End DOMContentLoaded