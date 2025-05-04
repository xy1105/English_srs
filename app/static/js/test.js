// app/static/js/test.js

document.addEventListener('DOMContentLoaded', function() {

    // === Test Setup Page Logic ===
    const mode1Radio = document.getElementById('mode1');
    const mode2Radio = document.getElementById('mode2');
    const mode3Radio = document.getElementById('mode3');
    const mode2SubOptionsDiv = document.getElementById('mode2_sub_options');
    const mode3SubOptionsDiv = document.getElementById('mode3_sub_options');
    const tagSelect = document.getElementById('tag_filter');
    const countDisplay = document.getElementById('filteredConceptCount');
    const tagCountLoading = document.getElementById('tag-count-loading');
    const quantityInput = document.getElementById('quantity');

    let tagCountsCache = null;

    async function fetchTagCounts() {
        if (tagCountsCache) return tagCountsCache;
        if (tagCountLoading) tagCountLoading.style.display = 'inline';
        try {
            const response = await fetch('/test/api/count_by_tag');
            if (!response.ok) throw new Error(`HTTP error ${response.status}`);
            const data = await response.json();
            tagCountsCache = data;
            console.debug("Fetched tag counts:", data);
            return data;
        } catch (error) {
            console.error('Error fetching tag counts:', error);
            return null;
        } finally {
             if (tagCountLoading) tagCountLoading.style.display = 'none';
        }
    }

    function populateTagCounts(countsData) {
        if (!tagSelect || !countsData || !countsData.tags) return;
        tagSelect.options.length = 0;
        const allOption = document.createElement('option');
        allOption.value = "";
        allOption.textContent = `所有单词 (${countsData.all || 0})`;
        allOption.selected = true;
        allOption.setAttribute('data-count', countsData.all || 0);
        tagSelect.appendChild(allOption);
        countsData.tags.forEach(tag => {
            const option = document.createElement('option');
            option.value = tag.id;
            option.textContent = `${tag.name} (${tag.concept_count || 0})`;
            option.setAttribute('data-count', tag.concept_count || 0);
            tagSelect.appendChild(option);
        });
        updateFilteredCountDisplay();
    }

    function updateFilteredCountDisplay() {
        if (!tagSelect || !countDisplay) return;
        try {
             const selectedOption = tagSelect.options[tagSelect.selectedIndex];
             const count = selectedOption.getAttribute('data-count');
             countDisplay.textContent = count || '所选标签';
             if (quantityInput && count) {
                 quantityInput.max = count;
             } else if (quantityInput) {
                 quantityInput.removeAttribute('max');
             }
        } catch(e) {
             console.error("Error updating filtered count display:", e);
             countDisplay.textContent = 'N/A';
        }
    }

    if (tagSelect) {
        fetchTagCounts().then(counts => {
            if (counts) populateTagCounts(counts);
            tagSelect.addEventListener('change', updateFilteredCountDisplay);
        });
        console.debug("Test setup tag filter count initialization started.");
    }

    function toggleSubOptions() {
        const mode2Selected = mode2Radio && mode2Radio.checked;
        const mode3Selected = mode3Radio && mode3Radio.checked;

        if (mode2SubOptionsDiv) {
            const subRadios2 = mode2SubOptionsDiv.querySelectorAll('input[type="radio"]');
            mode2SubOptionsDiv.style.display = mode2Selected ? 'block' : 'none';
            subRadios2.forEach(radio => radio.disabled = !mode2Selected);
            if (mode2Selected && !mode2SubOptionsDiv.querySelector('input[name="test_mode_sub_2"]:checked')) {
                (document.getElementById('sub_meaning') || subRadios2[0])?.setAttribute('checked', true);
            }
        }
        if (mode3SubOptionsDiv) {
            const subRadios3 = mode3SubOptionsDiv.querySelectorAll('input[type="radio"]');
            mode3SubOptionsDiv.style.display = mode3Selected ? 'block' : 'none';
            subRadios3.forEach(radio => radio.disabled = !mode3Selected);
            if (mode3Selected && !mode3SubOptionsDiv.querySelector('input[name="test_mode_sub_3"]:checked')) {
                 (document.getElementById('sub_blank_term') || subRadios3[0])?.setAttribute('checked', true);
            }
        }
    }

    [mode1Radio, mode2Radio, mode3Radio].forEach(radio => {
        if (radio) radio.addEventListener('change', toggleSubOptions);
    });

    if (mode1Radio) {
        toggleSubOptions();
        console.debug("Test setup mode toggles initialized.");
    }


    // === Test Session Page Logic ===
    const showAnswerBtn = document.getElementById('showAnswerBtn');
    const answerSection = document.getElementById('answerSection');
    const judgmentForm = document.getElementById('judgmentForm');
    const answerInputMeaning = document.getElementById('answerInputMeaning');
    const answerInputPhrase = document.getElementById('answerInputPhrase');
    const showHintBtn = document.getElementById('showHintBtn');
    const hintSection = document.getElementById('hintSection');
    const listRecallTable = document.querySelector('.list-recall-table');

    const isMode1Or2 = showAnswerBtn && answerSection && judgmentForm && !listRecallTable;
    const isMode3 = listRecallTable && judgmentForm;

    if (isMode1Or2) {
        console.debug("Initializing Mode 1/2 test session JS.");
        function showAnswer() {
             if (!answerSection.classList.contains('visible')) {
                console.debug("Showing test answer section.");
                answerSection.classList.add('visible');
                showAnswerBtn.style.display = 'none';
                if (showHintBtn) showHintBtn.style.display = 'none';
                if (hintSection) hintSection.classList.remove('visible');
                const firstJudgmentButton = judgmentForm.querySelector('button[name="result"]');
                if (firstJudgmentButton) setTimeout(() => firstJudgmentButton.focus(), 100);
             }
        }
        showAnswerBtn.addEventListener('click', showAnswer);
        if (showHintBtn && hintSection) {
            showHintBtn.addEventListener('click', function() {
                console.debug("Showing hint.");
                hintSection.classList.add('visible');
                showHintBtn.style.display = 'none';
            });
        }
        document.addEventListener('keydown', function(event) {
             const isAnswerVisible = answerSection.classList.contains('visible');
             const isInputFocused = document.activeElement === answerInputMeaning || document.activeElement === answerInputPhrase;
             const isButtonFocused = document.activeElement.tagName === 'BUTTON';

             if (event.code === 'Space' && !isInputFocused && !isButtonFocused && !isAnswerVisible && showAnswerBtn.style.display !== 'none') {
                  console.debug("Spacebar pressed to show test answer.");
                  event.preventDefault();
                  showAnswer();
                  return;
             }
             if (isAnswerVisible && !isInputFocused) {
                 let targetButton = null;
                 if (event.key === 'ArrowLeft' || event.key.toLowerCase() === 'i') { targetButton = judgmentForm.querySelector('button[value="incorrect"]'); }
                 else if (event.key === 'ArrowRight' || event.key.toLowerCase() === 'c') { targetButton = judgmentForm.querySelector('button[value="correct"]'); }

                 if (targetButton) {
                     console.debug(`Judgment key '${event.key || event.code}' pressed for '${targetButton.value}'`);
                     event.preventDefault();
                     targetButton.focus();
                     targetButton.classList.add('active');
                     setTimeout(() => targetButton.classList.remove('active'), 150);
                     setTimeout(() => targetButton.click(), 50);
                 }
             }
             if (!isAnswerVisible && (event.key === 'Enter') && (document.activeElement === answerInputMeaning || document.activeElement === answerInputPhrase)) {
                 console.debug("Enter pressed in input field to show answer.");
                 event.preventDefault();
                 showAnswer();
             }
        });

    } else if (isMode3) {
        console.debug("Initializing Mode 3 test session JS.");
        const rows = listRecallTable.querySelectorAll('tbody tr');
        const totalItems = rows.length;
        const submitButton = document.getElementById('submitListResultsBtn');
        const markedCountSpan = document.getElementById('marked_count');
        const correctInput = document.getElementById('total_correct_input');
        const incorrectInput = document.getElementById('total_incorrect_input');
        let markedItems = 0;
        let correctCount = 0;
        let incorrectCount = 0;

        rows.forEach(row => {
            const blankArea = row.querySelector('.blank-area');
            // No longer needed: const answerContent = row.querySelector('.answer-content');
            const correctBtn = row.querySelector('.mark-correct');
            const incorrectBtn = row.querySelector('.mark-incorrect');
            const btnGroup = row.querySelector('.judgment-buttons-list');
            const correctIndicator = row.querySelector('.correct-indicator');
            const incorrectIndicator = row.querySelector('.incorrect-indicator');
            let isMarked = false;
            let wasCorrect = null;

            // --- CORRECTED: Click Listener for blankArea ---
            if (blankArea) {
                blankArea.addEventListener('click', () => {
                    // Toggle the 'revealed' class on the blankArea itself
                    blankArea.classList.toggle('revealed');
                    console.debug('Toggled revealed class on blank area.');
                });
            }

            function updateCounts() {
                if (markedCountSpan) markedCountSpan.textContent = markedItems;
                if (correctInput) correctInput.value = correctCount;
                if (incorrectInput) incorrectInput.value = incorrectCount;
                if (submitButton) submitButton.disabled = (markedItems !== totalItems);
            }

            function markRow(isCorrect) {
                const rowTR = correctBtn.closest('tr'); // Get the parent row
                if (!rowTR) return;

                if (!isMarked) {
                    markedItems++;
                    isMarked = true;
                } else {
                    if (wasCorrect === true) correctCount--;
                    if (wasCorrect === false) incorrectCount--;
                }

                if (isCorrect) {
                    correctCount++;
                    wasCorrect = true;
                    correctIndicator?.classList.remove('d-none');
                    incorrectIndicator?.classList.add('d-none');
                    rowTR.classList.add('table-success'); // Apply class to TR
                    rowTR.classList.remove('table-danger');
                } else {
                    incorrectCount++;
                    wasCorrect = false;
                    incorrectIndicator?.classList.remove('d-none');
                    correctIndicator?.classList.add('d-none');
                    rowTR.classList.add('table-danger'); // Apply class to TR
                    rowTR.classList.remove('table-success');
                }
                btnGroup?.classList.add('d-none'); // Hide buttons after marking
                updateCounts();
            }

            correctBtn?.addEventListener('click', () => markRow(true));
            incorrectBtn?.addEventListener('click', () => markRow(false));
        });

         // Enable tooltips for the blank areas
         if (typeof bootstrap !== 'undefined' && typeof bootstrap.Tooltip === 'function') {
             const tooltipTriggerList = [].slice.call(listRecallTable.querySelectorAll('[data-bs-toggle="tooltip"]'));
             tooltipTriggerList.map(function (tooltipTriggerEl) {
                 return new bootstrap.Tooltip(tooltipTriggerEl);
             });
             console.debug("Mode 3 tooltips initialized.");
         } else {
             console.warn("Bootstrap Tooltip function not found for Mode 3.");
         }

    } // End Mode 3 check

    // --- Audio Play Initialization (Common) ---
    document.querySelectorAll('.btn-play-audio').forEach(button => {
        const onclickAttr = button.getAttribute('onclick');
        if (!onclickAttr || !onclickAttr.includes('playAudio')) {
             console.warn("Test Session: Audio button found without expected inline onclick.", button);
        }
    });

}); // End DOMContentLoaded