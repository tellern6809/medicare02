/**
 * Patient, Doctor & Admin Dashboards – Prescriptio
 */

'use strict';

// ── SIDEBAR TOGGLE ────────────────────────────────────────────────────────────

const sidebarToggle = document.getElementById('sidebarToggle');
const sidebar       = document.getElementById('sidebar');
let   sidebarOpen   = false;

if (sidebarToggle && sidebar) {
    sidebarToggle.addEventListener('click', () => {
        sidebarOpen = !sidebarOpen;
        sidebar.classList.toggle('open', sidebarOpen);
    });
    document.addEventListener('click', e => {
        if (sidebarOpen && !sidebar.contains(e.target) && !sidebarToggle.contains(e.target)) {
            sidebarOpen = false;
            sidebar.classList.remove('open');
        }
    });
}


// ── SECTION NAVIGATION ────────────────────────────────────────────────────────

function showSection(id) {
    document.querySelectorAll('.dash-section').forEach(s => s.classList.remove('active'));
    const target = document.getElementById(id);
    if (target) target.classList.add('active');
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.toggle('active', item.dataset.section === id);
    });
    if (window.innerWidth <= 900) {
        sidebarOpen = false;
        sidebar && sidebar.classList.remove('open');
    }
    history.replaceState(null, '', '#' + id);
}

document.querySelectorAll('.nav-item[data-section]').forEach(item => {
    item.addEventListener('click', e => {
        e.preventDefault();
        showSection(item.dataset.section);
    });
});

window.addEventListener('DOMContentLoaded', () => {
    const hash = window.location.hash.slice(1);
    if (hash && document.getElementById(hash)) showSection(hash);
});


// ── TOAST NOTIFICATIONS ───────────────────────────────────────────────────────

function showToast(msg, type) {
    let container = document.getElementById('toastContainer');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toastContainer';
        container.style.cssText =
            'position:fixed;top:24px;right:24px;z-index:99999;display:flex;' +
            'flex-direction:column;gap:10px;pointer-events:none;';
        document.body.appendChild(container);
    }
    const colors = {
        success: { bg: '#10b981', icon: '&#10003;' },
        error:   { bg: '#ef4444', icon: '&#10007;' },
        warning: { bg: '#f59e0b', icon: '!' },
        info:    { bg: '#3b82f6', icon: 'i' }
    };
    const c = colors[type] || colors.info;
    const toast = document.createElement('div');
    toast.style.cssText =
        'background:' + c.bg + ';color:#fff;padding:12px 18px 12px 14px;border-radius:10px;' +
        'font-size:14px;font-weight:500;box-shadow:0 4px 16px rgba(0,0,0,.18);' +
        'display:flex;align-items:center;gap:10px;pointer-events:auto;' +
        'opacity:0;transform:translateX(20px);transition:opacity .25s,transform .25s;' +
        'max-width:320px;';
    toast.innerHTML =
        '<span style="width:22px;height:22px;border-radius:50%;background:rgba(255,255,255,.25);' +
        'display:flex;align-items:center;justify-content:center;font-size:13px;flex-shrink:0;">' +
        c.icon + '</span><span>' + msg + '</span>';
    container.appendChild(toast);
    requestAnimationFrame(() => requestAnimationFrame(() => {
        toast.style.opacity = '1';
        toast.style.transform = 'translateX(0)';
    }));
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(20px)';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}


// ── CANCEL APPOINTMENT (AJAX) ─────────────────────────────────────────────────
// Attach click handlers directly to cancel buttons — no onsubmit confusion

function attachCancelHandlers() {
    document.querySelectorAll('form[data-cancel-ajax="1"]').forEach(form => {
        if (form._cancelAttached) return;
        form._cancelAttached = true;

        form.addEventListener('submit', e => e.preventDefault()); // block normal submit

        const btn = form.querySelector('button[type="submit"]');
        if (btn) {
            btn.addEventListener('click', e => {
                e.preventDefault();
                e.stopPropagation();
                openCancelModal(form);
            });
        }
    });
}

function openCancelModal(form) {
    const modal = document.getElementById('confirmModal');
    if (!modal) return;

    document.getElementById('modalTitle').textContent   = 'Cancel Appointment';
    document.getElementById('modalMessage').textContent = 'Are you sure you want to cancel this appointment?';

    // Store form reference directly on the modal
    modal._pendingCancelForm = form;
    modal.classList.add('open');
}

