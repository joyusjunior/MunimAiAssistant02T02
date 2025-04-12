import os
import logging
import json
import tempfile
import atexit
import glob
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, send_file, session
from utils.conversation_processor import process_message, get_session_state
from utils.data_manager import get_invoice_by_id, generate_invoice_pdf, get_expense_summary, generate_expense_summary_pdf
from utils.session_manager import create_session, get_session, update_session, clean_expired_sessions

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Create the app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "munim_ai_secret_key")
app.config['SESSION_TYPE'] = 'filesystem'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)

# Ensure data directory exists
os.makedirs("data", exist_ok=True)

# Initialize JSON files if they don't exist
def initialize_json_files():
    files = {
        "data/invoices.json": {"invoices": []},
        "data/transactions.json": {"transactions": []},
        "data/ledgers.json": {"ledgers": {}}
    }
    
    for file_path, initial_data in files.items():
        if not os.path.exists(file_path):
            with open(file_path, 'w') as f:
                json.dump(initial_data, f, indent=4)

initialize_json_files()

# Function to clean up temporary PDF files
def cleanup_temp_files():
    """Remove any temporary PDF files created by the application."""
    try:
        temp_dir = tempfile.gettempdir()
        for temp_file in glob.glob(os.path.join(temp_dir, "*.pdf")):
            try:
                os.remove(temp_file)
                logging.debug(f"Cleaned up temporary file: {temp_file}")
            except Exception as e:
                logging.error(f"Failed to remove temporary file {temp_file}: {str(e)}")
    except Exception as e:
        logging.error(f"Error during cleanup: {str(e)}")

# Register the cleanup function to run when the application exits
atexit.register(cleanup_temp_files)

# Cleanup expired sessions every hour (run in background in production)
def cleanup_sessions_task():
    """Scheduled task to clean up expired sessions."""
    count = clean_expired_sessions()
    logger.info(f"Cleaned up {count} expired sessions")

@app.before_request
def handle_session():
    """Make sure a valid session ID exists."""
    # Check if the request is for the API endpoint
    if request.endpoint == 'handle_message':
        # Ensure session_id exists and is valid
        session_id = request.json.get('session_id')
        if not session_id or get_session(session_id) is None:
            session_id = create_session()
            # Add the session_id to the request for processing
            if not hasattr(request, 'custom_data'):
                request.custom_data = {}
            request.custom_data['session_id'] = session_id

@app.route('/')
def index():
    """Render the main chat interface."""
    # Clean up old sessions periodically when users visit the site
    if datetime.now().minute % 10 == 0:  # Every 10 minutes
        cleanup_sessions_task()
    return render_template('index.html')

@app.route('/api/message', methods=['POST'])
def handle_message():
    """Process incoming messages and return the bot's response."""
    try:
        user_message = request.json.get('message', '')
        if not user_message:
            return jsonify({'error': 'No message provided'}), 400
        
        # Get session ID from request
        session_id = request.json.get('session_id')
        if not session_id or get_session(session_id) is None:
            # Create new session if needed
            session_id = create_session()
        
        # Process the message with session context
        response, new_session_id, new_session_state = process_message(
            user_message, 
            session_id
        )
        
        # Return both the response and the session information
        return jsonify({
            'response': response, 
            'session_id': new_session_id,
            'session_state': new_session_state
        })
    
    except Exception as e:
        logger.error(f"Error processing message: {str(e)}")
        return jsonify({'error': 'An error occurred processing your request'}), 500
        
@app.route('/api/session_state', methods=['GET'])
def session_state():
    """Return the current session state."""
    try:
        session_id = request.args.get('session_id')
        if not session_id:
            return jsonify({'error': 'No session ID provided'}), 400
            
        # Get session information
        state = get_session_state(session_id)
        if state is None:
            return jsonify({'error': 'Invalid session ID'}), 404
            
        return jsonify(state)
        
    except Exception as e:
        logger.error(f"Error retrieving session state: {str(e)}")
        return jsonify({'error': 'An error occurred retrieving session state'}), 500
        
@app.route('/download_invoice/<invoice_id>', methods=['GET'])
def download_invoice(invoice_id):
    """Generate and download an invoice PDF."""
    try:
        # Get the invoice data
        invoice = get_invoice_by_id(invoice_id)
        if not invoice:
            return "Invoice not found", 404
            
        # Generate the PDF
        pdf_path = generate_invoice_pdf(invoice)
        if not pdf_path:
            return "Failed to generate PDF", 500
            
        # Determine filename for download
        filename = f"Invoice_{invoice_id}.pdf"
        
        # Send the file for download and then remove it after sending
        return send_file(
            pdf_path,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=filename
        )
    
    except Exception as e:
        logger.error(f"Error downloading invoice: {str(e)}")
        return f"Error: {str(e)}", 500

@app.route('/download_expense_summary', methods=['GET'])
def download_expense_summary():
    """Generate and download an expense summary PDF."""
    try:
        # Get period parameters
        period = request.args.get('period', None)
        start_date = request.args.get('start_date', None)
        end_date = request.args.get('end_date', None)
        
        # Create period description text
        if start_date and end_date:
            period_text = f"From {start_date} to {end_date}"
        elif period:
            period_map = {
                'today': 'Today',
                'week': 'This Week',
                'month': 'This Month'
            }
            period_text = period_map.get(period, 'All Time')
        else:
            period_text = 'All Time'
            
        # Get the expense summary data
        summary = get_expense_summary(period, start_date, end_date)
        if not summary:
            return "No expense data found for the specified period", 404
            
        # Generate the PDF
        pdf_filename = generate_expense_summary_pdf(summary, period_text)
        if not pdf_filename:
            return "Failed to generate PDF", 500
            
        # Determine filepath
        pdf_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'downloads', pdf_filename)
        
        # Send the file for download
        return send_file(
            pdf_path,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"Expense_Summary_{datetime.now().strftime('%Y%m%d')}.pdf"
        )
    
    except Exception as e:
        logger.error(f"Error downloading expense summary: {str(e)}")
        return f"Error: {str(e)}", 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
