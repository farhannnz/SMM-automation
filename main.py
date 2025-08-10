#!/usr/bin/env python3
import os
import logging
import threading
from datetime import datetime

# Configure logging for the main process
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[logging.FileHandler(f"logs/run_{datetime.now().strftime('%Y-%m-%d')}.log")]
)

# Create all necessary directories first
for directory in ['logs', 'data', 'data/temp']:
    if not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)
        logging.info(f"Created directory: {directory}")

# Import modules (import config first!)
import config
from bot import start_bot
from app import app, initialize_app

if __name__ == "__main__":
    print("=" * 50)
    print("Starting SMM Automation System")
    print("=" * 50)
    
    # Load data
    config.load_data()
    logging.info(f"Data loaded successfully. Background jobs: {len(config.background_jobs)}")
    
    # Initialize app (ensure admin user exists)
    initialize_app()
    logging.info("App initialized successfully")
    
    # Start bot services
    print("Starting bot services...")
    job_thread, telegram_thread = start_bot()
    logging.info("Bot services started")
    
    # Run Flask app
    print("Starting web server...")
    logging.info("Starting web server")
    
    # You can modify these settings as needed
    host = '0.0.0.0'  # Listen on all interfaces
    port = 5000
    debug = False     # Set to False in production
    
    print(f"Web server running at http://{host}:{port}")
    print("Press Ctrl+C to stop")
    
    try:
        app.run(debug=debug, host=host, port=port)
    except KeyboardInterrupt:
        print("\nShutting down...")
        logging.info("Shutdown initiated by user (KeyboardInterrupt)")
    except Exception as e:
        print(f"\nError: {str(e)}")
        logging.error(f"Error running web server: {str(e)}")
    
    print("Shutdown complete")
    logging.info("Application shutdown complete")