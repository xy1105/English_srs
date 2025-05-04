/**
 * Handles JavaScript specific to the wrong_concepts.html page.
 * Currently, only initializes Bootstrap tooltips.
 */
document.addEventListener('DOMContentLoaded', function () {
    // Initialize Bootstrap Tooltips for elements on this page
    // (uses the global initializer function from script.js)
    if (typeof initializeBootstrapTooltips === 'function') {
        initializeBootstrapTooltips();
        console.debug("Wrong concepts page tooltips initialized.");
    } else {
        console.warn("Global function 'initializeBootstrapTooltips' not found.");
        // Fallback basic initialization if global func fails
        try {
             const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
             tooltipTriggerList.map(function (tooltipTriggerEl) {
                 return new bootstrap.Tooltip(tooltipTriggerEl);
             });
        } catch(e) {
             console.error("Fallback tooltip initialization failed:", e);
        }
    }
});