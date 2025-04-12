"""
Conversation processor for Munim AI that interprets user messages 
and manages multi-step conversations for financial tasks.
"""
import logging
import json
import re
from datetime import datetime, timedelta
from utils.session_manager import (
    SessionState, 
    get_session, 
    update_session,
    get_session_data,
    clear_session_data,
    create_session
)
from utils.data_manager import (
    create_invoice, 
    record_transaction, 
    get_ledger, 
    format_amount,
    format_date,
    get_expense_summary,
    get_invoice_by_id,
    format_invoice_html,
    parse_direct_command,
    get_financial_report,
    format_financial_report_html
)
from utils.tax_advisor import process_tax_query, is_tax_query

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Define conversation steps for different processes
INVOICE_STEPS = [
    "recipient",          # Who is the invoice for?
    "recipient_gst",      # What is the recipient's GST number? (optional)
    "items",              # What items/services are being invoiced?
    "place_of_supply",    # What is the place of supply? (for GST)
    "sender_gst",         # What is your GST number? (optional)
    "confirm"             # Confirm invoice details
]

EXPENSE_STEPS = [
    "amount",             # What is the expense amount?
    "date",               # When was the expense incurred?
    "category",           # What category does this expense fall under?
    "vendor",             # Who was this expense paid to? (optional)
    "notes",              # Any additional notes? (optional)
    "confirm"             # Confirm expense details
]

PAYMENT_STEPS = [
    "from_party",         # Who is the payment from?
    "amount",             # What is the payment amount?
    "date",               # When was the payment received?
    "notes",              # Any additional notes? (optional)
    "confirm"             # Confirm payment details
]

def process_message(message, session_id):
    """
    Process a user message with session context and determine the appropriate action.
    Returns a tuple of (response, session_id, session_state)
    """
    try:
        # Check for global exit/cancel command first
        if message.lower() in ["cancel", "exit", "quit", "stop", "end"]:
            # Clear the session state and data
            if session_id:
                update_session(session_id, state=SessionState.IDLE)
                clear_session_data(session_id)
            return (
                "I've cancelled what we were working on. How else can I help you today?",
                session_id,
                SessionState.IDLE
            )
        
        # Get the current session
        session = get_session(session_id)
        if not session:
            # If session is invalid, create a new one
            session_id = create_session()
            session = get_session(session_id)
            
        current_state = session.get("state", SessionState.IDLE)
        
        # Process based on current state
        if current_state == SessionState.IDLE:
            # Initial commands - determine intent
            return process_initial_command(message, session_id)
        
        elif current_state == SessionState.INVOICE_CREATION:
            # Continue invoice creation flow
            return process_invoice_step(message, session_id)
            
        elif current_state == SessionState.EXPENSE_RECORDING:
            # Continue expense recording flow
            return process_expense_step(message, session_id)
            
        elif current_state == SessionState.PAYMENT_RECORDING:
            # Continue payment recording flow
            return process_payment_step(message, session_id)
            
        elif current_state == SessionState.LEDGER_MANAGEMENT:
            # Continue ledger management flow
            return process_ledger_step(message, session_id)
            
        else:
            # Reset to idle if state is unknown
            update_session(session_id, state=SessionState.IDLE)
            return (
                "I'm not sure what we were working on. How can I help you today?",
                session_id,
                SessionState.IDLE
            )
            
    except Exception as e:
        logger.error(f"Error processing message: {str(e)}")
        # Reset to idle state on error
        if session_id:
            update_session(session_id, state=SessionState.IDLE)
        
        return (
            "Sorry, I had trouble processing that request. Could you try again with different wording?",
            session_id,
            SessionState.IDLE
        )

def process_initial_command(message, session_id):
    """
    Process a message when no conversation is in progress.
    Determines the user's intent and starts the appropriate flow or executes a one-time command.
    """
    message_lower = message.lower()
    
    # Check for invoice creation intent
    if "create invoice" in message_lower or "new invoice" in message_lower or "generate invoice" in message_lower:
        # Start invoice creation flow with a simplified flow path
        # Clear any existing session data to avoid contamination
        clear_session_data(session_id)
        # Set up the flow with distinct steps - no circular dependencies
        update_session(session_id, state=SessionState.INVOICE_CREATION, data={
            "current_step": "recipient",
            "flow_path": ["recipient", "recipient_gst", "sender_gst", "place_of_supply", "items", "confirm"]
        })
        return (
            "Let's create a GST-compliant invoice. First, who is this invoice for? Please provide the business or individual name.\n\n<em>You can type 'cancel' or 'exit' at any time to stop creating this invoice.</em>",
            session_id,
            SessionState.INVOICE_CREATION
        )
    
    # Check for expense recording intent
    elif "record expense" in message_lower or "add expense" in message_lower or "new expense" in message_lower:
        # Start expense recording flow
        update_session(session_id, state=SessionState.EXPENSE_RECORDING, data={"current_step": "amount"})
        return (
            "Let's record an expense. How much was spent? Please include the amount with the ₹ symbol (e.g., ₹1,500).\n\n<em>You can type 'cancel' or 'exit' at any time to stop recording this expense.</em>",
            session_id,
            SessionState.EXPENSE_RECORDING
        )
    
    # Check for payment recording intent
    elif "record payment" in message_lower or "payment received" in message_lower or "add payment" in message_lower:
        # Start payment recording flow
        update_session(session_id, state=SessionState.PAYMENT_RECORDING, data={"current_step": "from_party"})
        return (
            "Let's record a payment received. Who made this payment? Please provide the business or individual name.\n\n<em>You can type 'cancel' or 'exit' at any time to stop recording this payment.</em>",
            session_id,
            SessionState.PAYMENT_RECORDING
        )
    
    # Check for ledger viewing intent (one-time command)
    elif "show ledger" in message_lower or "view ledger" in message_lower:
        return process_ledger_command(message, session_id)
    
    # Check for expense summary intent (one-time command)
    elif "expense summary" in message_lower or "show expenses" in message_lower:
        return process_expense_summary_command(message, session_id)
    
    # Check for invoice viewing intent (one-time command)
    elif "show invoice" in message_lower or "view invoice" in message_lower:
        return process_view_invoice_command(message, session_id)
    
    # Check for menu or help request
    elif message_lower == "menu":
        return (
            generate_menu(),
            session_id,
            SessionState.IDLE
        )
    elif message_lower == "help" or message_lower == "?":
        return (
            generate_help_message(),
            session_id,
            SessionState.IDLE
        )
    
    # Check for financial report requests
    elif "financial report" in message_lower or "financial summary" in message_lower:
        return process_financial_report_command(message, session_id)
    
    # Check for tax and GST-related queries
    elif is_tax_query(message):
        # Process the tax query through our tax advisory module
        tax_response = process_tax_query(message)
        return (
            tax_response,
            session_id,
            SessionState.IDLE
        )
    
    # Default response for unrecognized commands
    else:
        # Try to match with various patterns using the natural language parser
        
        # Check for invoice pattern
        if (re.search(r'invoice to|invoice for|create invoice', message_lower) and 
            re.search(r'₹\s*[\d,]+', message_lower)):
            # This looks like a one-line invoice command, process it directly
            return process_direct_invoice_command(message, session_id)
        
        # Check for expense pattern
        elif (re.search(r'(?:expense|spent|paid|bill|purchase)', message_lower) and 
              re.search(r'(?:₹|rs\.?|inr|rupees?)\s*[\d,]+', message_lower)):
            # This looks like a one-line expense command, process it directly
            return process_direct_expense_command(message, session_id)
        
        # Check for payment/income pattern
        elif (re.search(r'(?:payment|received|collected|earned|income)', message_lower) and 
              re.search(r'(?:₹|rs\.?|inr|rupees?)\s*[\d,]+', message_lower)):
            # This looks like a one-line payment command, process it directly
            return process_direct_payment_command(message, session_id)
        
        # If none of the patterns match, use the more flexible direct command parser
        else:
            # Try to parse as a direct expense command
            parsed_expense = parse_direct_command(message, "expense")
            if parsed_expense and parsed_expense.get("amount"):
                # Process the parsed expense data
                return process_parsed_direct_command(parsed_expense, session_id)
            
            # Try to parse as a direct income/payment command
            parsed_income = parse_direct_command(message, "income")
            if parsed_income and parsed_income.get("amount"):
                # Process the parsed income data
                return process_parsed_direct_command(parsed_income, session_id)
            
            # No intent recognized, show help message
            return (
                "I'm not sure what you'd like to do. Try these commands:\n\n" +
                "• \"Create invoice\" - Start creating a GST invoice\n" +
                "• \"Record expense\" - Record a business expense\n" +
                "• \"Record payment\" - Record a payment received\n" +
                "• \"Show ledger of [name]\" - View a party's ledger\n" +
                "• \"Expense summary\" - Get your expense breakdown\n" +
                "• \"Financial report\" - Get detailed financial reports\n\n" +
                "Or use natural language like \"Spent ₹500 on office supplies yesterday\" or \"Received ₹1,000 from Client XYZ for website work\".\n\n" +
                "Type \"menu\" to see all options.",
                session_id,
                SessionState.IDLE
            )

