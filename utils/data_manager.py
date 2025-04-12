import json
import os
import re
import logging
import tempfile
from datetime import datetime, timedelta
from fpdf import FPDF

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# File paths
INVOICES_FILE = 'data/invoices.json'
TRANSACTIONS_FILE = 'data/transactions.json'
LEDGERS_FILE = 'data/ledgers.json'

def load_json_data(file_path):
    """Load data from a JSON file."""
    # Define default structures outside the try block
    default_structures = {
        INVOICES_FILE: {"invoices": []},
        TRANSACTIONS_FILE: {"transactions": []},
        LEDGERS_FILE: {"ledgers": {}}
    }
    
    try:
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                return json.load(f)
        else:
            # Create base structure if file doesn't exist
            return default_structures.get(file_path, {})
    except Exception as e:
        logger.error(f"Error loading data from {file_path}: {str(e)}")
        # Return empty default structures
        return default_structures.get(file_path, {})

def save_json_data(file_path, data):
    """Save data to a JSON file."""
    try:
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=4)
        return True
    except Exception as e:
        logger.error(f"Error saving data to {file_path}: {str(e)}")
        return False

def create_invoice(recipient, items=None, recipient_gst=None, sender_gst=None, custom_invoice_number=None, 
                 gst_rate=18, place_of_supply=None, reverse_charge=False, additional_details=None):
    """
    Create a new invoice and add it to the ledger according to GST compliance requirements.
    
    Args:
        recipient: Name of the invoice recipient
        items: List of items with their details. Each item should be a dict with 'name', 'amount', 'quantity', 
               'hsn_code', and optional 'gst_rate'
              If None, a single item will be created from the additional_details
        recipient_gst: GST number of the recipient (optional)
        sender_gst: GST number of the sender (optional)
        custom_invoice_number: Custom invoice number (optional, will generate one if not provided)
        gst_rate: Default GST rate to use for items that don't specify their own rate
        place_of_supply: Place of supply for GST purposes (required for GST compliance)
        reverse_charge: Whether this invoice is under reverse charge (Yes/No)
        additional_details: Additional details for the invoice, such as shipping address, terms, etc.

    Returns:
        The created invoice object or None if an error occurs
    """
    try:
        date = datetime.now()
        
        # Use provided custom invoice number or generate a new one
        invoice_id = custom_invoice_number or generate_id("invoice")
        
        # Process items or create a default item if none provided
        if not items:
            # Default to a single item using provided reason
            reason = "Services"
            amount = 0
            
            if additional_details:
                reason = additional_details.get("reason", reason)
                amount = additional_details.get("amount", amount)
            
            # Try to convert amount from string to float if needed
            if isinstance(amount, str):
                amount = float(amount.replace('₹', '').replace(',', ''))
                
            items = [{
                "name": reason,
                "amount": amount,
                "gst_rate": gst_rate
            }]
        
        # Calculate totals
        base_total = 0
        gst_total = 0
        
        # Process each item
        processed_items = []
        for item in items:
            # Clean up item name, sanitizing common issues
            item_name = item.get("name", "Item")
            # Fix common issues with item names
            if "invoice to" in item_name.lower() or "create invoice" in item_name.lower():
                item_name = "Professional Services"
            item_amount = item.get("amount", 0)
            item_gst_rate = item.get("gst_rate", gst_rate)  # Use default if not specified
            
            # Get HSN/SAC code (mandatory for GST-compliant invoices)
            hsn_code = item.get("hsn_code", "9983")  # Default to 9983 (IT services) if not specified
            
            # Get quantity and unit details
            quantity = item.get("quantity", 1)
            unit = item.get("unit", "Unit")
            
            # Convert amount from string to float if needed first
            if isinstance(item_amount, str):
                item_amount = float(item_amount.replace('₹', '').replace(',', ''))
                
            # Ensure quantity is a number
            if isinstance(quantity, str):
                try:
                    quantity = float(quantity)
                except ValueError:
                    quantity = 1
                    
            # Calculate rate per unit
            rate_per_unit = item_amount / quantity if quantity > 0 else item_amount
            
            # Get discount if any
            discount = item.get("discount", 0)
            discount_amount = (item_amount * discount / 100) if discount > 0 else 0
            
            # Calculate taxable value after discount
            taxable_value = item_amount - discount_amount
                
            # Calculate GST for this item based on taxable value
            # For interstate (IGST) or intrastate (CGST + SGST) based on place of supply
            seller_state = ""
            if additional_details and isinstance(additional_details, dict):
                seller_state = additional_details.get("seller_state", "")
            is_interstate = place_of_supply != seller_state
            
            # Calculate GST amounts
            item_gst_amount = taxable_value * (item_gst_rate / 100)
            
            if is_interstate:
                # IGST applies for interstate transactions
                igst_amount = item_gst_amount
                cgst_amount = 0
                sgst_amount = 0
            else:
                # CGST and SGST for intrastate (each half of total GST)
                igst_amount = 0
                cgst_amount = item_gst_amount / 2
                sgst_amount = item_gst_amount / 2
            
            item_total = taxable_value + item_gst_amount
            
            # Add to totals
            base_total += taxable_value
            gst_total += item_gst_amount
            
            # Add processed item to list with all GST details
            processed_items.append({
                "name": item_name,
                "hsn_code": hsn_code,
                "quantity": quantity,
                "unit": unit,
                "rate_per_unit": rate_per_unit,
                "base_amount": item_amount,
                "discount": discount,
                "discount_amount": discount_amount,
                "taxable_value": taxable_value,
                "gst_rate": item_gst_rate,
                "igst_amount": igst_amount,
                "cgst_amount": cgst_amount,
                "sgst_amount": sgst_amount,
                "gst_amount": item_gst_amount,
                "total_amount": item_total
            })
        
        total_amount = base_total + gst_total
        
        # Determine if this is interstate or intrastate for totals
        seller_state = ""
        if additional_details and isinstance(additional_details, dict):
            seller_state = additional_details.get("seller_state", "")
        is_interstate = place_of_supply != seller_state
        
        # Calculate total GST components
        if is_interstate:
            total_igst = gst_total
            total_cgst = 0
            total_sgst = 0
        else:
            total_igst = 0
            total_cgst = gst_total / 2
            total_sgst = gst_total / 2
        
        # Create invoice object with all required GST fields
        invoice = {
            "id": invoice_id,
            "recipient": recipient,
            "recipient_gst": recipient_gst,
            "sender_gst": sender_gst,
            "place_of_supply": place_of_supply or "Not Specified",
            "reverse_charge": reverse_charge,
            "base_amount": base_total,
            "gst_amount": gst_total,
            "cgst_amount": total_cgst,
            "sgst_amount": total_sgst,
            "igst_amount": total_igst,
            "total_amount": total_amount,
            "items": processed_items,
            "date": date.strftime("%Y-%m-%d %H:%M:%S"),
            "due_date": (date + timedelta(days=30)).strftime("%Y-%m-%d"),
            "status": "pending",
            "details": additional_details or {}
        }
        
        # Load current invoices
        data = load_json_data(INVOICES_FILE)
        if "invoices" in data:
            data["invoices"].append(invoice)
        else:
            data["invoices"] = [invoice]
        
        # Save updated invoices
        if save_json_data(INVOICES_FILE, data):
            # Update ledger - use the first item's name as reason or "Multiple items" if multiple items
            reason = processed_items[0]["name"] if len(processed_items) == 1 else "Multiple items"
            update_ledger(recipient, "invoice", total_amount, reason, date)
            return invoice
        return None
    except Exception as e:
        logger.error(f"Error creating invoice: {str(e)}")
        return None

