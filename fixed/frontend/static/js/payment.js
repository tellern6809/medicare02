/**
 * Payment Page – MediCare
 * Handles: Card (Stripe or demo), M-Pesa (Daraja STK or demo), PayPal SDK or demo
 */

'use strict';

// ── Method Tabs ──────────────────────────────────────
const methodTabs   = document.querySelectorAll('.method-tab');
const methodPanels = document.querySelectorAll('.method-panel');

methodTabs.forEach(tab => {
    tab.addEventListener('click', () => {
        const method = tab.dataset.method;
        methodTabs.forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        methodPanels.forEach(p => p.classList.remove('active'));
        const panel = document.getElementById('panel-' + method);
        if (panel) panel.classList.add('active');
    });
});

// ── Credit Card Formatting (demo mode) ───────────────
function formatCard(input) {
    let val = input.value.replace(/\D/g, '').substring(0, 16);
    val     = val.replace(/(.{4})/g, '$1 ').trim();
    input.value = val;
    const display = document.getElementById('cardDisplay');
    if (display) {
        const padded = (val + ' •••• •••• •••• ••••').substring(0, 19);
        display.textContent = padded;
    }
    const icon = document.querySelector('.card-icon');
    if (icon) {
        const num = val.replace(/\s/g,'');
        if (/^4/.test(num))           icon.className = 'fa-brands fa-cc-visa card-icon';
        else if (/^5[1-5]/.test(num)) icon.className = 'fa-brands fa-cc-mastercard card-icon';
        else if (/^3[47]/.test(num))  icon.className = 'fa-brands fa-cc-amex card-icon';
        else                          icon.className = 'fa-solid fa-credit-card card-icon';
    }
}

function formatExpiry(input) {
    let val = input.value.replace(/\D/g, '');
    if (val.length >= 3) val = val.substring(0,2) + '/' + val.substring(2,4);
    input.value = val;
    const display = document.getElementById('cardExpiryDisplay');
    if (display) display.textContent = val || 'MM/YY';
}

function setRef(refId) {
    const el = document.getElementById(refId);
    if (el) el.value = 'TXN-' + Date.now() + '-' + Math.random().toString(36).substring(2,8).toUpperCase();
}

// ── M-Pesa Phone Formatting ───────────────────────────
const mpesaPhone = document.getElementById('mpesaPhone');
if (mpesaPhone) {
    mpesaPhone.addEventListener('input', function() {
        this.value = this.value.replace(/\D/g, '').substring(0, 9);
    });
}

// ── Demo Card Form Validation ─────────────────────────
const cardForm = document.getElementById('cardForm');
if (cardForm) {
    cardForm.addEventListener('submit', e => {
        const num    = document.getElementById('cardNumber')?.value.replace(/\s/g,'') || '';
        const name   = document.getElementById('cardName')?.value.trim() || '';
        const expiry = document.getElementById('cardExpiry')?.value || '';
        const cvv    = document.getElementById('cardCvv')?.value || '';
        let errors = [];
        if (num.length < 16)                       errors.push('Invalid card number.');
        if (!name)                                 errors.push('Cardholder name required.');
        if (!/^\d{2}\/\d{2}$/.test(expiry))       errors.push('Expiry must be MM/YY.');
        if (cvv.length < 3)                        errors.push('Invalid CVV.');
        if (errors.length) { e.preventDefault(); alert(errors.join('\n')); return; }
        setRef('cardRef');
    });
}

// ── Demo PayPal Form Validation ───────────────────────
const paypalForm = document.getElementById('paypalForm');
if (paypalForm) {
    paypalForm.addEventListener('submit', e => {
        setRef('paypalRef');
    });
}

// ── M-Pesa STK Push Button ────────────────────────────
const mpesaPayBtn = document.getElementById('mpesaPayBtn');
if (mpesaPayBtn) {
    mpesaPayBtn.addEventListener('click', async () => {
        const phone = (document.getElementById('mpesaPhone')?.value || '').trim();
        if (!phone || phone.length < 9) {
            alert('Please enter a valid 9-digit M-Pesa number (e.g. 700123456)');
            return;
        }

        mpesaPayBtn.disabled = true;
        mpesaPayBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Sending STK Push…';

        try {
            const res  = await fetch('/payment/mpesa/stk', {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({ phone: '254' + phone, appointment_id: APPT_ID })
            });
            const data = await res.json();

            if (data.ok) {
                if (data.dev_mode) {
                    // Dev mode – payment recorded server-side, redirect to success
                    const form = document.getElementById('mpesaFallbackForm');
                    if (form) {
                        document.getElementById('mpesaFallbackRef').value = data.tx_ref || 'MPESA-DEV';
                        form.submit();
                    }
                } else {
                    mpesaPayBtn.innerHTML = '<i class="fa-solid fa-check-circle"></i> STK Push Sent – Check Your Phone';
                    mpesaPayBtn.style.background = '#10b981';
                    // Poll or wait; user confirms on phone then page auto-redirects via callback
                    startMpesaPoll();
                }
            } else {
                alert(data.error || 'STK Push failed. Please try again.');
                resetMpesaBtn();
            }
        } catch (err) {
            alert('Network error. Please check your connection and try again.');
            resetMpesaBtn();
        }
    });
}

