/**
 * Login & Registration Form Validation
 * MediCare 
 */

'use strict';

// ── Toggle password visibility ──
function togglePw(fieldId, btn) {
    const field = document.getElementById(fieldId);
    if (!field) return;
    const icon  = btn.querySelector('i');
    if (field.type === 'password') {
        field.type = 'text';
        icon.className = 'fa-solid fa-eye-slash';
    } else {
        field.type = 'password';
        icon.className = 'fa-solid fa-eye';
    }
}

// ── Password strength meter ──
const pwField   = document.getElementById('password');
const pwBar     = document.getElementById('pwBar');

if (pwField && pwBar) {
    pwField.addEventListener('input', () => {
        const val = pwField.value;
        let score = 0;
        if (val.length >= 8)            score++;
        if (/[A-Z]/.test(val))         score++;
        if (/[0-9]/.test(val))         score++;
        if (/[^A-Za-z0-9]/.test(val))  score++;

        const pct = (score / 4) * 100;
        pwBar.style.width = pct + '%';
        const colors = ['#ef4444','#f97316','#f59e0b','#22c55e'];
        pwBar.style.background = colors[score - 1] || '#e2e8f0';
    });
}

// ── Email validation ──
function validateEmail(email) {
    return /^[\w.+-]+@[\w-]+\.[\w.]+$/.test(email);
}

// ── Phone validation ──
function validatePhone(phone) {
    return /^\+?\d{9,15}$/.test(phone);
}

// ── Show field error ──
function showError(fieldId, msg) {
    const el = document.getElementById(fieldId + 'Error');
    if (el) { el.textContent = msg; }
    const input = document.getElementById(fieldId);
    if (input) { input.style.borderColor = '#ef4444'; }
}

function clearError(fieldId) {
    const el = document.getElementById(fieldId + 'Error');
    if (el) { el.textContent = ''; }
    const input = document.getElementById(fieldId);
    if (input) { input.style.borderColor = ''; }
}

// ── Register form validation ──
const registerForm = document.getElementById('registerForm');
if (registerForm) {
    registerForm.addEventListener('submit', e => {
        let valid = true;

        const fullname = document.getElementById('fullname');
        const email    = document.getElementById('email');
        const phone    = document.getElementById('phone');
        const password = document.getElementById('password');
        const confirm  = document.getElementById('confirm');

        // Reset
        ['fullname','email','phone','password','confirm'].forEach(clearError);

        if (!fullname || fullname.value.trim().length < 3) {
            showError('fullname', 'Full name must be at least 3 characters.');
            valid = false;
        }
        if (!email || !validateEmail(email.value.trim())) {
            showError('email', 'Please enter a valid email address.');
            valid = false;
        }
        if (!phone || !validatePhone(phone.value.trim())) {
            showError('phone', 'Phone must be 9–15 digits, optionally starting with +.');
            valid = false;
        }
        if (!password || password.value.length < 8) {
            showError('password', 'Password must be at least 8 characters.');
            valid = false;
        }
        if (!confirm || confirm.value !== (password && password.value)) {
            showError('confirm', 'Passwords do not match.');
            valid = false;
        }

        if (!valid) e.preventDefault();
    });

    // Real-time feedback
    document.getElementById('fullname')?.addEventListener('input', function() {
        if (this.value.trim().length >= 3) clearError('fullname');
    });
    document.getElementById('email')?.addEventListener('input', function() {
        if (validateEmail(this.value.trim())) clearError('email');
    });
    document.getElementById('phone')?.addEventListener('input', function() {
        if (validatePhone(this.value.trim())) clearError('phone');
    });
    document.getElementById('confirm')?.addEventListener('input', function() {
        const pw = document.getElementById('password');
        if (pw && this.value === pw.value) clearError('confirm');
    });
}

// ── Login form validation ──
const loginForm = document.getElementById('loginForm');
if (loginForm) {
    loginForm.addEventListener('submit', e => {
        let valid = true;
        const email    = document.getElementById('email');
        const password = document.getElementById('password');

        clearError('email'); clearError('password');

        if (!email || !validateEmail(email.value.trim())) {
            showError('email', 'Enter a valid email address.');
            valid = false;
        }
        if (!password || !password.value) {
            showError('password', 'Password is required.');
            valid = false;
        }
        if (!valid) e.preventDefault();
    });
}

