from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash
import os
import json
import time
import random
import logging
import requests
import threading
import traceback
import uuid
from datetime import datetime, timedelta
from functools import wraps

# Import from other modules
# Import config first - this is important
import config
from config import (
    ADMIN_USERNAME, ADMIN_PASSWORD, ADMIN_TELEGRAM_ID, TELEGRAM_BOT_TOKEN,
    user_data, activation_keys, active_users, background_jobs, bot_statistics, telegram_verification_codes,
    data_lock, save_data, load_data, is_user_activated, is_admin
)

# Import bot functionality after config
import bot
from bot import (
    create_telegram_keyboard, create_telegram_inline_keyboard, 
    send_telegram_message_with_keyboard, send_telegram_notification, notify_admin,
    generate_verification_code, verify_telegram_code, connect_smm_panel, 
    place_order, get_user_active_jobs, get_all_active_jobs, get_user_orders, stop_job
)

app = Flask(__name__)
app.secret_key = os.urandom(24)  # For session management

# Configure logging specifically for the web app
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[logging.FileHandler(f"logs/web_{datetime.now().strftime('%Y-%m-%d')}.log")]
)

# Admin required decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session['user_id'] != ADMIN_USERNAME:
            flash('Unauthorized access')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

# Helper functions
def generate_job_id():
    """Generate a unique job ID"""
    try:
        return f"job_{uuid.uuid4()}"
    except Exception:
        # Fallback if uuid module fails
        return f"job_{time.time()}_{random.randint(10000, 99999)}"

