"""
Tax advisory module for Munim AI that provides GST and Indian tax information
without requiring external API access.
"""

import re
from datetime import datetime

# GST rate database - structured by category and subcategory
GST_RATES = {
    "goods": {
        "essential": 0,  # 0% - Essential items like fresh vegetables, milk, etc.
        "necessary": 5,  # 5% - Items like sugar, tea, spices
        "standard": 12,  # 12% - Items like processed foods, smartphones
        "luxury": 18,  # 18% - Items like computers, high-end electronics
        "sin": 28,  # 28% - Items like luxury cars, tobacco
    },
    "services": {
        "essential": 0,  # 0% - Healthcare, education
        "basic": 5,  # 5% - Transport, small restaurants
        "standard": 12,  # 12% - Business class travel, budget hotels
        "premium": 18,  # 18% - IT services, banking, telecom
        "luxury": 28,  # 28% - High-end entertainment, luxury hotels
    }
}

# Common HSN/SAC codes
HSN_SAC_CODES = {
    # Services
    "9983": "IT Services (Software development, web design, etc.)",
    "9982": "Legal and accounting services",
    "9981": "Research and development services",
    "9971": "Financial and related services",
    "9963": "Accommodation, food and beverage services",
    "9964": "Passenger transport services",
    "9973": "Leasing or rental services with or without operator",
    "9987": "Maintenance, repair and installation services",
    "9997": "Other services n.e.c.",
    
    # Goods (selected commonly used codes)
    "8471": "Computers and peripherals",
    "8517": "Mobile phones and communication equipment",
    "8523": "Software on physical media",
    "9403": "Office furniture",
    "4820": "Office stationery and supplies",
    "8443": "Printers and printing equipment"
}

# Tax filing deadlines
FILING_DEADLINES = {
    "GSTR-1": "11th of the next month",
    "GSTR-3B": "20th of the next month",
    "GSTR-9": "31st December of the next fiscal year",
    "GSTR-9C": "31st December of the next fiscal year",
    "Income Tax Return (Individual)": "31st July",
    "Income Tax Return (Business)": "31st October",
    "TDS Return": "Quarterly - 31st July, 31st October, 31st January, 31st May"
}

# Tax deduction rates
TDS_RATES = {
    "Salary": "As per income tax slab",
    "Professional Services": "10%",
    "Rent (Equipment)": "2%",
    "Rent (Land/Building)": "10%",
    "Contract Payment": "2%",
    "Commission/Brokerage": "5%",
    "Interest from Bank": "10%"
}

# GST registration thresholds
GST_THRESHOLDS = {
    "Regular Business (Most States)": "₹20 lakh annual turnover",
    "Regular Business (Special Category States)": "₹10 lakh annual turnover",
    "E-commerce Operators": "No threshold (registration mandatory)",
    "Interstate Supply": "No threshold (registration mandatory)",
}

