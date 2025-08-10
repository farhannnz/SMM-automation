import os
import json
import time
import random
import logging
import requests
import threading
import traceback
from datetime import datetime, timedelta
import uuid

# Import shared configuration and variables
import config
from config import (
    TELEGRAM_BOT_TOKEN, ADMIN_TELEGRAM_ID, 
    user_data, background_jobs, bot_statistics, telegram_verification_codes,
    data_lock, save_data
)

# Check if we're running on Vercel
IS_VERCEL = os.environ.get('VERCEL') == '1'

# Configure logging specifically for the bot
if IS_VERCEL:
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
else:
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[logging.FileHandler(f"logs/bot_{datetime.now().strftime('%Y-%m-%d')}.log")]
    )

# Telegram keyboard helper functions
def create_telegram_keyboard(buttons, resize_keyboard=True, one_time_keyboard=False):
    """
    Create a Telegram keyboard with the specified buttons
    
    Args:
        buttons: List of lists, where each inner list is a row of buttons
        resize_keyboard: Whether to resize the keyboard
        one_time_keyboard: Whether the keyboard should be hidden after one use
        
    Returns:
        Dictionary representing a Telegram keyboard
    """
    return {
        "keyboard": buttons,
        "resize_keyboard": resize_keyboard,
        "one_time_keyboard": one_time_keyboard
    }

def create_telegram_inline_keyboard(buttons):
    """
    Create a Telegram inline keyboard with the specified buttons
    
    Args:
        buttons: List of lists, where each inner list is a row of buttons.
                Each button is a dict with 'text' and 'callback_data' keys
                
    Returns:
        Dictionary representing a Telegram inline keyboard
    """
    return {
        "inline_keyboard": buttons
    }