def record_transaction(transaction_type, name, amount, category=None, date=None, notes=None):
    """Record an expense or income transaction."""
    try:
        # Format the amount data
        if isinstance(amount, str):
            amount = float(amount.replace('₹', '').replace(',', ''))
        
        # Use provided date or current date
        if date is None:
            date_obj = datetime.now()
            date_str = date_obj.strftime("%Y-%m-%d %H:%M:%S")
        else:
            # If date is already a string, use it directly
            if isinstance(date, str):
                # Check if it has time component
                if len(date) <= 10:  # Only date part (YYYY-MM-DD)
                    date_str = f"{date} 00:00:00"
                else:
                    date_str = date
                date_obj = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
            else:
                # Assume it's a datetime object
                date_obj = date
                date_str = date_obj.strftime("%Y-%m-%d %H:%M:%S")
        
        # Create transaction object
        transaction = {
            "id": generate_id("transaction"),
            "type": transaction_type,  # 'expense' or 'income'
            "amount": amount,
            "date": date_str
        }
        
        # Add optional fields if provided
        if name:
            transaction["name"] = name
        
        if category:
            transaction["category"] = category
        else:
            transaction["category"] = "Uncategorized"
        
        if notes:
            transaction["notes"] = notes
        
        # Load current transactions
        data = load_json_data(TRANSACTIONS_FILE)
        if "transactions" in data:
            data["transactions"].append(transaction)
        else:
            data["transactions"] = [transaction]
        
        # Save updated transactions
        if save_json_data(TRANSACTIONS_FILE, data):
            # Update ledger if it has a name and is a relevant transaction type
            if name:
                if transaction_type == "income":
                    # For income, we're receiving from someone
                    update_ledger(name, "payment", amount, category or notes, date_obj)
                elif transaction_type == "expense":
                    # For expenses, we're paying someone
                    update_ledger(name, "invoice", -amount, category or notes, date_obj)
            return True
        return False
    except Exception as e:
        logger.error(f"Error recording transaction: {str(e)}")
        return False

def update_ledger(name, entry_type, amount, reason, date):
    """Update a person's ledger with a new entry."""
    try:
        # Load current ledgers
        data = load_json_data(LEDGERS_FILE)
        
        # Create person's ledger if it doesn't exist
        if name not in data["ledgers"]:
            data["ledgers"][name] = {
                "entries": [],
                "balance": 0
            }
        
        # Update balance based on entry type
        if entry_type == "invoice":
            # Money owed to us (positive)
            new_balance = data["ledgers"][name]["balance"] + amount
        elif entry_type == "payment":
            # Money we received (negative - reduces what they owe)
            new_balance = data["ledgers"][name]["balance"] - amount
        else:
            new_balance = data["ledgers"][name]["balance"]
        
        # Create ledger entry
        entry = {
            "type": entry_type,
            "amount": amount,
            "reason": reason,
            "date": date.strftime("%Y-%m-%d %H:%M:%S")
        }
        
        # Add entry and update balance
        data["ledgers"][name]["entries"].append(entry)
        data["ledgers"][name]["balance"] = new_balance
        
        # Save updated ledgers
        return save_json_data(LEDGERS_FILE, data)
    except Exception as e:
        logger.error(f"Error updating ledger: {str(e)}")
        return False

def get_ledger(name):
    """Get a person's ledger with all entries and balance."""
    try:
        data = load_json_data(LEDGERS_FILE)
        if name in data["ledgers"]:
            return data["ledgers"][name]
        return None
    except Exception as e:
        logger.error(f"Error getting ledger: {str(e)}")
        return None

def generate_id(prefix):
    """Generate a simple ID for invoices and transactions."""
    return f"{prefix}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

def format_amount(amount):
    """Format amount with ₹ symbol."""
    return f"₹{amount:,.2f}"

def format_date(date_str):
    """Convert full date string to simpler format for display."""
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        return date_obj.strftime("%d %b")
    except:
        return date_str

def get_expense_summary(period=None, start_date=None, end_date=None):
    """
    Get summary of expenses, optionally filtered by period or date range.
    
    Args:
        period: Can be 'today', 'week', 'month', or None for all time
        start_date: Optional start date for a custom date range (string in YYYY-MM-DD format)
        end_date: Optional end date for a custom date range (string in YYYY-MM-DD format)
        
    Returns:
        Dictionary with summary information or None if error occurs
    """
    try:
        data = load_json_data(TRANSACTIONS_FILE)
        transactions = data["transactions"]
        
        # Filter only expense transactions
        expenses = [t for t in transactions if t["type"] == "expense"]
        
        # Apply date filtering
        if start_date and end_date:
            # Custom date range
            start_datetime = datetime.strptime(start_date, "%Y-%m-%d")
            end_datetime = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)  # Include the end date
            expenses = [e for e in expenses if start_datetime <= datetime.strptime(e["date"], "%Y-%m-%d %H:%M:%S") < end_datetime]
        elif period:
            now = datetime.now()
            if period == 'today':
                # Filter for today's expenses
                start_date = datetime(now.year, now.month, now.day)
                expenses = [e for e in expenses if datetime.strptime(e["date"], "%Y-%m-%d %H:%M:%S") >= start_date]
            elif period == 'week':
                # Filter for this week's expenses (last 7 days)
                start_date = now - timedelta(days=7)
                expenses = [e for e in expenses if datetime.strptime(e["date"], "%Y-%m-%d %H:%M:%S") >= start_date]
            elif period == 'month':
                # Filter for this month's expenses
                start_date = datetime(now.year, now.month, 1)
                expenses = [e for e in expenses if datetime.strptime(e["date"], "%Y-%m-%d %H:%M:%S") >= start_date]
        
        # Calculate total amount
        total = sum(e["amount"] for e in expenses)
        
        # Group by category
        categories = {}
        for expense in expenses:
            category = expense.get("category") or "Uncategorized"
            if category not in categories:
                categories[category] = 0
            categories[category] += expense["amount"]
        
        # Sort expenses by date (newest first)
        sorted_expenses = sorted(expenses, key=lambda x: datetime.strptime(x["date"], "%Y-%m-%d %H:%M:%S"), reverse=True)
        
        # Format expenses for display
        formatted_expenses = []
        for expense in sorted_expenses:
            formatted_expense = {
                "id": expense.get("id", ""),
                "date": format_date(expense.get("date", "")),
                "category": expense.get("category", "Uncategorized"),
                "amount": format_amount(expense.get("amount", 0)),
                "raw_amount": expense.get("amount", 0),  # Needed for charts
                "name": expense.get("name", ""),
                "notes": expense.get("notes", "")
            }
            formatted_expenses.append(formatted_expense)
            
        return {
            "expenses": formatted_expenses,
            "total": total,
            "raw_total": total,  # Needed for charts
            "categories": categories,
            "category_percentages": {cat: (amt/total)*100 if total > 0 else 0 for cat, amt in categories.items()}
        }
    except Exception as e:
        logger.error(f"Error getting expense summary: {str(e)}")
        return None

def generate_expense_summary_pdf(summary, period_text):
    """Generate a PDF document for an expense summary.
    
    Args:
        summary: The expense summary dictionary
        period_text: Text describing the period of the summary
        
    Returns:
        Path to the generated PDF file
    """
    if not summary:
        return None
    
    try:
        # Create PDF object
        pdf = FPDF()
        pdf.add_page()
        
        # Set up fonts and header
        pdf.set_font('Arial', 'B', 16)
        pdf.cell(190, 10, 'EXPENSE SUMMARY', 0, 1, 'C')
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(190, 10, f'Period: {period_text}', 0, 1, 'C')
        
        # Add current date
        pdf.set_font('Arial', '', 10)
        pdf.cell(190, 10, f'Generated on: {datetime.now().strftime("%d %b, %Y")}', 0, 1, 'R')
        pdf.ln(5)
        
        # Add total amount
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(190, 10, f'Total Expenses: ₹{summary["total"]:,.2f}', 0, 1)
        pdf.ln(5)
        
        # Category breakdown section
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(190, 10, 'Category Breakdown:', 0, 1)
        
        # Categories table header
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(95, 10, 'Category', 1, 0)
        pdf.cell(40, 10, 'Amount', 1, 0, 'R')
        pdf.cell(55, 10, 'Percentage', 1, 1, 'R')
        
        # Add each category
        pdf.set_font('Arial', '', 10)
        for category, amount in summary["categories"].items():
            percentage = summary["category_percentages"][category]
            pdf.cell(95, 10, category, 1, 0)
            pdf.cell(40, 10, f'₹{amount:,.2f}', 1, 0, 'R')
            pdf.cell(55, 10, f"{percentage:.1f}%", 1, 1, 'R')
        
        # Transactions section
        pdf.ln(10)
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(190, 10, 'Transaction Details:', 0, 1)
        
        # Transactions table header
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(30, 10, 'Date', 1, 0)
        pdf.cell(40, 10, 'Category', 1, 0)
        pdf.cell(30, 10, 'Amount', 1, 0, 'R')
        pdf.cell(90, 10, 'Description', 1, 1)
        
        # Add each transaction
        pdf.set_font('Arial', '', 9)
        for expense in summary["expenses"]:
            # Prepare details
            details = expense["name"] if expense.get("name") else ""
            if expense.get("notes"):
                details += f" ({expense['notes']})" if details else expense["notes"]
            
            # Add row with multi-cell for description (to handle long text)
            pdf.cell(30, 10, expense["date"], 1, 0)
            pdf.cell(40, 10, expense["category"], 1, 0)
            pdf.cell(30, 10, expense["amount"], 1, 0, 'R')
            pdf.cell(90, 10, details[:40] + "..." if len(details) > 40 else details, 1, 1)
        
        # Generate a unique filename
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        filename = f"expense_summary_{timestamp}.pdf"
        filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'static', 'downloads', filename)
        
        # Ensure the downloads directory exists
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        # Save the PDF
        pdf.output(filepath)
        return filename
        
    except Exception as e:
        logger.error(f"Error generating expense summary PDF: {str(e)}")
        return None