# Common tax-related FAQs
TAX_FAQS = {
    "gst_composition_scheme": """
The GST Composition Scheme is a simplified tax payment option for small businesses.

Key features:
- Available for businesses with turnover up to ₹1.5 crore
- Pay tax at a flat rate (1% for traders, 5% for restaurants, 6% for others)
- Simplified quarterly returns
- Cannot claim input tax credit
- Cannot issue tax invoices
- Cannot engage in interstate supply

To opt for this scheme, file Form GST CMP-02 on the GST portal.
    """,
    
    "gst_invoice_requirements": """
Requirements for a valid GST invoice:

1. Name, address and GSTIN of the supplier
2. Serial number (unique for a financial year)
3. Date of issue
4. Name, address and GSTIN of the recipient (if registered)
5. HSN code or Service Accounting Code
6. Description of goods or services
7. Quantity of goods
8. Total value of goods/services
9. Taxable value of goods/services
10. Tax rate (CGST, SGST/UTGST, IGST)
11. Amount of tax charged
12. Place of supply
13. Signature of supplier or authorized representative
    """,
    
    "igst_vs_cgst_sgst": """
IGST vs CGST/SGST:

- IGST (Integrated GST): Applicable on interstate transactions
  Collected by the Central Government
  
- CGST (Central GST) & SGST (State GST): Applicable on intrastate transactions
  CGST goes to the Central Government
  SGST goes to the State Government
  
The combined CGST + SGST rate equals the IGST rate.
For example, if IGST is 18%, then CGST and SGST would be 9% each.
    """,
    
    "input_tax_credit": """
Input Tax Credit (ITC) in GST:

- ITC allows businesses to claim credit for taxes paid on purchases
- Can be claimed for GST paid on business-related purchases of goods and services
- To claim ITC, you need a valid tax invoice from a registered dealer
- Matched with supplier's GSTR-1 return through the GSTR-2B system
- Cannot be claimed for personal use items, blocked items (like motor vehicles in certain cases), and when supplier hasn't filed returns
- Must be claimed within 6 months from the date of invoice
    """,
    
    "gst_return_types": """
Common GST Return Types:

1. GSTR-1: Monthly/quarterly return for outward supplies
2. GSTR-3B: Monthly/quarterly summary return
3. GSTR-9: Annual return for regular taxpayers
4. GSTR-9A: Annual return for composition taxpayers
5. GSTR-9C: Annual reconciliation statement with audit certification (for turnover above ₹5 crore)
6. GSTR-4: Annual return for composition taxpayers
7. GSTR-7: Return for TDS deductors
8. GSTR-8: Return for e-commerce operators
    """
}

# Latest GST updates and changes - update this section regularly
LATEST_UPDATES = [
    {
        "date": "March 2025",
        "title": "New HSN Code Requirements",
        "description": "From April 1, 2025, 8-digit HSN codes are mandatory for businesses with turnover above ₹5 crore, and 6-digit codes for turnover between ₹1.5 to ₹5 crore."
    },
    {
        "date": "February 2025",
        "title": "E-invoicing Threshold Reduced",
        "description": "E-invoicing is now mandatory for businesses with turnover exceeding ₹10 crore from April 1, 2025."
    },
    {
        "date": "January 2025",
        "title": "GSTR-3B Auto-Population",
        "description": "GSTR-3B will now be auto-populated from GSTR-1 for all taxpayers, making return filing easier and more accurate."
    }
]

# Main function to process tax-related queries
def process_tax_query(query):
    """
    Process a tax-related query and return a response.
    
    Args:
        query: The user's question about taxes or GST
        
    Returns:
        A formatted response with the relevant information
    """
    query_lower = query.lower()
    
    # Check for specific question types
    if re.search(r'gst rate|tax rate|what.*rate', query_lower):
        return get_gst_rate_info(query_lower)
    elif re.search(r'hsn|sac code|hsn code|sac code', query_lower):
        return get_hsn_sac_info(query_lower)
    elif re.search(r'deadline|due date|file.*date|when.*file', query_lower):
        return get_filing_deadline_info(query_lower)
    elif re.search(r'tds|tax deducted|deduction rate', query_lower):
        return get_tds_info(query_lower)
    elif re.search(r'register|registration|threshold', query_lower):
        return get_registration_info(query_lower)
    elif re.search(r'composition scheme|composite scheme', query_lower):
        return get_faq_response("gst_composition_scheme")
    elif re.search(r'invoice|bill|requirements', query_lower):
        return get_faq_response("gst_invoice_requirements")
    elif re.search(r'igst|cgst|sgst|interstate|intrastate', query_lower):
        return get_faq_response("igst_vs_cgst_sgst")
    elif re.search(r'input tax credit|itc|claim.*tax', query_lower):
        return get_faq_response("input_tax_credit")
    elif re.search(r'return type|gstr|which return', query_lower):
        return get_faq_response("gst_return_types")
    elif re.search(r'update|news|recent change|latest', query_lower):
        return get_latest_updates()
    else:
        # General response for unrecognized tax questions
        return provide_general_tax_advice(query_lower)