# Send Telegram message with keyboard
def send_telegram_message_with_keyboard(chat_id, message, keyboard=None, parse_mode="Markdown"):
    """Send a message to a user via Telegram with an optional keyboard"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": parse_mode
        }
        
        if keyboard:
            data["reply_markup"] = json.dumps(keyboard)
            
        response = requests.post(url, data=data)
        if response.status_code == 200:
            logging.info(f"Telegram message with keyboard sent to {chat_id}")
            return True
        else:
            logging.info(f"Failed to send Telegram message with keyboard: {response.text}")
    except Exception as e:
        logging.error(f"Error sending Telegram message with keyboard: {str(e)}")
        logging.error(traceback.format_exc())
    return False

# Send Telegram notification (updated to include keyboard option)
def send_telegram_notification(user_id, message, keyboard=None):
    """Send a notification to a user via Telegram with optional keyboard"""
    # Check if user has a Telegram ID saved
    if user_id in user_data and 'telegram_id' in user_data[user_id]:
        telegram_id = user_data[user_id]['telegram_id']
        try:
            if keyboard:
                return send_telegram_message_with_keyboard(telegram_id, message, keyboard)
            else:
                url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                data = {
                    "chat_id": telegram_id,
                    "text": message,
                    "parse_mode": "Markdown"
                }
                response = requests.post(url, data=data)
                if response.status_code == 200:
                    logging.info(f"Telegram notification sent to {telegram_id}")
                    return True
                else:
                    logging.info(f"Failed to send Telegram notification: {response.text}")
        except Exception as e:
            logging.error(f"Error sending Telegram notification: {str(e)}")
            logging.error(traceback.format_exc())
    return False

# Send notification to admin
def notify_admin(message, keyboard=None):
    """Send notification to admin via Telegram with optional keyboard"""
    try:
        if ADMIN_TELEGRAM_ID:
            if keyboard:
                return send_telegram_message_with_keyboard(ADMIN_TELEGRAM_ID, message, keyboard)
            else:
                url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                data = {
                    "chat_id": ADMIN_TELEGRAM_ID,
                    "text": message,
                    "parse_mode": "Markdown"
                }
                response = requests.post(url, data=data)
                if response.status_code == 200:
                    logging.info(f"Admin notification sent")
                    return True
                else:
                    logging.info(f"Failed to send admin notification: {response.text}")
    except Exception as e:
        logging.error(f"Error sending admin notification: {str(e)}")
        logging.error(traceback.format_exc())
    return False

# Generate verification code for Telegram connection
def generate_verification_code(telegram_id):
    """Generate a verification code for Telegram connection"""
    code = ''.join(random.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789') for _ in range(6))
    
    with data_lock:
        telegram_verification_codes[telegram_id] = {
            "code": code,
            "created_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "expires_at": (datetime.now() + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
        }
    
    save_data()
    return code

# Verify Telegram code
def verify_telegram_code(telegram_id, code):
    """Verify the Telegram verification code"""
    with data_lock:
        if telegram_id in telegram_verification_codes:
            verify_data = telegram_verification_codes[telegram_id]
            if verify_data["code"] == code:
                # Check if code is expired
                expires_at = datetime.strptime(verify_data["expires_at"], '%Y-%m-%d %H:%M:%S')
                if datetime.now() <= expires_at:
                    # Code is valid
                    return True
    
    return False

# SMM Panel API Functions
def connect_smm_panel(api_url, api_key, action, params=None):
    """Connect to SMM panel API with comprehensive error handling"""
    if params is None:
        params = {}
    
    payload = {
        'key': api_key,
        'action': action,
        'format': 'json'
    }
    
    if params:
        payload.update(params)
    
    try:
        # Log API request (redact sensitive info)
        safe_payload = payload.copy()
        if 'key' in safe_payload:
            safe_payload['key'] = '***REDACTED***'
        logging.info(f"API Request to {api_url}: {json.dumps(safe_payload)}")
        
        # More robust request handling with additional timeouts
        response = requests.post(
            api_url, 
            data=payload, 
            verify=False, 
            timeout=(30, 60),  # 30 seconds connect timeout, 60 seconds read timeout
            headers={
                'User-Agent': 'SMM-Automation-Bot/1.0',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
        )
        
        if response.status_code != 200:
            logging.info(f"API Error: HTTP {response.status_code} - {response.text}")
            return {"error": f"HTTP Error: {response.status_code}"}
        
        try:
            result = response.json()
            logging.info(f"API Response: {json.dumps(result)}")
            return result
        except Exception as e:
            logging.info(f"Invalid JSON response from API: {str(e)}")
            return {"error": f"Invalid JSON response: {str(e)}"}
            
    except requests.exceptions.Timeout:
        logging.info(f"API request timeout: {api_url}")
        return {"error": "Connection timed out"}
    except requests.exceptions.ConnectionError:
        logging.info(f"API connection error: {api_url}")
        return {"error": "Connection error"}
    except Exception as e:
        logging.error(f"API request failed: {str(e)}")
        logging.error(traceback.format_exc())
        return {"error": str(e)}

def place_order(api_url, api_key, service_id, link, quantity, user_id):
    """Place an order with the SMM panel with enhanced error handling"""
    global bot_statistics
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    order_params = {
        'service': service_id,
        'link': link,
        'quantity': quantity,
    }
    
    logging.info(f"Placing order with quantity: {quantity} for service: {service_id}")
    
    try:
        new_order = connect_smm_panel(api_url, api_key, 'add', order_params)
        
        with data_lock:
            # Update statistics
            bot_statistics["total_orders"] += 1
            bot_statistics["last_24h_orders"] += 1
            
            if "order" in new_order:
                bot_statistics["successful_orders"] += 1
                # Estimate cost (this is a placeholder, you might want to calculate based on actual service rates)
                estimated_cost = quantity * 0.001  # Example calculation
                bot_statistics["total_spent"] += estimated_cost
                
                # Create inline keyboard for order details
                order_id = new_order['order']
                order_keyboard = create_telegram_inline_keyboard([
                    [{"text": "📊 Check Status", "callback_data": f"check_order_{order_id}"}],
                    [{"text": "📈 View on Website", "callback_data": f"view_order_{order_id}"}]
                ])
                
                # Send Telegram notification for successful order
                notification_message = (
                    "✅ *Order Placed Successfully*\n"
                    f"📅 Time: `{timestamp}`\n"
                    f"🔢 Order ID: `{order_id}`\n"
                    f"📦 Service: `{service_id}`\n"
                    f"📊 Quantity: `{quantity}`\n"
                    f"🔗 Link: `{link}`"
                )
                
                # Notify user with interactive buttons
                send_telegram_notification(user_id, notification_message, order_keyboard)
                
                # Notify admin
                admin_notification = (
                    "💰 *New Order Placed*\n"
                    f"👤 User: `{user_id}`\n"
                    f"📅 Time: `{timestamp}`\n"
                    f"🔢 Order ID: `{order_id}`\n"
                    f"📦 Service: `{service_id}`\n"
                    f"📊 Quantity: `{quantity}`\n"
                    f"🔗 Link: `{link}`"
                )
                
                admin_keyboard = create_telegram_inline_keyboard([
                    [{"text": "📊 Check Status", "callback_data": f"admin_check_order_{order_id}"}],
                    [{"text": "👤 View User", "callback_data": f"view_user_{user_id}"}]
                ])
                
                notify_admin(admin_notification, admin_keyboard)
            else:
                bot_statistics["failed_orders"] += 1
                
                # Send Telegram notification for failed order
                notification_message = (
                    "❌ *Order Failed*\n"
                    f"📅 Time: `{timestamp}`\n"
                    f"⚠️ Error: `{new_order.get('error', 'Unknown error')}`\n"
                    f"📦 Service: `{service_id}`\n"
                    f"📊 Quantity: `{quantity}`\n"
                    f"🔗 Link: `{link}`"
                )
                
                # Add retry button
                retry_keyboard = create_telegram_inline_keyboard([
                    [{"text": "🔄 Retry Order", "callback_data": f"retry_order_{service_id}_{quantity}_{link.replace(' ', '_')}"}]
                ])
                
                send_telegram_notification(user_id, notification_message, retry_keyboard)
                
                # Notify admin about failed order
                admin_notification = (
                    "⚠️ *Order Failed*\n"
                    f"👤 User: `{user_id}`\n"
                    f"📅 Time: `{timestamp}`\n"
                    f"❌ Error: `{new_order.get('error', 'Unknown error')}`\n"
                    f"📦 Service: `{service_id}`\n"
                    f"📊 Quantity: `{quantity}`\n"
                    f"🔗 Link: `{link}`"
                )
                notify_admin(admin_notification)
            
            try:
                save_data()
            except Exception as e:
                logging.error(f"Error saving data after order: {str(e)}")
                logging.error(traceback.format_exc())
        
        return [new_order, timestamp]
    except Exception as e:
        logging.error(f"Error placing order: {str(e)}")
        logging.error(traceback.format_exc())
        error_order = {"error": f"Internal error: {str(e)}"}
        return [error_order, timestamp]

def calculate_next_quantity(current_quantity, increase_range):
    """Calculate the next quantity based on increase range"""
    try:
        min_increase, max_increase = increase_range
        increase_percent = random.uniform(float(min_increase), float(max_increase))
        increase_amount = int(current_quantity * (increase_percent / 100))
        next_quantity = current_quantity + increase_amount
        return next_quantity
    except Exception as e:
        logging.error(f"Error calculating next quantity: {str(e)}")
        logging.error(traceback.format_exc())
        # Return a slight increase as fallback
        return int(current_quantity * 1.1)

def get_user_active_jobs(user_id):
    """Get all active jobs for a specific user"""
    user_jobs = []
    
    with data_lock:
        for job in background_jobs:
            if job['user_id'] == user_id and not job.get('stopped', False):
                user_jobs.append(job)
    
    return user_jobs

def get_all_active_jobs():
    """Get all active jobs for all users"""
    active_jobs = []
    
    with data_lock:
        for job in background_jobs:
            if not job.get('stopped', False):
                active_jobs.append(job)
    
    return active_jobs

def get_user_orders(user_id):
    """Get all orders for a specific user"""
    if user_id in user_data and 'orders' in user_data[user_id]:
        return user_data[user_id]['orders']
    return []

def stop_job(job_id, stopped_by=None):
    """Stop a specific job by ID"""
    with data_lock:
        for i, job in enumerate(background_jobs):
            if job['job_id'] == job_id:
                background_jobs[i]['stopped'] = True
                background_jobs[i]['stopped_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                
                if stopped_by:
                    background_jobs[i]['stopped_by'] = stopped_by
                
                # Send Telegram notification
                user_id = job['user_id']
                service_id = job['service_id']
                link = job['link']
                
                notification_message = (
                    "🛑 *Automation Job Stopped*\n"
                    f"📦 Service: `{service_id}`\n"
                    f"🔗 Link: `{link}`\n"
                    f"⏱ Stopped at: `{background_jobs[i]['stopped_at']}`"
                )
                
                # Add restart option button
                restart_keyboard = create_telegram_inline_keyboard([
                    [{"text": "🔄 Restart Job", "callback_data": f"restart_job_{job_id}"}],
                    [{"text": "📊 View Stats", "callback_data": f"job_stats_{job_id}"}]
                ])
                
                if stopped_by and stopped_by != user_id:
                    notification_message += f"\n👤 Stopped by admin"
                    
                    # Notify admin
                    admin_notification = (
                        "🛑 *Job Stopped by Admin*\n"
                        f"👤 User: `{user_id}`\n"
                        f"📦 Service: `{service_id}`\n"
                        f"🔗 Link: `{link}`\n"
                    )
                    notify_admin(admin_notification)
                
                send_telegram_notification(user_id, notification_message, restart_keyboard)
                
                try:
                    save_data()
                except Exception as e:
                    logging.error(f"Error saving data after stopping job: {str(e)}")
                    logging.error(traceback.format_exc())
                return True
    
    return False

# Process automation jobs with comprehensive error handling
def process_automation_jobs():
    """Process all automation jobs with robust error handling"""
    global background_jobs, user_data, bot_statistics

    logging.info("Starting automation job processing thread")
    
    # Initial job count check
    job_count = 0
    active_count = 0
    with data_lock:
        job_count = len(background_jobs)
        for job in background_jobs:
            if not job.get('stopped', False):
                active_count += 1
    
    logging.info(f"Initial job count: {job_count} (Active: {active_count})")

    while True:
        try:
            now = int(time.time())
            
            # Log job status periodically
            logging.info(f"Checking jobs at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            logging.info(f"Current background jobs count: {len(background_jobs)}")
            
            active_jobs = [job for job in background_jobs if not job.get('stopped', False)]
            logging.info(f"Active jobs count: {len(active_jobs)}")
            
            if len(active_jobs) > 0:
                logging.info(f"Active jobs: {[job.get('job_id', 'unknown') for job in active_jobs]}")
            
            with data_lock:
                updated_jobs = []
                
                for job in background_jobs:
                    try:
                        user_id = job.get('user_id', 'unknown')
                        job_id = job.get('job_id', 'unknown')
                        
                        # Skip if job is marked as stopped
                        if job.get('stopped', False):
                            updated_jobs.append(job)
                            continue
                        
                        # Debug info
                        next_run = job.get('next_run', 0)
                        if next_run > 0:
                            next_run_time = datetime.fromtimestamp(next_run).strftime('%Y-%m-%d %H:%M:%S')
                            logging.info(f"Job {job_id} next run: {next_run_time}, Current time: {datetime.fromtimestamp(now).strftime('%Y-%m-%d %H:%M:%S')}")
                        
                        # Check if it's time to run the job
                        if now >= job.get('next_run', 0):
                            logging.info(f"Processing job {job_id} for user {user_id}")
                            
                            # Check if user data exists
                            if user_id not in user_data:
                                logging.info(f"No data for user {user_id}")
                                updated_jobs.append(job)
                                continue
                            
                            # Get job configuration with safe fallbacks
                            api_url = job.get('api_url', '')
                            api_key = job.get('api_key', '')
                            service_id = job.get('service_id', '')
                            link = job.get('link', '')
                            current_quantity = job.get('quantity', 100)
                            increase_range = job.get('increase_range', [10, 20])
                            frequency_minutes = job.get('frequency', 60)
                            
                            logging.info(f"Running job {job_id}: Service {service_id}, Quantity {current_quantity}")
                            
                            # Place order
                            new_order, timestamp = place_order(api_url, api_key, service_id, link, current_quantity, user_id)
                            
                            # Store order in user history
                            if 'orders' not in user_data[user_id]:
                                user_data[user_id]['orders'] = []
                            
                            order_info = {
                                "timestamp": timestamp,
                                "quantity": current_quantity,
                                "response": new_order,
                                "job_id": job_id,
                                "service_id": service_id,
                                "link": link
                            }
                            
                            user_data[user_id]['orders'].append(order_info)
                            
                            # Also update the job's order history
                            if 'orders' not in job:
                                job['orders'] = []
                            job['orders'].append(order_info)
                            
                            # Calculate next quantity
                            next_quantity = calculate_next_quantity(current_quantity, increase_range)
                            
                            # Update job with new quantity and next run time
                            job['quantity'] = next_quantity
                            job['next_run'] = now + (frequency_minutes * 60)
                            
                            # Send job update notification with next run info
                            next_run_time = datetime.fromtimestamp(job['next_run']).strftime('%H:%M:%S')
                            
                            job_update_message = (
                                "📊 *Automation Job Update*\n"
                                f"📦 Service: `{service_id}`\n"
                                f"✅ Order placed: `{current_quantity}` units\n"
                                f"⏱ Next run at: `{next_run_time}`\n"
                                f"📈 Next quantity: `{next_quantity}`\n"
                            )
                            
                            job_control_keyboard = create_telegram_inline_keyboard([
                                [{"text": "⏱ Change Frequency", "callback_data": f"change_freq_{job_id}"}],
                                [{"text": "📊 Adjust Growth Rate", "callback_data": f"change_growth_{job_id}"}],
                                [{"text": "🛑 Stop Job", "callback_data": f"stop_job_{job_id}"}]
                            ])
                            
                            send_telegram_notification(user_id, job_update_message, job_control_keyboard)
                            logging.info(f"Job {job_id} processed successfully, next run at {next_run_time}")
                            
                            updated_jobs.append(job)
                        else:
                            # Keep this job for future runs
                            updated_jobs.append(job)
                    except Exception as e:
                        logging.error(f"Error processing job {job.get('job_id', 'unknown')}: {str(e)}")
                        logging.error(traceback.format_exc())
                        # Still add the job back to avoid losing it, but mark it for future retry
                        if 'error_count' not in job:
                            job['error_count'] = 1
                        else:
                            job['error_count'] += 1
                        
                        # Only retry up to 5 times, then mark as stopped
                        if job.get('error_count', 0) > 5:
                            job['stopped'] = True
                            job['stopped_reason'] = f"Too many errors: {str(e)}"
                            
                            # Notify user about job stopping due to errors
                            notification_message = (
                                "⚠️ *Automation Job Stopped Due to Errors*\n"
                                f"📦 Service: `{job.get('service_id', 'Unknown')}`\n"
                                f"🔗 Link: `{job.get('link', 'Unknown')}`\n"
                                f"❌ Reason: Too many consecutive errors\n"
                                "Please set up a new automation job."
                            )
                            
                            error_keyboard = create_telegram_inline_keyboard([
                                [{"text": "🔄 Set Up New Job", "callback_data": "new_job"}]
                            ])
                            
                            send_telegram_notification(job.get('user_id'), notification_message, error_keyboard)
                            
                            # Notify admin
                            admin_notification = (
                                "🔴 *Job Stopped Due to Errors*\n"
                                f"👤 User: `{job.get('user_id', 'Unknown')}`\n"
                                f"📦 Service: `{job.get('service_id', 'Unknown')}`\n"
                                f"❌ Reason: Too many consecutive errors"
                            )
                            notify_admin(admin_notification)
                        
                        updated_jobs.append(job)
                
                # Update background jobs safely
                background_jobs[:] = updated_jobs
                
                # Save after processing is complete
                try:
                    save_data()
                except Exception as e:
                    logging.error(f"Error saving data after job processing: {str(e)}")
                    logging.error(traceback.format_exc())
        except Exception as e:
            logging.error(f"Critical error in process_automation_jobs: {str(e)}")
            logging.error(traceback.format_exc())
        
        # Sleep for 15 seconds before checking again (more frequent checks)
        time.sleep(15)

# --- Bulk job session storage ---
telegram_user_sessions = {}

def store_user_session(chat_id, session_data):
    global telegram_user_sessions
    telegram_user_sessions[str(chat_id)] = session_data

def get_user_session(chat_id):
    return telegram_user_sessions.get(str(chat_id), None)

def clear_user_session(chat_id):
    global telegram_user_sessions
    if str(chat_id) in telegram_user_sessions:
        del telegram_user_sessions[str(chat_id)]

def find_user_by_telegram_id(chat_id):
    for username, user in user_data.items():
        if 'telegram_id' in user and user['telegram_id'] == str(chat_id):
            return username
    return None

# --- Bulk job creation function ---
def create_bulk_jobs_from_template(user_id, template_id, links):
    try:
        template = None
        if user_id in user_data and 'templates' in user_data[user_id]:
            for t in user_data[user_id]['templates']:
                if t.get('id') == template_id:
                    template = t
                    break
        if not template:
            logging.error(f"Template {template_id} not found for user {user_id}")
            return 0
        api_profile_name = template.get('api_profile', '')
        api_url = ''
        api_key = ''
        if (user_id in user_data and 'api_profiles' in user_data[user_id] and 
            api_profile_name in user_data[user_id]['api_profiles']):
            api_profile = user_data[user_id]['api_profiles'][api_profile_name]
            api_url = api_profile.get('api_url', '')
            api_key = api_profile.get('api_key', '')
        if not api_url or not api_key:
            logging.error(f"API profile {api_profile_name} not found or invalid")
            return 0
        created_jobs = []
        for link in links:
            job_id = f"job_{uuid.uuid4()}"
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
                'next_run': int(time.time()),
                'started_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'stopped': False,
                'orders': [],
                'template_id': template_id
            }
            created_jobs.append(new_job)
        with data_lock:
            background_jobs.extend(created_jobs)
            for t in user_data[user_id]['templates']:
                if t.get('id') == template_id:
                    t['usage_count'] = t.get('usage_count', 0) + len(created_jobs)
                    break
            save_data()
        notification_message = (
            "🚀 *Bulk Jobs Started via Telegram*\n"
            f"📝 Template: `{template.get('name', 'Unknown')}`\n"
            f"📦 Service: `{template.get('service_id', '')}`\n"
            f"📊 Starting Quantity: `{template.get('quantity', 100)}`\n"
            f"📈 Growth: `{template.get('increase_min', 10)}-{template.get('increase_max', 20)}%`\n"
            f"⏱ Frequency: Every `{template.get('frequency', 60)}` minutes\n"
            f"🔢 Total Jobs: `{len(created_jobs)}`\n\n"
            "Your first orders will be placed shortly for all links!"
        )
        send_telegram_notification(user_id, notification_message)
        admin_notification = (
            "🚀 *Bulk Jobs Created via Telegram*\n"
            f"👤 User: `{user_id}`\n"
            f"📝 Template: `{template.get('name', 'Unknown')}`\n"
            f"📦 Service: `{template.get('service_id', '')}`\n"
            f"🔢 Jobs Created: `{len(created_jobs)}`\n"
        )
        notify_admin(admin_notification)
        return len(created_jobs)
    except Exception as e:
        logging.error(f"Error creating bulk jobs: {str(e)}")
        logging.error(traceback.format_exc())
        return 0

# --- New Job Session Management for /newjob ---
def store_newjob_session(chat_id, step, data):
    if str(chat_id) not in telegram_user_sessions:
        telegram_user_sessions[str(chat_id)] = {}
    telegram_user_sessions[str(chat_id)]['newjob'] = {
        'step': step,
        'data': data
    }

def get_newjob_session(chat_id):
    if str(chat_id) in telegram_user_sessions and 'newjob' in telegram_user_sessions[str(chat_id)]:
        return telegram_user_sessions[str(chat_id)]['newjob']
    return None

def clear_newjob_session(chat_id):
    if str(chat_id) in telegram_user_sessions and 'newjob' in telegram_user_sessions[str(chat_id)]:
        del telegram_user_sessions[str(chat_id)]['newjob']

# --- Job creation and validation for /newjob ---
def create_jobs_from_telegram(user_id, job_data):
    """Create automation jobs from Telegram input"""
    try:
        api_urls = job_data.get('api_urls', [])
        api_keys = job_data.get('api_keys', [])
        target_links = job_data.get('target_links', [])
        service_ids = job_data.get('service_ids', [])
        quantity = int(job_data.get('quantity', 100))
        increase_min = float(job_data.get('increase_min', 10))
        increase_max = float(job_data.get('increase_max', 20))
        frequency = int(job_data.get('frequency', 60))
        is_bulk = len(api_urls) > 1 or len(target_links) > 1 or len(service_ids) > 1
        created_jobs = []
        # Pairing logic: zip or broadcast single values
        max_jobs = max(len(api_urls), len(target_links), len(service_ids))
        if max_jobs > 10:
            max_jobs = 10
        for i in range(max_jobs):
            job = {
                'job_id': f"job_{uuid.uuid4()}",
                'user_id': user_id,
                'api_url': api_urls[i] if i < len(api_urls) else api_urls[0],
                'api_key': api_keys[i] if i < len(api_keys) else api_keys[0],
                'service_id': service_ids[i] if i < len(service_ids) else service_ids[0],
                'link': target_links[i] if i < len(target_links) else target_links[0],
                'quantity': quantity,
                'increase_range': [increase_min, increase_max],
                'frequency': frequency,
                'next_run': int(time.time()),
                'started_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'stopped': False,
                'orders': []
            }
            created_jobs.append(job)
        with data_lock:
            background_jobs.extend(created_jobs)
            save_data()
        return len(created_jobs)
    except Exception as e:
        logging.error(f"Error creating jobs from Telegram: {str(e)}")
        logging.error(traceback.format_exc())
        return 0

def validate_api_connection(api_url, api_key):
    try:
        result = connect_smm_panel(api_url, api_key, 'balance')
        return 'error' not in result
    except:
        return False

def validate_job_parameters(quantity, increase_min, increase_max, frequency):
    try:
        quantity = int(quantity)
        increase_min = float(increase_min)
        increase_max = float(increase_max)
        frequency = int(frequency)
        return (quantity > 0 and 0 <= increase_min <= 100 and 0 <= increase_max <= 100 and increase_min <= increase_max and frequency >= 5)
    except:
        return False

# --- Update main menu keyboard to include New Job ---
def get_main_menu_keyboard():
    return create_telegram_keyboard([
        ["📊 My Orders", "🚀 My Jobs"],
        ["🚀 New Job", "📦 Bulk Jobs"],
        ["💼 Account"]
    ])

# Telegram message handler
def handle_telegram_update(update):
    """Handle updates from Telegram"""
    try:
        # Get necessary information
        if "message" in update:
            message = update["message"]
            chat_id = message["chat"]["id"]
            text = message.get("text", "")
            
            # Handle different commands
            if text == "/start":
                # Send welcome message with keyboard
                welcome_message = (
                    "👋 *Welcome to SMM Automation Bot!*\n\n"
                    "This bot helps you manage your SMM automation services and receive notifications.\n\n"
                    "Please choose an option below:"
                )
                
                keyboard = create_telegram_keyboard([
                    ["📱 Connect Account"],
                    ["📊 My Orders", "🚀 My Jobs"],
                    ["📦 Bulk Jobs", "💼 Account"]
                ])
                
                send_telegram_message_with_keyboard(chat_id, welcome_message, keyboard)
                
            elif text == "/connect" or text == "📱 Connect Account":
                # Generate verification code and send it to user
                verification_code = generate_verification_code(str(chat_id))
                
                connect_message = (
                    "🔗 *Connect Your Account*\n\n"
                    f"Your Chat ID is: `{chat_id}`\n"
                    f"Your verification code is: `{verification_code}`\n\n"
                    "Please enter both this Chat ID and verification code on the SMM Automation website to complete the connection."
                )
                
                # Add a keyboard with a button to go to website
                keyboard = create_telegram_inline_keyboard([
                    [{"text": "🌐 Open Website", "url": "http://yourdomain.com/connect_telegram"}]
                ])
                
                send_telegram_message_with_keyboard(chat_id, connect_message, keyboard)
                
            elif text == "/help":
                # Send help message with keyboard
                help_message = (
                    "ℹ️ *SMM Automation Bot Help*\n\n"
                    "*Available Commands:*\n"
                    "• /start - Start the bot\n"
                    "• /connect - Connect your account\n"
                    "• /orders - View your recent orders\n"
                    "• /jobs - View your active jobs\n"
                    "• /account - Manage your account\n"
                    "• /help - Show this help message\n\n"
                    "You can also use the buttons below for navigation."
                )
                
                keyboard = create_telegram_keyboard([
                    ["📱 Connect Account"],
                    ["📊 My Orders", "🚀 My Jobs"],
                    ["📦 Bulk Jobs", "💼 Account"]
                ])
                
                send_telegram_message_with_keyboard(chat_id, help_message, keyboard)
                
            elif text == "/orders" or text == "📊 My Orders":
                # Try to find user by Telegram ID
                user_found = False
                user_id = None
                
                for username, user in user_data.items():
                    if 'telegram_id' in user and user['telegram_id'] == str(chat_id):
                        user_found = True
                        user_id = username
                        break
                
                if user_found and user_id:
                    # Get user's recent orders
                    orders = get_user_orders(user_id)
                    
                    if orders:
                        # Show 5 most recent orders
                        recent_orders = orders[-5:] if len(orders) > 5 else orders
                        # Reverse to show newest first
                        recent_orders = recent_orders[::-1]
                        
                        orders_message = "📊 *Your Recent Orders*\n\n"
                        
                        for idx, order in enumerate(recent_orders, 1):
                            order_id = order['response'].get('order', 'Unknown')
                            service_id = order.get('service_id', 'Unknown')
                            quantity = order.get('quantity', 'Unknown')
                            timestamp = order.get('timestamp', 'Unknown')
                            
                            orders_message += (
                                f"*Order {idx}:*\n"
                                f"🔢 ID: `{order_id}`\n"
                                f"📦 Service: `{service_id}`\n"
                                f"📊 Quantity: `{quantity}`\n"
                                f"📅 Date: `{timestamp}`\n\n"
                            )
                        
                        # Add a keyboard with a button to go to website
                        keyboard = create_telegram_inline_keyboard([
                            [{"text": "🔄 Refresh Orders", "callback_data": "refresh_orders"}],
                            [{"text": "🌐 View All Orders", "url": "http://yourdomain.com/order_history"}]
                        ])
                        
                        send_telegram_message_with_keyboard(chat_id, orders_message, keyboard)
                    else:
                        no_orders_message = (
                            "📊 *Your Orders*\n\n"
                            "You don't have any orders yet.\n\n"
                            "Use the button below to place your first order!"
                        )
                        
                        keyboard = create_telegram_inline_keyboard([
                            [{"text": "🚀 Place Order", "url": "http://yourdomain.com/dashboard"}]
                        ])
                        
                        send_telegram_message_with_keyboard(chat_id, no_orders_message, keyboard)
                else:
                    # User not found, prompt to connect account
                    not_connected_message = (
                        "⚠️ *Account Not Connected*\n\n"
                        "Your Telegram account is not connected to any SMM Automation account.\n\n"
                        "Please use the button below to connect your account."
                    )
                    
                    keyboard = create_telegram_keyboard([
                        ["📱 Connect Account"]
                    ])
                    
                    send_telegram_message_with_keyboard(chat_id, not_connected_message, keyboard)
                
            elif text == "/jobs" or text == "🚀 My Jobs":
                # Try to find user by Telegram ID
                user_found = False
                user_id = None
                
                for username, user in user_data.items():
                    if 'telegram_id' in user and user['telegram_id'] == str(chat_id):
                        user_found = True
                        user_id = username
                        break
                
                if user_found and user_id:
                    # Get user's active jobs
                    active_jobs = get_user_active_jobs(user_id)
                    
                    if active_jobs:
                        jobs_message = "🚀 *Your Active Jobs*\n\n"
                        
                        for idx, job in enumerate(active_jobs, 1):
                            service_id = job.get('service_id', 'Unknown')
                            link = job.get('link', 'Unknown')
                            if len(link) > 30:
                                link = link[:27] + "..."
                            quantity = job.get('quantity', 'Unknown')
                            increase_range = job.get('increase_range', [0, 0])
                            frequency = job.get('frequency', 0)
                            
                            next_run = job.get('next_run', 0)
                            next_run_time = datetime.fromtimestamp(next_run).strftime('%H:%M:%S')
                            
                            jobs_message += (
                                f"*Job {idx}:*\n"
                                f"📦 Service: `{service_id}`\n"
                                f"🔗 Link: `{link}`\n"
                                f"📊 Next Quantity: `{quantity}`\n"
                                f"📈 Growth: `{increase_range[0]}-{increase_range[1]}%`\n"
                                f"⏱ Frequency: Every `{frequency}` minutes\n"
                                f"🕒 Next Run: `{next_run_time}`\n\n"
                            )
                        
                        # Add control buttons
                        job_buttons = []
                        for job in active_jobs[:3]:  # Limit to first 3 jobs to avoid too many buttons
                            job_id = job.get('job_id', '')
                            service_id = job.get('service_id', 'Job')
                            job_buttons.append([{"text": f"🛑 Stop {service_id}", "callback_data": f"stop_job_{job_id}"}])
                        
                        job_buttons.append([{"text": "🚀 New Job", "callback_data": "new_job"}])
                        job_buttons.append([{"text": "📦 Bulk Jobs", "callback_data": "bulk_jobs"}])
                        job_buttons.append([{"text": "🌐 Manage All Jobs", "url": "http://yourdomain.com/dashboard"}])
                        
                        keyboard = create_telegram_inline_keyboard(job_buttons)
                        
                        send_telegram_message_with_keyboard(chat_id, jobs_message, keyboard)
                    else:
                        no_jobs_message = (
                            "🚀 *Your Jobs*\n\n"
                            "You don't have any active automation jobs.\n\n"
                            "Use the button below to set up your first automation job!"
                        )
                        
                        keyboard = create_telegram_inline_keyboard([
                            [{"text": "🚀 Create Job", "url": "http://yourdomain.com/setup_automation"}]
                        ])
                        
                        send_telegram_message_with_keyboard(chat_id, no_jobs_message, keyboard)
                else:
                    # User not found, prompt to connect account
                    not_connected_message = (
                        "⚠️ *Account Not Connected*\n\n"
                        "Your Telegram account is not connected to any SMM Automation account.\n\n"
                        "Please use the button below to connect your account."
                    )
                    
                    keyboard = create_telegram_keyboard([
                        ["📱 Connect Account"]
                    ])
                    
                    send_telegram_message_with_keyboard(chat_id, not_connected_message, keyboard)
                
            elif text == "/account" or text == "💼 Account":
                # Try to find user by Telegram ID
                user_found = False
                user_id = None
                
                for username, user in user_data.items():
                    if 'telegram_id' in user and user['telegram_id'] == str(chat_id):
                        user_found = True
                        user_id = username
                        break
                
                if user_found and user_id:
                    # Show account info
                    account_message = (
                        "💼 *Your Account*\n\n"
                        f"Username: `{user_id}`\n"
                    )
                    
                    # Count orders
                    order_count = 0
                    if 'orders' in user_data[user_id]:
                        order_count = len(user_data[user_id]['orders'])
                    
                    # Count API profiles
                    api_profile_count = 0
                    if 'api_profiles' in user_data[user_id]:
                        api_profile_count = len(user_data[user_id]['api_profiles'])
                    
                    # Count active jobs
                    active_job_count = len(get_user_active_jobs(user_id))
                    
                    account_message += (
                        f"📊 Orders: `{order_count}`\n"
                        f"🔌 API Profiles: `{api_profile_count}`\n"
                        f"🚀 Active Jobs: `{active_job_count}`\n"
                        f"📱 Telegram: Connected\n"
                    )
                    
                    # Add account management buttons
                    keyboard = create_telegram_inline_keyboard([
                        [{"text": "📊 My Dashboard", "url": "http://yourdomain.com/dashboard"}],
                        [{"text": "⚙️ Account Settings", "url": "http://yourdomain.com/user_settings"}]
                    ])
                    
                    send_telegram_message_with_keyboard(chat_id, account_message, keyboard)
                else:
                    # User not found, prompt to connect account
                    not_connected_message = (
                        "⚠️ *Account Not Connected*\n\n"
                        "Your Telegram account is not connected to any SMM Automation account.\n\n"
                        "Please use the button below to connect your account."
                    )
                    
                    keyboard = create_telegram_keyboard([
                        ["📱 Connect Account"]
                    ])
                    
                    send_telegram_message_with_keyboard(chat_id, not_connected_message, keyboard)
                
            elif text == "/bulk" or text == "📦 Bulk Jobs":
                bulk_message = (
                    "📦 *Bulk Automation Setup*\n\n"
                    "To create multiple automation jobs at once, please send me:\n\n"
                    "1. Your links (one per line, max 10 links)\n"
                    "2. Service ID\n"
                    "3. Starting quantity\n"
                    "4. Growth rate (min-max %)\n"
                    "5. Frequency (minutes)\n\n"
                    "Format example:\n"
                    "`https://instagram.com/post1`\n"
                    "`https://instagram.com/post2`\n"
                    "`SERVICE_ID: 123`\n"
                    "`QUANTITY: 1000`\n"
                    "`GROWTH: 10-20`\n"
                    "`FREQUENCY: 60`"
                )
                keyboard = create_telegram_inline_keyboard([
                    [{"text": "🌐 Use Web Interface", "url": "http://yourdomain.com/setup_automation"}],
                    [{"text": "📝 Template Bulk", "callback_data": "template_bulk"}]
                ])
                send_telegram_message_with_keyboard(chat_id, bulk_message, keyboard)
                
            elif text == "/support":
                # Show support info
                support_message = (
                    "📞 *Support*\n\n"
                    "For support, please contact us through the website or send a message here.\n\n"
                    "Our support team will get back to you as soon as possible."
                )
                
                # Add support buttons
                keyboard = create_telegram_inline_keyboard([
                    [{"text": "📧 Email Support", "url": "mailto:support@yourdomain.com"}],
                    [{"text": "🌐 Help Center", "url": "http://yourdomain.com/help"}]
                ])
                
                send_telegram_message_with_keyboard(chat_id, support_message, keyboard)
                
            elif text == "/newjob" or text == "🚀 New Job":
                user_id = find_user_by_telegram_id(chat_id)
                if user_id:
                    newjob_message = (
                        "🚀 *Create New Automation Job*\n\n"
                        "Let's set up your automation job step by step.\n\n"
                        "**Step 1: API URLs**\n"
                        "Please enter your SMM Panel API URL(s):\n\n"
                        "• For single job: Enter one URL\n"
                        "• For bulk jobs: Enter multiple URLs (one per line)\n\n"
                        "*Example:*\n"
                        "`https://panel1.com/api/v2`\n"
                        "`https://panel2.com/api/v2`"
                    )
                    store_newjob_session(chat_id, 'api_urls', {})
                    send_telegram_message_with_keyboard(chat_id, newjob_message)
                else:
                    send_telegram_message_with_keyboard(chat_id, "❌ You must connect your account first using /connect.")
                return
            # --- Multi-step job creation flow ---
            session = get_newjob_session(chat_id)
            if session:
                user_id = find_user_by_telegram_id(chat_id)
                if user_id:
                    step = session['step']
                    if step == 'api_urls':
                        api_urls = [url.strip() for url in text.split('\n') if url.strip()]
                        session['data']['api_urls'] = api_urls
                        session['step'] = 'api_keys'
                        keys_message = (
                            f"**Step 2: API Keys**\n"
                            f"You entered {len(api_urls)} API URL(s).\n\n"
                            f"Please enter the corresponding API key(s) in the same order:\n"
                            f"(One per line if multiple)"
                        )
                        store_newjob_session(chat_id, 'api_keys', session['data'])
                        send_telegram_message_with_keyboard(chat_id, keys_message)
                        return
                    elif step == 'api_keys':
                        api_keys = [k.strip() for k in text.split('\n') if k.strip()]
                        session['data']['api_keys'] = api_keys
                        session['step'] = 'target_links'
                        links_message = (
                            f"**Step 3: Target Links**\n"
                            f"Please enter the link(s) to automate (one per line if multiple):"
                        )
                        store_newjob_session(chat_id, 'target_links', session['data'])
                        send_telegram_message_with_keyboard(chat_id, links_message)
                        return
                    elif step == 'target_links':
                        target_links = [l.strip() for l in text.split('\n') if l.strip()]
                        session['data']['target_links'] = target_links
                        session['step'] = 'service_ids'
                        service_message = (
                            f"**Step 4: Service IDs**\n"
                            f"Please enter the Service ID(s) (one per line if multiple):"
                        )
                        store_newjob_session(chat_id, 'service_ids', session['data'])
                        send_telegram_message_with_keyboard(chat_id, service_message)
                        return
                    elif step == 'service_ids':
                        service_ids = [s.strip() for s in text.split('\n') if s.strip()]
                        session['data']['service_ids'] = service_ids
                        session['step'] = 'quantity'
                        quantity_message = (
                            f"**Step 5: Quantity**\n"
                            f"Please enter the starting quantity (number):"
                        )
                        store_newjob_session(chat_id, 'quantity', session['data'])
                        send_telegram_message_with_keyboard(chat_id, quantity_message)
                        return
                    elif step == 'quantity':
                        session['data']['quantity'] = text.strip()
                        session['step'] = 'growth_rate'
                        growth_message = (
                            f"**Step 6: Growth Rate**\n"
                            f"Please enter the growth rate as min-max percentage (e.g. 10-20):"
                        )
                        store_newjob_session(chat_id, 'growth_rate', session['data'])
                        send_telegram_message_with_keyboard(chat_id, growth_message)
                        return
                    elif step == 'growth_rate':
                        try:
                            minmax = text.replace('%','').replace(' ','').split('-')
                            session['data']['increase_min'] = float(minmax[0])
                            session['data']['increase_max'] = float(minmax[1]) if len(minmax) > 1 else float(minmax[0])
                        except:
                            send_telegram_message_with_keyboard(chat_id, "❌ Invalid format. Please enter as min-max, e.g. 10-20.")
                            return
                        session['step'] = 'frequency'
                        freq_message = (
                            f"**Step 7: Frequency**\n"
                            f"How many minutes between each order? (e.g. 60):"
                        )
                        store_newjob_session(chat_id, 'frequency', session['data'])
                        send_telegram_message_with_keyboard(chat_id, freq_message)
                        return
                    elif step == 'frequency':
                        session['data']['frequency'] = text.strip()
                        # Validate all parameters
                        valid = validate_job_parameters(session['data']['quantity'], session['data']['increase_min'], session['data']['increase_max'], session['data']['frequency'])
                        if not valid:
                            send_telegram_message_with_keyboard(chat_id, "❌ Invalid job parameters. Please restart with /newjob.")
                            clear_newjob_session(chat_id)
                            return
                        # Optionally validate API connection for each pair
                        for api_url, api_key in zip(session['data']['api_urls'], session['data']['api_keys']):
                            if not validate_api_connection(api_url, api_key):
                                send_telegram_message_with_keyboard(chat_id, f"❌ API connection failed for {api_url}. Please check your API key.")
                                clear_newjob_session(chat_id)
                                return
                        # Create jobs
                        num_jobs = create_jobs_from_telegram(user_id, session['data'])
                        if num_jobs > 0:
                            summary = (
                                f"✅ *{num_jobs} job(s) created successfully!*\n\n"
                                f"You can manage your jobs from the web dashboard or use /jobs."
                            )
                            send_telegram_message_with_keyboard(chat_id, summary, get_main_menu_keyboard())
                        else:
                            send_telegram_message_with_keyboard(chat_id, "❌ Failed to create jobs. Please try again.")
                        clear_newjob_session(chat_id)
                        return
                
            else:
                # Try to find user by Telegram ID
                user_found = False
                user_id = None
                
                for username, user in user_data.items():
                    if 'telegram_id' in user and user['telegram_id'] == str(chat_id):
                        user_found = True
                        user_id = username
                        break
                
                if user_found:
                    # User is connected, show main menu
                    menu_message = (
                        "👋 *Hello!*\n\n"
                        "What would you like to do today? Use the buttons below to navigate."
                    )
                    
                    keyboard = create_telegram_keyboard([
                        ["📊 My Orders", "🚀 My Jobs"],
                        ["💼 Account"]
                    ])
                    
                    send_telegram_message_with_keyboard(chat_id, menu_message, keyboard)
                else:
                    # Default response for unknown commands when not connected
                    unknown_message = (
                        "Sorry, I don't understand that command. Please use the buttons below or type /help to see available commands.\n\n"
                        "It looks like your Telegram account is not connected to an SMM Automation account yet. Would you like to connect now?"
                    )
                    
                    keyboard = create_telegram_keyboard([
                        ["📱 Connect Account"],
                        ["❓ Help"]
                    ])
                    
                    send_telegram_message_with_keyboard(chat_id, unknown_message, keyboard)
        
        # Handle callback queries (button clicks)
        elif "callback_query" in update:
            callback_query = update["callback_query"]
            callback_data = callback_query.get("data", "")
            chat_id = callback_query["from"]["id"]
            
            # Handle different callback data
            if callback_data == "template_bulk":
                user_id = find_user_by_telegram_id(chat_id)
                if user_id and user_id in user_data and 'templates' in user_data[user_id]:
                    templates = user_data[user_id]['templates']
                    if templates:
                        template_message = "📝 *Select Template for Bulk Jobs*\n\n"
                        template_buttons = []
                        for template in templates[:5]:
                            template_name = template.get('name', 'Unknown')
                            template_id = template.get('id', '')
                            template_buttons.append([{
                                "text": f"📋 {template_name}",
                                "callback_data": f"bulk_template_{template_id}"
                            }])
                        keyboard = create_telegram_inline_keyboard(template_buttons)
                        send_telegram_message_with_keyboard(chat_id, template_message, keyboard)
                    else:
                        no_templates_message = (
                            "📝 *No Templates Found*\n\n"
                            "You need to create templates first to use bulk functionality.\n\n"
                            "Use the web interface to create templates."
                        )
                        keyboard = create_telegram_inline_keyboard([
                            [{"text": "🌐 Create Template", "url": "http://yourdomain.com/create_template"}]
                        ])
                        send_telegram_message_with_keyboard(chat_id, no_templates_message, keyboard)
                else:
                    no_templates_message = (
                        "📝 *No Templates Found*\n\n"
                        "You need to create templates first to use bulk functionality.\n\n"
                        "Use the web interface to create templates."
                    )
                    keyboard = create_telegram_inline_keyboard([
                        [{"text": "🌐 Create Template", "url": "http://yourdomain.com/create_template"}]
                    ])
                    send_telegram_message_with_keyboard(chat_id, no_templates_message, keyboard)
            elif callback_data.startswith("bulk_template_"):
                template_id = callback_data.replace("bulk_template_", "")
                bulk_prompt_message = (
                    "📦 *Bulk Job Creation*\n\n"
                    "Please send me the links you want to create jobs for.\n\n"
                    "*Format:*\n"
                    "Send each link on a separate line (max 10 links)\n\n"
                    "*Example:*\n"
                    "`https://instagram.com/post1`\n"
                    "`https://instagram.com/post2`\n"
                    "`https://instagram.com/post3`"
                )
                store_user_session(chat_id, {"action": "bulk_links", "template_id": template_id})
                send_telegram_message_with_keyboard(chat_id, bulk_prompt_message)
            elif callback_data.startswith("check_order_"):
                order_id = callback_data.replace("check_order_", "")
                
                # Send order status message
                status_message = (
                    "📊 *Order Status*\n\n"
                    f"Checking status for Order ID: `{order_id}`\n\n"
                    "Please wait a moment..."
                )
                
                send_telegram_message_with_keyboard(chat_id, status_message)
                
                # Here you would actually check the order status from your API
                # For now, just send a placeholder message
                status_update = (
                    "📊 *Order Status Update*\n\n"
                    f"Order ID: `{order_id}`\n"
                    "Status: `In Progress`\n"
                    "Completion: `35%`\n"
                    "Started: `2 hours ago`\n"
                    "Estimated completion: `5 hours`"
                )
                
                status_keyboard = create_telegram_inline_keyboard([
                    [{"text": "🔄 Refresh Status", "callback_data": f"check_order_{order_id}"}],
                    [{"text": "🌐 View on Website", "callback_data": f"view_order_{order_id}"}]
                ])
                
                send_telegram_message_with_keyboard(chat_id, status_update, status_keyboard)
                
            # Handle other callback queries...
            # Additional callback handlers would be implemented here
                
            else:
                # Default response for unknown callback data
                unknown_callback_message = (
                    "Sorry, I don't understand that action. Please try again or use the main menu."
                )
                
                keyboard = create_telegram_keyboard([
                    ["📱 Connect Account"],
                    ["📊 My Orders", "🚀 My Jobs"],
                    ["💼 Account"]
                ])
                
                send_telegram_message_with_keyboard(chat_id, unknown_callback_message, keyboard)
    except Exception as e:
        logging.error(f"Error handling Telegram update: {str(e)}")
        logging.error(traceback.format_exc())

# Telegram polling function to keep bot running
def start_telegram_polling():
    """Continuously poll for Telegram updates"""
    logging.info("Starting Telegram polling...")
    last_update_id = 0
    
    # Send startup notification to admin
    startup_message = (
        "🤖 *SMM Automation Bot Starting*\n\n"
        f"Bot started at: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n"
        "The bot is now online and ready to receive commands."
    )
    notify_admin(startup_message)
    
    while True:
        try:
            # Get updates from Telegram
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
            params = {
                "offset": last_update_id + 1,
                "timeout": 30
            }
            
            response = requests.get(url, params=params, timeout=31)
            
            if response.status_code == 200:
                data = response.json()
                if data["ok"] and data["result"]:
                    for update in data["result"]:
                        # Process each update
                        update_id = update["update_id"]
                        if update_id > last_update_id:
                            last_update_id = update_id
                        
                        # Handle the update
                        handle_telegram_update(update)
            
            # Sleep to avoid hitting Telegram's rate limits
            time.sleep(1)
            
        except Exception as e:
            logging.error(f"Error in Telegram polling: {str(e)}")
            logging.error(traceback.format_exc())
            time.sleep(5)  # Wait a bit longer on error

# Function to start all background processes
def start_bot():
    # Start the background job thread
    job_thread = threading.Thread(target=process_automation_jobs)
    job_thread.daemon = True
    job_thread.start()
    
    # Start the Telegram polling thread
    telegram_thread = threading.Thread(target=start_telegram_polling)
    telegram_thread.daemon = True
    telegram_thread.start()
    
    logging.info("Bot background processes started!")
    
    return job_thread, telegram_thread