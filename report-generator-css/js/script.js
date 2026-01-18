document.addEventListener('DOMContentLoaded', () => {
    // Load data from script tags
    const videoDataElement = document.getElementById('videoData');
    const viewsOverTimeDataElement = document.getElementById('viewsOverTimeData');
    const uploadsOverTimeDataElement = document.getElementById('uploadsOverTimeData');
    const topVideosByViewsDataElement = document.getElementById('topVideosByViewsData');
    const topVideosByDurationDataElement = document.getElementById('topVideosByDurationData'); // New
    const topVideosByLikesDataElement = document.getElementById('topVideosByLikesData');     // New

    const videos = videoDataElement ? JSON.parse(videoDataElement.textContent) : [];
    const viewsOverTime = viewsOverTimeDataElement ? JSON.parse(viewsOverTimeDataElement.textContent) : { labels: [], data: [] };
    const uploadsOverTime = uploadsOverTimeDataElement ? JSON.parse(uploadsOverTimeDataElement.textContent) : { labels: [], data: [] };
    const topVideosByViews = topVideosByViewsDataElement ? JSON.parse(topVideosByViewsDataElement.textContent) : [];
    const topVideosByDuration = topVideosByDurationDataElement ? JSON.parse(topVideosByDurationDataElement.textContent) : []; // New
    const topVideosByLikes = topVideosByLikesDataElement ? JSON.parse(topVideosByLikesDataElement.textContent) : [];     // New

    // Render Charts
    // Chart 1: Top Videos by Views (moved to first position)
    if (topVideosByViews.length > 0) {
        const topVideosViewsCtx = document.getElementById('topVideosByViewsChart').getContext('2d');
        new Chart(topVideosViewsCtx, {
            type: 'bar',
            data: {
                labels: topVideosByViews.map(v => v.title),
                datasets: [{
                    label: 'Top Videos by Views',
                    data: topVideosByViews.map(v => v.view_count),
                    backgroundColor: '#ffc107', // Yellow
                    borderColor: '#ffc107',
                    borderWidth: 1
                }]
            },
            options: {
                indexAxis: 'y', // Make it a horizontal bar chart
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: 'Top 10 Videos by Views',
                        color: '#e0e0e0'
                    },
                    legend: {
                        labels: {
                            color: '#e0e0e0'
                        }
                    }
                },
                scales: {
                    x: {
                        ticks: { color: '#e0e0e0' },
                        grid: { color: '#444444' }
                    },
                    y: {
                        ticks: { color: '#e0e0e0' },
                        grid: { color: '#444444' }
                    }
                }
            }
        });
    }

    // Chart 2: Top Videos by Duration (new chart)
    if (topVideosByDuration.length > 0) {
        const topVideosDurationCtx = document.getElementById('topVideosByDurationChart').getContext('2d');
        new Chart(topVideosDurationCtx, {
            type: 'bar',
            data: {
                labels: topVideosByDuration.map(v => v.title),
                datasets: [{
                    label: 'Top Videos by Duration',
                    data: topVideosByDuration.map(v => v.duration_seconds),
                    backgroundColor: '#17a2b8', // Teal
                    borderColor: '#17a2b8',
                    borderWidth: 1
                }]
            },
            options: {
                indexAxis: 'y', // Make it a horizontal bar chart
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: 'Top 10 Videos by Duration',
                        color: '#e0e0e0'
                    },
                    legend: {
                        labels: {
                            color: '#e0e0e0'
                        }
                    }
                },
                scales: {
                    x: {
                        ticks: { color: '#e0e0e0' },
                        grid: { color: '#444444' }
                    },
                    y: {
                        ticks: { color: '#e0e0e0' },
                        grid: { color: '#444444' }
                    }
                }
            }
        });
    }

    // Chart 3: Top Videos by Likes (new chart)
    if (topVideosByLikes.length > 0) {
        const topVideosLikesCtx = document.getElementById('topVideosByLikesChart').getContext('2d');
        new Chart(topVideosLikesCtx, {
            type: 'bar',
            data: {
                labels: topVideosByLikes.map(v => v.title),
                datasets: [{
                    label: 'Top Videos by Likes',
                    data: topVideosByLikes.map(v => v.like_count),
                    backgroundColor: '#dc3545', // Red
                    borderColor: '#dc3545',
                    borderWidth: 1
                }]
            },
            options: {
                indexAxis: 'y', // Make it a horizontal bar chart
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: 'Top 10 Videos by Likes',
                        color: '#e0e0e0'
                    },
                    legend: {
                        labels: {
                            color: '#e0e0e0'
                        }
                    }
                },
                scales: {
                    x: {
                        ticks: { color: '#e0e0e0' },
                        grid: { color: '#444444' }
                    },
                    y: {
                        ticks: { color: '#e0e0e0' },
                        grid: { color: '#444444' }
                    }
                }
            }
        });
    }

    // The original viewsOverTime and uploadsOverTime charts are commented out
    // as the data is not available.
    /*
    if (viewsOverTime.labels.length > 0) {
        const viewsCtx = document.getElementById('viewsOverTimeChart').getContext('2d');
        new Chart(viewsCtx, {
            type: 'line',
            data: {
                labels: viewsOverTime.labels,
                datasets: [{
                    label: 'Views Over Time',
                    data: viewsOverTime.data,
                    borderColor: '#007bff',
                    backgroundColor: 'rgba(0, 123, 255, 0.2)',
                    fill: true,
                    tension: 0.3
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: 'Views Over Time',
                        color: '#e0e0e0'
                    },
                    legend: {
                        labels: {
                            color: '#e0e0e0'
                        }
                    }
                },
                scales: {
                    x: {
                        ticks: { color: '#e0e0e0' },
                        grid: { color: '#444444' }
                    },
                    y: {
                        ticks: { color: '#e0e0e0' },
                        grid: { color: '#444444' }
                    }
                }
            }
        });
    }

    if (uploadsOverTime.labels.length > 0) {
        const uploadsCtx = document.getElementById('uploadsOverTimeChart').getContext('2d');
        new Chart(uploadsCtx, {
            type: 'bar',
            data: {
                labels: uploadsOverTime.labels,
                datasets: [{
                    label: 'Uploads Over Time',
                    data: uploadsOverTime.data,
                    backgroundColor: '#28a745',
                    borderColor: '#28a745',
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: 'Uploads Over Time',
                        color: '#e0e0e0'
                    },
                    legend: {
                        labels: {
                            color: '#e0e0e0'
                        }
                    }
                },
                scales: {
                    x: {
                        ticks: { color: '#e0e0e0' },
                        grid: { color: '#444444' }
                    },
                    y: {
                        ticks: { color: '#e0e0e0' },
                        grid: { color: '#444444' }
                    }
                }
            }
        });
    }
    */

    // Table Filtering
    window.filterVideoTable = function() {
        const input = document.getElementById('videoSearchInput');
        const filter = input.value.toLowerCase();
        const table = document.getElementById('videosTable');
        const tr = table.getElementsByTagName('tr');

        for (let i = 1; i < tr.length; i++) { // Start from 1 to skip header row
            const titleTd = tr[i].getElementsByTagName('td')[1]; // Title is the second column (index 1)
            if (titleTd) {
                const textValue = titleTd.textContent || titleTd.innerText;
                if (textValue.toLowerCase().indexOf(filter) > -1) {
                    tr[i].style.display = '';
                } else {
                    tr[i].style.display = 'none';
                }
            }
        }
    };

    // Table Sorting
    let currentSortColumn = -1;
    let sortDirection = 'asc'; // 'asc' or 'desc'

    window.sortTable = function(n, tableId, isNumeric = false) {
        const table = document.getElementById(tableId);
        const tbody = table.querySelector('tbody');
        const rows = Array.from(tbody.rows);
        const headers = table.getElementsByTagName('th');

        // Reset sort icons
        for (let i = 0; i < headers.length; i++) {
            const icon = headers[i].querySelector('.fas.fa-sort');
            if (icon) {
                icon.classList.remove('fa-sort-up', 'fa-sort-down');
                icon.classList.add('fa-sort');
            }
        }

        // Determine sort direction
        if (n === currentSortColumn) {
            sortDirection = (sortDirection === 'asc') ? 'desc' : 'asc';
        } else {
            sortDirection = 'asc';
            currentSortColumn = n;
        }

        // Update sort icon
        const currentIcon = headers[n].querySelector('.fas.fa-sort');
        if (currentIcon) {
            currentIcon.classList.remove('fa-sort');
            currentIcon.classList.add(sortDirection === 'asc' ? 'fa-sort-up' : 'fa-sort-down');
        }

        rows.sort((rowA, rowB) => {
            let x = rowA.getElementsByTagName('td')[n].textContent;
            let y = rowB.getElementsByTagName('td')[n].textContent;

            if (isNumeric) {
                // Remove commas for numeric comparison
                x = parseFloat(x.replace(/,/g, '')) || 0;
                y = parseFloat(y.replace(/,/g, '')) || 0;
            } else if (n === 2) { // Special handling for 'Upload Date' column (index 2)
                // Convert 'YYYY-MM-DD' to Date objects for proper comparison
                x = x !== "N/A" ? new Date(x) : new Date(0); // Use epoch for "N/A"
                y = y !== "N/A" ? new Date(y) : new Date(0);
            } else {
                x = x.toLowerCase();
                y = y.toLowerCase();
            }

            let comparison = 0;
            if (x > y) {
                comparison = 1;
            } else if (x < y) {
                comparison = -1;
            }
            return (sortDirection === 'desc') ? (comparison * -1) : comparison;
        });

        // Re-append sorted rows
        rows.forEach(row => tbody.appendChild(row));
    };

    // Initial population of the table (if not already done by Python)
    // This part is mostly for dynamic loading, but can ensure table is populated if Python doesn't do it fully
    const videosTableBody = document.getElementById('videosTable').querySelector('tbody');
    if (videosTableBody.children.length === 0 && videos.length > 0) {
        videos.forEach(v => {
            const row = videosTableBody.insertRow();
            row.innerHTML = `
                <td><a href="${v.url}" target="_blank"><img src="${v.thumbnail_url}" alt="Thumbnail" class="video-thumbnail"></a></td>
                <td><a href="${v.url}" target="_blank">${v.title}</a></td>
                <td>${v.upload_date}</td>
                <td>${v.view_count.toLocaleString()}</td>
                <td>${v.like_count.toLocaleString()}</td>
                <td>${v.comment_count.toLocaleString()}</td>
                <td>${v.duration_formatted}</td>
            `;
        });
    }
});