def get_invoice_by_id(invoice_id):
    """Get a specific invoice by ID."""
    try:
        data = load_json_data(INVOICES_FILE)
        for invoice in data["invoices"]:
            if invoice["id"] == invoice_id:
                return invoice
        return None
    except Exception as e:
        logger.error(f"Error getting invoice: {str(e)}")
        return None

def format_invoice_html(invoice):
    """Format an invoice as HTML for display in the chat."""
    if not invoice:
        return "Invoice not found."
    
    # GST information section
    gst_info = ""
    if invoice.get('sender_gst'):
        gst_info += f"<p><strong>Seller GST:</strong> {invoice['sender_gst']}</p>"
    if invoice.get('recipient_gst'):
        gst_info += f"<p><strong>Buyer GST:</strong> {invoice['recipient_gst']}</p>"
    
    # Place of supply and reverse charge
    place_of_supply = invoice.get('place_of_supply', 'Not Specified')
    reverse_charge = "Yes" if invoice.get('reverse_charge', False) else "No"
    
    gst_info += f"<p><strong>Place of Supply:</strong> {place_of_supply}</p>"
    gst_info += f"<p><strong>Reverse Charge:</strong> {reverse_charge}</p>"
    
    # Format the invoice as HTML - header section with proper GST compliance
    html = f"""<div style='border: 1px solid #ddd; padding: 15px; border-radius: 8px;'>
    <h3 style='color: #128C7E; margin-top: 0;'>TAX INVOICE</h3>
    <p><strong>Invoice No:</strong> {invoice['id']}</p>
    <p><strong>Date:</strong> {format_date(invoice['date'])}</p>
    <p><strong>Due Date:</strong> {invoice['due_date']}</p>
    
    <div style='display: flex; margin-top: 10px;'>
        <div style='flex: 1; border: 1px solid #eee; padding: 10px; margin-right: 5px;'>
            <h4 style='margin-top: 0;'>Seller Details</h4>
            <p><strong>Name:</strong> Your Business Name</p>
            {f"<p><strong>GST:</strong> {invoice['sender_gst']}</p>" if invoice.get('sender_gst') else ""}
            <p><strong>Address:</strong> Your Business Address</p>
        </div>
        <div style='flex: 1; border: 1px solid #eee; padding: 10px; margin-left: 5px;'>
            <h4 style='margin-top: 0;'>Buyer Details</h4>
            <p><strong>Name:</strong> {invoice['recipient']}</p>
            {f"<p><strong>GST:</strong> {invoice['recipient_gst']}</p>" if invoice.get('recipient_gst') else ""}
            <p><strong>Place of Supply:</strong> {place_of_supply}</p>
        </div>
    </div>
    
    <hr style='border-top: 1px solid #eee; margin-top: 15px;'>
    """
    
    # Items table with enhanced GST details
    html += """<table style='width: 100%; border-collapse: collapse; margin-top: 10px;'>
    <tr style='background-color: #f8f8f8; border-bottom: 1px solid #ddd;'>
        <th style='text-align: left; padding: 8px;'>Item</th>
        <th style='text-align: center; padding: 8px;'>HSN/SAC</th>
        <th style='text-align: center; padding: 8px;'>Qty</th>
        <th style='text-align: right; padding: 8px;'>Rate</th>
        <th style='text-align: right; padding: 8px;'>Taxable</th>
        <th style='text-align: center; padding: 8px;'>GST%</th>
        <th style='text-align: right; padding: 8px;'>GST Amt</th>
        <th style='text-align: right; padding: 8px;'>Total</th>
    </tr>
    """
    
    # Check if we have the new items structure or need to use the legacy structure
    if 'items' in invoice:
        # New structure with multiple items
        for item in invoice['items']:
            # Get item values with defaults for missing fields
            item_name = item.get('name', 'Item')
            # Sanitize item name for display
            if "invoice to" in item_name.lower() or "create invoice" in item_name.lower():
                item_name = "Professional Services"
            # If already named Website Development, keep it, or if it contains the keyword, name it properly
            elif item_name == "Website Development" or "website development" in item_name.lower():
                item_name = "Website Development"
            hsn_code = item.get('hsn_code', '-')
            quantity = item.get('quantity', 1)
            base_amount = item.get('base_amount', 0)
            taxable_value = item.get('taxable_value', base_amount)
            rate_per_unit = item.get('rate_per_unit', base_amount)
            gst_rate = item.get('gst_rate', 18)
            gst_amount = item.get('gst_amount', 0)
            total_amount = item.get('total_amount', 0)
            
            html += f"""
            <tr style='border-bottom: 1px solid #eee;'>
                <td style='padding: 8px;'>{item_name}</td>
                <td style='text-align: center; padding: 8px;'>{hsn_code}</td>
                <td style='text-align: center; padding: 8px;'>{quantity}</td>
                <td style='text-align: right; padding: 8px;'>{format_amount(rate_per_unit)}</td>
                <td style='text-align: right; padding: 8px;'>{format_amount(taxable_value)}</td>
                <td style='text-align: center; padding: 8px;'>{gst_rate}%</td>
                <td style='text-align: right; padding: 8px;'>{format_amount(gst_amount)}</td>
                <td style='text-align: right; padding: 8px;'>{format_amount(total_amount)}</td>
            </tr>
            """
    else:
        # Legacy structure with a single item
        reason = invoice.get('reason', 'Services')
        # If the reason is website development, make sure to standardize the capitalization
        if "website development" in reason.lower():
            reason = "Website Development"
        base_amount = invoice.get('base_amount', 0)
        gst_rate = invoice.get('gst_rate', 18)
        gst_amount = invoice.get('gst_amount', 0)
        total_amount = invoice.get('total_amount', 0)
        
        html += f"""
        <tr style='border-bottom: 1px solid #eee;'>
            <td style='padding: 8px;'>{reason}</td>
            <td style='text-align: center; padding: 8px;'>9983</td>
            <td style='text-align: center; padding: 8px;'>1</td>
            <td style='text-align: right; padding: 8px;'>{format_amount(base_amount)}</td>
            <td style='text-align: right; padding: 8px;'>{format_amount(base_amount)}</td>
            <td style='text-align: center; padding: 8px;'>{gst_rate}%</td>
            <td style='text-align: right; padding: 8px;'>{format_amount(gst_amount)}</td>
            <td style='text-align: right; padding: 8px;'>{format_amount(total_amount)}</td>
        </tr>
        """
    
    # Totals row with GST breakup
    is_interstate = invoice.get('igst_amount', 0) > 0
    
    if is_interstate:
        # Interstate GST (IGST)
        igst_amount = invoice.get('igst_amount', invoice.get('gst_amount', 0))
        gst_breakup = f"""
        <tr>
            <td colspan='6' style='text-align: right; padding: 8px;'><strong>IGST Total:</strong></td>
            <td style='text-align: right; padding: 8px;'>{format_amount(igst_amount)}</td>
            <td></td>
        </tr>
        """
    else:
        # Intrastate GST (CGST + SGST)
        cgst_amount = invoice.get('cgst_amount', invoice.get('gst_amount', 0) / 2)
        sgst_amount = invoice.get('sgst_amount', invoice.get('gst_amount', 0) / 2)
        gst_breakup = f"""
        <tr>
            <td colspan='6' style='text-align: right; padding: 8px;'><strong>CGST Total:</strong></td>
            <td style='text-align: right; padding: 8px;'>{format_amount(cgst_amount)}</td>
            <td></td>
        </tr>
        <tr>
            <td colspan='6' style='text-align: right; padding: 8px;'><strong>SGST Total:</strong></td>
            <td style='text-align: right; padding: 8px;'>{format_amount(sgst_amount)}</td>
            <td></td>
        </tr>
        """

    html += f"""
    <tr style='border-top: 2px solid #ddd; background-color: #f9f9f9;'>
        <td colspan='4' style='padding: 8px;'><strong>Taxable Amount</strong></td>
        <td style='text-align: right; padding: 8px;'><strong>{format_amount(invoice['base_amount'])}</strong></td>
        <td colspan='3'></td>
    </tr>
    {gst_breakup}
    <tr style='font-weight: bold; background-color: #f2f2f2;'>
        <td colspan='6' style='text-align: right; padding: 8px;'>Grand Total:</td>
        <td colspan='2' style='text-align: right; padding: 8px;'>{format_amount(invoice['total_amount'])}</td>
    </tr>
    </table>
    """
    
    # Amount in words
    total_in_words = f"Rupees {num_to_words(invoice.get('total_amount', 0))} Only"
    html += f"""
    <div style='margin-top: 15px; border-top: 1px solid #eee; padding-top: 10px;'>
        <p><strong>Amount in Words:</strong> {total_in_words}</p>
    </div>
    """
    
    # Bank details and terms
    html += f"""
    <div style='margin-top: 15px; border-top: 1px solid #eee; padding-top: 10px;'>
        <div style='display: flex;'>
            <div style='flex: 1;'>
                <h4>Bank Details:</h4>
                <p>Account Name: Your Business Name<br>
                Account Number: XXXXXXXXXXXX<br>
                IFSC: XXXXXX00000<br>
                Bank: Your Bank Name</p>
            </div>
            <div style='flex: 1; text-align: right;'>
                <h4>For Your Business</h4>
                <p style='margin-top: 50px;'>Authorized Signatory</p>
            </div>
        </div>
    </div>
    
    <div style='margin-top: 15px; border-top: 1px solid #eee; padding-top: 10px;'>
        <p><strong>Terms & Conditions:</strong></p>
        <ol style='margin: 5px 0; padding-left: 20px;'>
            <li>Payment is due within 30 days of invoice date.</li>
            <li>Please include the invoice number with your payment.</li>
            <li>GST calculation as per applicable rates.</li>
        </ol>
    </div>
    
    <div style='margin-top: 15px; border-top: 1px solid #eee; padding-top: 10px;'>
        <p><strong>Status:</strong> <span style='color: #FF9800;'>{invoice['status'].upper()}</span></p>
    </div>
    """
    
    # Additional details if any
    if invoice.get('details') and isinstance(invoice['details'], dict) and invoice['details']:
        html += "<div style='margin-top: 15px;'><p><strong>Additional Details:</strong></p><ul>"
        for key, value in invoice['details'].items():
            if key != 'reason' and key != 'amount':  # Skip these as they're already displayed
                html += f"<li><strong>{key.capitalize()}:</strong> {value}</li>"
        html += "</ul></div>"
    
    # Add download PDF button
    html += f"""
    <br>
    <div style='text-align: center;'>
        <a href='/download_invoice/{invoice["id"]}' 
           style='display: inline-block; background-color: #128C7E; color: white; padding: 8px 15px; 
                  text-decoration: none; border-radius: 4px; font-weight: bold;'>
           ⬇️ Download PDF
        </a>
    </div>
    """
    
    html += "</div>"
    
    return html

