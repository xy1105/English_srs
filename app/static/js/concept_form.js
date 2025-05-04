// app/static/js/concept_form.js

/**
 * Handles dynamic form elements (add/remove meanings, collocations)
 * on the add/edit concept page.
 */
document.addEventListener('DOMContentLoaded', function() {
    const meaningsContainer = document.getElementById('meaningsContainer');
    const addMeaningBtn = document.getElementById('addMeaningBtn');
    const meaningTemplateHTML = document.getElementById('meaningTemplate')?.innerHTML;
    const meaningsCountBadge = document.getElementById('meaningsCountBadge');

    const collocationsContainer = document.getElementById('collocationsContainer');
    const addCollocationBtn = document.getElementById('addCollocationBtn');
    const collocationTemplateHTML = document.getElementById('collocationTemplate')?.innerHTML;
    const collocationsCountBadge = document.getElementById('collocationsCountBadge');

    // --- Helper Functions ---

    /**
     * Updates the count displayed in a badge.
     * @param {HTMLElement} container The container holding the items.
     * @param {HTMLElement} badge The badge element to update.
     */
    function updateCountBadge(container, badge) {
        if (container && badge) {
            // Count direct children that match the group class
            const count = container.querySelectorAll(':scope > .meaning-group, :scope > .collocation-group').length;
            badge.textContent = count;
        }
    }

    /**
     * Adds a new item (meaning or collocation) to the form.
     * @param {HTMLElement} container Container element.
     * @param {string} templateHTML HTML template string.
     * @param {string} typePrefix 'meaning' or 'collocation'.
     * @param {HTMLElement} badge Badge element for count update.
     */
    function addItem(container, templateHTML, typePrefix, badge) {
        if (!container || !templateHTML) {
            console.error("Cannot add item: Container or template missing for", typePrefix);
            return;
        }
        // Determine the next index based on current number of groups
        let indexCounter = container.querySelectorAll(`.${typePrefix}-group`).length;

        const tempDiv = document.createElement('div');
        // Replace placeholder index in the template HTML string
        tempDiv.innerHTML = templateHTML.replace(/__INDEX__/g, indexCounter);
        const newItem = tempDiv.firstElementChild; // Get the actual element (.meaning-group or .collocation-group)

        if (!newItem) {
            console.error("Failed to create new item element from template for", typePrefix);
            return;
        }

        // --- Add Animation Class (Entrance) ---
        newItem.classList.add('form-item-enter');
        container.appendChild(newItem);
        // Trigger reflow before adding active class for transition
        void newItem.offsetWidth;
        newItem.classList.add('form-item-enter-active');

        // Remove animation classes after transition ends
        setTimeout(() => {
             newItem.classList.remove('form-item-enter', 'form-item-enter-active');
        }, 300); // Match CSS transition duration

        // --- Add Event Listener for the Remove Button ---
        const removeBtn = newItem.querySelector('.remove-item-btn');
        if (removeBtn) {
            removeBtn.addEventListener('click', function() {
                removeItem(newItem, container, badge);
            });
        } else {
            console.warn("Newly added item is missing a remove button for", typePrefix);
        }

        updateCountBadge(container, badge);
    }

    /**
     * Removes an item from the form with animation.
     * @param {HTMLElement} itemToRemove The item element to remove.
     * @param {HTMLElement} container The parent container.
     * @param {HTMLElement} badge The count badge to update.
     */
    function removeItem(itemToRemove, container, badge) {
         if (!itemToRemove) return;

         // --- Add Animation Class (Exit) ---
         itemToRemove.classList.add('form-item-leave-active');

         // Remove the element after animation completes
         setTimeout(() => {
            itemToRemove.remove();
            updateCountBadge(container, badge);
            // Optional: Renumber indices of remaining items if necessary,
            // but usually backend handles gaps gracefully by index order.
         }, 200); // Match CSS transition duration (slightly shorter for removal?)
    }

    // --- Event Listeners for Add Buttons ---
    if (addMeaningBtn && meaningsContainer && meaningTemplateHTML) {
        addMeaningBtn.addEventListener('click', function() {
            addItem(meaningsContainer, meaningTemplateHTML, 'meaning', meaningsCountBadge);
        });
    } else if (addMeaningBtn) {
         console.warn("Add Meaning button found, but container or template might be missing.");
    }

    if (addCollocationBtn && collocationsContainer && collocationTemplateHTML) {
        addCollocationBtn.addEventListener('click', function() {
            addItem(collocationsContainer, collocationTemplateHTML, 'collocation', collocationsCountBadge);
        });
    } else if (addCollocationBtn) {
        console.warn("Add Collocation button found, but container or template might be missing.");
    }

    // --- Add Event Listeners to Existing Remove Buttons (for items loaded on edit page) ---
    document.querySelectorAll('#meaningsContainer .remove-item-btn, #collocationsContainer .remove-item-btn').forEach(button => {
        button.addEventListener('click', function() {
            const group = button.closest('.meaning-group, .collocation-group');
            const container = group.parentElement; // meaningsContainer or collocationsContainer
            const badge = (container === meaningsContainer) ? meaningsCountBadge : collocationsCountBadge;
            if (group) {
                removeItem(group, container, badge);
            }
        });
    });

    // --- Initial Count Update on Page Load ---
    updateCountBadge(meaningsContainer, meaningsCountBadge);
    updateCountBadge(collocationsContainer, collocationsCountBadge);

});