'use strict';

// ── User search (already in the template, but enhanced here) ──
const userSearchInput = document.getElementById('userSearch');
if (userSearchInput) {
    userSearchInput.addEventListener('input', function() {
        filterUsers(this.value);
    });
}

function filterUsers(val) {
    const rows = document.querySelectorAll('#usersTable tbody tr');
    const q    = val.toLowerCase();
    rows.forEach(row => {
        row.style.display = row.textContent.toLowerCase().includes(q) ? '' : 'none';
    });
}

// ── Confirm all admin delete forms ──
// (handled globally in dashboard.js via event delegation)