function resetMpesaBtn() {
    if (mpesaPayBtn) {
        mpesaPayBtn.disabled = false;
        mpesaPayBtn.innerHTML = '<i class="fa-solid fa-mobile-screen-button"></i> Send STK Push – KES 1,500';
    }
}

// Poll after STK push to detect when callback recorded the payment
let mpesaPollTimer = null;
function startMpesaPoll() {
    let attempts = 0;
    mpesaPollTimer = setInterval(async () => {
        attempts++;
        if (attempts > 30) { clearInterval(mpesaPollTimer); resetMpesaBtn(); return; }
        try {
            // Check payment status via appointment API
            const res  = await fetch(`/api/payment/status/${APPT_ID}`);
            const data = await res.json();
            if (data.paid) {
                clearInterval(mpesaPollTimer);
                window.location.href = `/payment/success/${APPT_ID}`;
            }
        } catch (_) {}
    }, 3000);
}

// ── Stripe Integration ────────────────────────────────
if (typeof Stripe !== 'undefined' && HAS_STRIPE) {
    const stripe   = Stripe(STRIPE_PK);
    const elements = stripe.elements();
    const cardEl   = elements.create('card', {
        style: {
            base: { fontSize: '16px', color: '#1e293b', fontFamily: 'Inter, sans-serif' }
        }
    });

    try {
        cardEl.mount('#stripe-card-element');
    } catch (mountErr) {
        document.getElementById('stripe-card-errors').textContent =
            'Card input could not load. Please refresh the page or use M-Pesa / PayPal.';
    }

    // Detect silent mount failure (iframe not injected within 4 s)
    const mountCheck = setTimeout(() => {
        const el = document.getElementById('stripe-card-element');
        if (el && el.querySelector('iframe') === null) {
            document.getElementById('stripe-card-errors').textContent =
                'Card input failed to load. Please refresh or use M-Pesa / PayPal.';
        }
    }, 4000);

    cardEl.on('ready', () => clearTimeout(mountCheck));

    cardEl.on('change', e => {
        const errEl = document.getElementById('stripe-card-errors');
        if (errEl) errEl.textContent = e.error ? e.error.message : '';
    });

    const stripePayBtn = document.getElementById('stripePayBtn');
    if (stripePayBtn) {
        stripePayBtn.addEventListener('click', async () => {
            stripePayBtn.disabled = true;
            stripePayBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Processing…';

            try {
                // Get PaymentIntent client_secret from server
                const intentRes  = await fetch('/payment/stripe/intent', {
                    method:  'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body:    JSON.stringify({ appointment_id: APPT_ID })
                });
                const intentData = await intentRes.json();

                if (intentData.error) {
                    const errEl = document.getElementById('stripe-card-errors');
                    if (errEl) errEl.textContent = 'Payment setup failed: ' + intentData.error;
                    stripePayBtn.disabled = false;
                    stripePayBtn.innerHTML = '<i class="fa-solid fa-lock"></i> Pay KES 1,500 Securely';
                    return;
                }

                const name = document.getElementById('stripeCardName')?.value.trim() || '';
                const { error, paymentIntent } = await stripe.confirmCardPayment(
                    intentData.client_secret,
                    { payment_method: { card: cardEl, billing_details: { name } } }
                );

                if (error) {
                    document.getElementById('stripe-card-errors').textContent = error.message;
                    stripePayBtn.disabled = false;
                    stripePayBtn.innerHTML = '<i class="fa-solid fa-lock"></i> Pay KES 1,500 Securely';
                } else if (paymentIntent.status === 'succeeded') {
                    // Record in DB then redirect
                    const recordRes = await fetch('/payment/process', {
                        method:  'POST',
                        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                        body:    new URLSearchParams({
                            appointment_id:  APPT_ID,
                            amount:          1500,
                            method:          'stripe',
                            transaction_ref: paymentIntent.id
                        })
                    });
                    window.location.href = `/payment/success/${APPT_ID}`;
                }
            } catch (err) {
                document.getElementById('stripe-card-errors').textContent = 'Payment error. Please try again.';
                stripePayBtn.disabled = false;
                stripePayBtn.innerHTML = '<i class="fa-solid fa-lock"></i> Pay KES 1,500 Securely';
            }
        });
    }
}

// ── PayPal SDK Integration ────────────────────────────
// Called by the SDK script's onload callback (see bottom of payment.html)
function initPayPal() {
    if (typeof paypal === 'undefined' || !HAS_PAYPAL) return;
    const container = document.getElementById('paypal-button-container');
    if (!container) return;

    // USD amount – KES 1500 ÷ 130 (approximate exchange rate)
    // Replace 11.54 with your real USD price or pass it from the server
    const USD_AMOUNT = '11.54';

    paypal.Buttons({
        createOrder: (data, actions) => actions.order.create({
            purchase_units: [{
                amount: { value: USD_AMOUNT, currency_code: 'USD' },
                description: 'Medical Consultation – MediCare'
            }]
        }),
        onApprove: async (data, actions) => {
            const order = await actions.order.capture();
            document.getElementById('paypalTxRef').value = order.id;
            document.getElementById('paypalRecordForm').submit();
        },
        onError: err => {
            console.error('PayPal error:', err);
            alert('PayPal payment failed. Please try again or use another method.');
        },
        style: { layout: 'vertical', color: 'blue', shape: 'rect', label: 'pay' }
    }).render('#paypal-button-container');
}