def generate_invoice_pdf(invoice):
    """Generate a PDF document for an invoice.
    
    Args:
        invoice: The invoice object
        
    Returns:
        Path to the generated PDF file
    """
    if not invoice:
        return None
    
    try:
        # Create PDF object with UTF-8 encoding support
        pdf = FPDF()
        # Add a Unicode font that supports the Rupee symbol
        pdf.add_page()
        
        # Set up fonts
        pdf.set_font('Arial', 'B', 16)
        
        # Company/Seller info
        pdf.cell(190, 10, 'INVOICE', 0, 1, 'C')
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(190, 10, f'Invoice #{invoice["id"]}', 0, 1, 'C')
        
        # Date info
        pdf.set_font('Arial', '', 10)
        # Convert date string to date object for better formatting
        date_str = invoice.get('date', '')
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
            formatted_date = date_obj.strftime("%d %b, %Y")
        except:
            formatted_date = date_str
            
        due_date = invoice.get('due_date', '')
        
        pdf.cell(95, 10, f'Date: {formatted_date}', 0, 0)
        pdf.cell(95, 10, f'Due Date: {due_date}', 0, 1)
        
        # Customer/Recipient info
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(190, 10, 'Bill To:', 0, 1)
        pdf.set_font('Arial', '', 10)
        pdf.cell(190, 6, invoice.get('recipient', 'Customer'), 0, 1)
        
        # GST information if available
        if invoice.get('recipient_gst'):
            pdf.cell(190, 6, f"Buyer GST: {invoice['recipient_gst']}", 0, 1)
        if invoice.get('sender_gst'):
            pdf.cell(190, 6, f"Seller GST: {invoice['sender_gst']}", 0, 1)
        
        # Place of Supply (mandatory for GST compliance)
        place_of_supply = invoice.get('place_of_supply', 'Not Specified')
        pdf.cell(190, 6, f"Place of Supply: {place_of_supply}", 0, 1)
            
        pdf.ln(10)
        
        # Items table header
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(50, 10, 'Item', 1, 0, 'L')
        pdf.cell(15, 10, 'HSN/SAC', 1, 0, 'C')
        pdf.cell(15, 10, 'Qty', 1, 0, 'C')
        pdf.cell(25, 10, 'Amount', 1, 0, 'R')
        pdf.cell(20, 10, 'GST Rate', 1, 0, 'C')
        pdf.cell(25, 10, 'GST Amt', 1, 0, 'R')
        pdf.cell(40, 10, 'Total', 1, 1, 'R')
        
        # Items details
        pdf.set_font('Arial', '', 10)
        
        # Check if we have the new items structure or need to use the legacy structure
        if 'items' in invoice:
            # New structure with multiple items
            for item in invoice['items']:
                item_name = item.get('name', 'Item')
                # Sanitize item name for display
                if "invoice to" in item_name.lower() or "create invoice" in item_name.lower():
                    item_name = "Professional Services"
                # If already named Website Development, keep it, or if it contains the keyword, name it properly
                elif item_name == "Website Development" or "website development" in item_name.lower():
                    item_name = "Website Development"
                # Get HSN/SAC code or use default
                hsn_code = item.get('hsn_code', '-')
                # Get quantity or use default
                quantity = item.get('quantity', '1')
                base_amount = item.get('base_amount', 0)
                gst_rate = item.get('gst_rate', 18)
                gst_amount = item.get('gst_amount', 0)
                total_amount = item.get('total_amount', 0)
                
                # Use Rs. instead of ₹ to avoid encoding issues
                pdf.cell(50, 8, item_name[:20], 1, 0, 'L')  # Limit length to fit
                pdf.cell(15, 8, str(hsn_code), 1, 0, 'C')
                pdf.cell(15, 8, str(quantity), 1, 0, 'C')
                pdf.cell(25, 8, f"Rs. {base_amount:,.2f}", 1, 0, 'R')
                pdf.cell(20, 8, f"{gst_rate}%", 1, 0, 'C')
                pdf.cell(25, 8, f"Rs. {gst_amount:,.2f}", 1, 0, 'R')
                pdf.cell(40, 8, f"Rs. {total_amount:,.2f}", 1, 1, 'R')
        else:
            # Legacy structure with a single item
            reason = invoice.get('reason', 'Services')
            # If the reason is website development, make sure to standardize the capitalization
            if "website development" in reason.lower():
                reason = "Website Development"
            base_amount = invoice.get('base_amount', 0)
            gst_rate = invoice.get('gst_rate', 18)
            gst_amount = invoice.get('gst_amount', 0)
            total_amount = invoice.get('total_amount', 0)
            
            # Assign HSN code based on the service description
            hsn_code = "9983"  # Default IT consulting service
            if "website" in reason.lower() or "web" in reason.lower():
                hsn_code = "9983"  # Web portal design and development services
            elif "software" in reason.lower() or "app" in reason.lower():
                hsn_code = "9983"  # Software development services
            elif "consult" in reason.lower() or "advisory" in reason.lower():
                hsn_code = "9983"  # Management consultancy services 
            elif "design" in reason.lower() or "graphic" in reason.lower():
                hsn_code = "9983"  # Graphic design services
            elif "marketing" in reason.lower() or "seo" in reason.lower():
                hsn_code = "9983"  # Marketing/advertising services
            
            pdf.cell(50, 8, reason[:20], 1, 0, 'L')  # Limit length to fit
            pdf.cell(15, 8, hsn_code, 1, 0, 'C')
            pdf.cell(15, 8, '1', 1, 0, 'C')
            pdf.cell(25, 8, f"Rs. {base_amount:,.2f}", 1, 0, 'R')
            pdf.cell(20, 8, f"{gst_rate}%", 1, 0, 'C')
            pdf.cell(25, 8, f"Rs. {gst_amount:,.2f}", 1, 0, 'R')
            pdf.cell(40, 8, f"Rs. {total_amount:,.2f}", 1, 1, 'R')
            
        # Total row
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(105, 10, 'Total:', 1, 0, 'R')
        pdf.cell(45, 10, f"Rs. {invoice.get('gst_amount', 0):,.2f}", 1, 0, 'R')
        pdf.cell(40, 10, f"Rs. {invoice.get('total_amount', 0):,.2f}", 1, 1, 'R')
        
        # Amount in words
        total_in_words = f"Rupees {num_to_words(invoice.get('total_amount', 0))} Only"
        pdf.ln(5)
        pdf.cell(190, 8, f"Amount in Words: {total_in_words}", 0, 1)
        
        # Bank details
        pdf.ln(5)
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(190, 8, 'Bank Details:', 0, 1)
        pdf.set_font('Arial', '', 9)
        pdf.cell(190, 6, 'Account Name: Your Business Name', 0, 1)
        pdf.cell(190, 6, 'Account Number: XXXXXXXXXXXX', 0, 1)
        pdf.cell(190, 6, 'IFSC: XXXXXX00000', 0, 1)
        pdf.cell(190, 6, 'Bank: Your Bank Name', 0, 1)
        
        # Terms and conditions
        pdf.ln(5)
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(190, 8, 'Terms & Conditions:', 0, 1)
        pdf.set_font('Arial', '', 8)
        pdf.multi_cell(190, 5, '1. Payment is due within 30 days of invoice date.\n2. Please include the invoice number with your payment.\n3. GST calculation as per applicable rates.')
        
        # Add status and signature
        pdf.ln(5)
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(100, 8, f"Status: {invoice.get('status', 'PENDING').upper()}", 0, 0)
        pdf.cell(90, 8, "For Your Business Name", 0, 1, 'R')
        pdf.ln(15)
        pdf.cell(190, 8, "Authorized Signatory", 0, 1, 'R')
        
        # Create PDF file
        # Use tempfile to create a temporary file that will be automatically cleaned up
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as pdf_file:
            pdf_path = pdf_file.name
            pdf.output(pdf_path)
            return pdf_path
            
    except Exception as e:
        logger.error(f"Error generating PDF: {str(e)}")
        return None

