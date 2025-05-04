/**
 * Handles JavaScript interactions for the history.html page.
 * Currently, only initializes Bootstrap tooltips.
 */

document.addEventListener('DOMContentLoaded', function () {
    // Initialize Bootstrap Tooltips for elements on this page (if any)
    if (typeof initializeBootstrapTooltips === 'function') {
        initializeBootstrapTooltips();
        console.debug("History page tooltips initialized.");
    } else {
        console.warn("Global function 'initializeBootstrapTooltips' not found for history page.");
    }
});