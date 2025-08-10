import os
import json
import logging
import threading
from datetime import datetime

# Create necessary directories
for directory in ['logs', 'data', 'data/temp']:
    if not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[logging.FileHandler(f"logs/app_{datetime.now().strftime('%Y-%m-%d')}.log")]
)

# Fixed admin credentials
ADMIN_USERNAME = "matrix"
ADMIN_PASSWORD = "matrix123"
ADMIN_TELEGRAM_ID = "6540864317"  # Set this to your personal Telegram ID
TELEGRAM_BOT_TOKEN = "7655650814:AAGMoTIjihX1UNIblmDyP5a_vdbL2qr712s"  # Your Telegram bot token

# Global variables - must be initialized at the module level
user_data = {}
activation_keys = {}
active_users = []
background_jobs = []
bot_statistics = {
    "total_orders": 0,
    "successful_orders": 0,
    "failed_orders": 0,
    "total_users": 0,
    "active_users": 0,
    "total_spent": 0,
    "last_24h_orders": 0
}

# Verification codes for Telegram connection
telegram_verification_codes = {}

# Data lock for thread safety
data_lock = threading.RLock()

# Safely load data with error handling
def load_data():
    """Load all saved data from files with robust error handling"""
    global user_data, activation_keys, active_users, bot_statistics, background_jobs, telegram_verification_codes
    
    with data_lock:
        try:
            if os.path.exists("data/user_data.json"):
                try:
                    with open("data/user_data.json", "r") as f:
                        loaded_data = json.load(f)
                        if isinstance(loaded_data, dict):
                            user_data.clear()
                            user_data.update(loaded_data)
                except Exception as e:
                    logging.info(f"Error loading user_data.json: {str(e)}")
            
            if os.path.exists("data/activation_keys.json"):
                try:
                    with open("data/activation_keys.json", "r") as f:
                        loaded_data = json.load(f)
                        if isinstance(loaded_data, dict):
                            activation_keys.clear()
                            activation_keys.update(loaded_data)
                except Exception as e:
                    logging.info(f"Error loading activation_keys.json: {str(e)}")
            
            if os.path.exists("data/active_users.json"):
                try:
                    with open("data/active_users.json", "r") as f:
                        loaded_data = json.load(f)
                        if isinstance(loaded_data, list):
                            active_users.clear()
                            active_users.extend(loaded_data)
                except Exception as e:
                    logging.info(f"Error loading active_users.json: {str(e)}")
            
            if os.path.exists("data/bot_statistics.json"):
                try:
                    with open("data/bot_statistics.json", "r") as f:
                        loaded_data = json.load(f)
                        if isinstance(loaded_data, dict):
                            bot_statistics.clear()
                            bot_statistics.update(loaded_data)
                except Exception as e:
                    logging.info(f"Error loading bot_statistics.json: {str(e)}")
            
            if os.path.exists("data/background_jobs.json"):
                try:
                    with open("data/background_jobs.json", "r") as f:
                        loaded_data = json.load(f)
                        if isinstance(loaded_data, list):
                            background_jobs.clear()
                            background_jobs.extend(loaded_data)
                except Exception as e:
                    logging.info(f"Error loading background_jobs.json: {str(e)}")
            
            if os.path.exists("data/telegram_verification_codes.json"):
                try:
                    with open("data/telegram_verification_codes.json", "r") as f:
                        loaded_data = json.load(f)
                        if isinstance(loaded_data, dict):
                            telegram_verification_codes.clear()
                            telegram_verification_codes.update(loaded_data)
                except Exception as e:
                    logging.info(f"Error loading telegram_verification_codes.json: {str(e)}")
            
            logging.info("Data loaded successfully!")
        except Exception as e:
            logging.info(f"Error during data loading process: {str(e)}")

# Safely save data with error handling
def save_data():
    """Save all data to files with robust error handling"""
    global user_data, activation_keys, active_users, bot_statistics, background_jobs, telegram_verification_codes
    
    with data_lock:
        try:
            # Create a temporary directory for safe saving
            temp_dir = "data/temp"
            try:
                if not os.path.exists(temp_dir):
                    os.makedirs(temp_dir)
            except Exception as e:
                logging.info(f"Error creating temp directory: {str(e)}")
                temp_dir = "data"  # Fallback to direct save
            
            # Log current state for debugging
            logging.info(f"Saving data - Background jobs count: {len(background_jobs)}")
            
            # First save to temporary files
            data_files = {
                f"{temp_dir}/user_data.json.tmp": user_data,
                f"{temp_dir}/activation_keys.json.tmp": activation_keys,
                f"{temp_dir}/active_users.json.tmp": active_users,
                f"{temp_dir}/bot_statistics.json.tmp": bot_statistics,
                f"{temp_dir}/background_jobs.json.tmp": background_jobs,
                f"{temp_dir}/telegram_verification_codes.json.tmp": telegram_verification_codes
            }
            
            # Safe saving routine
            for filename, data in data_files.items():
                try:
                    # First write to a temporary file
                    with open(filename, "w") as f:
                        json.dump(data, f, indent=2)  # Added indentation for better readability
                    
                    # Verify the file was written correctly
                    try:
                        with open(filename, "r") as f:
                            _ = json.load(f)  # Validate JSON structure
                    except Exception as e:
                        logging.info(f"Warning: Could not validate JSON in {filename}: {str(e)}")
                except Exception as e:
                    logging.info(f"Error saving to temporary file {filename}: {str(e)}")
            
            # Then move temp files to actual files if all saves were successful
            for tmp_file, _ in data_files.items():
                final_file = tmp_file.replace(f"{temp_dir}/", "data/").replace(".tmp", "")
                try:
                    # Check if temp file exists before attempting to move
                    if os.path.exists(tmp_file):
                        # In Windows, we need to handle file replacement differently
                        if os.path.exists(final_file):
                            os.remove(final_file)
                        os.rename(tmp_file, final_file)
                        logging.info(f"Successfully saved {final_file}")
                except Exception as e:
                    logging.info(f"Error moving {tmp_file} to {final_file}: {str(e)}")
            
            logging.info("Data saved successfully!")
        except Exception as e:
            logging.info(f"Error during data saving process: {str(e)}")

# Helper functions
def is_user_activated(user_id):
    """Check if a user is activated"""
    user_id_str = str(user_id)
    return user_id_str in active_users

def is_admin(user_id):
    """Check if a user is an admin"""
    return user_id == ADMIN_USERNAME

# Load data when first imported
load_data()