def get_gst_rate_info(query):
    """Get information about GST rates based on the query"""
    # Check for specific goods or services
    goods_match = re.search(r'rate\s+(?:for|on)\s+([a-zA-Z0-9\s]+)', query)
    item = goods_match.group(1).strip().lower() if goods_match else None
    
    if item:
        # Try to match with known categories
        if any(word in item for word in ["software", "it", "computer", "tech", "website"]):
            return f"""
<strong>GST Rate Information:</strong>

For IT and software services, the applicable GST rate is <strong>18%</strong> (Standard rate for services).
HSN/SAC Code: 9983

This includes software development, website design and maintenance, IT consulting, and similar tech services.
"""
        elif any(word in item for word in ["accounting", "legal", "tax", "lawyer", "ca services"]):
            return f"""
<strong>GST Rate Information:</strong>

For professional services like accounting, legal, and tax advisory, the applicable GST rate is <strong>18%</strong>.
HSN/SAC Code: 9982

This includes services from chartered accountants, lawyers, tax consultants, and similar professionals.
"""
        elif any(word in item for word in ["restaurant", "food", "catering"]):
            return f"""
<strong>GST Rate Information:</strong>

For restaurant and food services:
- Restaurants without AC: <strong>5%</strong> GST (without input tax credit)
- Restaurants with AC or liquor license: <strong>18%</strong> GST
- Outdoor catering: <strong>18%</strong> GST

HSN/SAC Code: 9963
"""
        elif any(word in item for word in ["transport", "travel", "taxi", "freight"]):
            return f"""
<strong>GST Rate Information:</strong>

For transportation services:
- Public transport: <strong>Exempt</strong> from GST
- Air travel (economy): <strong>5%</strong> GST
- Air travel (business): <strong>12%</strong> GST
- Goods transport by road: <strong>5%</strong> GST
- Rail freight: <strong>5%</strong> GST

HSN/SAC Code: 9964-9966 (depending on the specific service)
"""
        else:
            # Generic response if specific item not identified
            return f"""
<strong>GST Rate Information:</strong>

GST rates are categorized as follows:
- 0% - Essential goods and services (healthcare, education)
- 5% - Necessary goods and some basic services
- 12% - Standard goods and services
- 18% - Premium services and luxury goods
- 28% - Sin and ultra-luxury goods

For specific rates for "{item}", please provide more details about its category or HSN/SAC code.
"""
    else:
        # General GST rate information
        return """
<strong>GST Rate Structure in India:</strong>

GST in India follows a multi-tier rate structure:

<strong>0% (Nil Rate):</strong>
- Essential food items
- Healthcare services
- Educational services

<strong>5% Rate:</strong>
- Basic necessities
- Transport services
- Economy hotels

<strong>12% Rate:</strong>
- Processed food
- Business class air tickets
- Smartphones

<strong>18% Rate:</strong>
- IT services
- Telecom services
- Financial services
- Restaurant dining (AC)

<strong>28% Rate:</strong>
- Luxury goods
- Cinema tickets
- High-end automobiles
- Tobacco products

For specific items, please ask about the particular good or service.
"""

