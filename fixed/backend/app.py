"""
Online Doctors Appointment System - Flask Backend
==========================================
Author: HMS System
Stack: Flask + MySQL + JWT + bcrypt
"""

import os, re, json, secrets
from datetime import datetime, timedelta
from functools import wraps
from dotenv import load_dotenv
load_dotenv()  # Load variables from .env file

from flask import (Flask, render_template, request, redirect,
                   url_for, flash, session, jsonify, make_response)
import mysql.connector
import bcrypt
import jwt

# Email support
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# File upload support
from werkzeug.utils import secure_filename
IMG_UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'static', 'uploads', 'avatars')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ──────────────────────────────────────────────
# App Configuration
# ──────────────────────────────────────────────
import logging
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__,
            template_folder=os.path.join(BASE_DIR, '..', 'frontend', 'templates'),
            static_folder=os.path.join(BASE_DIR, '..', 'frontend', 'static'))
app.secret_key = os.environ.get('SECRET_KEY')

# Always show INFO logs in terminal so email debugging is visible
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
app.logger.setLevel(logging.INFO)
JWT_SECRET    = os.environ.get('JWT_SECRET')
JWT_ALGORITHM = 'HS256'
JWT_EXP_HOURS = 8

# Payment gateway keys (loaded from .env)
PAYPAL_CLIENT_ID = os.environ.get('PAYPAL_CLIENT_ID')
PAYPAL_SECRET =os.environ.get('PAYPAL_SECRET')
STRIPE_PK        = os.environ.get('STRIPE_PK')
STRIPE_SK        = os.environ.get('STRIPE_SK')
MPESA_SHORTCODE  = os.environ.get('MPESA_SHORTCODE')

# Mail configuration – read fresh every call so .env changes take effect without restart
def _mail_cfg():
    host     = os.environ.get('MAIL_HOST', 'smtp.gmail.com')
    port     = int(os.environ.get('MAIL_PORT', 587))
    username = os.environ.get('MAIL_USERNAME', '').strip()
    password = os.environ.get('MAIL_PASSWORD', '').strip()
    sender   = os.environ.get('MAIL_FROM', username).strip()
    base_url = os.environ.get('APP_BASE_URL', 'https://medicare02.onrender.com').rstrip('/')
    return host, port, username, password, sender, base_url

# Keep module-level names for backwards compat (used as defaults only)
MAIL_HOST     = os.environ.get('MAIL_HOST', 'smtp.gmail.com')
MAIL_PORT     = int(os.environ.get('MAIL_PORT', 587))
MAIL_USERNAME = os.environ.get('MAIL_USERNAME', '').strip()
MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', '').strip()
MAIL_FROM     = os.environ.get('MAIL_FROM', MAIL_USERNAME).strip()
APP_BASE_URL  = os.environ.get('APP_BASE_URL', 'https://medicare02.onrender.com').rstrip('/')

# ──────────────────────────────────────────────
# Database Helper
# ──────────────────────────────────────────────
db_pool = mysql.connector.pooling.MySQLConnectionPool(
    pool_name="medicare_pool",
    pool_size=10,
    host=os.environ.get('DB_HOST', 'localhost'),
    port=int(os.environ.get('DB_PORT', 3306)),
    user=os.environ.get('DB_USER', 'root'),
    password=os.environ.get('DB_PASSWORD', ''),
    database=os.environ.get('DB_NAME', 'healthcare_db'),
    charset='utf8mb4'
)

def get_db():
    conn = db_pool.get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SET time_zone = '+03:00'")
        cur.close()
    except Exception:
        pass
    return conn
def query(sql, params=(), fetchone=False, fetchall=False, commit=False):
    """Generic query helper – prevents SQL injection via parameterised queries."""
    conn = None
    try:
        conn = get_db()
        cur  = conn.cursor(dictionary=True)
        cur.execute(sql, params)
        result = None
        if fetchone:
            result = cur.fetchone()
        elif fetchall:
            result = cur.fetchall()
        if commit:
            conn.commit()
            result = cur.lastrowid
        cur.close()
        return result
    except Exception as e:
        if conn:
            try: conn.rollback()
            except Exception: pass
        raise e
    finally:
        if conn:
            try: conn.close()
            except Exception: pass