// Wire up confirm button
document.addEventListener('DOMContentLoaded', () => {
    attachCancelHandlers();

    const confirmBtn = document.getElementById('modalConfirmBtn');
    // Skip if the doctor dashboard inline script already owns this modal
    if (confirmBtn && typeof window.doctorAction === 'undefined') {
        confirmBtn.addEventListener('click', async () => {
            const modal = document.getElementById('confirmModal');
            const form  = modal ? modal._pendingCancelForm : null;

            // Close modal immediately
            if (modal) {
                modal.classList.remove('open');
                modal._pendingCancelForm = null;
            }

            if (!form) return;

            const apptId = form.dataset.apptId;
            const btn    = form.querySelector('button[type="submit"]');

            // Disable button to prevent double-click
            if (btn) { btn.disabled = true; btn.textContent = 'Cancelling…'; }

            try {
                const res = await fetch(form.action, {
                    method:      'POST',
                    headers:     { 'X-Requested-With': 'XMLHttpRequest' },
                    credentials: 'same-origin'
                });

                let data = {};
                const ct = res.headers.get('content-type') || '';
                if (ct.includes('application/json')) {
                    data = await res.json();
                }

                if (res.ok && data.ok) {
                    // Update ALL rows with this appointment id (overview + full table)
                    document.querySelectorAll('[data-appt-id="' + apptId + '"]').forEach(row => {
                        row.dataset.status = 'cancelled';

                        // Swap badge
                        const badge = row.querySelector('.badge');
                        if (badge) {
                            badge.className   = 'badge badge-cancelled';
                            badge.textContent = 'Cancelled';
                        }

                        // Remove action buttons
                        const cf = row.querySelector('form[data-cancel-ajax]');
                        if (cf) cf.remove();
                        const payBtn  = row.querySelector('.btn-pay');
                        if (payBtn)  payBtn.remove();
                        const chatBtn = row.querySelector('.btn-chat');
                        if (chatBtn) chatBtn.remove();
                    });

                    showToast('Appointment cancelled successfully.', 'success');

                } else {
                    if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-ban"></i> Cancel'; }
                    showToast(data.error || 'Could not cancel. Please try again.', 'error');
                }

            } catch (err) {
                console.error('Cancel fetch error:', err);
                if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-ban"></i> Cancel'; }
                showToast('Network error. Please try again.', 'error');
            }
        });
    }

    // Close modal on overlay click or No button
    const modal = document.getElementById('confirmModal');
    if (modal) {
        modal.addEventListener('click', e => {
            if (e.target === modal) {
                modal.classList.remove('open');
                modal._pendingCancelForm = null;
            }
        });
    }

    const cancelModalBtn = document.querySelector('.btn-modal-cancel');
    if (cancelModalBtn) {
        cancelModalBtn.addEventListener('click', () => {
            const modal = document.getElementById('confirmModal');
            if (modal) {
                modal.classList.remove('open');
                modal._pendingCancelForm = null;
            }
        });
    }
});


// ── FILTER TABS (client-side) ─────────────────────────────────────────────────

document.querySelectorAll('.filter-tabs').forEach(tabGroup => {
    tabGroup.querySelectorAll('.filter-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            tabGroup.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const filter = btn.dataset.filter;
            const card   = tabGroup.closest('.dash-card');
            const rows   = card ? card.querySelectorAll('tbody tr[data-status]') : [];
            rows.forEach(row => {
                row.style.display = (filter === 'all' || row.dataset.status === filter) ? '' : 'none';
            });
        });
    });
});


// ── ANIMATED STAT COUNTERS ────────────────────────────────────────────────────

function animateCounter(el) {
    const target   = parseInt(el.dataset.target, 10) || 0;
    const duration = 800;
    const step     = target / (duration / 16);
    let current    = 0;
    const timer = setInterval(() => {
        current += step;
        if (current >= target) {
            el.textContent = target.toLocaleString();
            clearInterval(timer);
        } else {
            el.textContent = Math.floor(current).toLocaleString();
        }
    }, 16);
}

const observer = new IntersectionObserver(entries => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            entry.target.querySelectorAll('.stat-num[data-target]').forEach(animateCounter);
            observer.unobserve(entry.target);
        }
    });
}, { threshold: 0.2 });

document.querySelectorAll('.stats-grid').forEach(grid => observer.observe(grid));