def get_hsn_sac_info(query):
    """Get information about HSN/SAC codes"""
    # Check for a specific code
    code_match = re.search(r'(?:code|hsn|sac)\s+(?:for|of)\s+([a-zA-Z0-9\s]+)', query)
    item = code_match.group(1).strip().lower() if code_match else None
    
    if item:
        # Try to find relevant HSN/SAC code for common items
        if any(word in item for word in ["software", "it", "tech", "website", "app"]):
            return f"""
<strong>HSN/SAC Code Information:</strong>

For IT and software services:
- SAC Code: <strong>9983</strong>
- Description: Information technology services including software development, programming, integration, maintenance, web page design, tech support

This code applies to most software-related services including development, testing, and maintenance.
"""
        elif any(word in item for word in ["accounting", "financial", "tax", "ca"]):
            return f"""
<strong>HSN/SAC Code Information:</strong>

For accounting and tax services:
- SAC Code: <strong>9982</strong>
- Description: Legal and accounting services including bookkeeping, auditing, tax consulting

This covers services by chartered accountants, bookkeepers, and tax professionals.
"""
        elif any(word in item for word in ["computer", "laptop", "hardware"]):
            return f"""
<strong>HSN/SAC Code Information:</strong>

For computers and hardware:
- HSN Code: <strong>8471</strong>
- Description: Automatic data processing machines and units thereof

This covers computers, laptops, processors, and related hardware equipment.
"""
        elif any(word in item for word in ["phone", "mobile", "smartphone"]):
            return f"""
<strong>HSN/SAC Code Information:</strong>

For mobile phones and smartphones:
- HSN Code: <strong>8517</strong>
- Description: Telephone sets, including smartphones and other telephones for cellular networks

This covers all types of mobile phones and related communication devices.
"""
        else:
            return f"""
<strong>HSN/SAC Code Information:</strong>

I don't have a specific HSN/SAC code match for "{item}". HSN/SAC codes are 4-8 digit codes used to classify goods and services for GST.

For accurate classification:
1. Check your industry association guidelines
2. Consult the official GST HSN/SAC directory
3. Ask your tax professional for the appropriate code for your specific product/service

Using the correct HSN/SAC code is essential for GST compliance.
"""
    else:
        # General HSN/SAC information
        return """
<strong>HSN/SAC Code Information:</strong>

HSN (Harmonized System of Nomenclature) codes are used for goods, while SAC (Services Accounting Codes) are used for services under GST.

<strong>Importance of HSN/SAC codes:</strong>
- Required on all GST invoices
- Ensures uniform classification across India
- Helps determine the correct GST rate
- Used for GST return filing and reporting

<strong>Digit requirements based on turnover:</strong>
- Annual turnover up to ₹1.5 crore: 4-digit HSN codes
- Annual turnover between ₹1.5 to ₹5 crore: 6-digit HSN codes
- Annual turnover above ₹5 crore: 8-digit HSN codes

Common SAC codes for services:
- 9983: IT and information services
- 9982: Legal and accounting services
- 9971: Financial services
- 9963: Accommodation and food services

For specific codes, please ask about a particular good or service.
"""

def get_filing_deadline_info(query):
    """Get information about tax filing deadlines"""
    current_month = datetime.now().strftime("%B")
    current_year = datetime.now().year
    
    # Check for specific return type
    return_match = re.search(r'(?:deadline|due date)\s+(?:for|of)\s+([a-zA-Z0-9\-\s]+)', query)
    return_type = return_match.group(1).strip().upper() if return_match else None
    
    if return_type and return_type in FILING_DEADLINES:
        return f"""
<strong>Filing Deadline Information:</strong>

The due date for {return_type} is <strong>{FILING_DEADLINES[return_type]}</strong>.

Remember that late filing of returns incurs penalties:
- Late fee of ₹100 per day per tax (CGST & SGST)
- Maximum penalty of ₹5,000
- Interest at 18% per annum on tax liability

It's advisable to file at least 2-3 days before the deadline to avoid last-minute technical issues.
"""
    else:
        # Provide general filing calendar
        return f"""
<strong>Key Tax Filing Deadlines ({current_month} {current_year}):</strong>

<strong>Monthly GST Returns:</strong>
- GSTR-1: 11th of the next month
- GSTR-3B: 20th of the next month

<strong>Quarterly GST Returns (for small taxpayers):</strong>
- GSTR-1: 13th of the month following the quarter
- GSTR-3B: 22nd/24th of the month following the quarter

<strong>Annual GST Returns:</strong>
- GSTR-9/9A (Annual Return): 31st December {current_year}
- GSTR-9C (Reconciliation Statement): 31st December {current_year}

<strong>Income Tax Returns:</strong>
- For individuals without audit: 31st July {current_year}
- For businesses requiring audit: 31st October {current_year}

<strong>TDS Returns:</strong>
- Quarterly: 31st July, 31st October, 31st January, 31st May

For specific return deadlines, please mention the return type (e.g., "deadline for GSTR-3B").
"""