def num_to_words(num):
    """Convert a number to words for display in invoices."""
    try:
        num = float(num)
    except:
        return "zero"
    
    under_20 = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 
                'ten', 'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen', 
                'seventeen', 'eighteen', 'nineteen']
    tens = ['', '', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety']
    
    if num < 20:
        return under_20[int(num)]
    
    if num < 100:
        return tens[int(num/10)] + ('' if num % 10 == 0 else ' ' + under_20[int(num % 10)])
    
    if num < 1000:
        return under_20[int(num/100)] + ' hundred' + ('' if num % 100 == 0 else ' and ' + num_to_words(num % 100))
    
    if num < 100000:
        return num_to_words(int(num/1000)) + ' thousand' + ('' if num % 1000 == 0 else ' ' + num_to_words(num % 1000))
    
    if num < 10000000:
        return num_to_words(int(num/100000)) + ' lakh' + ('' if num % 100000 == 0 else ' ' + num_to_words(num % 100000))
    
    return num_to_words(int(num/10000000)) + ' crore' + ('' if num % 10000000 == 0 else ' ' + num_to_words(num % 10000000))

def parse_direct_date(date_str):
    """
    Parse a date from natural language expressions with enhanced capabilities
    """
    if not date_str:
        return None
        
    date_str = date_str.lower().strip()
    today = datetime.now()
    
    # Handle common date expressions
    if date_str in ["today", "now"]:
        return today.strftime("%Y-%m-%d")
    elif date_str in ["yesterday"]:
        return (today - timedelta(days=1)).strftime("%Y-%m-%d")
    elif date_str in ["day before yesterday"]:
        return (today - timedelta(days=2)).strftime("%Y-%m-%d")
    elif date_str in ["tomorrow"]:
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")
    
    # Handle "X days ago" pattern
    days_ago_match = re.search(r'(\d+)\s+days?\s+ago', date_str)
    if days_ago_match:
        days = int(days_ago_match.group(1))
        return (today - timedelta(days=days)).strftime("%Y-%m-%d")
    
    # Handle "X weeks ago" pattern
    weeks_ago_match = re.search(r'(\d+)\s+weeks?\s+ago', date_str)
    if weeks_ago_match:
        weeks = int(weeks_ago_match.group(1))
        return (today - timedelta(weeks=weeks)).strftime("%Y-%m-%d")
    
    # Day of week references
    days_of_week = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6
    }
    
    for day_name, weekday_num in days_of_week.items():
        if day_name in date_str:
            # Calculate days to go back to reach the last occurrence of this day
            days_back = (today.weekday() - weekday_num) % 7
            if days_back == 0:  # It's today
                if "last" in date_str:  # "last monday" means previous week
                    days_back = 7
            
            target_date = today - timedelta(days=days_back)
            return target_date.strftime("%Y-%m-%d")
    
    # Try to extract month names or dates
    months = {
        "jan": 1, "january": 1,
        "feb": 2, "february": 2,
        "mar": 3, "march": 3,
        "apr": 4, "april": 4,
        "may": 5,
        "jun": 6, "june": 6,
        "jul": 7, "july": 7,
        "aug": 8, "august": 8,
        "sep": 9, "september": 9,
        "oct": 10, "october": 10,
        "nov": 11, "november": 11,
        "dec": 12, "december": 12
    }
    
    # Check for quarter references
    if "q1" in date_str or "first quarter" in date_str:
        year = today.year
        year_match = re.search(r'\b(20\d{2})\b', date_str)
        if year_match:
            year = int(year_match.group(1))
        return f"{year}-01-01"  # Start of Q1
    elif "q2" in date_str or "second quarter" in date_str:
        year = today.year
        year_match = re.search(r'\b(20\d{2})\b', date_str)
        if year_match:
            year = int(year_match.group(1))
        return f"{year}-04-01"  # Start of Q2
    elif "q3" in date_str or "third quarter" in date_str:
        year = today.year
        year_match = re.search(r'\b(20\d{2})\b', date_str)
        if year_match:
            year = int(year_match.group(1))
        return f"{year}-07-01"  # Start of Q3
    elif "q4" in date_str or "fourth quarter" in date_str:
        year = today.year
        year_match = re.search(r'\b(20\d{2})\b', date_str)
        if year_match:
            year = int(year_match.group(1))
        return f"{year}-10-01"  # Start of Q4
    
    # Check for month and day pattern (e.g., "April 5" or "5 April")
    for month_name, month_num in months.items():
        if month_name in date_str:
            # Try to extract the day
            day_match = re.search(r'(\d{1,2})(st|nd|rd|th)?\s+' + month_name, date_str) or \
                       re.search(month_name + r'\s+(\d{1,2})(st|nd|rd|th)?', date_str)
            
            # If we found a day, use it, otherwise use the 1st day of the month
            if day_match:
                day = int(day_match.group(1))
                if 1 <= day <= 31:
                    # Extract year if present, otherwise use current year
                    year = today.year
                    year_match = re.search(r'\b(20\d{2})\b', date_str)
                    if year_match:
                        year = int(year_match.group(1))
                    
                    # Check for "last year" context
                    if "last year" in date_str or "previous year" in date_str:
                        year = today.year - 1
                        
                    return f"{year}-{month_num:02d}-{day:02d}"
            else:
                # Just month name without day, assume 1st day of month
                year = today.year
                year_match = re.search(r'\b(20\d{2})\b', date_str)
                if year_match:
                    year = int(year_match.group(1))
                
                return f"{year}-{month_num:02d}-01"
                    
    # Try to parse as YYYY-MM-DD, DD/MM/YYYY, MM/DD/YYYY
    date_formats = [
        r'(\d{4})-(\d{1,2})-(\d{1,2})',  # YYYY-MM-DD
        r'(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})',  # DD/MM/YYYY or MM/DD/YYYY
        r'(\d{1,2})[/.-](\d{1,2})'  # DD/MM or MM/DD (assume current year)
    ]
    
    for date_format in date_formats:
        match = re.search(date_format, date_str)
        if match:
            if len(match.groups()) == 3:
                if len(match.group(1)) == 4:  # YYYY-MM-DD
                    year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
                else:  # DD/MM/YYYY or MM/DD/YYYY
                    # For simplicity, assume DD/MM/YYYY format (common in India)
                    day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
                    # But handle potential US format MM/DD/YYYY
                    if month > 12 and day <= 12:
                        day, month = month, day
                        
                # Validate date components
                if 1 <= month <= 12 and 1 <= day <= 31:
                    return f"{year}-{month:02d}-{day:02d}"
            else:  # DD/MM or MM/DD (assume current year)
                first, second = int(match.group(1)), int(match.group(2))
                # If first number > 12, assume it's a day
                if first > 12 and second <= 12:
                    day, month = first, second
                else:
                    # Otherwise assume DD/MM format (common in India)
                    day, month = first, second
                    
                # Validate date components
                if 1 <= month <= 12 and 1 <= day <= 31:
                    return f"{today.year}-{month:02d}-{day:02d}"
    
    # Check for "last/next month", "last/next year", "beginning/start of month/year", "end of month/year" patterns
    if "last month" in date_str or "previous month" in date_str:
        # Last month (first day)
        if "beginning" in date_str or "start" in date_str:
            return (today.replace(day=1) - timedelta(days=1)).replace(day=1).strftime("%Y-%m-%d")
        # Last month (last day)
        elif "end" in date_str:
            return (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m-%d")
        # Last month (same day)
        else:
            last_month = today.replace(day=1) - timedelta(days=1)
            day = min(today.day, [31, 29 if last_month.year % 4 == 0 else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][last_month.month-1])
            return last_month.replace(day=day).strftime("%Y-%m-%d")
    elif "next month" in date_str:
        # Next month (first day)
        if "beginning" in date_str or "start" in date_str:
            next_month = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
            return next_month.strftime("%Y-%m-%d")
        # Next month (last day)
        elif "end" in date_str:
            next_month = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
            last_day = ([31, 29 if next_month.year % 4 == 0 else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][next_month.month-1])
            return next_month.replace(day=last_day).strftime("%Y-%m-%d")
        # Next month (same day)
        else:
            next_month = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
            day = min(today.day, [31, 29 if next_month.year % 4 == 0 else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][next_month.month-1])
            return next_month.replace(day=day).strftime("%Y-%m-%d")
    elif "last year" in date_str or "previous year" in date_str:
        # Last year (same day)
        return today.replace(year=today.year-1).strftime("%Y-%m-%d")
    elif "beginning of the year" in date_str or "start of the year" in date_str:
        # Beginning of current year
        return today.replace(month=1, day=1).strftime("%Y-%m-%d")
    elif "end of the year" in date_str:
        # End of current year
        return today.replace(month=12, day=31).strftime("%Y-%m-%d")
        
    # If no pattern matches, return None
    return None

def parse_direct_command(command, command_type="expense"):
    """
    Parse a direct command for expense/income/payment recording with natural language support
    
    Args:
        command: The natural language command
        command_type: The type of command (expense, income, payment)
        
    Returns:
        Dictionary with extracted parameters or None if parsing fails
    """
    command = command.strip()
    command_lower = command.lower()
    
    # Extract amount
    amount_match = re.search(r'(?:₹|rs\.?|inr|rupees?)\s*([\d,]+(?:\.\d+)?)', command_lower)
    if not amount_match:
        # Try without currency symbol
        amount_match = re.search(r'(?:spent|paid|received|amount|rs|cost|price|bill of)\s+([\d,]+(?:\.\d+)?)', command_lower)
    
    if amount_match:
        amount_str = amount_match.group(1).replace(',', '')
        try:
            amount = float(amount_str)
        except ValueError:
            amount = None
    else:
        amount = None
    
    if not amount:
        # Can't proceed without an amount
        return None
    
    # Extract date
    date = None
    date_patterns = [
        r'(?:on|dated|date|for date)\s+([^,\.]+)',
        r'(?:yesterday|today|tomorrow)'
    ]
    
    for pattern in date_patterns:
        date_match = re.search(pattern, command_lower)
        if date_match:
            date_text = date_match.group(1) if len(date_match.groups()) > 0 else date_match.group(0)
            date = parse_direct_date(date_text)
            if date:
                break
    
    # Extract name (vendor/customer)
    name = None
    name_patterns = [
        r'(?:to|from|vendor|party|customer|client|paid to|received from)\s+([A-Za-z\s&]+?)(?:\s+(?:on|for|amount|₹|rs|dated))',
        r'(?:to|from|vendor|party|customer|client|paid to|received from)\s+([A-Za-z\s&]+)$'
    ]
    
    for pattern in name_patterns:
        name_match = re.search(pattern, command_lower)
        if name_match:
            name = name_match.group(1).strip().title()
            break
    
    # Extract category
    category = None
    category_patterns = [
        r'(?:category|type|under|for)\s+([a-zA-Z\s]+?)(?:\s+(?:on|dated|amount|₹|rs))',
        r'(?:category|type|under|for)\s+([a-zA-Z\s]+)$'
    ]
    
    # If the command contains "for" followed by a noun phrase, it's likely the category
    for pattern in category_patterns:
        category_match = re.search(pattern, command_lower)
        if category_match:
            category = category_match.group(1).strip().capitalize()
            break
    
    # Try to extract notes (everything that wasn't captured by other fields)
    notes = None
    
    # Look for specific notes pattern
    notes_match = re.search(r'notes?:?\s+(.+?)(?:\s+(?:on|dated|category|type)|\s*$)', command_lower)
    if notes_match:
        notes = notes_match.group(1).strip()
    elif "for" in command_lower and not category:
        # If we didn't extract a category but the command has "for", it might be notes
        for_match = re.search(r'for\s+(.+?)(?:\s+(?:on|dated)|\s*$)', command_lower)
        if for_match:
            notes = for_match.group(1).strip()
    
    # Build result dictionary with all extracted fields
    result = {
        "type": command_type,
        "amount": amount
    }
    
    if name:
        result["name"] = name
    if date:
        result["date"] = date
    if category:
        result["category"] = category
    if notes:
        result["notes"] = notes
    
    return result

def get_financial_report(report_type="monthly", month=None, year=None):
    """
    Generate a financial report for a specific period
    
    Args:
        report_type: The type of report ("monthly", "quarterly", "yearly")
        month: Month number (1-12) for monthly reports
        year: Year for the report (defaults to current year)
        
    Returns:
        A dictionary containing the report data
    """
    try:
        # Default to current month and year if not specified
        current_date = datetime.now()
        if not year:
            year = current_date.year
        if not month and report_type == "monthly":
            month = current_date.month
            
        # Load transaction data
        data = load_json_data(TRANSACTIONS_FILE)
        transactions = data.get("transactions", [])
        
        # Initialize report structure
        report = {
            "type": report_type,
            "period": "",
            "summary": {
                "total_income": 0,
                "total_expenses": 0,
                "net_profit": 0
            },
            "income": {
                "total": 0,
                "by_category": {}
            },
            "expenses": {
                "total": 0,
                "by_category": {}
            },
            "transactions": []
        }
        
        # Set period label based on report type
        if report_type == "monthly":
            month_name = current_date.replace(month=month).strftime("%B")
            report["period"] = f"{month_name} {year}"
        elif report_type == "quarterly":
            # Determine quarter based on month
            if not month:
                # Use current quarter if month not specified
                current_quarter = (current_date.month - 1) // 3 + 1
                month = current_quarter * 3  # Last month of the quarter
            else:
                current_quarter = (month - 1) // 3 + 1
            report["period"] = f"Q{current_quarter} {year}"
        else:  # yearly
            report["period"] = f"Year {year}"
            
        # Filter transactions based on report type
        filtered_transactions = []
        
        for transaction in transactions:
            # Parse transaction date
            try:
                tx_date = datetime.strptime(transaction.get("date", ""), "%Y-%m-%d %H:%M:%S")
                
                # Filter based on report type
                include_transaction = False
                
                if report_type == "monthly":
                    include_transaction = (tx_date.year == year and tx_date.month == month)
                elif report_type == "quarterly":
                    tx_quarter = (tx_date.month - 1) // 3 + 1
                    requested_quarter = (month - 1) // 3 + 1
                    include_transaction = (tx_date.year == year and tx_quarter == requested_quarter)
                else:  # yearly
                    include_transaction = (tx_date.year == year)
                    
                if include_transaction:
                    filtered_transactions.append(transaction)
            except:
                # Skip transactions with invalid dates
                continue
        
        # Process filtered transactions
        for transaction in filtered_transactions:
            amount = transaction.get("amount", 0)
            category = transaction.get("category", "Uncategorized")
            tx_type = transaction.get("type", "")
            
            # Add to report transactions list
            report["transactions"].append(transaction)
            
            if tx_type == "income":
                # Process income
                report["summary"]["total_income"] += amount
                report["income"]["total"] += amount
                
                # Update category breakdown
                if category not in report["income"]["by_category"]:
                    report["income"]["by_category"][category] = 0
                report["income"]["by_category"][category] += amount
                
            elif tx_type == "expense":
                # Process expense (expense amounts are negative)
                absolute_amount = abs(amount)
                report["summary"]["total_expenses"] += absolute_amount
                report["expenses"]["total"] += absolute_amount
                
                # Update category breakdown
                if category not in report["expenses"]["by_category"]:
                    report["expenses"]["by_category"][category] = 0
                report["expenses"]["by_category"][category] += absolute_amount
        
        # Calculate net profit
        report["summary"]["net_profit"] = report["summary"]["total_income"] - report["summary"]["total_expenses"]
        
        # Sort transactions by date
        report["transactions"].sort(key=lambda x: x.get("date", ""), reverse=True)
        
        return report
        
    except Exception as e:
        logger.error(f"Error generating financial report: {str(e)}")
        return None

def format_financial_report_html(report):
    """
    Format a financial report as HTML for display in the chat
    
    Args:
        report: The financial report object from get_financial_report()
        
    Returns:
        HTML string for display
    """
    if not report:
        return "No report data available."
    
    # Format main report figures
    html = f"""<div style='border: 1px solid #ddd; padding: 15px; border-radius: 8px;'>
    <h3 style='color: #128C7E; margin-top: 0;'>Financial Report - {report["period"]}</h3>
    
    <div style='display: flex; margin-top: 15px;'>
        <div style='flex: 1; border: 1px solid #eee; padding: 10px; margin-right: 5px; background-color: #f9f9f9;'>
            <p style='font-weight: bold; margin: 0;'>Total Income</p>
            <p style='font-size: 18px; margin: 5px 0;'>{format_amount(report["summary"]["total_income"])}</p>
        </div>
        <div style='flex: 1; border: 1px solid #eee; padding: 10px; margin-left: 5px; margin-right: 5px; background-color: #f9f9f9;'>
            <p style='font-weight: bold; margin: 0;'>Total Expenses</p>
            <p style='font-size: 18px; margin: 5px 0;'>{format_amount(report["summary"]["total_expenses"])}</p>
        </div>
        <div style='flex: 1; border: 1px solid #eee; padding: 10px; margin-left: 5px; background-color: #f0f7f4;'>
            <p style='font-weight: bold; margin: 0;'>Net Profit</p>
            <p style='font-size: 18px; margin: 5px 0; color: {"green" if report["summary"]["net_profit"] >= 0 else "red"};'>
                {format_amount(report["summary"]["net_profit"])}
            </p>
        </div>
    </div>
    """
    
    # Add expense breakdown by category
    if report["expenses"]["by_category"]:
        html += """
        <h4 style='margin-top: 20px; margin-bottom: 10px;'>Expenses by Category</h4>
        <table style='width: 100%; border-collapse: collapse;'>
            <tr style='background-color: #f2f2f2;'>
                <th style='text-align: left; padding: 8px; border: 1px solid #ddd;'>Category</th>
                <th style='text-align: right; padding: 8px; border: 1px solid #ddd;'>Amount</th>
                <th style='text-align: right; padding: 8px; border: 1px solid #ddd;'>% of Total</th>
            </tr>
        """
        
        # Sort categories by amount (highest first)
        sorted_categories = sorted(
            report["expenses"]["by_category"].items(),
            key=lambda x: x[1], 
            reverse=True
        )
        
        for category, amount in sorted_categories:
            percentage = (amount / report["expenses"]["total"]) * 100 if report["expenses"]["total"] > 0 else 0
            html += f"""
            <tr>
                <td style='text-align: left; padding: 8px; border: 1px solid #ddd;'>{category}</td>
                <td style='text-align: right; padding: 8px; border: 1px solid #ddd;'>{format_amount(amount)}</td>
                <td style='text-align: right; padding: 8px; border: 1px solid #ddd;'>{percentage:.1f}%</td>
            </tr>
            """
            
        html += "</table>"
    
    # Add income breakdown by category
    if report["income"]["by_category"]:
        html += """
        <h4 style='margin-top: 20px; margin-bottom: 10px;'>Income by Category</h4>
        <table style='width: 100%; border-collapse: collapse;'>
            <tr style='background-color: #f2f2f2;'>
                <th style='text-align: left; padding: 8px; border: 1px solid #ddd;'>Category</th>
                <th style='text-align: right; padding: 8px; border: 1px solid #ddd;'>Amount</th>
                <th style='text-align: right; padding: 8px; border: 1px solid #ddd;'>% of Total</th>
            </tr>
        """
        
        # Sort categories by amount (highest first)
        sorted_categories = sorted(
            report["income"]["by_category"].items(),
            key=lambda x: x[1], 
            reverse=True
        )
        
        for category, amount in sorted_categories:
            percentage = (amount / report["income"]["total"]) * 100 if report["income"]["total"] > 0 else 0
            html += f"""
            <tr>
                <td style='text-align: left; padding: 8px; border: 1px solid #ddd;'>{category}</td>
                <td style='text-align: right; padding: 8px; border: 1px solid #ddd;'>{format_amount(amount)}</td>
                <td style='text-align: right; padding: 8px; border: 1px solid #ddd;'>{percentage:.1f}%</td>
            </tr>
            """
            
        html += "</table>"
    
    # Add recent transactions
    if report["transactions"]:
        html += """
        <h4 style='margin-top: 20px; margin-bottom: 10px;'>Recent Transactions</h4>
        <table style='width: 100%; border-collapse: collapse;'>
            <tr style='background-color: #f2f2f2;'>
                <th style='text-align: left; padding: 8px; border: 1px solid #ddd;'>Date</th>
                <th style='text-align: left; padding: 8px; border: 1px solid #ddd;'>Description</th>
                <th style='text-align: left; padding: 8px; border: 1px solid #ddd;'>Category</th>
                <th style='text-align: right; padding: 8px; border: 1px solid #ddd;'>Amount</th>
            </tr>
        """
        
        # Show only the 10 most recent transactions
        recent_transactions = sorted(
            report["transactions"],
            key=lambda x: x.get("date", ""),
            reverse=True
        )[:10]
        
        for tx in recent_transactions:
            tx_date = datetime.strptime(tx.get("date", ""), "%Y-%m-%d %H:%M:%S").strftime("%d %b %Y")
            tx_type = tx.get("type", "")
            tx_name = tx.get("name", "")
            tx_category = tx.get("category", "Uncategorized")
            tx_amount = tx.get("amount", 0)
            
            # Format description based on transaction type
            if tx_type == "expense":
                description = f"Paid to {tx_name}" if tx_name else "Expense"
                row_color = "#fff0f0"  # Light red for expenses
            else:  # income
                description = f"Received from {tx_name}" if tx_name else "Income"
                row_color = "#f0fff0"  # Light green for income
                
            html += f"""
            <tr style='background-color: {row_color};'>
                <td style='text-align: left; padding: 8px; border: 1px solid #ddd;'>{tx_date}</td>
                <td style='text-align: left; padding: 8px; border: 1px solid #ddd;'>{description}</td>
                <td style='text-align: left; padding: 8px; border: 1px solid #ddd;'>{tx_category}</td>
                <td style='text-align: right; padding: 8px; border: 1px solid #ddd;'>{format_amount(abs(tx_amount))}</td>
            </tr>
            """
            
        html += "</table>"
    
    html += "</div>"
    return html
    
def get_financial_report(report_type="monthly", month=None, year=None):
    """
    Generate a financial report for a specific period
    
    Args:
        report_type: The type of report ("monthly", "quarterly", "yearly")
        month: Month number (1-12) for monthly reports
        year: Year for the report (defaults to current year)
        
    Returns:
        A dictionary containing the report data
    """
    try:
        # Set default values if not provided
        if year is None:
            year = datetime.now().year
            
        if month is None and report_type == "monthly":
            month = datetime.now().month
            
        # Load transaction data
        transactions_data = load_json_data(TRANSACTIONS_FILE)
        transactions = transactions_data.get("transactions", [])
        
        # Filter transactions based on report type and period
        filtered_transactions = []
        quarter = None
        
        if report_type == "monthly" and month is not None:
            # Filter by specific month and year
            start_date = datetime(year, month, 1)
            # Calculate end date (first day of next month)
            if month == 12:
                end_date = datetime(year + 1, 1, 1)
            else:
                end_date = datetime(year, month + 1, 1)
                
            # Filter transactions in this month
            for transaction in transactions:
                try:
                    trans_date = datetime.strptime(transaction["date"], "%Y-%m-%d %H:%M:%S")
                    if start_date <= trans_date < end_date:
                        filtered_transactions.append(transaction)
                except:
                    # Skip transactions with invalid dates
                    continue
        
        elif report_type == "quarterly":
            # Determine quarter start and end months
            if month is None:
                # Use current quarter if not specified
                current_month = datetime.now().month
                quarter = (current_month - 1) // 3 + 1
                start_month = (quarter - 1) * 3 + 1
            else:
                # Use the quarter containing the specified month
                quarter = (month - 1) // 3 + 1
                start_month = (quarter - 1) * 3 + 1
                
            # Calculate start and end dates for the quarter
            start_date = datetime(year, start_month, 1)
            if start_month + 3 > 12:
                end_date = datetime(year + 1, (start_month + 3) % 12 or 12, 1)
            else:
                end_date = datetime(year, start_month + 3, 1)
                
            # Filter transactions in this quarter
            for transaction in transactions:
                try:
                    trans_date = datetime.strptime(transaction["date"], "%Y-%m-%d %H:%M:%S")
                    if start_date <= trans_date < end_date:
                        filtered_transactions.append(transaction)
                except:
                    # Skip transactions with invalid dates
                    continue
        
        elif report_type == "yearly":
            # Filter by specific year
            start_date = datetime(year, 1, 1)
            end_date = datetime(year + 1, 1, 1)
            
            # Filter transactions in this year
            for transaction in transactions:
                try:
                    trans_date = datetime.strptime(transaction["date"], "%Y-%m-%d %H:%M:%S")
                    if start_date <= trans_date < end_date:
                        filtered_transactions.append(transaction)
                except:
                    # Skip transactions with invalid dates
                    continue
        
        # If no transactions found, return None
        if not filtered_transactions:
            return None
            
        # Calculate report metrics
        total_income = sum(t["amount"] for t in filtered_transactions if t["type"] == "income")
        total_expenses = sum(t["amount"] for t in filtered_transactions if t["type"] == "expense")
        profit = total_income - total_expenses
        
        # Group expenses by category
        expense_categories = {}
        for transaction in filtered_transactions:
            if transaction["type"] == "expense":
                category = transaction.get("category", "Uncategorized")
                if category not in expense_categories:
                    expense_categories[category] = 0
                expense_categories[category] += transaction["amount"]
        
        # Sort expense categories by amount (highest first)
        sorted_expense_categories = sorted(
            expense_categories.items(), 
            key=lambda x: x[1], 
            reverse=True
        )
        
        # Group income by category/source
        income_categories = {}
        for transaction in filtered_transactions:
            if transaction["type"] == "income":
                category = transaction.get("category", "Uncategorized")
                if category not in income_categories:
                    income_categories[category] = 0
                income_categories[category] += transaction["amount"]
        
        # Sort income categories by amount (highest first)
        sorted_income_categories = sorted(
            income_categories.items(), 
            key=lambda x: x[1], 
            reverse=True
        )
        
        # Build the report object
        report = {
            "report_type": report_type,
            "period": {
                "year": year,
                "month": month if report_type == "monthly" else None,
                "quarter": quarter if report_type == "quarterly" else None
            },
            "summary": {
                "total_income": total_income,
                "total_expenses": total_expenses,
                "profit": profit,
                "margin": (profit / total_income * 100) if total_income > 0 else 0
            },
            "expense_categories": sorted_expense_categories,
            "income_categories": sorted_income_categories,
            "transactions": filtered_transactions
        }
        
        return report
        
    except Exception as e:
        logger.error(f"Error generating financial report: {str(e)}")
        return None

def format_financial_report_html(report):
    """
    Format a financial report as HTML for display in the chat
    
    Args:
        report: The financial report object from get_financial_report()
        
    Returns:
        HTML string for display
    """
    try:
        # Extract report data
        report_type = report["report_type"]
        period_info = report["period"]
        summary = report["summary"]
        
        # Format period title
        if report_type == "monthly" and period_info["month"] is not None:
            month_name = datetime(2000, period_info["month"], 1).strftime("%B")
            title = f"Financial Report: {month_name} {period_info['year']}"
        elif report_type == "quarterly" and period_info["quarter"] is not None:
            quarter = period_info["quarter"]
            title = f"Financial Report: Q{quarter} {period_info['year']}"
        else:  # yearly
            title = f"Financial Report: {period_info['year']}"
        
        # Start building the HTML
        html = f"<strong>{title}</strong><br><br>"
        
        # Add summary section
        html += "<strong>📊 Financial Summary</strong><br>"
        html += f"Total Income: {format_amount(summary['total_income'])}<br>"
        html += f"Total Expenses: {format_amount(summary['total_expenses'])}<br>"
        html += f"Profit: {format_amount(summary['profit'])}<br>"
        html += f"Profit Margin: {summary['margin']:.1f}%<br><br>"
        
        # Add expense breakdown
        html += "<strong>💸 Expense Breakdown</strong><br>"
        for category, amount in report["expense_categories"]:
            percent = (amount / summary['total_expenses'] * 100) if summary['total_expenses'] > 0 else 0
            html += f"{category}: {format_amount(amount)} ({percent:.1f}%)<br>"
        
        html += "<br>"
        
        # Add income breakdown
        html += "<strong>💰 Income Sources</strong><br>"
        for category, amount in report["income_categories"]:
            percent = (amount / summary['total_income'] * 100) if summary['total_income'] > 0 else 0
            html += f"{category}: {format_amount(amount)} ({percent:.1f}%)<br>"
        
        # Add recommendation section based on the data
        html += "<br><strong>💡 Insights</strong><br>"
        
        # Profitability insight
        if summary['margin'] > 20:
            html += "• Your profit margin is healthy at over 20%.<br>"
        elif summary['margin'] > 0:
            html += "• Your profit margin is positive but could be improved.<br>"
        else:
            html += "• Your expenses exceeded income during this period.<br>"
        
        # Expense insight
        if report["expense_categories"]:
            top_expense_category, top_expense_amount = report["expense_categories"][0]
            expense_percentage = (top_expense_amount / summary['total_expenses'] * 100) if summary['total_expenses'] > 0 else 0
            
            if expense_percentage > 50:
                html += f"• Your largest expense ({top_expense_category}) accounts for over 50% of all expenses.<br>"
        
        # Income source insight
        if len(report["income_categories"]) == 1:
            html += "• Your income is coming from a single source. Consider diversifying.<br>"
        
        # Growth recommendation
        if report_type != "yearly" and summary['profit'] > 0:
            html += "• Consider reinvesting some profits into business growth.<br>"
        
        return html
        
    except Exception as e:
        logger.error(f"Error formatting financial report: {str(e)}")
        return "There was an error formatting the financial report."
