// app/static/js/manage_concepts.js

/**
 * Handles JavaScript interactions on the manage_concepts.html page, including:
 * - Delete confirmation modal logic.
 * - Activating the correct view switcher button.
 * - Handling expand/collapse buttons for concept details.
 */

document.addEventListener('DOMContentLoaded', function() {

    // --- Delete Confirmation Modal ---
    const deleteConfirmModal = document.getElementById('deleteConfirmModal');
    if (deleteConfirmModal) {
        deleteConfirmModal.addEventListener('show.bs.modal', function (event) {
            const button = event.relatedTarget; // Button that triggered the modal
            if (!button) return; // Exit if modal wasn't triggered by a button

            // Extract data attributes from the button
            const itemId = button.getAttribute('data-bs-item-id');
            const itemTerm = button.getAttribute('data-bs-item-term');
            const itemType = button.getAttribute('data-bs-item-type'); // 'concept' or 'collocation' (though only concept delete implemented)
            const originView = button.getAttribute('data-bs-origin-view');
            const originPage = button.getAttribute('data-bs-origin-page');
            const originSearch = button.getAttribute('data-bs-origin-search');
            const originTag = button.getAttribute('data-bs-origin-tag');
            const originPos = button.getAttribute('data-bs-origin-pos');

            // Update modal content
            const itemTypeText = (itemType === 'concept') ? '单词/概念' : '搭配';
            const termToDeleteSpan = deleteConfirmModal.querySelector('#termToDelete');
            const itemTypeSpan = deleteConfirmModal.querySelector('#itemTypeToDelete');
            const warningSpan = deleteConfirmModal.querySelector('#deleteConceptWarning');

            if (termToDeleteSpan) termToDeleteSpan.textContent = itemTerm || '该项目';
            if (itemTypeSpan) itemTypeSpan.textContent = itemTypeText;

            // Show concept-specific warning
            if (warningSpan) {
                warningSpan.classList.toggle('d-none', itemType !== 'concept');
            }

            // --- Set up the delete form ---
            const deleteForm = deleteConfirmModal.querySelector('#deleteForm');
            const submitButton = deleteForm ? deleteForm.querySelector('button[type="submit"]') : null;

            if (deleteForm && submitButton) {
                 // Define base URLs (replace with actual base URL generation if needed, but Flask's url_for is better)
                 // This is a fallback if url_for cannot be easily used in JS directly without passing from template
                 const conceptDeleteBaseUrl = '/concepts/delete/'; // Adjust if URL prefix changes

                 let formAction = '#'; // Default to non-functional
                 submitButton.disabled = true; // Disable by default

                 if (itemType === 'concept' && itemId) {
                     formAction = `${conceptDeleteBaseUrl}${itemId}`; // Construct URL
                     submitButton.disabled = false; // Enable for concepts
                 } else {
                     console.warn("Deletion for item type '" + itemType + "' is not implemented or item ID is missing.");
                 }

                 deleteForm.action = formAction;

                 // Populate hidden fields for redirect parameters
                 const setHiddenInput = (id, value) => {
                    const input = deleteForm.querySelector(`#${id}`);
                    if (input) input.value = value || '';
                 };
                 setHiddenInput('deleteOriginView', originView);
                 setHiddenInput('deleteOriginPage', originPage);
                 setHiddenInput('deleteOriginSearch', originSearch);
                 setHiddenInput('deleteOriginTag', originTag);
                 setHiddenInput('deleteOriginPos', originPos);

            } else {
                console.error("Delete form or submit button not found in modal.");
            }
        });

        // Optional: Reset button state when modal hides, just in case
        deleteConfirmModal.addEventListener('hide.bs.modal', function (event) {
            const submitButton = deleteConfirmModal.querySelector('#deleteForm button[type="submit"]');
            if (submitButton) {
                submitButton.disabled = false; // Re-enable on close
            }
        });
    } else {
        console.debug("Delete confirmation modal not found on this page.");
    }


    // --- Activate View Switcher Button ---
    // Get current view from URL query parameters
    try {
        const urlParams = new URLSearchParams(window.location.search);
        const currentView = urlParams.get('view') || 'concepts'; // Default to concepts

        const conceptBtn = document.querySelector('.view-switcher a[href*="view=concepts"]');
        const collBtn = document.querySelector('.view-switcher a[href*="view=collocations"]');

        const setActive = (btn, isActive) => {
            if (btn) {
                btn.classList.toggle('active', isActive);
                btn.classList.toggle('btn-primary', isActive);
                btn.classList.toggle('btn-outline-primary', !isActive);
                btn.setAttribute('aria-current', isActive ? 'page' : 'false');
            }
        };

        setActive(conceptBtn, currentView === 'concepts');
        setActive(collBtn, currentView === 'collocations');

    } catch (e) {
         console.error("Error activating view switcher:", e);
    }

    // --- Expand/Collapse Button Icon Toggle ---
    // Add event listener to all collapse triggers within the concept list
    const collapseElements = document.querySelectorAll('.concept-list [data-bs-toggle="collapse"]');
    collapseElements.forEach(button => {
        const targetId = button.getAttribute('data-bs-target');
        if (!targetId) return;

        const targetCollapse = document.querySelector(targetId);
        if (!targetCollapse) return;

        // Update icon when collapse is shown
        targetCollapse.addEventListener('shown.bs.collapse', function () {
             button.setAttribute('aria-expanded', 'true');
             // Optional: Change icon class or content if needed (CSS handles this now)
             // console.debug(`Collapse ${targetId} shown`);
        });

        // Update icon when collapse is hidden
        targetCollapse.addEventListener('hidden.bs.collapse', function () {
             button.setAttribute('aria-expanded', 'false');
              // Optional: Change icon class or content if needed (CSS handles this now)
             // console.debug(`Collapse ${targetId} hidden`);
        });
    });

});