def generate_key(expires_days=30):
    """Generate a new activation key with expiration date"""
    global activation_keys
    
    try:
        key = ''.join(random.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789') for _ in range(16))
        
        now = datetime.now()
        expires = now + timedelta(days=expires_days)
        
        with data_lock:
            activation_keys[key] = {
                "used": False,
                "created_at": now.strftime("%Y-%m-%d %H:%M:%S"),
                "expires_at": expires.strftime("%Y-%m-%d %H:%M:%S"),
                "used_by": None
            }
        
        save_data()
        return key
    except Exception as e:
        logging.info(f"Error generating key: {str(e)}")
        return "ERROR" + ''.join(random.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789') for _ in range(10))
def pause_job(job_id, user_id):
    """Pause a specific job"""
    with data_lock:
        for job in background_jobs:
            if job['job_id'] == job_id and job['user_id'] == user_id:
                job['paused'] = True
                job['paused_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                save_data()
                return True
    return False

def resume_job(job_id, user_id):
    """Resume a specific job"""
    with data_lock:
        for job in background_jobs:
            if job['job_id'] == job_id and job['user_id'] == user_id:
                job['paused'] = False
                job['resumed_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                # Set next run to immediate
                job['next_run'] = int(time.time())
                save_data()
                return True
    return False

def pause_bulk_jobs(bulk_group_id, user_id):
    """Pause all jobs in a bulk group"""
    paused_count = 0
    with data_lock:
        for job in background_jobs:
            if (job.get('bulk_group_id') == bulk_group_id and 
                job['user_id'] == user_id and 
                not job.get('stopped', False)):
                job['paused'] = True
                job['paused_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                paused_count += 1
        if paused_count > 0:
            save_data()
    return paused_count

def resume_bulk_jobs(bulk_group_id, user_id):
    """Resume all jobs in a bulk group"""
    resumed_count = 0
    with data_lock:
        for job in background_jobs:
            if (job.get('bulk_group_id') == bulk_group_id and 
                job['user_id'] == user_id and 
                not job.get('stopped', False)):
                job['paused'] = False
                job['resumed_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                job['next_run'] = int(time.time())
                resumed_count += 1
        if resumed_count > 0:
            save_data()
    return resumed_count

def stop_bulk_jobs(bulk_group_id, user_id):
    """Stop all jobs in a bulk group"""
    stopped_count = 0
    with data_lock:
        for job in background_jobs:
            if (job.get('bulk_group_id') == bulk_group_id and 
                job['user_id'] == user_id and 
                not job.get('stopped', False)):
                job['stopped'] = True
                job['stopped_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                stopped_count += 1
        if stopped_count > 0:
            save_data()
    return stopped_count

def activate_user(user_id, key):
    """Activate a user with a given key"""
    global activation_keys, active_users, bot_statistics
    
    user_id_str = str(user_id)
    
    with data_lock:
        if key in activation_keys and not activation_keys[key]["used"]:
            try:
                expires_at = datetime.strptime(activation_keys[key]["expires_at"], "%Y-%m-%d %H:%M:%S")
                now = datetime.now()
                
                if now < expires_at:
                    activation_keys[key]["used"] = True
                    activation_keys[key]["used_by"] = user_id_str
                    
                    if user_id_str not in active_users:
                        active_users.append(user_id_str)
                        bot_statistics["active_users"] = len(active_users)
                    
                    # Notify admin of new user activation
                    notify_admin(f"🆕 *New User Activated*\n👤 Username: `{user_id}`\n🔑 Key: `{key}`")
                    
                    save_data()
                    return True
            except Exception as e:
                logging.info(f"Error activating user: {str(e)}")
    
    return False

# Create a template filter to convert timestamp to readable format
@app.template_filter('timestamp_to_datetime')
def timestamp_to_datetime(timestamp):
    try:
        dt = datetime.fromtimestamp(timestamp)
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except:
        return 'N/A'

# Routes
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    theme = "light"
    if 'user_id' in session:
        user_id = session['user_id']
        if user_id in user_data and 'theme' in user_data[user_id]:
            theme = user_data[user_id]['theme']
    return render_template('index.html', theme=theme)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        # Check for admin login
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['user_id'] = username
            session['is_admin'] = True
            flash('Welcome, Administrator!')
            return redirect(url_for('admin_panel'))
        
        # Regular user login
        if username in user_data and user_data[username].get('password') == password:
            session['user_id'] = username
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password')
    
    theme = "light"
    if 'user_id' in session:
        user_id = session['user_id']
        if user_id in user_data and 'theme' in user_data[user_id]:
            theme = user_data[user_id]['theme']
    return render_template('login.html', theme=theme)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        activation_key = request.form['activation_key']
        telegram_id = request.form.get('telegram_id', '')  # Optional Telegram ID
        
        if password != confirm_password:
            flash('Passwords do not match')
            return render_template('register.html')
        
        if username in user_data:
            flash('Username already exists')
            return render_template('register.html')
        
        # Check if activation key is valid
        if activation_key not in activation_keys or activation_keys[activation_key]["used"]:
            flash('Invalid or already used activation key')
            return render_template('register.html')
        
        # Create user
        user_data[username] = {
            'password': password,
            'api_profiles': {},
            'orders': [],
            'templates': [],  # Initialize templates array
            'date_joined': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        # Add Telegram ID if provided
        if telegram_id:
            user_data[username]['telegram_id'] = telegram_id
        
        # Activate user
        user_id_str = str(username)
        
        # Mark key as used
        activation_keys[activation_key]["used"] = True
        activation_keys[activation_key]["used_by"] = user_id_str
        
        # Add to active users
        if user_id_str not in active_users:
            active_users.append(user_id_str)
            bot_statistics["active_users"] = len(active_users)
        
        save_data()
        
        # Update total users count
        bot_statistics['total_users'] = len(user_data)
        
        # Notify admin of new registration
        notify_admin(f"👥 *New User Registration*\n👤 Username: `{username}`\n📱 Telegram ID: `{telegram_id or 'Not provided'}`\n🔑 Key: `{activation_key}`")
        
        flash('Registration successful! Your account is now active and ready to use.')
        session['user_id'] = username
        return redirect(url_for('dashboard'))
    
    theme = "light"
    if 'user_id' in session:
        user_id = session['user_id']
        if user_id in user_data and 'theme' in user_data[user_id]:
            theme = user_data[user_id]['theme']
    return render_template('register.html', theme=theme)

@app.route('/connect_telegram', methods=['GET', 'POST'])
def connect_telegram():
    if 'user_id' not in session:
        flash('Please log in first')
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    
    if request.method == 'POST':
        telegram_id = request.form['telegram_id']
        verification_code = request.form.get('verification_code', '')
        
        # Verify the Telegram ID and verification code
        if verify_telegram_code(telegram_id, verification_code):
            # Update user data with Telegram ID
            if user_id in user_data:
                user_data[user_id]['telegram_id'] = telegram_id
                save_data()
                
                # Send a welcome message to the user
                welcome_message = (
                    "🎉 *Connection Successful!*\n\n"
                    f"Your account `{user_id}` has been successfully connected to this Telegram chat.\n\n"
                    "You will now receive notifications about your orders and automation jobs here.\n\n"
                    "Use the menu below to manage your account."
                )
                
                # Create a keyboard with common options
                keyboard = create_telegram_keyboard([
                    ["📊 My Orders", "🚀 My Jobs"],
                    ["💼 Account", "📞 Support"]
                ])
                
                if send_telegram_message_with_keyboard(telegram_id, welcome_message, keyboard):
                    flash('Telegram connected successfully! A welcome message has been sent.')
                else:
                    flash('Telegram ID saved, but welcome message failed. Please check if the ID is correct.')
                
                return redirect(url_for('dashboard'))
            else:
                flash('User not found')
        else:
            flash('Invalid verification code. Please make sure you entered the correct code.')
    
    # Get current Telegram ID if any
    current_telegram_id = ""
    if user_id in user_data and 'telegram_id' in user_data[user_id]:
        current_telegram_id = user_data[user_id]['telegram_id']
    
    return render_template('connect_telegram.html', current_telegram_id=current_telegram_id, theme=theme_preference(user_id))

@app.route('/test_telegram_connection', methods=['POST'])
def test_telegram_connection():
    """Send a test message to the user's Telegram ID"""
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Not logged in"})
    
    user_id = session['user_id']
    
    try:
        data = request.get_json()
        telegram_id = data.get('telegram_id', '')
        
        if not telegram_id:
            return jsonify({"success": False, "error": "Telegram ID not provided"})
        
        # Send test message
        test_message = (
            "🔔 *Test Notification*\n\n"
            "This is a test message from SMM Automation.\n\n"
            "If you're seeing this, your Telegram connection is working correctly! 🎉"
        )
        
        # Create a keyboard with common options
        keyboard = create_telegram_keyboard([
            ["📊 My Orders", "🚀 My Jobs"],
            ["💼 Account", "📞 Support"]
        ])
        
        success = send_telegram_message_with_keyboard(telegram_id, test_message, keyboard)
        
        if success:
            return jsonify({"success": True})
        else:
            return jsonify({"success": False, "error": "Failed to send message. Please check the Telegram ID."})
    except Exception as e:
        logging.info(f"Error sending test Telegram message: {str(e)}")
        return jsonify({"success": False, "error": str(e)})

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    
    if not is_user_activated(user_id) and user_id != ADMIN_USERNAME:
        flash('Your account needs activation. Please enter a valid activation key.')
        return redirect(url_for('login'))
    
    # Get user's active jobs
    active_jobs = get_user_active_jobs(user_id)
    
    # Get user's recent orders
    recent_orders = []
    if user_id in user_data and 'orders' in user_data[user_id]:
        # Get last 5 orders
        orders = user_data[user_id]['orders']
        recent_orders = orders[-5:] if len(orders) > 5 else orders
        # Reverse to show newest first
        recent_orders = recent_orders[::-1]
    
    # Get API profiles
    api_profiles = {}
    if user_id in user_data:
        api_profiles = user_data[user_id].get('api_profiles', {})
    
    # Check if user has connected Telegram
    has_telegram = False
    if user_id in user_data and 'telegram_id' in user_data[user_id]:
        has_telegram = True
    
    return render_template('dashboard.html', 
                          user_id=user_id,
                          active_jobs=active_jobs,
                          recent_orders=recent_orders,
                          api_profiles=api_profiles,
                          has_telegram=has_telegram,
                          theme=theme_preference(user_id))

@app.route('/setup_automation', methods=['GET', 'POST'])
def setup_automation():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    
    if not is_user_activated(user_id) and user_id != ADMIN_USERNAME:
        flash('Your account needs activation')
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        try:
            # Get form data
            api_url = request.form['api_url']
            api_key = request.form['api_key']
            service_id = request.form['service_id']
            # Read optional extra service IDs (for bulk mode only)
            bulk_service_ids_raw = request.form.get('bulk_service_ids', '')
            bulk_service_ids = [sid.strip() for sid in bulk_service_ids_raw.split('\n') if sid.strip()]

            quantity = int(request.form['quantity'])
            increase_min = float(request.form['increase_min'])
            increase_max = float(request.form['increase_max'])
            frequency = int(request.form['frequency'])

            if frequency < 5:
                frequency = 5

            # Check modes
            bulk_mode = request.form.get('bulk_mode') == '1'
            individual_settings = request.form.get('individual_settings') == '1'

            links = []
            created_jobs = []

            if bulk_mode:
                # Parse multiple links
                bulk_group_id = f"bulk_{uuid.uuid4()}"
                bulk_links = request.form.get('bulk_links', '')
                links = [link.strip() for link in bulk_links.split('\n') if link.strip()]

                if not links:
                    flash('Please enter at least one link for bulk automation')
                    return redirect(url_for('setup_automation'))

                if len(links) > 10:
                    flash('Maximum 10 links allowed for bulk automation')
                    return redirect(url_for('setup_automation'))

            else:
                # Single link mode
                bulk_group_id = None

                link = request.form['link']
                links = [link]

            # ----- Individual settings mode (multiple services with same link) -----
            if individual_settings and bulk_mode:
                service_configs = []
                form_data = request.form.to_dict()
                service_index = 0
                
                while f'individual_service_id_{service_index}' in form_data:
                    service_config = {
                        'service_id': form_data[f'individual_service_id_{service_index}'],
                        'quantity': int(form_data[f'individual_quantity_{service_index}']),
                        'increase_min': float(form_data[f'individual_increase_min_{service_index}']),
                        'increase_max': float(form_data[f'individual_increase_max_{service_index}']),
                        'frequency': int(form_data[f'individual_frequency_{service_index}'])
                    }
                    
                    if service_config['frequency'] < 5:
                        service_config['frequency'] = 5
                        
                    service_configs.append(service_config)
                    service_index += 1
                
                if not service_configs:
                    flash('No service configurations found')
                    return redirect(url_for('setup_automation'))
                
                # Create jobs with individual settings for each link
                for config in service_configs:
                    for link in links:
                        job_id = generate_job_id()
                        new_job = {
                            'job_id': job_id,
                            'user_id': user_id,
                            'api_url': api_url,
                            'api_key': api_key,
                            'service_id': config['service_id'],
                            'link': link,
                            'quantity': config['quantity'],
                            'increase_range': [config['increase_min'], config['increase_max']],
                            'frequency': config['frequency'],
                            'next_run': int(time.time()),
                            'started_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                            'stopped': False,
                            'paused': False,  # New field to track pause state
                            'bulk_group_id': bulk_group_id if bulk_mode else None,  # Group ID for bulk operations
                            'paused_at': None,  # Timestamp when paused
                            'resumed_at': None,  # Timestamp when resumed
                            'orders': []
                        }
                        created_jobs.append(new_job)

                # Save jobs
                with data_lock:
                    background_jobs.extend(created_jobs)
                    save_data()

                # Send notification (simplified)
                notification_message = (
                    f"🚀 *Individual Automation Jobs Started*\n"
                    f"🔢 Total Jobs: `{len(created_jobs)}`\n"
                    f"Your first orders will be placed shortly!"
                )
                send_telegram_notification(user_id, notification_message)
                notify_admin(f"🚀 *Individual Automation Jobs Created* by user `{user_id}`, total `{len(created_jobs)}` jobs.")
                
                flash('Individual automation job(s) started successfully!')
                return redirect(url_for('dashboard'))

            # ----- Bulk or single job mode -----
            else:
                for link in links:
                    all_service_ids = [service_id] + bulk_service_ids
                    for sid in all_service_ids:
                        job_id = generate_job_id()
                        new_job = {
                            'job_id': job_id,
                            'user_id': user_id,
                            'api_url': api_url,
                            'api_key': api_key,
                            'service_id': sid,
                            'link': link,
                            'quantity': quantity,
                            'increase_range': [increase_min, increase_max],
                            'frequency': frequency,
                            'next_run': int(time.time()),
                            'started_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                            'stopped': False,
                            'orders': []
                        }
                        created_jobs.append(new_job)
                
                # Save jobs
                with data_lock:
                    background_jobs.extend(created_jobs)
                    save_data()

                if bulk_mode:
                    notification_message = (
                        "🚀 *Bulk Automation Jobs Started*\n"
                        f"📦 Service: `{service_id}`\n"
                        f"📊 Starting Quantity: `{quantity}`\n"
                        f"📈 Increase: `{increase_min}-{increase_max}%`\n"
                        f"⏱ Frequency: Every `{frequency}` minutes\n"
                        f"🔢 Total Jobs: `{len(created_jobs)}`\n\n"
                        "Your first orders will be placed shortly for all links!"
                    )
                    admin_notification = (
                        "🚀 *Bulk Automation Jobs Created*\n"
                        f"👤 User: `{user_id}`\n"
                        f"📦 Service: `{service_id}`\n"
                        f"🔢 Jobs Created: `{len(created_jobs)}`\n"
                        f"⏱ Frequency: Every `{frequency}` minutes"
                    )
                    send_telegram_notification(user_id, notification_message)
                    notify_admin(admin_notification)
                else:
                    # Single job notification
                    job = created_jobs[0]
                    job_id = job['job_id']
                    job_keyboard = create_telegram_inline_keyboard([
                        [{"text": "⏱ Change Frequency", "callback_data": f"change_freq_{job_id}"}],
                        [{"text": "📊 Adjust Growth Rate", "callback_data": f"change_growth_{job_id}"}],
                        [{"text": "🛑 Stop Job", "callback_data": f"stop_job_{job_id}"}]
                    ])
                    notification_message = (
                        "🚀 *New Automation Job Started*\n"
                        f"📦 Service: `{service_id}`\n"
                        f"🔗 Link: `{job['link']}`\n"
                        f"📊 Starting Quantity: `{quantity}`\n"
                        f"📈 Increase: `{increase_min}-{increase_max}%`\n"
                        f"⏱ Frequency: Every `{frequency}` minutes\n\n"
                        "Your first order will be placed shortly!"
                    )
                    send_telegram_notification(user_id, notification_message, job_keyboard)

                    admin_notification = (
                        "🚀 *New Automation Job Created*\n"
                        f"👤 User: `{user_id}`\n"
                        f"📦 Service: `{service_id}`\n"
                        f"🔗 Link: `{job['link']}`\n"
                        f"⏱ Frequency: Every `{frequency}` minutes"
                    )
                    notify_admin(admin_notification)

                flash('Automation job(s) started successfully!')
                return redirect(url_for('dashboard'))

        except Exception as e:
            logging.error(f"Error creating automation job: {str(e)}")
            logging.error(traceback.format_exc())
            flash(f'Error creating automation job: {str(e)}')
            return redirect(url_for('setup_automation'))

    # GET request
    api_profiles = {}
    if user_id in user_data:
        api_profiles = user_data[user_id].get('api_profiles', {})

    return render_template('setup_automation.html', api_profiles=api_profiles, theme=theme_preference(user_id))

@app.route('/api_profiles')
def api_profiles():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    
    if not is_user_activated(user_id) and user_id != ADMIN_USERNAME:
        flash('Your account needs activation')
        return redirect(url_for('login'))
    
    api_profiles = {}
    if user_id in user_data:
        api_profiles = user_data[user_id].get('api_profiles', {})
    
    return render_template('api_profiles.html', api_profiles=api_profiles, theme=theme_preference(user_id))

@app.route('/add_api_profile', methods=['GET', 'POST'])
def add_api_profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    
    if not is_user_activated(user_id) and user_id != ADMIN_USERNAME:
        flash('Your account needs activation')
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        profile_name = request.form['profile_name']
        api_url = request.form['api_url']
        api_key = request.form['api_key']
        
        # Test API connection before saving
        test_response = connect_smm_panel(api_url, api_key, 'balance')
        if 'error' in test_response:
            flash(f'Failed to connect to API: {test_response["error"]}')
            return render_template('add_api_profile.html', theme=theme_preference(user_id))
        
        # Save API profile
        with data_lock:
            if user_id not in user_data:
                user_data[user_id] = {
                    'api_profiles': {},
                    'orders': [],
                    'templates': []  # Initialize templates array
                }
            
            if 'api_profiles' not in user_data[user_id]:
                user_data[user_id]['api_profiles'] = {}
            
            user_data[user_id]['api_profiles'][profile_name] = {
                'api_url': api_url,
                'api_key': api_key,
                'added_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
            save_data()
        
        # Send Telegram notification
        if user_id in user_data and 'telegram_id' in user_data[user_id]:
            telegram_id = user_data[user_id]['telegram_id']
            notification_message = (
                "✅ *New API Profile Added*\n"
                f"Name: `{profile_name}`\n"
                f"Balance: `{test_response.get('balance', 'N/A')} {test_response.get('currency', '')}`"
            )
            
            profile_keyboard = create_telegram_inline_keyboard([
                [{"text": "📊 View Profiles", "callback_data": "view_profiles"}],
                [{"text": "🚀 Create Automation", "callback_data": "create_automation"}]
            ])
            
            send_telegram_message_with_keyboard(telegram_id, notification_message, profile_keyboard)
        
        flash(f'API profile "{profile_name}" added successfully!')
        return redirect(url_for('api_profiles'))
    
    return render_template('add_api_profile.html', theme=theme_preference(user_id))

@app.route('/delete_api_profile/<profile_name>', methods=['POST'])
def delete_api_profile(profile_name):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    
    if not is_user_activated(user_id) and user_id != ADMIN_USERNAME:
        return redirect(url_for('login'))
    
    with data_lock:
        if user_id in user_data and 'api_profiles' in user_data[user_id] and profile_name in user_data[user_id]['api_profiles']:
            del user_data[user_id]['api_profiles'][profile_name]
            save_data()
            
            # Send Telegram notification
            if 'telegram_id' in user_data[user_id]:
                notification_message = (
                    "🗑️ *API Profile Deleted*\n"
                    f"Profile: `{profile_name}` has been deleted successfully."
                )
                send_telegram_notification(user_id, notification_message)
            
            flash(f'API profile "{profile_name}" deleted successfully!')
        else:
            flash('API profile not found')
    
    return redirect(url_for('api_profiles'))

@app.route('/order_history')
def order_history():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    
    if not is_user_activated(user_id) and user_id != ADMIN_USERNAME:
        flash('Your account needs activation')
        return redirect(url_for('login'))
    
    orders = []
    if user_id in user_data and 'orders' in user_data[user_id]:
        orders = user_data[user_id]['orders']
        # Reverse to show newest first
        orders = orders[::-1]
    
    return render_template('order_history.html', orders=orders, theme=theme_preference(user_id))

@app.route('/stop_job/<job_id>')
def stop_job_route(job_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    
    # Find the job
    job_found = False
    with data_lock:
        for job in background_jobs:
            if job['job_id'] == job_id and (job['user_id'] == user_id or user_id == ADMIN_USERNAME):
                job_found = True
                stop_job(job_id, user_id)
                save_data()  # Ensure changes are saved to disk
                break
    
    if job_found:
        flash('Job stopped successfully')
    else:
        flash('Job not found or not authorized to stop it')
    
    # Redirect based on who stopped the job
    if user_id == ADMIN_USERNAME and request.referrer and 'admin' in request.referrer:
        return redirect(url_for('admin_jobs'))
    return redirect(url_for('dashboard'))

@app.route('/user_settings')
def user_settings():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    
    # Get user preferences
    theme_preference_val = "light"
    if user_id in user_data and 'theme' in user_data[user_id]:
        theme_preference_val = user_data[user_id]['theme']
    
    # Check if user has connected Telegram
    has_telegram = False
    telegram_id = ""
    if user_id in user_data and 'telegram_id' in user_data[user_id]:
        has_telegram = True
        telegram_id = user_data[user_id]['telegram_id']
    
    return render_template('user_settings.html', 
                          theme_preference=theme_preference_val, 
                          has_telegram=has_telegram,
                          telegram_id=telegram_id,
                          theme=theme_preference_val)

@app.route('/save_preferences', methods=['POST'])
def save_preferences():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    
    # Save theme preference
    if request.form.get('theme'):
        theme = request.form.get('theme')
        with data_lock:
            if user_id not in user_data:
                user_data[user_id] = {}
            user_data[user_id]['theme'] = theme
            save_data()
    
    flash('Preferences saved successfully')
    return redirect(url_for('user_settings'))

@app.route('/toggle_theme', methods=['POST'])
def toggle_theme():
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': 'Not logged in'})
    
    user_id = session['user_id']
    
    try:
        data = request.get_json()
        theme = data.get('theme', 'light')
        
        # Save new theme
        with data_lock:
            if user_id not in user_data:
                user_data[user_id] = {}
            user_data[user_id]['theme'] = theme
            save_data()
        
        return jsonify({'status': 'success', 'theme': theme})
    except Exception as e:
        logging.info(f"Error toggling theme: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/admin')
@admin_required
def admin_panel():
    # Get statistics
    active_jobs_count = 0
    for job in background_jobs:
        if not job.get('stopped', False):
            active_jobs_count += 1
    
    stats = {
        'total_users': len(user_data),
        'active_users': len(active_users),
        'total_orders': bot_statistics['total_orders'],
        'successful_orders': bot_statistics['successful_orders'],
        'failed_orders': bot_statistics['failed_orders'],
        'last_24h_orders': bot_statistics['last_24h_orders'],
        'active_jobs': active_jobs_count,
        'total_spent': bot_statistics['total_spent']
    }
    
    return render_template('admin.html', stats=stats, keys=activation_keys, users=user_data, theme=theme_preference(ADMIN_USERNAME))

@app.route('/admin/generate_key/<int:days>')
@admin_required
def admin_generate_key(days):
    # Generate a key with specified expiration
    key = generate_key(days)
    flash(f'New key generated: {key} (Valid for {days} days)')
    
    # Notify admin via Telegram
    notify_admin(f"🔑 *New Activation Key Generated*\n\nKey: `{key}`\nValid for: `{days}` days")
    
    return redirect(url_for('admin_panel'))

@app.route('/admin/revoke_key/<key>', methods=['POST'])
@admin_required
def admin_revoke_key(key):
    """Revoke an activation key"""
    global activation_keys
    
    try:
        with data_lock:
            if key in activation_keys and not activation_keys[key]["used"]:
                # Mark the key as used, revoked and add timestamp
                activation_keys[key]["used"] = True
                activation_keys[key]["revoked"] = True
                activation_keys[key]["revoked_at"] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                activation_keys[key]["revoked_by"] = session.get('user_id', 'admin')
                save_data()
                
                # Notify admin via Telegram
                notify_admin(f"🔒 *Activation Key Revoked*\n\nKey: `{key}`\nRevoked by: `{session.get('user_id', 'admin')}`")
                
                return jsonify({'success': True})
            else:
                return jsonify({'success': False, 'message': 'Key not found or already used'})
    except Exception as e:
        logging.info(f"Error revoking key: {str(e)}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/admin/users')
@admin_required
def admin_users():
    return render_template('admin_users.html', users=user_data, active_users=active_users, theme=theme_preference(ADMIN_USERNAME))

@app.route('/admin/user_details/<username>')
@admin_required
def admin_user_details(username):
    if username not in user_data:
        flash('User not found')
        return redirect(url_for('admin_users'))
    
    # Get user details
    user = user_data[username]
    is_active = username in active_users
    api_profiles = user.get('api_profiles', {})
    orders = user.get('orders', [])
    
    # Get user's active jobs
    active_jobs = get_user_active_jobs(username)
    
    return render_template('admin_user_details.html', 
                         username=username, 
                         user=user, 
                         is_active=is_active, 
                         api_profiles=api_profiles, 
                         orders=orders, 
                         active_jobs=active_jobs,
                         theme=theme_preference(ADMIN_USERNAME))

@app.route('/admin/jobs')
@admin_required
def admin_jobs():
    # Get all active jobs
    active_jobs = get_all_active_jobs()
    
    return render_template('admin_jobs.html', jobs=active_jobs, theme=theme_preference(ADMIN_USERNAME))

@app.route('/admin/orders')
@admin_required
def admin_orders():
    # Get all orders from all users
    all_orders = []
    for username, user in user_data.items():
        if 'orders' in user:
            for order in user['orders']:
                order_copy = order.copy()
                order_copy['username'] = username
                all_orders.append(order_copy)
    
    # Sort by timestamp (newest first)
    all_orders.sort(key=lambda x: x['timestamp'], reverse=True)
    
    return render_template('admin_orders.html', orders=all_orders, theme=theme_preference(ADMIN_USERNAME))

@app.route('/admin/view_user_orders/<username>')
@admin_required
def admin_view_user_orders(username):
    if username not in user_data:
        flash('User not found')
        return redirect(url_for('admin_users'))
    
    # Get user's orders
    orders = user_data[username].get('orders', [])
    # Reverse to show newest first
    orders = orders[::-1]
    
    return render_template('admin_user_orders.html', 
                          username=username, 
                          orders=orders,
                          theme=theme_preference(ADMIN_USERNAME))

@app.route('/admin/deactivate/<user_id>', methods=['POST'])
@admin_required
def admin_deactivate_user(user_id):
    # Deactivate user
    with data_lock:
        if user_id in active_users:
            active_users.remove(user_id)
            save_data()
            flash(f'User {user_id} deactivated successfully')
            
            # Send Telegram notification
            notification_message = (
                "⚠️ *Account Deactivated*\n"
                "Your account has been deactivated by an administrator.\n"
                "Please contact support for more information."
            )
            send_telegram_notification(user_id, notification_message)
            
            # Notify admin
            notify_admin(f"🔒 *User Deactivated*\n\nUser: `{user_id}`\nDeactivated by: `{session.get('user_id', 'admin')}`")
        else:
            flash(f'User {user_id} is not active')
    
    return redirect(url_for('admin_users'))

@app.route('/admin/message_user/<username>', methods=['GET', 'POST'])
@admin_required
def admin_message_user(username):
    if username not in user_data:
        flash('User not found')
        return redirect(url_for('admin_users'))
    
    if request.method == 'POST':
        message = request.form.get('message', '')
        
        if message and username in user_data and 'telegram_id' in user_data[username]:
            # Send message via Telegram
            admin_message = (
                "📢 *Message from Administrator*\n\n"
                f"{message}"
            )
            
            # Add a reply button
            reply_keyboard = create_telegram_inline_keyboard([
                [{"text": "📝 Reply to Admin", "callback_data": "reply_to_admin"}]
            ])
            
            if send_telegram_notification(username, admin_message, reply_keyboard):
                flash(f'Message sent to {username} successfully')
            else:
                flash(f'Failed to send message to {username}')
        else:
            flash('User does not have Telegram connected or message is empty')
        
        return redirect(url_for('admin_user_details', username=username))
    
    return render_template('admin_message_user.html', 
                          username=username,
                          theme=theme_preference(ADMIN_USERNAME))

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('is_admin', None)
    return redirect(url_for('index'))

# Template management routes
@app.route('/templates')
def templates():
    """View all templates for the current user"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    
    if not is_user_activated(user_id) and user_id != ADMIN_USERNAME:
        flash('Your account needs activation')
        return redirect(url_for('login'))
    
    # Get user's templates - ensure the templates field exists
    templates = []
    if user_id in user_data:
        # Create templates field if it doesn't exist
        if 'templates' not in user_data[user_id]:
            with data_lock:
                user_data[user_id]['templates'] = []
                save_data()
        templates = user_data[user_id]['templates']
    
    # Get API profiles for reference
    api_profiles = {}
    if user_id in user_data and 'api_profiles' in user_data[user_id]:
        api_profiles = user_data[user_id]['api_profiles']
    
    return render_template('templates.html', templates=templates, api_profiles=api_profiles, theme=theme_preference(user_id))

@app.route('/create_template', methods=['GET', 'POST'])
def create_template():
    """Create a new template"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    
    if not is_user_activated(user_id) and user_id != ADMIN_USERNAME:
        flash('Your account needs activation')
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        try:
            # Get form data
            template_name = request.form.get('template_name', '').strip()
            template_description = request.form.get('template_description', '').strip()
            api_profile = request.form.get('api_profile', '').strip()
            service_id = request.form.get('service_id', '').strip()
            quantity = int(request.form.get('quantity', 100))
            increase_min = float(request.form.get('increase_min', 10))
            increase_max = float(request.form.get('increase_max', 20))
            frequency = int(request.form.get('frequency', 60))

            # NEW: Handle bulk & individual settings
            bulk_mode = request.form.get('bulk_mode') == '1'
            individual_settings = request.form.get('individual_settings') == '1'

            # Bulk service IDs (one per line)
            bulk_service_ids_raw = request.form.get('bulk_service_ids', '')
            bulk_service_ids = [sid.strip() for sid in bulk_service_ids_raw.split('\n') if sid.strip()]

            # Individual configurations
            individual_configs = []
            if individual_settings:
                form_data = request.form.to_dict()
                service_index = 0
                while f'individual_service_id_{service_index}' in form_data:
                    config = {
                        'service_id': form_data[f'individual_service_id_{service_index}'],
                        'quantity': int(form_data[f'individual_quantity_{service_index}']),
                        'increase_min': float(form_data[f'individual_increase_min_{service_index}']),
                        'increase_max': float(form_data[f'individual_increase_max_{service_index}']),
                        'frequency': int(form_data[f'individual_frequency_{service_index}'])
                    }
                    individual_configs.append(config)
                    service_index += 1

            # Validation
            if not template_name or not api_profile or not service_id:
                flash('Please fill in all required fields')
                return redirect(url_for('create_template'))
            
            if frequency < 5:
                frequency = 5  # enforce minimum
            
            # Generate unique template ID
            template_id = f"template_{uuid.uuid4()}"
            
            # Create template object
            new_template = {
                'id': template_id,
                'name': template_name,
                'description': template_description,
                'api_profile': api_profile,
                'service_id': service_id,
                'bulk_service_ids': bulk_service_ids,
                'bulk_mode': bulk_mode,
                'individual_settings': individual_settings,
                'individual_configs': individual_configs,
                'quantity': quantity,
                'increase_min': increase_min,
                'increase_max': increase_max,
                'frequency': frequency,
                'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'usage_count': 0
            }
            
            # Save to user data
            with data_lock:
                if user_id not in user_data:
                    user_data[user_id] = {
                        'api_profiles': {},
                        'orders': [],
                        'templates': []
                    }
                if 'templates' not in user_data[user_id]:
                    user_data[user_id]['templates'] = []
                
                user_data[user_id]['templates'].append(new_template)
                save_data()
            
            flash(f'Template "{template_name}" created successfully')
            return redirect(url_for('templates'))
        
        except Exception as e:
            logging.error(f"Error creating template: {str(e)}")
            logging.error(traceback.format_exc())
            flash(f'Error creating template: {str(e)}')
            return redirect(url_for('create_template'))
    
    # GET request
    api_profiles = {}
    if user_id in user_data and 'api_profiles' in user_data[user_id]:
        api_profiles = user_data[user_id].get('api_profiles', {})
    
    return render_template('create_template.html', api_profiles=api_profiles, theme=theme_preference(user_id))

@app.route('/edit_template/<template_id>', methods=['GET', 'POST'])
def edit_template(template_id):
    """Edit an existing template"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    
    if not is_user_activated(user_id) and user_id != ADMIN_USERNAME:
        flash('Your account needs activation')
        return redirect(url_for('login'))
    
    # Find the template
    template = None
    template_index = -1
    
    if user_id in user_data and 'templates' in user_data[user_id]:
        for i, t in enumerate(user_data[user_id]['templates']):
            if t.get('id') == template_id:
                template = t
                template_index = i
                break
    
    if template is None:
        flash('Template not found')
        return redirect(url_for('templates'))
    
    if request.method == 'POST':
        try:
            # Get form data
            template_name = request.form.get('template_name', '').strip()
            template_description = request.form.get('template_description', '').strip()
            api_profile = request.form.get('api_profile', '').strip()
            service_id = request.form.get('service_id', '').strip()
            quantity = int(request.form.get('quantity', 100))
            increase_min = float(request.form.get('increase_min', 10))
            increase_max = float(request.form.get('increase_max', 20))
            frequency = int(request.form.get('frequency', 60))
            
            # Validation
            if not template_name or not api_profile or not service_id:
                flash('Please fill in all required fields')
                return redirect(url_for('edit_template', template_id=template_id))
            
            # Validate minimum frequency
            if frequency < 5:
                frequency = 5  # Enforce a minimum of 5 minutes
            
            # Update template object
            with data_lock:
                user_data[user_id]['templates'][template_index].update({
                    'name': template_name,
                    'description': template_description,
                    'api_profile': api_profile,
                    'service_id': service_id,
                    'quantity': quantity,
                    'increase_min': increase_min,
                    'increase_max': increase_max,
                    'frequency': frequency,
                    'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                })
                save_data()
            
            flash(f'Template "{template_name}" updated successfully')
            return redirect(url_for('templates'))
        except Exception as e:
            logging.error(f"Error updating template: {str(e)}")
            logging.error(traceback.format_exc())
            flash(f'Error updating template: {str(e)}')
            return redirect(url_for('edit_template', template_id=template_id))
    
    # GET request - show form with existing data
    # Get saved API profiles for selection
    api_profiles = {}
    if user_id in user_data and 'api_profiles' in user_data[user_id]:
        api_profiles = user_data[user_id].get('api_profiles', {})
    
    # Create a copy of the template editing page, but with the existing data
    return render_template('create_template.html', 
                         template=template,
                         api_profiles=api_profiles, 
                         edit_mode=True,
                         theme=theme_preference(user_id))

@app.route('/delete_template/<template_id>', methods=['POST'])
def delete_template(template_id):
    """Delete a template"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    
    if not is_user_activated(user_id) and user_id != ADMIN_USERNAME:
        flash('Your account needs activation')
        return redirect(url_for('login'))
    
    # Find and delete the template
    template_name = "Unknown"
    found = False
    
    with data_lock:
        if user_id in user_data and 'templates' in user_data[user_id]:
            for i, template in enumerate(user_data[user_id]['templates']):
                if template.get('id') == template_id:
                    template_name = template.get('name', 'Unknown')
                    user_data[user_id]['templates'].pop(i)
                    found = True
                    break
        
        if found:
            save_data()
            flash(f'Template "{template_name}" deleted successfully')
        else:
            flash('Template not found')
    
    return redirect(url_for('templates'))

@app.route('/use_template/<template_id>')
def use_template(template_id):
    """Use a template to create a new automation job"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    
    if not is_user_activated(user_id) and user_id != ADMIN_USERNAME:
        flash('Your account needs activation')
        return redirect(url_for('login'))
    
    try:
        # Find the template
        template = None
        
        if user_id in user_data and 'templates' in user_data[user_id]:
            for t in user_data[user_id]['templates']:
                if t.get('id') == template_id:
                    template = t
                    break
        
        if template is None:
            flash('Template not found')
            return redirect(url_for('templates'))
        
        # Get API profile details
        api_profile_name = template.get('api_profile', '')
        api_url = ''
        api_key = ''
        
        if user_id in user_data and 'api_profiles' in user_data[user_id] and api_profile_name in user_data[user_id]['api_profiles']:
            api_profile = user_data[user_id]['api_profiles'][api_profile_name]
            api_url = api_profile.get('api_url', '')
            api_key = api_profile.get('api_key', '')
        
        if not api_url or not api_key:
            flash('API profile not found or invalid')
            return redirect(url_for('templates'))
        
        # Generate a unique job ID
        job_id = generate_job_id()
        
        # Create job configuration using template settings
        new_job = {
            'job_id': job_id,
            'user_id': user_id,
            'api_url': api_url,
            'api_key': api_key,
            'service_id': template.get('service_id', ''),
            'link': request.args.get('link', ''),  # Optional link parameter
            'quantity': template.get('quantity', 100),
            'increase_range': [template.get('increase_min', 10), template.get('increase_max', 20)],
            'frequency': template.get('frequency', 60),
            'next_run': int(time.time()),  # Run immediately
            'started_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'stopped': False,
            'orders': [],
            'template_id': template_id
        }
        
        # If no link was provided, redirect to a form to enter the link
        if not new_job['link']:
            return redirect(url_for('setup_automation_with_template', template_id=template_id))
        
        # Add the job to background jobs
        with data_lock:
            background_jobs.append(new_job)
            
            # Increment template usage count
            for t in user_data[user_id]['templates']:
                if t.get('id') == template_id:
                    t['usage_count'] = t.get('usage_count', 0) + 1
                    break
            
            save_data()
        
        # Create inline keyboard for job management
        job_keyboard = create_telegram_inline_keyboard([
            [{"text": "⏱ Change Frequency", "callback_data": f"change_freq_{job_id}"}],
            [{"text": "📊 Adjust Growth Rate", "callback_data": f"change_growth_{job_id}"}],
            [{"text": "🛑 Stop Job", "callback_data": f"stop_job_{job_id}"}]
        ])
        
        # Send Telegram notification
        notification_message = (
            "🚀 *New Automation Job Started*\n"
            f"📝 Template: `{template.get('name', 'Unknown')}`\n"
            f"📦 Service: `{template.get('service_id', '')}`\n"
            f"🔗 Link: `{new_job['link']}`\n"
            f"📊 Starting Quantity: `{template.get('quantity', 100)}`\n"
            f"📈 Increase: `{template.get('increase_min', 10)}-{template.get('increase_max', 20)}%`\n"
            f"⏱ Frequency: Every `{template.get('frequency', 60)}` minutes\n\n"
            "Your first order will be placed shortly!"
        )
        send_telegram_notification(user_id, notification_message, job_keyboard)
        
        # Notify admin
        admin_notification = (
            "🚀 *New Job from Template*\n"
            f"👤 User: `{user_id}`\n"
            f"📝 Template: `{template.get('name', 'Unknown')}`\n"
            f"📦 Service: `{template.get('service_id', '')}`\n"
            f"🔗 Link: `{new_job['link']}`\n"
        )
        notify_admin(admin_notification)
        
        flash(f'Automation job created from template "{template.get("name")}" and started successfully!')
        return redirect(url_for('dashboard'))
    except Exception as e:
        logging.error(f"Error using template: {str(e)}")
        logging.error(traceback.format_exc())
        flash(f'Error using template: {str(e)}')
        return redirect(url_for('templates'))

# Add this updated route to app.py to replace the existing setup_automation_with_template route

@app.route('/setup_automation_with_template/<template_id>', methods=['GET', 'POST'])
def setup_automation_with_template(template_id):
    """Setup automation with a template but prompt for link"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    
    if not is_user_activated(user_id) and user_id != ADMIN_USERNAME:
        flash('Your account needs activation')
        return redirect(url_for('login'))
    
    try:
        # Find the template
        template = None
        
        if user_id in user_data and 'templates' in user_data[user_id]:
            for t in user_data[user_id]['templates']:
                if t.get('id') == template_id:
                    template = t
                    break
        
        if template is None:
            flash('Template not found')
            return redirect(url_for('templates'))
        
        if request.method == 'POST':
            # Check for bulk mode
            bulk_mode = request.form.get('bulk_mode') == '1'
            links = []
            
            if bulk_mode:
                # Parse multiple links
                bulk_links = request.form.get('template_bulk_links', '')
                links = [link.strip() for link in bulk_links.split('\n') if link.strip()]
                
                if not links:
                    flash('Please enter at least one link for bulk automation')
                    return redirect(url_for('setup_automation_with_template', template_id=template_id))
                
                if len(links) > 10:
                    flash('Maximum 10 links allowed for bulk automation')
                    return redirect(url_for('setup_automation_with_template', template_id=template_id))
            else:
                # Single link mode
                link = request.form.get('link', '').strip()
                
                if not link:
                    flash('Please enter a link')
                    return redirect(url_for('setup_automation_with_template', template_id=template_id))
                
                links = [link]
            
            # Get API profile details
            api_profile_name = template.get('api_profile', '')
            api_url = ''
            api_key = ''
            
            if user_id in user_data and 'api_profiles' in user_data[user_id] and api_profile_name in user_data[user_id]['api_profiles']:
                api_profile = user_data[user_id]['api_profiles'][api_profile_name]
                api_url = api_profile.get('api_url', '')
                api_key = api_profile.get('api_key', '')
            
            if not api_url or not api_key:
                flash('API profile not found or invalid')
                return redirect(url_for('templates'))
            
            created_jobs = []
            
            # Create jobs for all links
            for link in links:
                job_id = generate_job_id()
                
                # Create job configuration using template settings
                new_job = {
                    'job_id': job_id,
                    'user_id': user_id,
                    'api_url': api_url,
                    'api_key': api_key,
                    'service_id': template.get('service_id', ''),
                    'link': link,
                    'quantity': template.get('quantity', 100),
                    'increase_range': [template.get('increase_min', 10), template.get('increase_max', 20)],
                    'frequency': template.get('frequency', 60),
                    'next_run': int(time.time()),  # Run immediately
                    'started_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'stopped': False,
                    'orders': [],
                    'template_id': template_id
                }
                
                created_jobs.append(new_job)
            
            # Add the jobs to background jobs
            with data_lock:
                background_jobs.extend(created_jobs)
                
                # Increment template usage count
                for t in user_data[user_id]['templates']:
                    if t.get('id') == template_id:
                        t['usage_count'] = t.get('usage_count', 0) + len(created_jobs)
                        break
                
                save_data()
            
            if bulk_mode:
                # Bulk notification
                notification_message = (
                    "🚀 *Bulk Template Jobs Started*\n"
                    f"📝 Template: `{template.get('name', 'Unknown')}`\n"
                    f"📦 Service: `{template.get('service_id', '')}`\n"
                    f"📊 Starting Quantity: `{template.get('quantity', 100)}`\n"
                    f"📈 Increase: `{template.get('increase_min', 10)}-{template.get('increase_max', 20)}%`\n"
                    f"⏱ Frequency: Every `{template.get('frequency', 60)}` minutes\n"
                    f"🔢 Total Jobs: `{len(created_jobs)}`\n\n"
                    "Your first orders will be placed shortly for all links!"
                )
                
                send_telegram_notification(user_id, notification_message)
                
                # Notify admin
                admin_notification = (
                    "🚀 *Bulk Template Jobs Created*\n"
                    f"👤 User: `{user_id}`\n"
                    f"📝 Template: `{template.get('name', 'Unknown')}`\n"
                    f"📦 Service: `{template.get('service_id', '')}`\n"
                    f"🔢 Jobs Created: `{len(created_jobs)}`\n"
                )
                notify_admin(admin_notification)
                
                flash(f'Created {len(created_jobs)} automation jobs from template "{template.get("name")}"!')
            else:
                # Single job notification
                job = created_jobs[0]
                job_id = job['job_id']
                
                # Create inline keyboard for job management
                job_keyboard = create_telegram_inline_keyboard([
                    [{"text": "⏱ Change Frequency", "callback_data": f"change_freq_{job_id}"}],
                    [{"text": "📊 Adjust Growth Rate", "callback_data": f"change_growth_{job_id}"}],
                    [{"text": "🛑 Stop Job", "callback_data": f"stop_job_{job_id}"}]
                ])
                
                # Send Telegram notification
                notification_message = (
                    "🚀 *Template Job Started*\n"
                    f"📝 Template: `{template.get('name', 'Unknown')}`\n"
                    f"📦 Service: `{template.get('service_id', '')}`\n"
                    f"🔗 Link: `{job['link']}`\n"
                    f"📊 Starting Quantity: `{template.get('quantity', 100)}`\n"
                    f"📈 Increase: `{template.get('increase_min', 10)}-{template.get('increase_max', 20)}%`\n"
                    f"⏱ Frequency: Every `{template.get('frequency', 60)}` minutes\n\n"
                    "Your first order will be placed shortly!"
                )
                send_telegram_notification(user_id, notification_message, job_keyboard)
                
                # Notify admin
                admin_notification = (
                    "🚀 *Template Job Created*\n"
                    f"👤 User: `{user_id}`\n"
                    f"📝 Template: `{template.get('name', 'Unknown')}`\n"
                    f"📦 Service: `{template.get('service_id', '')}`\n"
                    f"🔗 Link: `{job['link']}`\n"
                )
                notify_admin(admin_notification)
                
                flash(f'Automation job created from template "{template.get("name")}" and started successfully!')
            
            return redirect(url_for('dashboard'))
        
        # GET request - show form to enter link
        return render_template('setup_template_link.html', 
                            template=template,
                            theme=theme_preference(user_id))
    except Exception as e:
        logging.error(f"Error setting up template: {str(e)}")
        logging.error(traceback.format_exc())
        flash(f'Error setting up template: {str(e)}')
        return redirect(url_for('templates'))
    
# Helper function to get user theme preference
def theme_preference(user_id):
    """Get the theme preference for a user"""
    if user_id in user_data and 'theme' in user_data[user_id]:
        return user_data[user_id]['theme']
    return "light"


@app.route('/pause_job/<job_id>')
def pause_job_route(job_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    
    if pause_job(job_id, user_id):
        # Send notification
        notification_message = "⏸️ *Job Paused*\nYour automation job has been paused successfully."
        send_telegram_notification(user_id, notification_message)
        flash('Job paused successfully')
    else:
        flash('Job not found or not authorized')
    
    return redirect(url_for('dashboard'))

@app.route('/resume_job/<job_id>')
def resume_job_route(job_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    
    if resume_job(job_id, user_id):
        # Send notification
        notification_message = "▶️ *Job Resumed*\nYour automation job has been resumed and will continue processing."
        send_telegram_notification(user_id, notification_message)
        flash('Job resumed successfully')
    else:
        flash('Job not found or not authorized')
    
    return redirect(url_for('dashboard'))

@app.route('/bulk_action/<action>/<bulk_group_id>')
def bulk_action_route(action, bulk_group_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    
    if action == 'pause':
        count = pause_bulk_jobs(bulk_group_id, user_id)
        if count > 0:
            notification_message = f"⏸️ *Bulk Jobs Paused*\n{count} automation jobs have been paused."
            send_telegram_notification(user_id, notification_message)
            flash(f'{count} jobs paused successfully')
        else:
            flash('No jobs found to pause')
    
    elif action == 'resume':
        count = resume_bulk_jobs(bulk_group_id, user_id)
        if count > 0:
            notification_message = f"▶️ *Bulk Jobs Resumed*\n{count} automation jobs have been resumed."
            send_telegram_notification(user_id, notification_message)
            flash(f'{count} jobs resumed successfully')
        else:
            flash('No jobs found to resume')
    
    elif action == 'stop':
        count = stop_bulk_jobs(bulk_group_id, user_id)
        if count > 0:
            notification_message = f"🛑 *Bulk Jobs Stopped*\n{count} automation jobs have been stopped."
            send_telegram_notification(user_id, notification_message)
            flash(f'{count} jobs stopped successfully')
        else:
            flash('No jobs found to stop')
    
    return redirect(url_for('dashboard'))

@app.context_processor
def inject_theme():
    """Inject the user's theme preference into all templates"""
    theme = "light"
    if 'user_id' in session:
        user_id = session['user_id']
        theme = theme_preference(user_id)
    
    return {'theme': theme}

# Make sure admin user exists and at least one activation key is available
def initialize_app():
    # Debug info at startup
    logging.info(f"---- App Initialization ----")
    logging.info(f"Background jobs: {len(background_jobs)}")
    logging.info(f"Users: {len(user_data)}")
    
    # Make sure admin.html exists by generating a key
    if not activation_keys:
        generate_key(30)
        logging.info("Generated initial activation key")
    
    # Make sure admin user exists
    if ADMIN_USERNAME not in user_data:
        with data_lock:
            user_data[ADMIN_USERNAME] = {
                'password': ADMIN_PASSWORD,
                'api_profiles': {},
                'orders': [],
                'templates': [],  # Initialize templates array
                'is_admin': True,
                'theme': 'light',
                'date_joined': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            if ADMIN_USERNAME not in active_users:
                active_users.append(ADMIN_USERNAME)
            save_data()
            logging.info("Admin account created")