# ──────────────────────────────────────────────
# JWT Helpers
# ──────────────────────────────────────────────
def generate_token(user_id, role):
    payload = {
        'user_id': user_id,
        'role':    role,
        'exp':     datetime.utcnow() + timedelta(hours=JWT_EXP_HOURS)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def decode_token(token):
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

# ──────────────────────────────────────────────
# Auth Decorators
# ──────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            # Return JSON for AJAX requests so the frontend can handle it gracefully
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': 'Session expired. Please log in again.', 'login_required': True}), 401
            flash('Please log in first.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if session.get('role') not in roles:
                flash('Access denied.', 'danger')
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return decorated
    return decorator

# ──────────────────────────────────────────────
# Input Validation
# ──────────────────────────────────────────────
def validate_email(email):
    return re.match(r'^[\w.+-]+@[\w-]+\.[\w.]+$', email)

def validate_phone(phone):
    return re.match(r'^\+?\d{9,15}$', phone)

def sanitize(text):
    return str(text).strip() if text else ''

# ══════════════════════════════════════════════
# PUBLIC ROUTES
# ══════════════════════════════════════════════

@app.route('/')
def index():
    """Landing page."""
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('landing.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        fullname = sanitize(request.form.get('fullname'))
        email    = sanitize(request.form.get('email')).lower()
        phone    = sanitize(request.form.get('phone'))
        password = request.form.get('password', '')
        confirm  = request.form.get('confirm', '')

        # Validation
        errors = []
        if not fullname or len(fullname) < 3:
            errors.append('Full name must be at least 3 characters.')
        if not validate_email(email):
            errors.append('Invalid email address.')
        if not validate_phone(phone):
            errors.append('Invalid phone number.')
        if len(password) < 8:
            errors.append('Password must be at least 8 characters.')
        if password != confirm:
            errors.append('Passwords do not match.')

        if errors:
            for e in errors: flash(e, 'danger')
            return render_template('register.html')

        # Check duplicate email
        existing = query('SELECT id FROM users WHERE email=%s', (email,), fetchone=True)
        if existing:
            flash('Email already registered.', 'danger')
            return render_template('register.html')

        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        query('INSERT INTO users (fullname,email,phone,password,role) VALUES (%s,%s,%s,%s,"patient")',
              (fullname, email, phone, hashed), commit=True)
        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        email    = sanitize(request.form.get('email')).lower()
        password = request.form.get('password', '')

        if not email or not password:
            flash('Please enter email and password.', 'danger')
            return render_template('login.html')

        user = query('SELECT * FROM users WHERE email=%s', (email,), fetchone=True)

        if user and bcrypt.checkpw(password.encode(), user['password'].encode()):
            session['user_id']  = user['id']
            session['role']     = user['role']
            session['fullname'] = user['fullname']
            token = generate_token(user['id'], user['role'])
            session['token'] = token
            # Doctor forced password change on first login
            if user['role'] == 'doctor' and user.get('must_change_password'):
                session['must_change_password'] = True
            flash(f'Welcome back, {user["fullname"]}!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid email or password.', 'danger')

    return render_template('login.html')


@app.route('/logout')
def logout():
    uid = session.get('user_id')
    if uid:
        try:
            query("UPDATE user_presence SET is_online=0 WHERE user_id=%s", (uid,), commit=True)
        except Exception:
            pass
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))


@app.route('/dashboard')
@login_required
def dashboard():
    role = session.get('role')
    if role == 'patient': return redirect(url_for('patient_dashboard'))
    if role == 'doctor':  return redirect(url_for('doctor_dashboard'))
    if role == 'admin':   return redirect(url_for('admin_dashboard'))
    return redirect(url_for('index'))

# ══════════════════════════════════════════════
# PATIENT ROUTES
# ══════════════════════════════════════════════

@app.route('/patient/dashboard')
@login_required
@role_required('patient')
def patient_dashboard():
    uid = session['user_id']

    # Stats
    stats = query("""
        SELECT
            COUNT(*) AS total,
            SUM(status='Pending')   AS pending,
            SUM(status='Accepted')  AS accepted,
            SUM(status='Completed') AS completed,
            SUM(status='Cancelled') AS cancelled,
            SUM(status='Rejected')  AS rejected
        FROM appointments WHERE patient_id=%s
    """, (uid,), fetchone=True)

    appointments = query("""
        SELECT a.*, u.fullname AS doctor_name, u.specialization,
               p.status AS pay_status, p.id AS payment_id
        FROM appointments a
        JOIN users u ON u.id = a.doctor_id
        LEFT JOIN payments p ON p.appointment_id = a.id AND p.status='Paid'
        WHERE a.patient_id=%s
        ORDER BY a.created_at DESC
    """, (uid,), fetchall=True)

    doctors = query("SELECT id, fullname, specialization FROM users WHERE role='doctor' ORDER BY fullname", fetchall=True)

    patient = query('SELECT id, fullname, email, phone, profile_picture FROM users WHERE id=%s', (uid,), fetchone=True)
    return render_template('patient_dashboard.html',
                           stats=stats,
                           appointments=appointments,
                           doctors=doctors,
                           patient=patient,
                           now=datetime.today())


@app.route('/patient/book', methods=['POST'])
@login_required
@role_required('patient')
def book_appointment():
    uid       = session['user_id']
    doctor_id = request.form.get('doctor_id')
    date      = sanitize(request.form.get('date'))
    time      = sanitize(request.form.get('time'))
    reason    = sanitize(request.form.get('reason'))

    if not all([doctor_id, date, time, reason]):
        flash('All fields are required.', 'danger')
        return redirect(url_for('patient_dashboard'))

    # Prevent past dates
    try:
        appt_date = datetime.strptime(date, '%Y-%m-%d').date()
        if appt_date < datetime.today().date():
            flash('Cannot book an appointment in the past.', 'danger')
            return redirect(url_for('patient_dashboard'))
    except ValueError:
        flash('Invalid date format.', 'danger')
        return redirect(url_for('patient_dashboard'))

    query("""
        INSERT INTO appointments (patient_id, doctor_id, date, time, reason, status)
        VALUES (%s,%s,%s,%s,%s,'Pending')
    """, (uid, doctor_id, date, time, reason), commit=True)

    # ── Email notifications on appointment submission ──
    try:
        patient = query('SELECT id, fullname, email FROM users WHERE id=%s', (uid,), fetchone=True)
        doctor  = query('SELECT id, fullname, email FROM users WHERE id=%s AND role="doctor"', (doctor_id,), fetchone=True)
        app.logger.info('BOOK APPT: patient_id=%s patient_email=%s doctor_id=%s doctor_email=%s',
                        uid,
                        patient.get('email') if patient else 'NOT FOUND',
                        doctor_id,
                        doctor.get('email') if doctor else 'NOT FOUND')
        appt_info = {
            'date':        date,
            'time':        time,
            'reason':      reason,
            'doctor_name': f"Dr. {doctor['fullname']}" if doctor else 'Selected Doctor',
        }
        # 1. Notify patient their booking was received
        if patient and patient.get('email'):
            app.logger.info('Sending Submitted email TO patient: %s', patient['email'])
            send_appointment_email(patient['email'], patient['fullname'], 'Submitted', appt_info)
        else:
            app.logger.warning('Patient email missing – no Submitted email sent. patient=%s', patient)
        # 2. Notify doctor a new appointment is waiting
        if doctor and doctor.get('email'):
            app.logger.info('Sending doctor notification TO doctor: %s', doctor['email'])
            send_doctor_notification_email(
                doctor['email'], doctor['fullname'],
                patient['fullname'] if patient else 'A patient',
                appt_info
            )
        else:
            app.logger.warning('Doctor email missing – no doctor notification sent. doctor=%s', doctor)
    except Exception as _e:
        app.logger.error('Book appointment email error: %s', _e, exc_info=True)
    # ────────────────────────────────────────────────────────────

    flash('Appointment booked successfully! Awaiting doctor confirmation.', 'success')
    return redirect(url_for('patient_dashboard'))


@app.route('/patient/cancel/<int:appt_id>', methods=['POST'])
@login_required
@role_required('patient')
def cancel_appointment(appt_id):
    uid = session['user_id']

    appt = query('SELECT * FROM appointments WHERE id=%s AND patient_id=%s',
                 (appt_id, uid), fetchone=True)

    # AJAX request → return JSON
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if not appt:
        if is_ajax:
            return jsonify({'error': 'Appointment not found.'}), 404
        flash('Appointment not found.', 'danger')
    elif appt['status'] in ('Completed', 'Rejected', 'Cancelled'):
        if is_ajax:
            return jsonify({'error': 'This appointment cannot be cancelled.'}), 400
        flash('This appointment cannot be cancelled.', 'warning')
    else:
        query("UPDATE appointments SET status='Cancelled' WHERE id=%s AND patient_id=%s",
              (appt_id, uid), commit=True)
        if is_ajax:
            return jsonify({'ok': True, 'appt_id': appt_id})
        flash('Appointment cancelled.', 'success')

    return redirect(url_for('patient_dashboard'))

# ══════════════════════════════════════════════
# PAYMENT ROUTES
# ══════════════════════════════════════════════

@app.route('/payment/<int:appt_id>')
@login_required
@role_required('patient')
def payment_page(appt_id):
    uid  = session['user_id']
    appt = query("""
        SELECT a.*, u.fullname AS doctor_name, u.specialization
        FROM appointments a JOIN users u ON u.id=a.doctor_id
        WHERE a.id=%s AND a.patient_id=%s AND a.status='Accepted'
    """, (appt_id, uid), fetchone=True)

    if not appt:
        flash('Payment not available for this appointment.', 'danger')
        return redirect(url_for('patient_dashboard'))

    # Check already paid
    paid = query('SELECT id FROM payments WHERE appointment_id=%s AND status="Paid"',
                 (appt_id,), fetchone=True)
    if paid:
        flash('This appointment has already been paid.', 'info')
        return redirect(url_for('patient_dashboard'))

    return render_template('payment.html',
                           appointment=appt,
                           paypal_client_id=PAYPAL_CLIENT_ID,
                           stripe_pk=STRIPE_PK)


@app.route('/payment/process', methods=['POST'])
@login_required
@role_required('patient')
def process_payment():
    uid      = session['user_id']
    appt_id  = request.form.get('appointment_id')
    method   = sanitize(request.form.get('method'))
    amount   = request.form.get('amount', 1500)
    tx_ref   = sanitize(request.form.get('transaction_ref', 'TXN-' + str(datetime.now().timestamp())))

    if method not in ('paypal', 'mpesa', 'stripe'):
        flash('Invalid payment method.', 'danger')
        return redirect(url_for('patient_dashboard'))

    # Verify appointment belongs to patient and is Accepted
    appt = query("SELECT * FROM appointments WHERE id=%s AND patient_id=%s AND status='Accepted'",
                 (appt_id, uid), fetchone=True)
    if not appt:
        flash('Payment not valid for this appointment.', 'danger')
        return redirect(url_for('patient_dashboard'))

    # Prevent double payment
    existing = query('SELECT id FROM payments WHERE appointment_id=%s AND status="Paid"',
                     (appt_id,), fetchone=True)
    if existing:
        flash('Already paid.', 'info')
        return redirect(url_for('patient_dashboard'))

    query("""
        INSERT INTO payments (appointment_id, patient_id, amount, method, status, transaction_ref)
        VALUES (%s,%s,%s,%s,'Paid',%s)
    """, (appt_id, uid, amount, method, tx_ref), commit=True)

    flash('Payment successful! Your appointment is confirmed.', 'success')
    return redirect(url_for('payment_success', appt_id=appt_id))


@app.route('/payment/stripe/intent', methods=['POST'])
@login_required
@role_required('patient')
def stripe_create_intent():
    """Create a Stripe PaymentIntent. Replace STRIPE_SK with your real key."""
    try:
        import stripe as stripe_lib
        stripe_lib.api_key = STRIPE_SK
        data = request.get_json()
        # KES is not supported by Stripe; convert to USD cents (KES 1500 ≈ USD 11.54)
        # Update the rate or pass it dynamically as needed
        intent = stripe_lib.PaymentIntent.create(
            amount=1154,  # USD 11.54 in cents (KES 1500 / ~130)
            currency='usd',
            metadata={'appointment_id': data.get('appointment_id'),
                      'patient_id': session['user_id']}
        )
        return jsonify({'client_secret': intent['client_secret']})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/payment/mpesa/stk', methods=['POST'])
@login_required
@role_required('patient')
def mpesa_stk_push():
    """Initiate Daraja STK Push. Fill in MPESA_* env vars to activate."""
    import requests as req_lib, base64, time
    data = request.get_json()
    phone = sanitize(data.get('phone', '')).replace('+', '').strip()
    appt_id = data.get('appointment_id')

    MPESA_CONSUMER_KEY    = os.environ.get('MPESA_CONSUMER_KEY')
    MPESA_CONSUMER_SECRET = os.environ.get('MPESA_CONSUMER_SECRET')
    MPESA_PASSKEY         = os.environ.get('MPESA_PASSKEY')
    MPESA_SHORTCODE       = os.environ.get('MPESA_SHORTCODE')
    MPESA_CALLBACK_URL    = os.environ.get('MPESA_CALLBACK_URL')

    # If keys are placeholders, simulate success for development
    if 'YOUR_' in MPESA_CONSUMER_KEY:
        # Dev mode: record as simulated payment
        tx_ref = 'MPESA-SIM-' + str(int(datetime.now().timestamp()))
        uid = session['user_id']
        existing = query('SELECT id FROM payments WHERE appointment_id=%s AND status="Paid"', (appt_id,), fetchone=True)
        if not existing:
            query("""INSERT INTO payments (appointment_id, patient_id, amount, method, status, transaction_ref)
                     VALUES (%s,%s,1500,'mpesa','Paid',%s)""", (appt_id, uid, tx_ref), commit=True)
        return jsonify({'ok': True, 'dev_mode': True, 'tx_ref': tx_ref})

    try:
        credentials = base64.b64encode(f'{MPESA_CONSUMER_KEY}:{MPESA_CONSUMER_SECRET}'.encode()).decode()
        token_res = req_lib.get(
            'https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials',
            headers={'Authorization': f'Basic {credentials}'}
        )
        token = token_res.json().get('access_token')
        timestamp = time.strftime('%Y%m%d%H%M%S')
        password  = base64.b64encode(f'{MPESA_SHORTCODE}{MPESA_PASSKEY}{timestamp}'.encode()).decode()

        stk_res = req_lib.post(
            'https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest',
            headers={'Authorization': f'Bearer {token}'},
            json={
                'BusinessShortCode': MPESA_SHORTCODE,
                'Password': password,
                'Timestamp': timestamp,
                'TransactionType': 'CustomerPayBillOnline',
                'Amount': 1500,
                'PartyA': phone,
                'PartyB': MPESA_SHORTCODE,
                'PhoneNumber': phone,
                'CallBackURL': MPESA_CALLBACK_URL,
                'AccountReference': f'APPT-{appt_id}',
                'TransactionDesc': 'Medical Consultation Fee'
            }
        )
        result = stk_res.json()
        return jsonify({'ok': result.get('ResponseCode') == '0', 'result': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/mpesa-express-simulate/', methods=['POST'])
def mpesa_callback():
    """Daraja will POST payment confirmation here."""
    data = request.get_json(silent=True) or {}
    try:
        cb = data['Body']['stkCallback']
        if cb['ResultCode'] == 0:
            items = {i['Name']: i['Value'] for i in cb['CallbackMetadata']['Item'] if 'Value' in i}
            tx_ref  = items.get('MpesaReceiptNumber', 'MPESA-' + str(datetime.now().timestamp()))
            account = items.get('AccountReference', '')
            appt_id = account.replace('APPT-', '') if account.startswith('APPT-') else None
            phone   = str(items.get('PhoneNumber', ''))

            if appt_id:
                appt = query('SELECT * FROM appointments WHERE id=%s', (appt_id,), fetchone=True)
                if appt:
                    existing = query('SELECT id FROM payments WHERE appointment_id=%s AND status="Paid"',
                                     (appt_id,), fetchone=True)
                    if not existing:
                        query("""INSERT INTO payments (appointment_id, patient_id, amount, method, status, transaction_ref)
                                 VALUES (%s,%s,1500,'mpesa','Paid',%s)""",
                              (appt_id, appt['patient_id'], tx_ref), commit=True)
    except Exception:
        pass
    return jsonify({'ResultCode': 0, 'ResultDesc': 'Accepted'})


@app.route('/payment/success/<int:appt_id>')
@login_required
@role_required('patient')
def payment_success(appt_id):
    uid   = session['user_id']
    appt  = query("""
        SELECT a.*, u.fullname AS doctor_name, p.amount, p.method, p.paid_at
        FROM appointments a
        JOIN users u ON u.id=a.doctor_id
        JOIN payments p ON p.appointment_id=a.id
        WHERE a.id=%s AND a.patient_id=%s
    """, (appt_id, uid), fetchone=True)
    return render_template('payment_success.html', appointment=appt)

# ══════════════════════════════════════════════
# DOCTOR ROUTES
# ══════════════════════════════════════════════

@app.route('/doctor/dashboard')
@login_required
@role_required('doctor')
def doctor_dashboard():
    uid = session['user_id']

    stats = query("""
        SELECT
            SUM(status='Pending')   AS pending,
            SUM(status='Accepted')  AS accepted,
            SUM(status='Completed') AS completed
        FROM appointments WHERE doctor_id=%s
    """, (uid,), fetchone=True)

    appointments = query("""
        SELECT a.*, u.fullname AS patient_name, u.phone AS patient_phone
        FROM appointments a
        JOIN users u ON u.id=a.patient_id
        WHERE a.doctor_id=%s
        ORDER BY a.date ASC, a.time ASC
    """, (uid,), fetchall=True)

    doctor = query('SELECT id, fullname, email, phone, specialization, profile_picture FROM users WHERE id=%s', (uid,), fetchone=True)
    must_change = session.pop('must_change_password', False)
    return render_template('doctor_dashboard.html', stats=stats, appointments=appointments, doctor=doctor, must_change_password=must_change)


@app.route('/doctor/update/<int:appt_id>/<action>', methods=['POST'])
@login_required
@role_required('doctor')
def doctor_update(appt_id, action):
    uid = session['user_id']
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    appt = query('SELECT * FROM appointments WHERE id=%s AND doctor_id=%s',
                 (appt_id, uid), fetchone=True)

    if not appt:
        if is_ajax:
            return jsonify({'ok': False, 'error': 'Appointment not found'}), 404
        flash('Appointment not found.', 'danger')
        return redirect(url_for('doctor_dashboard'))

    status_map = {'accept': 'Accepted', 'reject': 'Rejected', 'complete': 'Completed'}
    allowed = {
        'accept':   appt['status'] == 'Pending',
        'reject':   appt['status'] == 'Pending',
        'complete': appt['status'] == 'Accepted'
    }

    if action not in status_map or not allowed.get(action):
        if is_ajax:
            return jsonify({'ok': False, 'error': 'Action not permitted'}), 400
        flash('Action not permitted.', 'warning')
    else:
        new_status = status_map[action]
        query('UPDATE appointments SET status=%s WHERE id=%s AND doctor_id=%s',
              (new_status, appt_id, uid), commit=True)

        # ── Send appointment notification email to patient ──
        try:
            patient = query('SELECT id, fullname, email FROM users WHERE id=%s', (appt['patient_id'],), fetchone=True)
            doctor  = query('SELECT fullname FROM users WHERE id=%s AND role="doctor"', (uid,), fetchone=True)
            app.logger.info('DOCTOR UPDATE: new_status=%s patient_id=%s patient_email=%s',
                            new_status,
                            appt['patient_id'],
                            patient.get('email') if patient else 'NOT FOUND')
            if patient and patient.get('email'):
                appt_info = {
                    'date':        appt.get('date'),
                    'time':        appt.get('time'),
                    'reason':      appt.get('reason'),
                    'doctor_name': f"Dr. {doctor['fullname']}" if doctor else 'Your Doctor',
                }
                app.logger.info('Sending %s email TO patient: %s', new_status, patient['email'])
                send_appointment_email(patient['email'], patient['fullname'], new_status, appt_info)
            else:
                app.logger.warning('Patient email missing for status update. patient=%s', patient)
        except Exception as email_err:
            app.logger.error('Appointment email error: %s', email_err, exc_info=True)
        # ────────────────────────────────────────────────────

        if is_ajax:
            # Return updated stats too
            stats = query("""
                SELECT
                    SUM(status='Pending')   AS pending,
                    SUM(status='Accepted')  AS accepted,
                    SUM(status='Completed') AS completed
                FROM appointments WHERE doctor_id=%s
            """, (uid,), fetchone=True)
            return jsonify({
                'ok': True,
                'new_status': new_status,
                'appt_id': appt_id,
                'stats': {k: int(v or 0) for k, v in stats.items()}
            })
        flash(f'Appointment marked as {new_status}.', 'success')

    return redirect(url_for('doctor_dashboard'))


@app.route('/api/doctor/appointments')
@login_required
@role_required('doctor')
def api_doctor_appointments():
    """Return appointments list as JSON for live refresh."""
    uid = session['user_id']
    appointments = query("""
        SELECT a.*, u.fullname AS patient_name, u.phone AS patient_phone
        FROM appointments a
        JOIN users u ON u.id=a.patient_id
        WHERE a.doctor_id=%s
        ORDER BY a.date ASC, a.time ASC
    """, (uid,), fetchall=True)

    result = []
    for a in appointments:
        result.append({
            'id':           a['id'],
            'patient_name': a['patient_name'],
            'patient_phone':a['patient_phone'],
            'date':         str(a['date']),
            'time':         str(a['time']),
            'reason':       a['reason'],
            'status':       a['status'],
        })
    return jsonify({'appointments': result})


# ══════════════════════════════════════════════
# PROFILE ROUTES (patient + doctor)
# ══════════════════════════════════════════════

@app.route('/profile/update', methods=['POST'])
@login_required
def update_profile():
    """Update name, phone (and specialization for doctors)."""
    uid      = session['user_id']
    role     = session['role']
    fullname = sanitize(request.form.get('fullname', ''))
    phone    = sanitize(request.form.get('phone', ''))
    spec     = sanitize(request.form.get('specialization', ''))

    errors = []
    if len(fullname) < 3:
        errors.append('Full name must be at least 3 characters.')
    if not validate_phone(phone):
        errors.append('Invalid phone number.')
    if errors:
        for e in errors:
            flash(e, 'danger')
        return redirect(url_for('dashboard'))

    if role == 'doctor':
        query('UPDATE users SET fullname=%s, phone=%s, specialization=%s WHERE id=%s',
              (fullname, phone, spec, uid), commit=True)
    else:
        query('UPDATE users SET fullname=%s, phone=%s WHERE id=%s',
              (fullname, phone, uid), commit=True)

    session['fullname'] = fullname
    flash('Profile updated successfully.', 'success')
    return redirect(url_for('dashboard'))


@app.route('/profile/picture', methods=['POST'])
@login_required
def update_profile_picture():
    """Upload and save a new profile picture."""
    uid  = session['user_id']
    file = request.files.get('profile_picture')

    if not file or file.filename == '':
        flash('No file selected.', 'warning')
        return redirect(url_for('dashboard'))

    if not allowed_file(file.filename):
        flash('Invalid file type. Please upload a PNG, JPG, JPEG, GIF, or WEBP image.', 'danger')
        return redirect(url_for('dashboard'))

    os.makedirs(IMG_UPLOAD_FOLDER, exist_ok=True)
    ext      = file.filename.rsplit('.', 1)[1].lower()
    filename = secure_filename(f'user_{uid}.{ext}')
    filepath = os.path.join(IMG_UPLOAD_FOLDER, filename)
    file.save(filepath)

    # Store relative path from static/ so url_for('static') works
    rel_path = f'uploads/avatars/{filename}'
    query('UPDATE users SET profile_picture=%s WHERE id=%s', (rel_path, uid), commit=True)
    flash('Profile picture updated!', 'success')
    return redirect(url_for('dashboard'))


@app.route('/profile/change-password', methods=['POST'])
@login_required
def change_password():
    """Change password (used by doctors on first login and by anyone from profile)."""
    uid          = session['user_id']
    current_pw   = request.form.get('current_password', '')
    new_pw       = request.form.get('new_password', '')
    confirm_pw   = request.form.get('confirm_password', '')

    user = query('SELECT password, must_change_password FROM users WHERE id=%s', (uid,), fetchone=True)
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('dashboard'))

    # If it's a forced change, skip current-password check
    is_forced = bool(user.get('must_change_password'))
    if not is_forced:
        if not bcrypt.checkpw(current_pw.encode(), user['password'].encode()):
            flash('Current password is incorrect.', 'danger')
            return redirect(url_for('dashboard'))

    if len(new_pw) < 8:
        flash('New password must be at least 8 characters.', 'danger')
        return redirect(url_for('dashboard'))
    if new_pw != confirm_pw:
        flash('Passwords do not match.', 'danger')
        return redirect(url_for('dashboard'))

    hashed = bcrypt.hashpw(new_pw.encode(), bcrypt.gensalt()).decode()
    query('UPDATE users SET password=%s, must_change_password=0 WHERE id=%s',
          (hashed, uid), commit=True)
    flash('Password changed successfully!', 'success')
    return redirect(url_for('dashboard'))

# ══════════════════════════════════════════════
# ADMIN ROUTES
# ══════════════════════════════════════════════

@app.route('/admin/dashboard')
@login_required
@role_required('admin')
def admin_dashboard():
    stats = query("""
        SELECT
            (SELECT COUNT(*) FROM users WHERE role='patient') AS total_patients,
            (SELECT COUNT(*) FROM users WHERE role='doctor')  AS total_doctors,
            (SELECT COUNT(*) FROM users)                      AS total_users,
            (SELECT COUNT(*) FROM appointments)               AS total_appointments,
            (SELECT COALESCE(SUM(amount),0) FROM payments WHERE status='Paid') AS total_revenue
    """, fetchone=True)

    filter_status = request.args.get('status', 'All')
    if filter_status != 'All':
        appointments = query("""
            SELECT a.*, p.fullname AS patient_name, d.fullname AS doctor_name
            FROM appointments a
            JOIN users p ON p.id=a.patient_id
            JOIN users d ON d.id=a.doctor_id
            WHERE a.status=%s ORDER BY a.created_at DESC
        """, (filter_status,), fetchall=True)
    else:
        appointments = query("""
            SELECT a.*, p.fullname AS patient_name, d.fullname AS doctor_name
            FROM appointments a
            JOIN users p ON p.id=a.patient_id
            JOIN users d ON d.id=a.doctor_id
            ORDER BY a.created_at DESC
        """, fetchall=True)

    users    = query("SELECT id, fullname, email, phone, role, specialization, created_at FROM users ORDER BY created_at DESC", fetchall=True)
    doctors  = query("SELECT id, fullname, email, specialization FROM users WHERE role='doctor' ORDER BY fullname", fetchall=True)

    return render_template('admin_dashboard.html',
                           stats=stats,
                           appointments=appointments,
                           users=users,
                           doctors=doctors,
                           filter_status=filter_status)


@app.route('/admin/appointment/status/<int:appt_id>', methods=['POST'])
@login_required
@role_required('admin')
def admin_update_status(appt_id):
    new_status = sanitize(request.form.get('status'))
    allowed    = ('Pending','Accepted','Rejected','Completed','Cancelled')
    if new_status not in allowed:
        flash('Invalid status.', 'danger')
    else:
        query('UPDATE appointments SET status=%s WHERE id=%s', (new_status, appt_id), commit=True)
        flash(f'Status updated to {new_status}.', 'success')

        # ── Send appointment notification email to patient ──
        if new_status in ('Accepted', 'Rejected', 'Completed'):
            try:
                appt = query("""
                    SELECT a.*, u.fullname AS patient_name, u.email AS patient_email,
                           d.fullname AS doctor_name
                    FROM appointments a
                    JOIN users u ON u.id = a.patient_id
                    JOIN users d ON d.id = a.doctor_id
                    WHERE a.id=%s
                """, (appt_id,), fetchone=True)
                if appt and appt.get('patient_email'):
                    appt_info = {
                        'date':        appt.get('date'),
                        'time':        appt.get('time'),
                        'reason':      appt.get('reason'),
                        'doctor_name': f"Dr. {appt['doctor_name']}",
                    }
                    send_appointment_email(appt['patient_email'], appt['patient_name'], new_status, appt_info)
            except Exception as email_err:
                app.logger.error('Admin appointment email error: %s', email_err)
        # ────────────────────────────────────────────────────

    return redirect(url_for('admin_dashboard'))


@app.route('/admin/appointment/delete/<int:appt_id>', methods=['POST'])
@login_required
@role_required('admin')
def admin_delete_appointment(appt_id):
    query('DELETE FROM appointments WHERE id=%s', (appt_id,), commit=True)
    flash('Appointment deleted.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/doctor/add', methods=['POST'])
@login_required
@role_required('admin')
def admin_add_doctor():
    fullname       = sanitize(request.form.get('fullname'))
    email          = sanitize(request.form.get('email')).lower()
    phone          = sanitize(request.form.get('phone'))
    specialization = sanitize(request.form.get('specialization'))
    password       = request.form.get('password', 'Doctor@1234')

    errors = []
    if not fullname: errors.append('Full name required.')
    if not validate_email(email): errors.append('Invalid email.')
    if not validate_phone(phone): errors.append('Invalid phone.')
    if not specialization: errors.append('Specialization required.')

    if errors:
        for e in errors: flash(e, 'danger')
        return redirect(url_for('admin_dashboard'))

    existing = query('SELECT id FROM users WHERE email=%s', (email,), fetchone=True)
    if existing:
        flash('Email already registered.', 'danger')
        return redirect(url_for('admin_dashboard'))

    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    query("""
        INSERT INTO users (fullname, email, phone, password, role, specialization, must_change_password)
        VALUES (%s,%s,%s,%s,'doctor',%s, 1)
    """, (fullname, email, phone, hashed, specialization), commit=True)
    flash(f'Dr. {fullname} added successfully. Default password: {password}', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/doctor/delete/<int:uid>', methods=['POST'])
@login_required
@role_required('admin')
def admin_delete_doctor(uid):
    query('DELETE FROM users WHERE id=%s AND role="doctor"', (uid,), commit=True)
    flash('Doctor removed.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/user/delete/<int:uid>', methods=['POST'])
@login_required
@role_required('admin')
def admin_delete_user(uid):
    if uid == session['user_id']:
        flash('Cannot delete yourself.', 'danger')
        return redirect(url_for('admin_dashboard'))
    query('DELETE FROM users WHERE id=%s', (uid,), commit=True)
    flash('User deleted.', 'success')
    return redirect(url_for('admin_dashboard'))


# ══════════════════════════════════════════════
# API ENDPOINTS (JSON)
# ══════════════════════════════════════════════

@app.route('/api/stats')
@login_required
def api_stats():
    """AJAX endpoint for live dashboard counters."""
    uid  = session['user_id']
    role = session['role']

    if role == 'patient':
        data = query("""
            SELECT SUM(status='Pending') AS pending, SUM(status='Accepted') AS accepted,
                   SUM(status='Completed') AS completed, SUM(status='Cancelled') AS cancelled
            FROM appointments WHERE patient_id=%s
        """, (uid,), fetchone=True)
    elif role == 'doctor':
        data = query("""
            SELECT SUM(status='Pending') AS pending, SUM(status='Accepted') AS accepted,
                   SUM(status='Completed') AS completed
            FROM appointments WHERE doctor_id=%s
        """, (uid,), fetchone=True)
    else:
        data = query("""
            SELECT COUNT(*) AS total_appointments,
                   COALESCE(SUM(p.amount),0) AS revenue
            FROM appointments a
            LEFT JOIN payments p ON p.appointment_id=a.id AND p.status='Paid'
        """, fetchone=True)

    return jsonify({k: int(v or 0) for k, v in data.items()})


@app.route('/api/payment/status/<int:appt_id>')
@login_required
@role_required('patient')
def payment_status(appt_id):
    uid  = session['user_id']
    paid = query('SELECT id FROM payments WHERE appointment_id=%s AND patient_id=%s AND status="Paid"',
                 (appt_id, uid), fetchone=True)
    return jsonify({'paid': bool(paid)})


# ══════════════════════════════════════════════
# CHAT ROUTES
# ══════════════════════════════════════════════

@app.route('/api/presence/ping', methods=['POST'])
@login_required
def presence_ping():
    """Called periodically by the client to mark user as online."""
    uid = session['user_id']
    try:
        query("""
            INSERT INTO user_presence (user_id, is_online, last_seen)
            VALUES (%s, 1, UTC_TIMESTAMP())
            ON DUPLICATE KEY UPDATE is_online=1, last_seen=UTC_TIMESTAMP()
        """, (uid,), commit=True)
    except Exception as e:
        # Never let a presence ping crash the server
        app.logger.warning('presence_ping error: %s', e)
    return jsonify({'ok': True})


@app.route('/api/presence/offline', methods=['POST'])
@login_required
def presence_offline():
    """Mark current user as offline immediately (called on page unload)."""
    uid = session.get('user_id')
    if uid:
        try:
            query("UPDATE user_presence SET is_online=0 WHERE user_id=%s", (uid,), commit=True)
        except Exception:
            pass
    return ('', 204)


@app.route('/api/presence/<int:user_id>')
@login_required
def get_presence(user_id):
    """Return online status for a given user."""
    p = query("SELECT is_online, last_seen FROM user_presence WHERE user_id=%s", (user_id,), fetchone=True)
    if not p:
        return jsonify({'online': False, 'last_seen': None})
    # Mark offline if last_seen > 30 seconds ago
    last = p['last_seen']
    online = p['is_online'] == 1 and (datetime.utcnow() - last).total_seconds() < 30
    return jsonify({'online': online, 'last_seen': str(last)})


@app.route('/api/chat/<int:appt_id>/messages')
@login_required
def get_messages(appt_id):
    """Return messages for a chat (patient or doctor of the appointment)."""
    uid  = session['user_id']
    role = session['role']

    appt = query("SELECT * FROM appointments WHERE id=%s", (appt_id,), fetchone=True)
    if not appt:
        return jsonify({'error': 'Appointment not found'}), 404
    if uid not in (appt['patient_id'], appt['doctor_id']):
        return jsonify({'error': 'Access denied'}), 403
    if appt['status'] != 'Accepted':
        return jsonify({'error': 'Chat only available for accepted appointments'}), 403

    # Mark messages sent to me as read
    query("""
        UPDATE chat_messages SET is_read=1
        WHERE appointment_id=%s AND receiver_id=%s AND is_read=0
    """, (appt_id, uid), commit=True)

    messages = query("""
        SELECT m.*, u.fullname AS sender_name, u.role AS sender_role
        FROM chat_messages m
        JOIN users u ON u.id = m.sender_id
        WHERE m.appointment_id=%s
        ORDER BY m.created_at ASC
    """, (appt_id,), fetchall=True)

    result = []
    for m in messages:
        result.append({
            'id':           m['id'],
            'sender_id':    m['sender_id'],
            'sender_name':  m['sender_name'],
            'sender_role':  m['sender_role'],
            'message':      m['message'],
            'is_read':      bool(m['is_read']),
            'delivered':    bool(m['delivered']),
            'created_at':   str(m['created_at']),
            'is_mine':      m['sender_id'] == uid,
        })

    # also return the other party's presence
    other_id = appt['doctor_id'] if uid == appt['patient_id'] else appt['patient_id']
    p = query("SELECT is_online, last_seen FROM user_presence WHERE user_id=%s", (other_id,), fetchone=True)
    other_online = False
    if p:
        other_online = p['is_online'] == 1 and (datetime.utcnow() - p['last_seen']).total_seconds() < 30

    return jsonify({'messages': result, 'other_online': other_online, 'my_id': uid})


@app.route('/api/chat/<int:appt_id>/send', methods=['POST'])
@login_required
def send_message(appt_id):
    """Send a chat message."""
    uid  = session['user_id']
    appt = query("SELECT * FROM appointments WHERE id=%s", (appt_id,), fetchone=True)
    if not appt:
        return jsonify({'error': 'Appointment not found'}), 404
    if uid not in (appt['patient_id'], appt['doctor_id']):
        return jsonify({'error': 'Access denied'}), 403
    if appt['status'] != 'Accepted':
        return jsonify({'error': 'Chat only available for accepted appointments'}), 403

    data       = request.get_json()
    message    = sanitize(data.get('message', ''))
    if not message:
        return jsonify({'error': 'Empty message'}), 400

    receiver_id = appt['doctor_id'] if uid == appt['patient_id'] else appt['patient_id']

    # Check receiver presence for delivered flag
    p = query("SELECT is_online, last_seen FROM user_presence WHERE user_id=%s", (receiver_id,), fetchone=True)
    receiver_online = False
    if p:
        receiver_online = p['is_online'] == 1 and (datetime.utcnow() - p['last_seen']).total_seconds() < 30

    msg_id = query("""
        INSERT INTO chat_messages (appointment_id, sender_id, receiver_id, message, delivered, is_read)
        VALUES (%s,%s,%s,%s,%s,%s)
    """, (appt_id, uid, receiver_id, message, 1, 1 if receiver_online else 0), commit=True)

    msg = query("SELECT * FROM chat_messages WHERE id=%s", (msg_id,), fetchone=True)

    return jsonify({
        'id':        msg['id'],
        'message':   msg['message'],
        'delivered': bool(msg['delivered']),
        'is_read':   bool(msg['is_read']),
        'created_at': str(msg['created_at']),
        'is_mine':   True,
        'other_online': receiver_online
    })


@app.route('/api/chat/<int:appt_id>/mark_read', methods=['POST'])
@login_required
def mark_read(appt_id):
    uid = session['user_id']
    query("""
        UPDATE chat_messages SET is_read=1
        WHERE appointment_id=%s AND receiver_id=%s AND is_read=0
    """, (appt_id, uid), commit=True)
    return jsonify({'ok': True})


# ──────────────────────────────────────────────

def send_doctor_notification_email(to_email, doctor_name, patient_name, appt):
    """Notify the doctor by email that a new appointment has been booked."""
    host, port, username, password, sender, base_url = _mail_cfg()
    if not username or not password:
        app.logger.warning('Mail not configured – doctor notification NOT sent to %s', to_email)
        return

    appt_date    = str(appt.get('date', 'N/A'))
    appt_time    = str(appt.get('time', 'N/A'))
    reason       = appt.get('reason', 'N/A')
    dashboard    = f"{base_url}/dashboard"

    html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;padding:40px 20px;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#fff;border-radius:20px;overflow:hidden;box-shadow:0 8px 30px rgba(0,0,0,.1);">
        <tr>
          <td style="background:linear-gradient(135deg,#0f172a,#1d4ed8);padding:36px 40px;text-align:center;">
            <div style="font-size:40px;margin-bottom:8px;">&#128203;</div>
            <h1 style="color:#fff;margin:0;font-size:26px;font-weight:700;">MediCare</h1>
            <p style="color:rgba(255,255,255,.75);margin:6px 0 0;font-size:14px;">Doctor Portal Notification</p>
          </td>
        </tr>
        <tr>
          <td style="padding:40px 40px 32px;">
            <h2 style="color:#1e293b;font-size:22px;margin:0 0 12px;">New Appointment Request</h2>
            <p style="color:#475569;font-size:15px;line-height:1.6;margin:0 0 24px;">
              Hi <strong>Dr. {doctor_name}</strong>,<br><br>
              A patient has booked an appointment with you. Please log in to accept or reject it.
            </p>
            <table width="100%" cellpadding="0" cellspacing="0" style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;margin-bottom:28px;">
              <tr><td style="padding:20px 24px;">
                <p style="margin:0 0 4px;color:#94a3b8;font-size:12px;font-weight:600;text-transform:uppercase;">Appointment Details</p>
                <hr style="border:none;border-top:1px solid #e2e8f0;margin:10px 0;">
                <table width="100%" cellpadding="5" cellspacing="0">
                  <tr>
                    <td style="color:#64748b;font-size:13px;width:38%;">&#128100; Patient</td>
                    <td style="color:#1e293b;font-size:13px;font-weight:600;">{patient_name}</td>
                  </tr>
                  <tr>
                    <td style="color:#64748b;font-size:13px;">&#128197; Date</td>
                    <td style="color:#1e293b;font-size:13px;font-weight:600;">{appt_date}</td>
                  </tr>
                  <tr>
                    <td style="color:#64748b;font-size:13px;">&#128336; Time</td>
                    <td style="color:#1e293b;font-size:13px;font-weight:600;">{appt_time}</td>
                  </tr>
                  <tr>
                    <td style="color:#64748b;font-size:13px;">&#128203; Reason</td>
                    <td style="color:#1e293b;font-size:13px;font-weight:600;">{reason}</td>
                  </tr>
                </table>
              </td></tr>
            </table>
            <div style="text-align:center;">
              <a href="{dashboard}" style="background:#1d4ed8;color:#fff;padding:14px 32px;border-radius:12px;text-decoration:none;font-weight:700;font-size:15px;display:inline-block;">
                Go to My Dashboard
              </a>
            </div>
          </td>
        </tr>
        <tr>
          <td style="background:#f8fafc;padding:24px 40px;border-top:1px solid #e2e8f0;text-align:center;">
            <p style="color:#94a3b8;font-size:12px;margin:0;">&#169; 2024 MediCare · This is an automated message.</p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body></html>"""

    text_body = f"""MediCare – New Appointment Request

Hi Dr. {doctor_name},

Patient  : {patient_name}
Date     : {appt_date}
Time     : {appt_time}
Reason   : {reason}

Log in to accept or reject: {dashboard}

— The MediCare Team
"""
    try:
        msg            = MIMEMultipart('alternative')
        msg['Subject'] = 'MediCare – New Appointment Request &#128203;'
        msg['From']    = f'MediCare <{sender}>'
        msg['To']      = to_email
        msg.attach(MIMEText(text_body, 'plain'))
        msg.attach(MIMEText(html_body, 'html'))
        with smtplib.SMTP(host, port) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(username, password)
            server.sendmail(sender, to_email, msg.as_string())
        app.logger.info('Doctor notification email sent to %s', to_email)
    except Exception as e:
        app.logger.error('send_doctor_notification_email failed: %s', e)

# Password Reset – Email Helper
# ──────────────────────────────────────────────
def send_reset_email(to_email, to_name, reset_url):
    """Send a password-reset email. Returns (True, None) or (False, error_msg)."""
    host, port, username, password, sender, base_url = _mail_cfg()

    if not username or not password:
        app.logger.warning('MAIL_USERNAME/MAIL_PASSWORD not set – reset email NOT sent to %s', to_email)
        return False, 'Email service not configured. Please set MAIL_USERNAME and MAIL_PASSWORD in .env'

    subject   = 'MediCare – Password Reset Request'
    html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;padding:40px 20px;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#fff;border-radius:20px;overflow:hidden;box-shadow:0 8px 30px rgba(0,0,0,.1);">
        <tr>
          <td style="background:linear-gradient(135deg,#1e3a8a,#2563eb);padding:36px 40px;text-align:center;">
            <div style="font-size:36px;margin-bottom:8px;">&#127968;</div>
            <h1 style="color:#fff;margin:0;font-size:26px;font-weight:700;">MediCare</h1>
            <p style="color:rgba(255,255,255,.75);margin:6px 0 0;font-size:14px;">Your trusted healthcare platform</p>
          </td>
        </tr>
        <tr>
          <td style="padding:40px 40px 32px;">
            <h2 style="color:#1e293b;font-size:22px;margin:0 0 12px;">Password Reset Request</h2>
            <p style="color:#475569;font-size:15px;line-height:1.6;margin:0 0 20px;">
              Hi <strong>{to_name}</strong>,<br><br>
              We received a request to reset your MediCare password.
              Click the button below — this link expires in <strong>30 minutes</strong>.
            </p>
            <div style="text-align:center;margin:32px 0;">
              <a href="{reset_url}" style="background:#2563eb;color:#fff;padding:16px 36px;border-radius:12px;text-decoration:none;font-weight:700;font-size:16px;display:inline-block;">
                &#128272; Reset My Password
              </a>
            </div>
            <p style="color:#64748b;font-size:13px;margin:0 0 8px;">If the button does not work, copy this link into your browser:</p>
            <p style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:12px 16px;font-size:12px;color:#2563eb;word-break:break-all;margin:0 0 24px;">{reset_url}</p>
            <div style="background:#fef3c7;border-left:4px solid #f59e0b;border-radius:0 10px 10px 0;padding:14px 18px;">
              <p style="color:#92400e;font-size:13px;margin:0;">
                <strong>&#9888;&#65039; Didn't request this?</strong> Ignore this email — your password will not change.
              </p>
            </div>
          </td>
        </tr>
        <tr>
          <td style="background:#f8fafc;padding:24px 40px;border-top:1px solid #e2e8f0;text-align:center;">
            <p style="color:#94a3b8;font-size:12px;margin:0;">&#169; 2024 MediCare · Secure Healthcare Platform<br>This is an automated message — please do not reply.</p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body></html>"""

    text_body = f"""MediCare – Password Reset

Hi {to_name},

Reset your password here:
{reset_url}

This link expires in 30 minutes.
If you did not request this, ignore this email.

— The MediCare Team
"""

    try:
        msg            = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From']    = f'MediCare <{sender}>'
        msg['To']      = to_email
        msg.attach(MIMEText(text_body, 'plain'))
        msg.attach(MIMEText(html_body, 'html'))

        app.logger.info('send_reset_email: FROM=%s  TO=%s', sender, to_email)
        with smtplib.SMTP(host, port) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(username, password)
            server.sendmail(sender, [to_email], msg.as_string())

        app.logger.info('SUCCESS: Password reset email delivered to %s', to_email)
        return True, None
    except smtplib.SMTPAuthenticationError:
        err = 'SMTP authentication failed. Check MAIL_USERNAME and MAIL_PASSWORD in .env'
        app.logger.error('send_reset_email AUTH ERROR: %s', err)
        return False, err
    except Exception as e:
        app.logger.error('send_reset_email FAILED: %s', e, exc_info=True)
        return False, str(e)


# ──────────────────────────────────────────────
# Appointment Notification Email Helper
# ──────────────────────────────────────────────
def send_appointment_email(to_email, to_name, status, appt):
    """Send appointment status notification. status: Submitted|Accepted|Rejected|Completed"""
    host, port, username, password, sender, base_url = _mail_cfg()

    if not username or not password:
        app.logger.warning('MAIL_USERNAME/MAIL_PASSWORD not set – appointment email NOT sent to %s', to_email)
        return False, 'Email service not configured.'

    status_config = {
        'Submitted': {
            'subject':   'MediCare – Appointment Request Received &#128203;',
            'icon':      '&#128203;',
            'gradient':  'linear-gradient(135deg,#1e3a8a,#2563eb)',
            'color':     '#2563eb',
            'heading':   'Appointment Request Received',
            'message':   'Your appointment request has been <strong>submitted successfully</strong>. The doctor will review it shortly.',
            'tag_bg':    '#dbeafe', 'tag_fg': '#1e3a8a', 'tag':  'PENDING REVIEW',
        },
        'Accepted': {
            'subject':   'MediCare – Appointment Confirmed &#9989;',
            'icon':      '&#9989;',
            'gradient':  'linear-gradient(135deg,#14532d,#16a34a)',
            'color':     '#16a34a',
            'heading':   'Appointment Confirmed!',
            'message':   'Great news! Your appointment has been <strong>accepted</strong> by the doctor. Please be ready at the scheduled time.',
            'tag_bg':    '#dcfce7', 'tag_fg': '#14532d', 'tag':  'CONFIRMED',
        },
        'Rejected': {
            'subject':   'MediCare – Appointment Update',
            'icon':      '&#10060;',
            'gradient':  'linear-gradient(135deg,#7f1d1d,#dc2626)',
            'color':     '#dc2626',
            'heading':   'Appointment Not Accepted',
            'message':   'Unfortunately your appointment request could not be accepted at this time. Please book a new appointment or contact support.',
            'tag_bg':    '#fee2e2', 'tag_fg': '#7f1d1d', 'tag':  'NOT ACCEPTED',
        },
        'Completed': {
            'subject':   'MediCare – Appointment Completed &#127881;',
            'icon':      '&#127881;',
            'gradient':  'linear-gradient(135deg,#1e3a8a,#2563eb)',
            'color':     '#2563eb',
            'heading':   'Appointment Completed',
            'message':   'Your appointment has been marked as <strong>completed</strong>. We hope you had a great experience. Take care!',
            'tag_bg':    '#dbeafe', 'tag_fg': '#1e3a8a', 'tag':  'COMPLETED',
        },
    }

    cfg = status_config.get(status)
    if not cfg:
        app.logger.warning('send_appointment_email: unknown status "%s"', status)
        return False, f'Unknown status: {status}'

    appt_date   = str(appt.get('date', 'N/A'))
    appt_time   = str(appt.get('time', 'N/A'))
    doctor_name = appt.get('doctor_name', 'Your Doctor')
    reason      = appt.get('reason', 'N/A')
    dashboard   = f"{base_url}/dashboard"

    html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;padding:40px 20px;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#fff;border-radius:20px;overflow:hidden;box-shadow:0 8px 30px rgba(0,0,0,.1);">
        <tr>
          <td style="background:{cfg['gradient']};padding:36px 40px;text-align:center;">
            <div style="font-size:40px;margin-bottom:8px;">{cfg['icon']}</div>
            <h1 style="color:#fff;margin:0;font-size:26px;font-weight:700;">MediCare</h1>
            <p style="color:rgba(255,255,255,.75);margin:6px 0 0;font-size:14px;">Your trusted healthcare platform</p>
          </td>
        </tr>
        <tr>
          <td style="padding:40px 40px 32px;">
            <h2 style="color:#1e293b;font-size:22px;margin:0 0 12px;">{cfg['heading']}</h2>
            <p style="color:#475569;font-size:15px;line-height:1.6;margin:0 0 24px;">
              Hi <strong>{to_name}</strong>,<br><br>{cfg['message']}
            </p>
            <table width="100%" cellpadding="0" cellspacing="0" style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;margin-bottom:28px;">
              <tr><td style="padding:20px 24px;">
                <p style="margin:0 0 4px;color:#94a3b8;font-size:12px;font-weight:600;text-transform:uppercase;">Appointment Details</p>
                <hr style="border:none;border-top:1px solid #e2e8f0;margin:10px 0;">
                <table width="100%" cellpadding="5" cellspacing="0">
                  <tr>
                    <td style="color:#64748b;font-size:13px;width:38%;">&#128104;&#8205;&#9877;&#65039; Doctor</td>
                    <td style="color:#1e293b;font-size:13px;font-weight:600;">{doctor_name}</td>
                  </tr>
                  <tr>
                    <td style="color:#64748b;font-size:13px;">&#128197; Date</td>
                    <td style="color:#1e293b;font-size:13px;font-weight:600;">{appt_date}</td>
                  </tr>
                  <tr>
                    <td style="color:#64748b;font-size:13px;">&#128336; Time</td>
                    <td style="color:#1e293b;font-size:13px;font-weight:600;">{appt_time}</td>
                  </tr>
                  <tr>
                    <td style="color:#64748b;font-size:13px;">&#128203; Reason</td>
                    <td style="color:#1e293b;font-size:13px;font-weight:600;">{reason}</td>
                  </tr>
                  <tr>
                    <td style="color:#64748b;font-size:13px;">&#127991;&#65039; Status</td>
                    <td><span style="background:{cfg['tag_bg']};color:{cfg['tag_fg']};font-size:11px;font-weight:700;padding:3px 10px;border-radius:20px;">{cfg['tag']}</span></td>
                  </tr>
                </table>
              </td></tr>
            </table>
            <div style="text-align:center;margin-bottom:12px;">
              <a href="{dashboard}" style="background:{cfg['color']};color:#fff;padding:14px 32px;border-radius:12px;text-decoration:none;font-weight:700;font-size:15px;display:inline-block;">
                View My Dashboard
              </a>
            </div>
          </td>
        </tr>
        <tr>
          <td style="background:#f8fafc;padding:24px 40px;border-top:1px solid #e2e8f0;text-align:center;">
            <p style="color:#94a3b8;font-size:12px;margin:0;">&#169; 2024 MediCare · This is an automated message — please do not reply.</p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body></html>"""

    text_body = f"""MediCare – {cfg['heading']}

Hi {to_name},

Status  : {status}
Doctor  : {doctor_name}
Date    : {appt_date}
Time    : {appt_time}
Reason  : {reason}

View your dashboard: {dashboard}

— The MediCare Team
"""

    try:
        msg            = MIMEMultipart('alternative')
        msg['Subject'] = cfg['subject']
        msg['From']    = f'MediCare <{sender}>'
        msg['To']      = to_email
        msg.attach(MIMEText(text_body, 'plain'))
        msg.attach(MIMEText(html_body, 'html'))

        app.logger.info('send_appointment_email: FROM=%s  TO=%s  STATUS=%s', sender, to_email, status)
        with smtplib.SMTP(host, port) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(username, password)
            server.sendmail(sender, [to_email], msg.as_string())

        app.logger.info('SUCCESS: Appointment email (%s) delivered to %s', status, to_email)
        return True, None
    except smtplib.SMTPAuthenticationError:
        err = 'SMTP auth failed. Check MAIL_USERNAME and MAIL_PASSWORD in .env'
        app.logger.error('send_appointment_email AUTH ERROR: %s', err)
        return False, err
    except Exception as e:
        app.logger.error('send_appointment_email FAILED: %s', e, exc_info=True)
        return False, str(e)


# ──────────────────────────────────────────────
# Forgot Password – Request Reset Link
# ──────────────────────────────────────────────
@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        if not email or not validate_email(email):
            flash('Please enter a valid email address.', 'danger')
            return render_template('forgot_password.html')

        user = query('SELECT id, fullname, email FROM users WHERE email=%s', (email,), fetchone=True)

        # Always show the same message to prevent email enumeration
        if user:
            token = secrets.token_urlsafe(48)
            # Delete old tokens for this user first
            query('DELETE FROM password_reset_tokens WHERE user_id=%s', (user['id'],), commit=True)
            # Use MySQL UTC_TIMESTAMP() for expiry so there is NO clock mismatch
            # between Python and MySQL — expiry is 60 minutes from now
            query(
                'INSERT INTO password_reset_tokens (user_id, token, expires_at) '
                'VALUES (%s, %s, DATE_ADD(NOW(), INTERVAL 60 MINUTE))',
                (user['id'], token), commit=True
            )
            reset_url = url_for('reset_password', token=token, _external=True)
            sent, err = send_reset_email(user['email'], user['fullname'], reset_url)
            if not sent:
                app.logger.error('Reset email failed for %s: %s', email, err)

        flash(
            'If that email is registered, you will receive a reset link shortly. '
            'Please check your inbox (and spam folder).',
            'success'
        )
        return render_template('forgot_password.html')

    return render_template('forgot_password.html')


# ──────────────────────────────────────────────
# Reset Password – Set New Password
# ──────────────────────────────────────────────
@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    # Validate token
    # Check token exists at all (for better error logging)
    raw = query(
        'SELECT prt.*, u.fullname, u.email FROM password_reset_tokens prt '
        'JOIN users u ON u.id = prt.user_id WHERE prt.token=%s',
        (token,), fetchone=True
    )
    if raw:
        app.logger.info(
            'RESET TOKEN CHECK: used=%s  expires_at=%s  UTC_NOW=%s',
            raw.get('used'),
            raw.get('expires_at'),
            query('SELECT NOW() AS t', fetchone=True).get('t')
        )
    else:
        app.logger.warning('RESET TOKEN CHECK: token not found in DB')

    record = query(
        'SELECT prt.*, u.fullname, u.email FROM password_reset_tokens prt '
        'JOIN users u ON u.id = prt.user_id '
        'WHERE prt.token=%s AND prt.used=0 AND prt.expires_at > NOW()',
        (token,), fetchone=True
    )
    if not record:
        app.logger.warning('RESET TOKEN REJECTED: token=%s...  raw_found=%s', token[:10], raw is not None)

    if request.method == 'POST':
        if not record:
            flash('This reset link is invalid or has expired.', 'danger')
            return render_template('reset_password.html', valid_token=False, token=token)

        password = request.form.get('password', '')
        confirm  = request.form.get('confirm', '')

        if len(password) < 8:
            flash('Password must be at least 8 characters.', 'danger')
            return render_template('reset_password.html', valid_token=True, token=token)

        if password != confirm:
            flash('Passwords do not match.', 'danger')
            return render_template('reset_password.html', valid_token=True, token=token)

        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        # Update password
        query('UPDATE users SET password=%s WHERE id=%s', (hashed, record['user_id']), commit=True)
        # Invalidate token
        query('UPDATE password_reset_tokens SET used=1 WHERE token=%s', (token,), commit=True)

        flash('Your password has been reset successfully. You can now sign in.', 'success')
        return redirect(url_for('login'))

    valid = record is not None
    return render_template('reset_password.html', valid_token=valid, token=token)


# ──────────────────────────────────────────────
# Error Handlers
# ──────────────────────────────────────────────
@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def server_error(e):
    return render_template('404.html', error=str(e)), 500


# ──────────────────────────────────────────────
# Run
# ──────────────────────────────────────────────
def ensure_tables():
    """Create any missing tables on startup so the app never crashes on first run."""
    try:
        # No FOREIGN KEY constraints — compatible with Railway MySQL
        query("""
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                id         INT AUTO_INCREMENT PRIMARY KEY,
                user_id    INT NOT NULL,
                token      VARCHAR(128) NOT NULL UNIQUE,
                expires_at DATETIME NOT NULL,
                used       TINYINT(1) NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """, commit=True)
        query("""
            CREATE TABLE IF NOT EXISTS user_presence (
                user_id   INT PRIMARY KEY,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_online TINYINT(1) NOT NULL DEFAULT 0
            )
        """, commit=True)
        query("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id             INT AUTO_INCREMENT PRIMARY KEY,
                appointment_id INT NOT NULL,
                sender_id      INT NOT NULL,
                receiver_id    INT NOT NULL,
                message        TEXT NOT NULL,
                delivered      TINYINT(1) DEFAULT 0,
                is_read        TINYINT(1) DEFAULT 0,
                created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """, commit=True)

        # ── Migrate existing users table: add new columns if they don't exist ──
        conn = get_db()
        cur  = conn.cursor(dictionary=True)
        cur.execute("SHOW COLUMNS FROM users LIKE 'profile_picture'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE users ADD COLUMN profile_picture VARCHAR(255) DEFAULT NULL")
            conn.commit()
            app.logger.info('ensure_tables: added profile_picture column to users')
        cur.execute("SHOW COLUMNS FROM users LIKE 'must_change_password'")
        if not cur.fetchone():
            cur.execute("ALTER TABLE users ADD COLUMN must_change_password TINYINT(1) NOT NULL DEFAULT 0")
            conn.commit()
            app.logger.info('ensure_tables: added must_change_password column to users')
        cur.close()
        conn.close()

    except Exception as e:
        app.logger.warning('ensure_tables: %s', e)


# ══════════════════════════════════════════════
# DEBUG EMAIL ROUTE  (remove in production)
# Visit: http://localhost:5000/debug-email?to=youremail@gmail.com
# ══════════════════════════════════════════════
@app.route('/debug-email')
def debug_email():
    import traceback
    host, port, username, password, sender, base_url = _mail_cfg()

    results = []
    results.append(f"MAIL_HOST     = {host}")
    results.append(f"MAIL_PORT     = {port}")
    results.append(f"MAIL_USERNAME = {username!r}")
    results.append(f"MAIL_PASSWORD = {'SET (hidden)' if password else 'NOT SET ← FIX THIS'}")
    results.append(f"MAIL_FROM     = {sender!r}")
    results.append(f"APP_BASE_URL  = {base_url!r}")
    results.append("")

    to = request.args.get('to', '').strip()
    if not to:
        results.append("Add ?to=your@email.com to this URL to send a test email.")
        return "<pre>" + "\n".join(results) + "</pre>"

    if not username or not password:
        results.append("ERROR: MAIL_USERNAME or MAIL_PASSWORD is empty.")
        results.append("Open your .env file and fill in:")
        results.append("  MAIL_USERNAME=your_gmail@gmail.com")
        results.append("  MAIL_PASSWORD=your_16_char_app_password")
        results.append("")
        results.append("Get an App Password at: https://myaccount.google.com/apppasswords")
        return "<pre>" + "\n".join(results) + "</pre>"

    results.append(f"Attempting to send test email to: {to}")
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = 'MediCare – Email Test'
        msg['From']    = f'MediCare <{sender}>'
        msg['To']      = to
        msg.attach(MIMEText('This is a test email from your MediCare app. If you see this, email is working!', 'plain'))
        with smtplib.SMTP(host, port) as server:
            server.set_debuglevel(0)
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(username, password)
            server.sendmail(sender, to, msg.as_string())
        results.append("")
        results.append("SUCCESS! Test email sent to " + to)
        results.append("Check your inbox (and spam folder).")
    except smtplib.SMTPAuthenticationError as e:
        results.append("")
        results.append("AUTHENTICATION ERROR: " + str(e))
        results.append("Your MAIL_PASSWORD is wrong.")
        results.append("Make sure you are using a Gmail APP PASSWORD, not your Gmail login password.")
        results.append("Get one at: https://myaccount.google.com/apppasswords")
    except smtplib.SMTPRecipientsRefused as e:
        results.append("RECIPIENT REFUSED: " + str(e))
    except Exception as e:
        results.append("")
        results.append("ERROR: " + str(e))
        results.append("")
        results.append(traceback.format_exc())

    return "<pre>" + "\n".join(results) + "</pre>"


# Run ensure_tables on every startup (works with gunicorn on Render too)
with app.app_context():
    ensure_tables()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