def process_invoice_step(message, session_id):
    """Process a step in the invoice creation conversation flow"""
    session_data = get_session_data(session_id)
    if not session_data:
        # If session data is None (which could happen if session expired)
        update_session(session_id, state=SessionState.IDLE)
        return (
            "I lost track of our conversation. Let's start over. What would you like to do?",
            session_id,
            SessionState.IDLE
        )
        
    current_step = session_data.get("current_step", "recipient")
    # Get the flow path or create a default one
    flow_path = session_data.get("flow_path", ["recipient", "recipient_gst", "sender_gst", "place_of_supply", "items", "confirm"])
    
    # Special case for exiting the flow
    if message.lower() in ["cancel", "exit", "quit", "stop"]:
        update_session(session_id, state=SessionState.IDLE)
        clear_session_data(session_id)
        return (
            "Invoice creation cancelled. Is there anything else I can help you with?",
            session_id,
            SessionState.IDLE
        )
    
    # Process the current step
    if current_step == "recipient":
        # Store recipient name
        update_session(session_id, data={"recipient": message.strip(), "current_step": "recipient_gst"})
        return (
            f"Adding invoice for {message.strip()}. What is their GST number? (Type 'skip' if not applicable)",
            session_id,
            SessionState.INVOICE_CREATION
        )
    
    elif current_step == "recipient_gst":
        # Handle skipping GST number
        if message.lower() == "skip":
            update_session(session_id, data={"current_step": "sender_gst"})
            return (
                "What is your business GST number? (Type 'skip' if not applicable)",
                session_id,
                SessionState.INVOICE_CREATION
            )
        else:
            # Validate GST number format
            gst_match = re.match(r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[0-9A-Z]{1}[Z]{1}[0-9A-Z]{1}$', message.strip())
            if not gst_match:
                return (
                    """<div style='border: 1px solid #e0e0e0; padding: 12px; border-radius: 8px; background-color: #f9f9f9;'>
                    <p><strong>The GST number doesn't appear to be valid.</strong></p>
                    <p>A valid GST number follows this format: <code>29ABCDE1234F1Z5</code></p>
                    <p>GST numbers have 15 characters:</p>
                    <ul style='margin-left: 15px; padding-left: 5px;'>
                      <li>First 2 digits: State code</li>
                      <li>Next 10 characters: PAN number</li>
                      <li>Next 1 digit: Entity number</li>
                      <li>Next 1 character: Z (fixed)</li>
                      <li>Last 1 character: Check code</li>
                    </ul>
                    <p>Please enter a valid GST number or type 'skip' to continue without it.</p>
                    </div>""",
                    session_id,
                    SessionState.INVOICE_CREATION
                )
            update_session(session_id, data={"recipient_gst": message.strip(), "current_step": "sender_gst"})
            return (
                "What is your business GST number? (Type 'skip' if not applicable)",
                session_id,
                SessionState.INVOICE_CREATION
            )
    
    elif current_step == "sender_gst":
        if message.lower() == "skip":
            update_session(session_id, data={"current_step": "place_of_supply"})
        else:
            # Validate GST number format
            gst_match = re.match(r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[0-9A-Z]{1}[Z]{1}[0-9A-Z]{1}$', message.strip())
            if not gst_match:
                return (
                    "That doesn't look like a valid GST number. Please provide a valid GST number in the format like 29ABCDE1234F1Z5, or type 'skip'.",
                    session_id,
                    SessionState.INVOICE_CREATION
                )
            update_session(session_id, data={"sender_gst": message.strip(), "current_step": "place_of_supply"})
        
        return (
            "What is the place of supply? (State name or code where the service is consumed, important for GST calculation)",
            session_id,
            SessionState.INVOICE_CREATION
        )
        
    elif current_step == "place_of_supply":
        update_session(session_id, data={"place_of_supply": message.strip(), "current_step": "items"})
        
        return (
            "Now, please list the items or services with their amounts.\nExample: \"Website design ₹10,000, Hosting ₹5,000\"\nOr simply enter a single service like \"Professional Services ₹15,000\"",
            session_id,
            SessionState.INVOICE_CREATION
        )
    
    elif current_step == "items":
        # Process items with amounts
        items = []
        amounts = re.findall(r'([\w\s]+)\s*(₹\s*[\d,]+(?:\.\d+)?)', message)
        
        if not amounts:
            # If no pattern matches, see if there's a single amount
            amount_match = re.search(r'(₹\s*[\d,]+(?:\.\d+)?)', message)
            if amount_match:
                # There's an amount but no clear item name, use a default or the full message
                amount = amount_match.group(1).strip()
                item_name = "Professional Services"
                
                # Try to extract a better description from the message
                text_parts = message.split(amount)
                if len(text_parts) > 0 and text_parts[0].strip():
                    # If there's text before the amount, use it as the service description
                    item_name = text_parts[0].strip()
                elif len(text_parts) > 1 and text_parts[1].strip():
                    # If there's text after the amount, use it as the service description
                    description_match = re.search(r'^\s*for\s+(.+)$', text_parts[1].strip(), re.IGNORECASE)
                    if description_match:
                        item_name = description_match.group(1).strip()
                
                # Detect common IT services and assign appropriate HSN code
                hsn_code = "9983"  # Default IT consulting service
                if "website" in item_name.lower() or "web" in item_name.lower():
                    hsn_code = "9983"  # Web portal design and development services
                elif "software" in item_name.lower() or "app" in item_name.lower():
                    hsn_code = "9983"  # Software development services
                elif "consult" in item_name.lower() or "advisory" in item_name.lower():
                    hsn_code = "9983"  # Management consultancy services 
                elif "design" in item_name.lower() or "graphic" in item_name.lower():
                    hsn_code = "9983"  # Graphic design services
                elif "marketing" in item_name.lower() or "seo" in item_name.lower():
                    hsn_code = "9983"  # Marketing/advertising services
                    
                items.append({
                    "name": item_name,
                    "amount": amount,
                    "gst_rate": 18,  # Default GST rate
                    "hsn_code": hsn_code,
                    "quantity": 1,
                    "unit": "Service"
                })
            else:
                return (
                    "I couldn't understand the items and amounts. Please list services with amounts, like \"Website design ₹10,000\" or \"Professional Services ₹15,000\".",
                    session_id,
                    SessionState.INVOICE_CREATION
                )
        else:
            # Process each item-amount pair
            for item_text, amount in amounts:
                item_name = item_text.strip()
                # Detect common IT services and assign appropriate HSN code for the item
                hsn_code = "9983"  # Default IT consulting service
                if "website" in item_name.lower() or "web" in item_name.lower():
                    hsn_code = "9983"  # Web portal design and development services
                elif "software" in item_name.lower() or "app" in item_name.lower():
                    hsn_code = "9983"  # Software development services
                elif "consult" in item_name.lower() or "advisory" in item_name.lower():
                    hsn_code = "9983"  # Management consultancy services 
                elif "design" in item_name.lower() or "graphic" in item_name.lower():
                    hsn_code = "9983"  # Graphic design services
                elif "marketing" in item_name.lower() or "seo" in item_name.lower():
                    hsn_code = "9983"  # Marketing/advertising services
                
                items.append({
                    "name": item_name,
                    "amount": amount,
                    "gst_rate": 18,  # Default GST rate
                    "hsn_code": hsn_code,
                    "quantity": 1,
                    "unit": "Service"
                })
        
        # Store items and move to confirm step directly (breaking the circular reference)
        update_session(session_id, data={"items": items, "current_step": "confirm"})
        
        # Prepare confirmation message with all collected information
        data = get_session_data(session_id)
        confirmation = "<strong>Please confirm these invoice details:</strong><br><br>"
        confirmation += f"<strong>Recipient:</strong> {data.get('recipient', 'Not specified')}<br>"
        
        if data.get('recipient_gst'):
            confirmation += f"<strong>Recipient GST:</strong> {data.get('recipient_gst')}<br>"
            
        confirmation += f"<strong>Place of Supply:</strong> {data.get('place_of_supply', 'Not specified')}<br>"
        
        if data.get('sender_gst'):
            confirmation += f"<strong>Sender GST:</strong> {data.get('sender_gst')}<br>"
            
        confirmation += "<br><strong>Items:</strong><br>"
        total_amount = 0
        for item in data.get('items', []):
            # Clean amount string and extract the number
            amount_str = item.get('amount', '₹0').replace('₹', '').replace(',', '').strip()
            try:
                amount_value = float(amount_str)
                total_amount += amount_value
            except ValueError:
                amount_value = 0
                
            confirmation += f"- {item.get('name', 'Unknown')} ({item.get('amount', '₹0')})<br>"
            
        confirmation += f"<br><strong>Total Amount:</strong> ₹{total_amount:.2f}<br>"
        confirmation += f"<strong>GST (18%):</strong> ₹{total_amount * 0.18:.2f}<br>"
        confirmation += f"<strong>Total with GST:</strong> ₹{total_amount * 1.18:.2f}<br><br>"
        
        confirmation += "Reply with 'confirm' to create this invoice, or 'edit' to make changes."
        
        return (
            confirmation,
            session_id,
            SessionState.INVOICE_CREATION
        )
    
# We removed this duplicate block to fix the loop - the handler above already processes this step
    
    elif current_step == "sender_gst":
        # Handle skipping sender GST
        if message.lower() == "skip":
            update_session(session_id, data={"current_step": "confirm"})
        else:
            # Validate GST number format
            gst_match = re.match(r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[0-9A-Z]{1}[Z]{1}[0-9A-Z]{1}$', message.strip())
            if not gst_match:
                return (
                    "That doesn't look like a valid GST number. Please provide a valid GST number in the format like 29ABCDE1234F1Z5, or type 'skip'.",
                    session_id,
                    SessionState.INVOICE_CREATION
                )
            update_session(session_id, data={"sender_gst": message.strip(), "current_step": "confirm"})
        
        # Prepare confirmation message with all collected information
        data = get_session_data(session_id)
        confirmation = "<strong>Please confirm these invoice details:</strong><br><br>"
        confirmation += f"<strong>Recipient:</strong> {data.get('recipient', 'Not specified')}<br>"
        
        if data.get('recipient_gst'):
            confirmation += f"<strong>Recipient GST:</strong> {data.get('recipient_gst')}<br>"
            
        confirmation += f"<strong>Place of Supply:</strong> {data.get('place_of_supply', 'Not specified')}<br>"
        
        if data.get('sender_gst'):
            confirmation += f"<strong>Sender GST:</strong> {data.get('sender_gst')}<br>"
            
        confirmation += "<br><strong>Items:</strong><br>"
        total_amount = 0
        for item in data.get('items', []):
            # Clean amount string and extract the number
            amount_str = item.get('amount', '₹0').replace('₹', '').replace(',', '').strip()
            try:
                amount_value = float(amount_str)
                total_amount += amount_value
            except:
                # If conversion fails, just display the original string
                pass
                
            confirmation += f"• {item.get('name', 'Item')}: {item.get('amount', '₹0')} + {item.get('gst_rate', 18)}% GST<br>"
            
        confirmation += f"<br><strong>Estimated Total:</strong> ₹{total_amount:,.2f} plus applicable GST<br><br>"
        confirmation += "Reply with 'confirm' to create this invoice, or 'edit' to make changes."
        
        return (
            confirmation,
            session_id,
            SessionState.INVOICE_CREATION
        )
    
    elif current_step == "confirm":
        if message.lower() == "confirm":
            # Process the collected information to create the invoice
            data = get_session_data(session_id)
            
            try:
                # Extract all required fields from session data
                # Enhance additional details with seller state
                additional_details = {
                    "seller_state": "Delhi",  # Default seller state
                    "invoice_date": datetime.now().strftime("%Y-%m-%d"),
                    "due_date": (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
                    "invoice_notes": "Thank you for your business!"
                }
                
                # Extract seller state from seller GST if possible
                if data.get('sender_gst') and len(data.get('sender_gst', '')) >= 2:
                    # First 2 digits of GST are state code
                    state_code = data.get('sender_gst')[:2]
                    # Map state code to state name (simplified version)
                    state_map = {
                        "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", 
                        "04": "Chandigarh", "05": "Uttarakhand", "06": "Haryana", 
                        "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh", 
                        "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh", 
                        "13": "Nagaland", "14": "Manipur", "15": "Mizoram", 
                        "16": "Tripura", "17": "Meghalaya", "18": "Assam", 
                        "19": "West Bengal", "20": "Jharkhand", "21": "Odisha", 
                        "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat", 
                        "27": "Maharashtra", "29": "Karnataka", "30": "Goa", 
                        "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry", 
                        "36": "Telangana", "37": "Andhra Pradesh"
                    }
                    additional_details["seller_state"] = state_map.get(state_code, "Delhi")
                
                invoice = create_invoice(
                    recipient=data.get('recipient'),
                    items=data.get('items', []),
                    recipient_gst=data.get('recipient_gst'),
                    sender_gst=data.get('sender_gst'),
                    place_of_supply=data.get('place_of_supply'),
                    # Default values for other fields
                    reverse_charge=False,
                    additional_details=additional_details
                )
                
                if invoice:
                    # Reset session state
                    update_session(session_id, state=SessionState.IDLE)
                    clear_session_data(session_id)
                    
                    # Format success message
                    response = f"✅ Invoice to {data.get('recipient')} created successfully! Invoice #{invoice['id']}<br><br>"
                    response += format_invoice_html(invoice)
                    
                    return (
                        response,
                        session_id,
                        SessionState.IDLE
                    )
                else:
                    return (
                        "I encountered an error creating your invoice. Please try again.",
                        session_id,
                        SessionState.IDLE
                    )
            except Exception as e:
                logger.error(f"Error creating invoice: {str(e)}")
                update_session(session_id, state=SessionState.IDLE)
                clear_session_data(session_id)
                
                return (
                    f"I'm sorry, there was an error creating your invoice: {str(e)}. Please try again.",
                    session_id,
                    SessionState.IDLE
                )
        
        elif message.lower() == "edit":
            # Go back to the beginning of the invoice flow
            update_session(session_id, data={"current_step": "recipient"})
            
            return (
                "Let's start over. Who is this invoice for? Please provide the business or individual name.",
                session_id,
                SessionState.INVOICE_CREATION
            )
        
        else:
            return (
                "Please reply with 'confirm' to create this invoice, or 'edit' to make changes.",
                session_id,
                SessionState.INVOICE_CREATION
            )
    
    # Default response if step is unknown - this should never happen
    # But if it does, reset to idle state instead of looping
    logger.error(f"Unknown invoice step: {current_step}")
    update_session(session_id, state=SessionState.IDLE)
    clear_session_data(session_id)
    return (
        "I'm having trouble with the invoice creation process. Let's try again later. Is there anything else I can help you with?",
        session_id,
        SessionState.IDLE
    )

def process_expense_step(message, session_id):
    """Process a step in the expense recording conversation flow"""
    session_data = get_session_data(session_id)
    current_step = session_data.get("current_step", "amount")
    
    # Special case for exiting the flow
    if message.lower() in ["cancel", "exit", "quit", "stop"]:
        update_session(session_id, state=SessionState.IDLE)
        clear_session_data(session_id)
        return (
            "Expense recording cancelled. Is there anything else I can help you with?",
            session_id,
            SessionState.IDLE
        )
    
    # Process the current step
    if current_step == "amount":
        amount_match = re.search(r'(₹\s*[\d,]+(?:\.\d+)?)', message)
        if not amount_match:
            return (
                "I couldn't understand the amount. Please include an amount with the ₹ symbol, like '₹500'.",
                session_id,
                SessionState.EXPENSE_RECORDING
            )
        
        # Store amount and move to next step
        update_session(session_id, data={"amount": amount_match.group(1).strip(), "current_step": "date"})
        
        return (
            "When was this expense incurred? (Today, Yesterday, or a specific date like 05/04/2025)",
            session_id,
            SessionState.EXPENSE_RECORDING
        )
    
    elif current_step == "date":
        # Parse date input
        date_str = message.strip().lower()
        expense_date = None
        
        if date_str == "today":
            expense_date = datetime.now().strftime("%Y-%m-%d")
        elif date_str == "yesterday":
            expense_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        else:
            # Try to parse various date formats
            date_patterns = [
                (r'(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})', "%Y-%m-%d"),  # DD/MM/YYYY or DD-MM-YYYY
                (r'(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})', "%Y-%m-%d"),  # YYYY/MM/DD or YYYY-MM-DD
            ]
            
            for pattern, date_format in date_patterns:
                match = re.search(pattern, date_str)
                if match:
                    try:
                        if len(match.groups()) == 3:
                            day, month, year = match.groups()
                            if len(year) == 2:
                                year = "20" + year  # Assume 20xx for 2-digit years
                            
                            # Validate day/month values
                            day = int(day)
                            month = int(month)
                            
                            if 1 <= day <= 31 and 1 <= month <= 12:
                                expense_date = f"{year}-{month:02d}-{day:02d}"
                            
                    except ValueError:
                        pass
            
        if not expense_date:
            return (
                "I couldn't understand that date. Please enter 'today', 'yesterday', or a date in the format DD/MM/YYYY.",
                session_id,
                SessionState.EXPENSE_RECORDING
            )
        
        # Store date and move to next step
        update_session(session_id, data={"date": expense_date, "current_step": "category"})
        
        return (
            "What category does this expense fall under? (e.g., Office Supplies, Travel, Rent, Marketing, etc.)",
            session_id,
            SessionState.EXPENSE_RECORDING
        )
    
    elif current_step == "category":
        # Store category and move to next step
        update_session(session_id, data={"category": message.strip(), "current_step": "vendor"})
        
        return (
            "Who was this expense paid to? (Type 'skip' if not applicable)",
            session_id,
            SessionState.EXPENSE_RECORDING
        )
    
    elif current_step == "vendor":
        # Store vendor (or handle skip) and move to next step
        if message.lower() != "skip":
            update_session(session_id, data={"vendor": message.strip()})
        
        update_session(session_id, data={"current_step": "notes"})
        
        return (
            "Any additional notes for this expense? (Type 'skip' if none)",
            session_id,
            SessionState.EXPENSE_RECORDING
        )
    
    elif current_step == "notes":
        # Store notes (or handle skip) and move to confirm step
        if message.lower() != "skip":
            update_session(session_id, data={"notes": message.strip()})
        
        update_session(session_id, data={"current_step": "confirm"})
        
        # Prepare confirmation message
        data = get_session_data(session_id)
        confirmation = "<strong>Please confirm these expense details:</strong><br><br>"
        confirmation += f"<strong>Amount:</strong> {data.get('amount', 'Not specified')}<br>"
        confirmation += f"<strong>Date:</strong> {data.get('date', 'Not specified')}<br>"
        confirmation += f"<strong>Category:</strong> {data.get('category', 'Not specified')}<br>"
        
        if data.get('vendor'):
            confirmation += f"<strong>Paid to:</strong> {data.get('vendor')}<br>"
        
        if data.get('notes'):
            confirmation += f"<strong>Notes:</strong> {data.get('notes')}<br>"
        
        confirmation += "<br>Reply with 'confirm' to record this expense, or 'edit' to make changes."
        
        return (
            confirmation,
            session_id,
            SessionState.EXPENSE_RECORDING
        )
    
    elif current_step == "confirm":
        if message.lower() == "confirm":
            # Process the collected data to record the expense
            data = get_session_data(session_id)
            
            try:
                # Record the transaction
                success = record_transaction(
                    "expense",
                    data.get('vendor'),
                    data.get('amount'),
                    data.get('category'),
                    data.get('date'),
                    data.get('notes')
                )
                
                # Reset session state
                update_session(session_id, state=SessionState.IDLE)
                clear_session_data(session_id)
                
                if success:
                    return (
                        f"✅ Expense of {data.get('amount')} for {data.get('category')} recorded successfully.",
                        session_id,
                        SessionState.IDLE
                    )
                else:
                    return (
                        "I encountered an error recording your expense. Please try again.",
                        session_id,
                        SessionState.IDLE
                    )
            except Exception as e:
                logger.error(f"Error recording expense: {str(e)}")
                update_session(session_id, state=SessionState.IDLE)
                clear_session_data(session_id)
                
                return (
                    f"I'm sorry, there was an error recording your expense: {str(e)}. Please try again.",
                    session_id,
                    SessionState.IDLE
                )
        
        elif message.lower() == "edit":
            # Go back to the beginning of the expense flow
            update_session(session_id, data={"current_step": "amount"})
            
            return (
                "Let's start over. How much was the expense? Please include the amount with the ₹ symbol.",
                session_id,
                SessionState.EXPENSE_RECORDING
            )
        
        else:
            return (
                "Please reply with 'confirm' to record this expense, or 'edit' to make changes.",
                session_id,
                SessionState.EXPENSE_RECORDING
            )
    
    # Default response if step is unknown - this should never happen
    # But if it does, reset to idle state instead of looping
    logger.error(f"Unknown expense step: {current_step}")
    update_session(session_id, state=SessionState.IDLE)
    clear_session_data(session_id)
    return (
        "I'm having trouble with the expense recording process. Let's try again later. Is there anything else I can help you with?",
        session_id,
        SessionState.IDLE
    )

def process_payment_step(message, session_id):
    """Process a step in the payment recording conversation flow"""
    session_data = get_session_data(session_id)
    current_step = session_data.get("current_step", "from_party")
    
    # Special case for exiting the flow
    if message.lower() in ["cancel", "exit", "quit", "stop"]:
        update_session(session_id, state=SessionState.IDLE)
        clear_session_data(session_id)
        return (
            "Payment recording cancelled. Is there anything else I can help you with?",
            session_id,
            SessionState.IDLE
        )
    
    # Process the current step
    if current_step == "from_party":
        # Store the payer's name
        update_session(session_id, data={"from_party": message.strip(), "current_step": "amount"})
        
        return (
            f"How much did {message.strip()} pay? Please include the amount with the ₹ symbol.",
            session_id,
            SessionState.PAYMENT_RECORDING
        )
    
    elif current_step == "amount":
        amount_match = re.search(r'(₹\s*[\d,]+(?:\.\d+)?)', message)
        if not amount_match:
            return (
                "I couldn't understand the amount. Please include an amount with the ₹ symbol, like '₹1,500'.",
                session_id,
                SessionState.PAYMENT_RECORDING
            )
        
        # Store amount and move to next step
        update_session(session_id, data={"amount": amount_match.group(1).strip(), "current_step": "date"})
        
        return (
            "When was this payment received? (Today, Yesterday, or a specific date like 05/04/2025)",
            session_id,
            SessionState.PAYMENT_RECORDING
        )
    
    elif current_step == "date":
        # Parse date input (same logic as expense date parsing)
        date_str = message.strip().lower()
        payment_date = None
        
        if date_str == "today":
            payment_date = datetime.now().strftime("%Y-%m-%d")
        elif date_str == "yesterday":
            payment_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        else:
            # Try to parse various date formats
            date_patterns = [
                (r'(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})', "%Y-%m-%d"),  # DD/MM/YYYY or DD-MM-YYYY
                (r'(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})', "%Y-%m-%d"),  # YYYY/MM/DD or YYYY-MM-DD
            ]
            
            for pattern, date_format in date_patterns:
                match = re.search(pattern, date_str)
                if match:
                    try:
                        if len(match.groups()) == 3:
                            day, month, year = match.groups()
                            if len(year) == 2:
                                year = "20" + year  # Assume 20xx for 2-digit years
                            
                            # Validate day/month values
                            day = int(day)
                            month = int(month)
                            
                            if 1 <= day <= 31 and 1 <= month <= 12:
                                payment_date = f"{year}-{month:02d}-{day:02d}"
                            
                    except ValueError:
                        pass
            
        if not payment_date:
            return (
                "I couldn't understand that date. Please enter 'today', 'yesterday', or a date in the format DD/MM/YYYY.",
                session_id,
                SessionState.PAYMENT_RECORDING
            )
        
        # Store date and move to next step
        update_session(session_id, data={"date": payment_date, "current_step": "notes"})
        
        return (
            "What was this payment for? (Type 'skip' if not applicable)",
            session_id,
            SessionState.PAYMENT_RECORDING
        )
    
    elif current_step == "notes":
        # Store notes (or handle skip) and move to confirm step
        if message.lower() != "skip":
            update_session(session_id, data={"notes": message.strip()})
        
        update_session(session_id, data={"current_step": "confirm"})
        
        # Prepare confirmation message
        data = get_session_data(session_id)
        confirmation = "<strong>Please confirm these payment details:</strong><br><br>"
        confirmation += f"<strong>From:</strong> {data.get('from_party', 'Not specified')}<br>"
        confirmation += f"<strong>Amount:</strong> {data.get('amount', 'Not specified')}<br>"
        confirmation += f"<strong>Date:</strong> {data.get('date', 'Not specified')}<br>"
        
        if data.get('notes'):
            confirmation += f"<strong>Notes:</strong> {data.get('notes')}<br>"
        
        confirmation += "<br>Reply with 'confirm' to record this payment, or 'edit' to make changes."
        
        return (
            confirmation,
            session_id,
            SessionState.PAYMENT_RECORDING
        )
    
    elif current_step == "confirm":
        if message.lower() == "confirm":
            # Process the collected data to record the payment
            data = get_session_data(session_id)
            
            try:
                # Record the transaction as income
                success = record_transaction(
                    "income",
                    data.get('from_party'),
                    data.get('amount'),
                    data.get('notes', "Payment"),
                    data.get('date')
                )
                
                # Reset session state
                update_session(session_id, state=SessionState.IDLE)
                clear_session_data(session_id)
                
                if success:
                    return (
                        f"✅ Payment of {data.get('amount')} from {data.get('from_party')} recorded successfully.",
                        session_id,
                        SessionState.IDLE
                    )
                else:
                    return (
                        "I encountered an error recording the payment. Please try again.",
                        session_id,
                        SessionState.IDLE
                    )
            except Exception as e:
                logger.error(f"Error recording payment: {str(e)}")
                update_session(session_id, state=SessionState.IDLE)
                clear_session_data(session_id)
                
                return (
                    f"I'm sorry, there was an error recording the payment: {str(e)}. Please try again.",
                    session_id,
                    SessionState.IDLE
                )
        
        elif message.lower() == "edit":
            # Go back to the beginning of the payment flow
            update_session(session_id, data={"current_step": "from_party"})
            
            return (
                "Let's start over. Who made this payment? Please provide the business or individual name.",
                session_id,
                SessionState.PAYMENT_RECORDING
            )
        
        else:
            return (
                "Please reply with 'confirm' to record this payment, or 'edit' to make changes.",
                session_id,
                SessionState.PAYMENT_RECORDING
            )
    
    # Default response if step is unknown - this should never happen
    # But if it does, reset to idle state instead of looping
    logger.error(f"Unknown payment step: {current_step}")
    update_session(session_id, state=SessionState.IDLE)
    clear_session_data(session_id)
    return (
        "I'm having trouble with the payment recording process. Let's try again later. Is there anything else I can help you with?",
        session_id,
        SessionState.IDLE
    )

def process_ledger_step(message, session_id):
    """Process a step in the ledger management conversation flow"""
    # For now, this is a placeholder for future implementation
    update_session(session_id, state=SessionState.IDLE)
    return (
        "Ledger management will be implemented soon.",
        session_id,
        SessionState.IDLE
    )

def process_direct_invoice_command(message, session_id):
    """Process a one-line direct invoice command"""
    try:
        # Extract recipient name
        recipient_match = re.search(r'(?:invoice to|invoice for) ([A-Za-z0-9\s&.,-]+?)(?:\s+for|\s+with|\s+₹|\s+[0-9]|$)', message, re.IGNORECASE)
        if not recipient_match:
            return (
                "I couldn't understand who the invoice is for. Please try again with a clearer format, like: 'invoice to Ramesh for ₹5,000'",
                session_id,
                SessionState.IDLE
            )
        
        recipient = recipient_match.group(1).strip()
        
        # Extract amount
        amount_match = re.search(r'(₹\s*[\d,]+(?:\.\d+)?)', message)
        if not amount_match:
            return (
                "I couldn't understand the invoice amount. Please include an amount like '₹2,000'.",
                session_id,
                SessionState.IDLE
            )
        
        amount = amount_match.group(1).strip()
        
        # Try to extract service description
        description = "Services"
        description_match = re.search(r'for\s+([^₹\n]+?)(?:\s+with|\s+seller|\s+buyer|\s+place|\s+hsn|\s+gst|\s*$)', message, re.IGNORECASE)
        if description_match:
            description = description_match.group(1).strip()
        
        # Extract GST information if present
        recipient_gst_match = re.search(r'(?:buyer gst|recipient gst)[:\s]+([A-Z0-9]+)', message, re.IGNORECASE)
        sender_gst_match = re.search(r'(?:seller gst|my gst)[:\s]+([A-Z0-9]+)', message, re.IGNORECASE)
        pos_match = re.search(r'(?:place of supply|pos)[:\s]+([A-Za-z\s]+)', message, re.IGNORECASE)
        
        recipient_gst = recipient_gst_match.group(1).strip() if recipient_gst_match else None
        sender_gst = sender_gst_match.group(1).strip() if sender_gst_match else None
        place_of_supply = pos_match.group(1).strip() if pos_match else None
        
        # Create a simple invoice item with HSN code
        # Detect common IT services and assign appropriate HSN code based on description
        hsn_code = "9983"  # Default IT consulting service
        if "website" in description.lower() or "web" in description.lower():
            hsn_code = "9983"  # Web portal design and development services
        elif "software" in description.lower() or "app" in description.lower():
            hsn_code = "9983"  # Software development services
        elif "consult" in description.lower() or "advisory" in description.lower():
            hsn_code = "9983"  # Management consultancy services 
        elif "design" in description.lower() or "graphic" in description.lower():
            hsn_code = "9983"  # Graphic design services
        elif "marketing" in description.lower() or "seo" in description.lower():
            hsn_code = "9983"  # Marketing/advertising services
            
        items = [{
            "name": description,
            "amount": amount,
            "gst_rate": 18,  # Default GST rate
            "hsn_code": hsn_code,
            "quantity": 1,
            "unit": "Service"
        }]
        
        # Create the invoice
        invoice = create_invoice(
            recipient=recipient,
            items=items,
            recipient_gst=recipient_gst,
            sender_gst=sender_gst,
            place_of_supply=place_of_supply,
            reverse_charge=False,
            additional_details={}
        )
        
        if invoice:
            response = f"✅ Invoice to {recipient} for {amount} created successfully! Invoice #{invoice['id']}<br><br>"
            response += format_invoice_html(invoice)
            
            return (
                response,
                session_id,
                SessionState.IDLE
            )
        else:
            return (
                "I encountered an error creating your invoice. Please try again with more details.",
                session_id,
                SessionState.IDLE
            )
    except Exception as e:
        logger.error(f"Error processing direct invoice command: {str(e)}")
        return (
            f"I had trouble creating that invoice. Error: {str(e)}",
            session_id,
            SessionState.IDLE
        )

def process_direct_expense_command(message, session_id):
    """Process a one-line direct expense command"""
    try:
        # Extract amount
        amount_match = re.search(r'(₹\s*[\d,]+(?:\.\d+)?)', message)
        if not amount_match:
            return (
                "I couldn't understand the expense amount. Please include an amount like '₹450'.",
                session_id,
                SessionState.IDLE
            )
        
        amount = amount_match.group(1).strip()
        
        # Try to extract vendor and category
        name = None
        category = None
        
        # Look for words after the amount
        rest_of_message = message[message.find(amount) + len(amount):].strip()
        if rest_of_message:
            parts = rest_of_message.split(' for ', 1)
            if len(parts) > 1:
                name = parts[0].strip()
                category = parts[1].strip()
            else:
                # If no "for" found, use the whole text as category
                category = rest_of_message
        
        # Record the transaction
        success = record_transaction("expense", name, amount, category)
        
        if success:
            response = f"✅ Expense of {amount} recorded"
            if name:
                response += f" paid to {name}"
            if category:
                response += f" for {category}"
            return (
                response + ".",
                session_id,
                SessionState.IDLE
            )
        else:
            return (
                "I encountered an error recording your expense. Please try again with more details.",
                session_id,
                SessionState.IDLE
            )
    except Exception as e:
        logger.error(f"Error processing direct expense command: {str(e)}")
        return (
            f"I had trouble recording that expense. Error: {str(e)}",
            session_id,
            SessionState.IDLE
        )

def process_direct_payment_command(message, session_id):
    """Process a one-line direct payment command"""
    try:
        # Extract person name
        from_match = re.search(r'(?:from|by) ([A-Za-z\s]+)', message, re.IGNORECASE)
        
        # Extract amount
        amount_match = re.search(r'(₹\s*[\d,]+(?:\.\d+)?)', message)
        if not amount_match:
            return (
                "I couldn't understand the payment amount. Please include an amount like '₹1,500'.",
                session_id,
                SessionState.IDLE
            )
        
        amount = amount_match.group(1).strip()
        
        # Extract person's name if possible
        name = None
        if from_match:
            name = from_match.group(1).strip()
        
        # Look for reason (optional)
        reason_match = re.search(r'for ([^₹]+)(?:$|\.)', message)
        reason = reason_match.group(1).strip() if reason_match else "payment"
        
        # Record the payment as income
        success = record_transaction("income", name, amount, reason)
        
        if success:
            response = f"✅ Payment of {amount} received"
            if name:
                response += f" from {name}"
            return (
                response + " and recorded to their ledger.",
                session_id,
                SessionState.IDLE
            )
        else:
            return (
                "I encountered an error recording the payment. Please try again with more details.",
                session_id,
                SessionState.IDLE
            )
    except Exception as e:
        logger.error(f"Error processing direct payment command: {str(e)}")
        return (
            f"I had trouble recording that payment. Error: {str(e)}",
            session_id,
            SessionState.IDLE
        )

def process_ledger_command(message, session_id):
    """Process a command to view a ledger"""
    try:
        # Extract person name
        name_match = re.search(r'ledger (?:of|for)?\s*([A-Za-z\s]+)', message, re.IGNORECASE)
        if not name_match:
            return (
                "Please specify whose ledger you want to see, like: 'show ledger of Ramesh' or just 'show ledger Ramesh'",
                session_id,
                SessionState.IDLE
            )
        
        name = name_match.group(1).strip()
        
        # Get the ledger data
        ledger = get_ledger(name)
        if not ledger or not ledger.get("entries", []):
            return (
                f"I don't have any ledger entries for {name} yet. To create entries, you can:\n\n"
                f"• Create an invoice for {name}\n"
                f"• Record a payment from {name}\n\n"
                f"Once you have transactions with {name}, they will appear in this ledger.",
                session_id, 
                SessionState.IDLE
            )
        
        # Format the ledger for display
        response = f"<strong>Ledger for {name}:</strong><br>"
        
        if len(ledger["entries"]) == 0:
            response += "No entries yet."
        else:
            # Add a simple table for entries
            response += "<table class='ledger-table'>"
            response += "<tr><th>Date</th><th>Type</th><th>Amount</th><th>Details</th></tr>"
            
            for entry in ledger["entries"]:
                entry_type = "Invoice" if entry["type"] == "invoice" else "Payment"
                date = format_date(entry["date"])
                amount = format_amount(entry["amount"])
                reason = entry["reason"] if entry["reason"] else ""
                
                response += f"<tr><td>{date}</td><td>{entry_type}</td><td>{amount}</td><td>{reason}</td></tr>"
            
            response += "</table>"
        
        # Add balance summary
        balance = ledger["balance"]
        balance_formatted = format_amount(abs(balance))
        
        if balance > 0:
            response += f"<div class='ledger-summary'>Balance: {balance_formatted} receivable</div>"
        elif balance < 0:
            response += f"<div class='ledger-summary'>Balance: {balance_formatted} payable</div>"
        else:
            response += "<div class='ledger-summary'>Balance: Settled (₹0)</div>"
        
        return (
            response,
            session_id,
            SessionState.IDLE
        )
    except Exception as e:
        logger.error(f"Error processing ledger command: {str(e)}")
        return (
            f"I had trouble retrieving that ledger. Error: {str(e)}",
            session_id,
            SessionState.IDLE
        )

def process_expense_summary_command(message, session_id):
    """Process a command to view expense summaries with enhanced natural language date parsing"""
    try:
        # Determine the period or date range
        message_lower = message.lower()
        
        # Default values
        period = None
        start_date = None
        end_date = None
        
        # First check for standard periods (simple single-word matches)
        if "today" in message_lower:
            period = "today"
        elif "week" in message_lower or "weekly" in message_lower or "last 7 days" in message_lower:
            period = "week"
        elif "month" in message_lower or "monthly" in message_lower:
            period = "month"
        elif "quarter" in message_lower or "quarterly" in message_lower:
            # Check if it's a specific quarter (Q1, Q2, Q3, Q4)
            quarter_match = re.search(r'q(\d)', message_lower)
            if quarter_match:
                quarter_num = int(quarter_match.group(1))
                if 1 <= quarter_num <= 4:
                    # Get the first day of the quarter
                    year = datetime.now().year
                    month = (quarter_num - 1) * 3 + 1  # Q1=1, Q2=4, Q3=7, Q4=10
                    start_date = f"{year}-{month:02d}-01"
                    
                    # Get the last day of the quarter
                    if quarter_num < 4:
                        end_month = quarter_num * 3
                        end_date = f"{year}-{end_month:02d}-30"  # Approximation
                    else:
                        end_date = f"{year}-12-31"
            else:
                # Current quarter
                now = datetime.now()
                current_quarter = (now.month - 1) // 3 + 1
                month = (current_quarter - 1) * 3 + 1
                start_date = f"{now.year}-{month:02d}-01"
                if current_quarter < 4:
                    end_month = current_quarter * 3
                    end_date = f"{now.year}-{end_month:02d}-30"  # Approximation
                else:
                    end_date = f"{now.year}-12-31"
        
        # Check for natural language date references if no simple period was detected
        if not period and not (start_date and end_date):
            # Various natural language date patterns
            
            # Last X days
            days_pattern = re.search(r'last\s+(\d+)\s+days', message_lower)
            if days_pattern:
                days = int(days_pattern.group(1))
                end_date = datetime.now().strftime("%Y-%m-%d")
                start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            
            # Last week, last month, last quarter, last year
            elif "last week" in message_lower:
                # Last week - 7 days ago to today
                end_date = datetime.now().strftime("%Y-%m-%d")
                start_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            elif "last month" in message_lower:
                # Last calendar month
                today = datetime.now()
                if today.month == 1:
                    # January - go to previous year December
                    start_date = f"{today.year-1}-12-01"
                    end_date = f"{today.year-1}-12-31"
                else:
                    # Any other month
                    prev_month = today.month - 1
                    start_date = f"{today.year}-{prev_month:02d}-01"
                    # Last day of previous month is day before 1st of current month
                    last_day = (today.replace(day=1) - timedelta(days=1)).day
                    end_date = f"{today.year}-{prev_month:02d}-{last_day:02d}"
            elif "last quarter" in message_lower:
                # Last calendar quarter
                today = datetime.now()
                current_quarter = (today.month - 1) // 3 + 1
                if current_quarter == 1:
                    # If current is Q1, last was Q4 of previous year
                    start_date = f"{today.year-1}-10-01"
                    end_date = f"{today.year-1}-12-31"
                else:
                    # Otherwise it's the previous quarter this year
                    prev_quarter = current_quarter - 1
                    start_month = (prev_quarter - 1) * 3 + 1
                    end_month = prev_quarter * 3
                    start_date = f"{today.year}-{start_month:02d}-01"
                    # Last day varies by month
                    month_last_days = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
                    # Adjust for leap years
                    if today.year % 4 == 0 and (today.year % 100 != 0 or today.year % 400 == 0):
                        month_last_days[1] = 29
                    end_date = f"{today.year}-{end_month:02d}-{month_last_days[end_month-1]:02d}"
            elif "last year" in message_lower:
                # Last calendar year
                today = datetime.now()
                start_date = f"{today.year-1}-01-01"
                end_date = f"{today.year-1}-12-31"
                
            # Current periods (this week, this month, etc.)
            elif "this week" in message_lower:
                today = datetime.now()
                # Start of current week (Monday)
                days_since_monday = today.weekday()
                start_date = (today - timedelta(days=days_since_monday)).strftime("%Y-%m-%d")
                end_date = today.strftime("%Y-%m-%d")
            elif "this month" in message_lower:
                today = datetime.now()
                start_date = f"{today.year}-{today.month:02d}-01"
                end_date = today.strftime("%Y-%m-%d")
            elif "this quarter" in message_lower:
                today = datetime.now()
                current_quarter = (today.month - 1) // 3 + 1
                start_month = (current_quarter - 1) * 3 + 1
                start_date = f"{today.year}-{start_month:02d}-01"
                end_date = today.strftime("%Y-%m-%d")
            elif "this year" in message_lower:
                today = datetime.now()
                start_date = f"{today.year}-01-01"
                end_date = today.strftime("%Y-%m-%d")
                
            # Year to date
            elif "year to date" in message_lower or "ytd" in message_lower:
                today = datetime.now()
                start_date = f"{today.year}-01-01"
                end_date = today.strftime("%Y-%m-%d")
                
            # Specific month names (January, February, etc.)
            else:
                # Check for month names in the message
                months = {
                    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
                    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12
                }
                
                for month_name, month_num in months.items():
                    if month_name in message_lower:
                        # Found a month name
                        year = datetime.now().year
                        # Check if there's a specific year mentioned
                        year_match = re.search(r'\b(20\d{2})\b', message)
                        if year_match:
                            year = int(year_match.group(1))
                        
                        # Get start and end dates for the month
                        start_date = f"{year}-{month_num:02d}-01"
                        
                        # Determine last day of month
                        month_last_days = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
                        # Adjust for leap years
                        if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0):
                            month_last_days[1] = 29
                            
                        end_date = f"{year}-{month_num:02d}-{month_last_days[month_num-1]:02d}"
                        break
        
        # If still no date range found, check for explicit date format
        if not period and not (start_date and end_date):
            # Check for custom date range with explicit format "from X to Y"
            if "from" in message_lower and "to" in message_lower:
                # First try standard date format
                date_pattern = r'from\s+(\d{1,2}[-/\.]\d{1,2}[-/\.]\d{2,4})\s+to\s+(\d{1,2}[-/\.]\d{1,2}[-/\.]\d{2,4})'
                date_match = re.search(date_pattern, message_lower)
                
                if date_match:
                    # Parse dates in standard format
                    try:
                        start_date_str = date_match.group(1)
                        end_date_str = date_match.group(2)
                        
                        # Convert DD-MM-YYYY to YYYY-MM-DD
                        for date_format in ["%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%d-%m-%y", "%d/%m/%y", "%d.%m.%y"]:
                            try:
                                parsed_start = datetime.strptime(start_date_str, date_format)
                                parsed_end = datetime.strptime(end_date_str, date_format)
                                start_date = parsed_start.strftime("%Y-%m-%d")
                                end_date = parsed_end.strftime("%Y-%m-%d")
                                break
                            except ValueError:
                                continue
                        
                        if not start_date or not end_date:
                            # Try using our natural language date parser
                            from utils.data_manager import parse_direct_date
                            start_date = parse_direct_date(start_date_str)
                            end_date = parse_direct_date(end_date_str)
                            
                            if not start_date or not end_date:
                                return (
                                    "I couldn't understand the date format. Please use DD-MM-YYYY format, for example: 'expense summary from 01-04-2025 to 07-04-2025'",
                                    session_id,
                                    SessionState.IDLE
                                )
                    except Exception as e:
                        # Try natural language format for "from X to Y" where X and Y are text descriptions
                        from_match = re.search(r'from\s+([^t][^\s]+(?:\s+[^\s]+){0,4}?)\s+to', message_lower)
                        to_match = re.search(r'to\s+([^f][^\s]+(?:\s+[^\s]+){0,4}?)(?:\s+|$)', message_lower)
                        
                        if from_match and to_match:
                            from_text = from_match.group(1).strip()
                            to_text = to_match.group(1).strip()
                            
                            # Use the direct date parser
                            from utils.data_manager import parse_direct_date
                            start_date = parse_direct_date(from_text)
                            end_date = parse_direct_date(to_text)
                            
                            if not start_date or not end_date:
                                return (
                                    f"I had trouble understanding the date range '{from_text}' to '{to_text}'. Please try a different format.",
                                    session_id,
                                    SessionState.IDLE
                                )
                        else:
                            return (
                                f"I had trouble parsing the date range. Please use format: 'expense summary from DD-MM-YYYY to DD-MM-YYYY'. Error: {str(e)}",
                                session_id,
                                SessionState.IDLE
                            )
                else:
                    # Try natural language format for "from X to Y" where X and Y are text descriptions
                    from_match = re.search(r'from\s+([^t][^\s]+(?:\s+[^\s]+){0,4}?)\s+to', message_lower)
                    to_match = re.search(r'to\s+([^f][^\s]+(?:\s+[^\s]+){0,4}?)(?:\s+|$)', message_lower)
                    
                    if from_match and to_match:
                        from_text = from_match.group(1).strip()
                        to_text = to_match.group(1).strip()
                        
                        # Use the direct date parser
                        from utils.data_manager import parse_direct_date
                        start_date = parse_direct_date(from_text)
                        end_date = parse_direct_date(to_text)
                        
                        if not start_date or not end_date:
                            return (
                                f"I had trouble understanding the date range '{from_text}' to '{to_text}'. Please try a different format.",
                                session_id,
                                SessionState.IDLE
                            )
                    else:
                        # No valid date range pattern found
                        return (
                            "Please specify a valid date range. For example: 'expense summary from 01-04-2025 to 07-04-2025' or 'expense summary last month'",
                            session_id,
                            SessionState.IDLE
                        )
        
        # Get expense summary with the appropriate filtering
        summary = get_expense_summary(period, start_date, end_date)
        if not summary:
            return (
                "I couldn't generate an expense summary. There may be no expenses recorded yet.",
                session_id,
                SessionState.IDLE
            )
        
        # Format the summary response
        if start_date and end_date:
            # Format dates for display (YYYY-MM-DD to DD-MM-YYYY)
            display_start = datetime.strptime(start_date, "%Y-%m-%d").strftime("%d-%m-%Y")
            display_end = datetime.strptime(end_date, "%Y-%m-%d").strftime("%d-%m-%Y")
            response = f"<strong>Expense Summary from {display_start} to {display_end}:</strong><br>"
            period_text = f"between {display_start} and {display_end}"
        elif period:
            period_text = "today" if period == "today" else f"this {period}"
            response = f"<strong>Expense Summary for {period_text.capitalize()}:</strong><br>"
        else:
            response = "<strong>All-Time Expense Summary:</strong><br>"
            period_text = "yet"
        
        total = summary["total"]
        
        if total == 0:
            return (
                f"No expenses recorded {period_text}.",
                session_id,
                SessionState.IDLE
            )
        
        # Format total
        response += f"<div class='summary-total'>Total: {format_amount(total)}</div><br>"
        
        # Add pie chart for categories
        chart_id = f"expense_chart_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        response += f"""
        <div style="margin: 20px 0;">
            <canvas id="{chart_id}" width="400" height="200"></canvas>
        </div>
        <script>
        document.addEventListener('DOMContentLoaded', function() {{
            // Get the canvas element
            var ctx = document.getElementById('{chart_id}').getContext('2d');
            
            // Create the pie chart
            var myChart = new Chart(ctx, {{
                type: 'pie',
                data: {{
                    labels: {list(summary["categories"].keys())},
                    datasets: [{{
                        data: {list(summary["categories"].values())},
                        backgroundColor: [
                            '#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', '#9966FF', 
                            '#FF9F40', '#8AC249', '#EA5F89', '#00CFDD', '#FF8373'
                        ]
                    }}]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {{
                        legend: {{
                            position: 'bottom',
                        }},
                        title: {{
                            display: true,
                            text: 'Expense Distribution by Category'
                        }}
                    }}
                }}
            }});
        }});
        </script>
        
        <!-- Format categories breakdown -->
        <strong>By Category:</strong><br>
        <table class='summary-table'>
        <tr><th>Category</th><th>Amount</th><th>Percentage</th></tr>
        """
        
        for category, amount in summary["categories"].items():
            percentage = summary["category_percentages"][category]
            response += f"<tr><td>{category}</td><td>{format_amount(amount)}</td><td>{percentage:.1f}%</td></tr>"
        
        response += "</table>"
        
        # Add download PDF button and detailed transactions table (collapsible)
        response += f"""
        <div style="margin-top: 20px; display: flex; justify-content: space-between; align-items: center;">
            <button onclick="toggleTransactions()" style="background-color: #128C7E; color: white; border: none; padding: 8px 15px; border-radius: 4px; cursor: pointer; flex: 2; margin-right: 10px;">
                View Detailed Transactions
            </button>
            
            <a href="/download_expense_summary?period={period or ''}&start_date={start_date or ''}&end_date={end_date or ''}" 
               style="display: inline-block; background-color: #FF6384; color: white; padding: 8px 15px; 
                      text-decoration: none; border-radius: 4px; font-weight: bold; flex: 1; text-align: center;">
               ⬇️ Download PDF
            </a>
        </div>
            
        <div id="transactionsDetail" style="display: none; margin-top: 10px;">
            <table class="transactions-table" style="width: 100%; border-collapse: collapse; margin-top: 10px;">
                <tr style="background-color: #f8f8f8;">
                    <th style="text-align: left; padding: 8px;">Date</th>
                    <th style="text-align: left; padding: 8px;">Category</th>
                    <th style="text-align: right; padding: 8px;">Amount</th>
                    <th style="text-align: left; padding: 8px;">Details</th>
                </tr>
        """
        
        # Add each transaction
        for expense in summary["expenses"]:
            details = expense["name"] if expense["name"] else ""
            if expense["notes"]:
                details += f" ({expense['notes']})" if details else expense["notes"]
                
            response += f"""
                <tr style="border-bottom: 1px solid #eee;">
                    <td style="padding: 8px;">{expense["date"]}</td>
                    <td style="padding: 8px;">{expense["category"]}</td>
                    <td style="text-align: right; padding: 8px;">{expense["amount"]}</td>
                    <td style="padding: 8px;">{details}</td>
                </tr>
            """
        
        response += """
                </table>
            </div>
        </div>
        
        <script>
        function toggleTransactions() {
            var x = document.getElementById("transactionsDetail");
            if (x.style.display === "none") {
                x.style.display = "block";
            } else {
                x.style.display = "none";
            }
        }
        </script>
        """
        
        return (
            response,
            session_id,
            SessionState.IDLE
        )
    except Exception as e:
        logger.error(f"Error processing expense summary command: {str(e)}")
        return (
            f"I had trouble generating the expense summary. Error: {str(e)}",
            session_id,
            SessionState.IDLE
        )

def process_view_invoice_command(message, session_id):
    """Process a command to view a specific invoice"""
    try:
        # Extract invoice ID
        id_match = re.search(r'invoice (?:number |#)?([a-zA-Z0-9_]+)', message, re.IGNORECASE)
        
        if not id_match:
            return (
                "Please specify which invoice you want to view, for example: 'show invoice #invoice_20250406123456'",
                session_id,
                SessionState.IDLE
            )
        
        invoice_id = id_match.group(1).strip()
        
        # Get the invoice
        invoice = get_invoice_by_id(invoice_id)
        if not invoice:
            return (
                f"Invoice #{invoice_id} not found. Please check the invoice number and try again.",
                session_id,
                SessionState.IDLE
            )
        
        # Format and return the invoice HTML
        return (
            format_invoice_html(invoice),
            session_id,
            SessionState.IDLE
        )
    except Exception as e:
        logger.error(f"Error processing view invoice command: {str(e)}")
        return (
            f"I had trouble retrieving that invoice. Error: {str(e)}",
            session_id,
            SessionState.IDLE
        )

def process_parsed_direct_command(parsed_data, session_id):
    """
    Process a command parsed by the natural language processor
    
    Args:
        parsed_data: Dictionary with extracted parameters
        session_id: The current session ID
        
    Returns:
        Response tuple (message, session_id, state)
    """
    try:
        command_type = parsed_data.get("type", "expense")
        
        if command_type == "expense":
            # Process as an expense
            amount = parsed_data.get("amount")
            name = parsed_data.get("name", "")
            category = parsed_data.get("category", "Miscellaneous")
            date_str = parsed_data.get("date")
            notes = parsed_data.get("notes", "")
            
            # Record the transaction
            success = record_transaction(
                transaction_type="expense",
                name=name,
                amount=amount,
                category=category,
                date=date_str,
                notes=notes
            )
            
            if success:
                # Format a success message
                response = f"✅ Recorded expense of {format_amount(amount)}"
                if name:
                    response += f" paid to {name}"
                if category:
                    response += f" under {category}"
                if date_str:
                    # Format date for display
                    try:
                        display_date = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d %b %Y")
                        response += f" on {display_date}"
                    except:
                        # If date formatting fails, use the raw string
                        response += f" on {date_str}"
                if notes:
                    response += f" ({notes})"
                        
                return (response, session_id, SessionState.IDLE)
            else:
                return (
                    "Sorry, I couldn't record that expense. Please try again with a clearer format.",
                    session_id,
                    SessionState.IDLE
                )
        
        elif command_type == "income":
            # Process as income/payment
            amount = parsed_data.get("amount")
            name = parsed_data.get("name", "")
            category = parsed_data.get("category", "Income")
            date_str = parsed_data.get("date")
            notes = parsed_data.get("notes", "")
            
            # Record the transaction
            success = record_transaction(
                transaction_type="income",
                name=name,
                amount=amount,
                category=category,
                date=date_str,
                notes=notes
            )
            
            if success:
                # Format a success message
                response = f"✅ Recorded payment of {format_amount(amount)}"
                if name:
                    response += f" received from {name}"
                if category:
                    response += f" as {category}"
                if date_str:
                    # Format date for display
                    try:
                        display_date = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d %b %Y")
                        response += f" on {display_date}"
                    except:
                        # If date formatting fails, use the raw string
                        response += f" on {date_str}"
                if notes:
                    response += f" ({notes})"
                    
                return (response, session_id, SessionState.IDLE)
            else:
                return (
                    "Sorry, I couldn't record that payment. Please try again with a clearer format.",
                    session_id,
                    SessionState.IDLE
                )
        
        else:
            # Unsupported command type
            return (
                "I'm not sure how to process that command. Please try a different format or use 'menu' to see available options.",
                session_id,
                SessionState.IDLE
            )
    
    except Exception as e:
        logger.error(f"Error processing direct command: {str(e)}")
        return (
            f"Sorry, there was an error processing your command: {str(e)}. Please try a different format.",
            session_id,
            SessionState.IDLE
        )

def process_financial_report_command(message, session_id):
    """
    Process a command to generate a financial report
    
    Args:
        message: The user message
        session_id: The current session ID
        
    Returns:
        Response tuple (message, session_id, state)
    """
    message_lower = message.lower()
    
    # Determine the report type and period
    report_type = "monthly"  # Default to monthly report
    month = datetime.now().month  # Default to current month
    year = datetime.now().year   # Default to current year
    
    # Check for specific report types
    if "yearly" in message_lower or "annual" in message_lower:
        report_type = "yearly"
    elif "quarterly" in message_lower or "quarter" in message_lower:
        report_type = "quarterly"
        
        # Try to determine which quarter
        quarter_match = re.search(r'q(\d)', message_lower)
        if quarter_match:
            quarter = int(quarter_match.group(1))
            if 1 <= quarter <= 4:
                month = quarter * 3  # Last month of the quarter
    
    # Check for specific time periods
    if "last month" in message_lower or "previous month" in message_lower:
        # Set to last month
        current_date = datetime.now()
        last_month_date = current_date.replace(day=1) - timedelta(days=1)
        month = last_month_date.month
        year = last_month_date.year
    elif "this month" in message_lower or "current month" in message_lower:
        # Already set to current month (default)
        pass
    elif "last year" in message_lower or "previous year" in message_lower:
        year = datetime.now().year - 1
    
    # Extract specific month names if present
    months = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12
    }
    
    for month_name, month_num in months.items():
        if month_name in message_lower:
            month = month_num
            # Check if a specific year is mentioned
            year_match = re.search(r'\b(20\d{2})\b', message)
            if year_match:
                year = int(year_match.group(1))
            break
    
    # Generate the financial report
    report = get_financial_report(report_type, month, year)
    
    if report:
        # Format the report as HTML and return it
        return (
            format_financial_report_html(report),
            session_id,
            SessionState.IDLE
        )
    else:
        return (
            "I couldn't generate a financial report. This could be because there are no transactions for the specified period.",
            session_id,
            SessionState.IDLE
        )

def generate_menu():
    """Generate a menu of available commands"""
    menu = """<div style="font-family: Arial, sans-serif; max-width: 100%;">
    <h3 style="color: #4a6fa5; text-align: center; margin-bottom: 15px;">🧮 Munim AI Menu</h3>
    
    <div class="menu-section" style="margin-bottom: 15px; border: 1px solid #e0e0e0; border-radius: 8px; overflow: hidden;">
        <div style="background-color: #f0f4f8; padding: 8px 12px; font-weight: bold;">
            📋 GST Invoices
        </div>
        <div style="padding: 10px 15px; font-size: 14px;">
            • "Create invoice" - Start a new GST invoice<br>
            • "Show invoice #[ID]" - View an existing invoice<br>
            • "Invoice to ABC Corp for ₹10,000" - Fast creation
        </div>
    </div>
    
    <div class="menu-section" style="margin-bottom: 15px; border: 1px solid #e0e0e0; border-radius: 8px; overflow: hidden;">
        <div style="background-color: #f0f4f8; padding: 8px 12px; font-weight: bold;">
            💰 Expenses & Payments
        </div>
        <div style="padding: 10px 15px; font-size: 14px;">
            • "Record expense" - Add a new expense<br>
            • "Record payment" - Record a payment received<br>
            • "Expense summary" - View expense breakdown<br>
            • "Expense summary from 01-04-2025 to 07-04-2025" - Custom date range<br>
            • "Spent ₹500 on office supplies yesterday"
        </div>
    </div>
    
    <div class="menu-section" style="margin-bottom: 15px; border: 1px solid #e0e0e0; border-radius: 8px; overflow: hidden;">
        <div style="background-color: #f0f4f8; padding: 8px 12px; font-weight: bold;">
            📒 Ledger Management
        </div>
        <div style="padding: 10px 15px; font-size: 14px;">
            • "Show ledger of [name]" - View a party's ledger<br>
            • "Settlement with [name]" - Record a settlement
        </div>
    </div>
    
    <div class="menu-section" style="margin-bottom: 15px; border: 1px solid #e0e0e0; border-radius: 8px; overflow: hidden;">
        <div style="background-color: #f0f4f8; padding: 8px 12px; font-weight: bold;">
            📊 Financial Reports
        </div>
        <div style="padding: 10px 15px; font-size: 14px;">
            • "Financial report" - Get monthly summary<br>
            • "Financial report Q1" - Get quarterly report<br>
            • "Financial report March" - Specific month
        </div>
    </div>
    
    <div class="menu-section" style="margin-bottom: 15px; border: 1px solid #e0e0e0; border-radius: 8px; overflow: hidden;">
        <div style="background-color: #f0f4f8; padding: 8px 12px; font-weight: bold;">
            🛠️ Natural Language Commands
        </div>
        <div style="padding: 10px 15px; font-size: 14px;">
            • "Received ₹20,000 from XYZ Ltd for website work"<br>
            • "Paid ₹1,200 to Electricity Board on April 5"
        </div>
    </div>
    
    <div class="menu-section" style="margin-bottom: 15px; border: 1px solid #e0e0e0; border-radius: 8px; overflow: hidden;">
        <div style="background-color: #f0f4f8; padding: 8px 12px; font-weight: bold;">
            📚 Tax Advisory
        </div>
        <div style="padding: 10px 15px; font-size: 14px;">
            • "What is the GST rate for IT services?"<br>
            • "What are the GST filing deadlines?"<br>
            • "What HSN code should I use for consulting?"<br>
            • "What are the latest GST updates?"
        </div>
    </div>
    
    <p style="text-align: center; font-size: 14px; font-style: italic; margin-top: 15px;">Type any command above or ask me about your finances and taxes!</p>
</div>
"""
    return menu
    
def generate_help_message():
    """Generate a help message with GST-specific information and explanation of how to use the app"""
    help_msg = """<div style="font-family: Arial, sans-serif; max-width: 100%; padding: 15px; background-color: #f9fcff; border-radius: 8px; border: 1px solid #d0e3f0;">
    <h3 style="color: #2a4b8d; margin-top: 0;">🧮 Welcome to Munim AI!</h3>
    
    <p>I'm your business finance assistant designed specifically for Indian businesses. Here's how I can help you:</p>
    
    <div style="margin: 15px 0; padding: 12px; background-color: #fff; border-radius: 8px; border-left: 4px solid #4a90e2;">
        <h4 style="margin-top: 0; color: #2a4b8d;">💼 GST-Compliant Invoicing</h4>
        <p>Create professional GST invoices that are fully compliant with Indian tax requirements.</p>
        <ul style="margin-bottom: 0; padding-left: 20px;">
            <li>Supports CGST/SGST for intra-state transactions</li>
            <li>Supports IGST for inter-state transactions</li>
            <li>Automatically validates GST numbers</li>
            <li>Calculates taxes based on the place of supply</li>
        </ul>
    </div>
    
    <div style="margin: 15px 0; padding: 12px; background-color: #fff; border-radius: 8px; border-left: 4px solid #50b46c;">
        <h4 style="margin-top: 0; color: #2a4b8d;">📊 Financial Management</h4>
        <p>Track all your business finances in one place:</p>
        <ul style="margin-bottom: 0; padding-left: 20px;">
            <li>Record and categorize expenses</li>
            <li>Track payments received</li>
            <li>Maintain digital ledgers for each party</li>
            <li>Generate financial reports for any time period</li>
        </ul>
    </div>
    
    <div style="margin: 15px 0; padding: 12px; background-color: #fff; border-radius: 8px; border-left: 4px solid #e2a864;">
        <h4 style="margin-top: 0; color: #2a4b8d;">💬 Natural Language Instructions</h4>
        <p>Talk to me like you're chatting with a colleague:</p>
        <ul style="margin-bottom: 0; padding-left: 20px;">
            <li>"Create an invoice for ABC Company for ₹15,000"</li>
            <li>"I spent ₹2,500 on office supplies yesterday"</li>
            <li>"Received ₹30,000 from XYZ Ltd for consulting"</li>
            <li>"Show me the ledger for Priya Sharma"</li>
        </ul>
    </div>
    
    <div style="margin: 15px 0; padding: 12px; background-color: #fff; border-radius: 8px; border-left: 4px solid #9b64e2;">
        <h4 style="margin-top: 0; color: #2a4b8d;">📚 Tax Advisory</h4>
        <p>Ask me about GST and Indian tax regulations:</p>
        <ul style="margin-bottom: 0; padding-left: 20px;">
            <li>"What is the GST rate for IT services?"</li>
            <li>"What HSN code should I use for my software business?"</li>
            <li>"When is the GSTR-3B filing deadline?"</li>
            <li>"What are the latest GST updates and changes?"</li>
        </ul>
    </div>
    
    <p style="margin-top: 20px;"><strong>Need a full list of commands?</strong> Type "menu" to see all available options.</p>
    <p style="font-style: italic; margin-bottom: 0;">Your data is stored securely and never shared with third parties.</p>
</div>
"""
    return help_msg

def get_session_state(session_id):
    """Return the current session state and any relevant data"""
    session = get_session(session_id)
    if not session:
        return None
    
    return {
        "state": session.get("state", SessionState.IDLE),
        "data": session.get("data", {})
    }