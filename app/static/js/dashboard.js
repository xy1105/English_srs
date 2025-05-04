// app/static/js/dashboard.js

/**
 * Handles JavaScript specific to the dashboard page (index.html),
 * primarily initializing the mastery chart.
 */
document.addEventListener('DOMContentLoaded', function () {
    const ctx = document.getElementById('masteryChart')?.getContext('2d');

    if (ctx) {
        fetchMasteryData(ctx);
    } else {
         console.debug("Mastery chart canvas not found on this page.");
    }
});

/**
 * Fetches mastery data from the API and initializes the Chart.js chart.
 * @param {CanvasRenderingContext2D} ctx The canvas context for the chart.
 */
function fetchMasteryData(ctx) {
    // Assumes the API endpoint is defined correctly in the Flask app
    const apiUrl = '/api/mastery-data';

    fetch(apiUrl)
        .then(response => {
            if (!response.ok) {
                // Throw an error with status text to be caught below
                throw new Error(`HTTP error ${response.status}: ${response.statusText}`);
            }
            return response.json();
        })
        .then(data => {
            // Basic validation of received data
            if (data && data.labels && data.datasets && data.datasets.length > 0 && data.labels.length === data.datasets[0].data.length) {

                // Check if there's actually any data to display
                const hasData = data.datasets[0].data.some(val => val > 0);

                if (hasData) {
                    initializeMasteryChart(ctx, data);
                } else {
                    displayChartFallbackMessage(ctx, "还没有足够的数据来显示掌握程度分布。");
                    console.info("No non-zero data received for mastery chart.");
                }

            } else {
                // Handle cases where data structure is invalid
                throw new Error("Invalid data structure received from API.");
            }
        })
        .catch(error => {
            console.error('Error fetching or processing mastery chart data:', error);
            displayChartFallbackMessage(ctx, `加载图表数据时出错: ${error.message}`);
        });
}

/**
 * Initializes the Chart.js Doughnut chart with the provided data.
 * @param {CanvasRenderingContext2D} ctx The canvas context.
 * @param {object} chartData Data object formatted for Chart.js.
 */
function initializeMasteryChart(ctx, chartData) {
    try {
        const masteryChart = new Chart(ctx, {
            type: 'doughnut', // Or 'pie'
            data: chartData,
            options: {
                responsive: true,
                maintainAspectRatio: false, // Allows chart to fill container height
                animation: {
                    animateScale: true, // Animate drawing
                    animateRotate: true
                },
                plugins: {
                    legend: {
                        position: 'bottom', // More space at the bottom
                        labels: {
                            padding: 15, // Spacing for legend items
                            boxWidth: 12,
                            font: { size: 11 } // Smaller legend font
                        }
                    },
                    title: {
                        display: false, // Title is usually in the card header
                    },
                    tooltip: {
                        backgroundColor: 'rgba(0, 0, 0, 0.8)', // Darker tooltip
                        titleFont: { size: 13 },
                        bodyFont: { size: 12 },
                        padding: 10,
                        callbacks: {
                            // Custom label format: "Level: X 词 (Y.Y%)"
                            label: function(context) {
                                let label = context.label || '';
                                if (label) { label += ': '; }
                                if (context.parsed !== null) {
                                    label += context.parsed + ' 词';
                                    // Calculate percentage
                                    const total = context.chart.data.datasets[0].data.reduce((a, b) => a + b, 0);
                                    const percentage = total > 0 ? ((context.parsed / total) * 100).toFixed(1) : 0;
                                    label += ` (${percentage}%)`;
                                }
                                return label;
                            }
                        }
                    }
                },
                // Optional: Adjust cutout percentage for doughnut chart
                cutout: '60%' // Makes the hole slightly larger/smaller
            }
        });
        console.debug("Mastery chart initialized successfully.");
    } catch (e) {
         console.error("Error creating Chart.js instance:", e);
         displayChartFallbackMessage(ctx, "渲染图表时发生错误。");
    }
}

/**
 * Displays a fallback message inside the chart container if data loading/rendering fails.
 * @param {CanvasRenderingContext2D} ctx The canvas context.
 * @param {string} message The message to display.
 */
function displayChartFallbackMessage(ctx, message = "无法加载图表数据。") {
    const container = ctx.canvas.parentNode;
    if (container) {
        container.innerHTML = `<div class="d-flex align-items-center justify-content-center h-100"><p class="text-center text-muted small p-3">${message}</p></div>`;
    }
}