def get_tds_info(query):
    """Get information about TDS rates and rules"""
    # Check for specific TDS type
    tds_match = re.search(r'tds\s+(?:for|on)\s+([a-zA-Z0-9\s]+)', query)
    tds_type = tds_match.group(1).strip().title() if tds_match else None
    
    if tds_type and tds_type in TDS_RATES:
        return f"""
<strong>TDS Information:</strong>

The TDS rate for {tds_type} is <strong>{TDS_RATES[tds_type]}</strong>.

Key points:
- TDS must be deducted at the time of payment or credit, whichever is earlier
- TDS must be deposited by the 7th of the next month
- TDS returns must be filed quarterly
- TDS certificates must be issued to deductees

If payment is below threshold limits, TDS may not be applicable. Please consult with a tax professional for your specific situation.
"""
    else:
        # General TDS information
        return """
<strong>TDS (Tax Deducted at Source) Information:</strong>

Common TDS rates:
- Salary: As per income tax slab
- Professional Services: 10%
- Rent (Equipment): 2%
- Rent (Land/Building): 10%
- Contract Payment: 2%
- Commission/Brokerage: 5%
- Interest from Bank: 10%

Important TDS compliance requirements:
1. Register for TAN (Tax Deduction Account Number)
2. Deduct tax at the applicable rate when making specified payments
3. Deposit TDS with the government by the 7th of the next month
4. File quarterly TDS returns (Form 24Q, 26Q, 27Q)
5. Issue TDS certificates to deductees (Form 16, 16A)

For specific TDS rates, please ask about a particular payment type.
"""

def get_registration_info(query):
    """Get information about GST registration requirements"""
    return """
<strong>GST Registration Requirements:</strong>

<strong>Turnover Thresholds for Mandatory GST Registration:</strong>
- Regular Business (Most States): ₹20 lakh annual turnover
- Regular Business (Special Category States*): ₹10 lakh annual turnover
- E-commerce Operators: No threshold (registration mandatory)
- Interstate Supply: No threshold (registration mandatory)

*Special Category States: Manipur, Mizoram, Nagaland, Tripura, Meghalaya, Arunachal Pradesh, Sikkim, Uttarakhand, Himachal Pradesh, Jammu and Kashmir

<strong>Other cases where registration is mandatory:</strong>
- Casual/Non-resident taxable persons
- Agents of registered persons
- Input Service Distributors
- Persons liable to pay GST under reverse charge
- Electronic Commerce Operators
- Persons supplying through E-commerce Operators

Registration can be done online through the GST portal (www.gst.gov.in) with necessary documents including PAN, business address proof, bank account details, and identity proof.
"""

def get_faq_response(faq_key):
    """Get a standard response for common tax FAQs"""
    if faq_key in TAX_FAQS:
        return f"<strong>{faq_key.replace('_', ' ').title()}:</strong>\n\n{TAX_FAQS[faq_key]}"
    else:
        return "I don't have specific information on this topic. Please ask a more specific tax-related question."

def get_latest_updates():
    """Get information about latest GST and tax updates"""
    updates_html = "<strong>Latest GST and Tax Updates:</strong><br><br>"
    
    for update in LATEST_UPDATES:
        updates_html += f"<strong>{update['date']} - {update['title']}</strong><br>"
        updates_html += f"{update['description']}<br><br>"
        
    updates_html += """
Note: Always verify the latest updates from official sources like:
- GST Portal (www.gst.gov.in)
- Income Tax Department (www.incometaxindia.gov.in)
- Central Board of Indirect Taxes and Customs (www.cbic.gov.in)
"""
    return updates_html

def provide_general_tax_advice(query):
    """Provide general tax advice when a specific query category can't be identified"""
    return f"""
I understand you're asking about Indian tax regulations, but I need more specific details to provide an accurate answer.

You can ask me about:
- GST rates for specific products or services
- HSN/SAC codes for various business activities
- Tax filing deadlines and return types
- TDS rates and requirements
- GST registration thresholds
- Input tax credit rules
- Interstate vs. intrastate GST
- GST composition scheme
- GST invoice requirements
- Recent GST updates and changes

Please rephrase your question to be more specific about which tax aspect you need help with.
"""

def is_tax_query(query):
    """Determine if a query is related to taxes or GST"""
    tax_keywords = [
        'gst', 'tax', 'tds', 'filing', 'return', 'hsn', 'sac', 'igst', 'cgst', 'sgst',
        'input credit', 'itc', 'invoice requirement', 'composition scheme', 'deadline',
        'due date', 'registration', 'threshold', 'reverse charge', 'e-invoice', 'eway bill'
    ]
    
    query_lower = query.lower()
    return any(keyword in query_lower for keyword in tax_keywords)