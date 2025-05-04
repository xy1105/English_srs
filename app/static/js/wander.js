/**
 * Handles JavaScript interactions for the wander_display.html page.
 * Currently, only includes audio playback initialization.
 */
document.addEventListener('DOMContentLoaded', function() {

    // Uses the global playAudio function from script.js
    document.querySelectorAll('.btn-play-audio').forEach(button => {
        const onclickAttr = button.getAttribute('onclick');
        // Check if the button has the expected inline onclick attribute
        if (!onclickAttr || !onclickAttr.includes('playAudio')) {
             console.warn("Wander Display: Audio button found without expected inline onclick.", button);
        }
    });

    console.debug("Wander display script initialized.");

}); // End DOMContentLoaded