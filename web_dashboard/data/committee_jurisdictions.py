"""
Committee Jurisdiction Definitions
===================================

This module defines the "Cheat Sheet" for AI analysis of congressional trades.
Instead of relying on the AI's internal knowledge about committee powers, we inject
explicit descriptions of what each committee regulates.

This is especially important for smaller LLMs (like Granite 8B) that have strong
reasoning capabilities but limited world knowledge.
"""

# The "Cheat Sheet" for the AI
# We inject these descriptions into the prompt so the AI doesn't have to guess.
COMMITTEE_CONTEXT = {
    # --- HIGH POWER COMMITTEES ---
    "House Committee on Appropriations": (
        "Controls ALL government spending and contracts. Direct conflict with any "
        "company receiving federal funds (Defense, Pharma, Construction, Infrastructure)."
    ),
    
    "House Committee on Energy and Commerce": (
        "Regulates Healthcare (Pharma, Hospitals, Insurance), Energy (Oil, Gas, Clean Energy), "
        "Telecommunications (ISPs, Media, Broadcasting), and Technology (Consumer Protection, Data Privacy)."
    ),
    
    "House Committee on Financial Services": (
        "Regulates Banks, Insurance, Fintech, Crypto, and Securities/Stock Markets. "
        "Does NOT regulate retail businesses, restaurants, or non-financial companies."
    ),
    
    "House Committee on Armed Services": (
        "Regulates Defense Contractors (Lockheed Martin, Boeing, Raytheon), Aerospace, "
        "Military Intelligence, and Cybersecurity for defense."
    ),
    
    "House Committee on Ways and Means": (
        "Writes the Tax Code (affects ALL companies) and Trade Policy (Tariffs, Imports/Exports). "
        "Broad but indirect influence."
    ),
    
    # --- SPECIFIC / TECHNICAL COMMITTEES ---
    "House Committee on the Judiciary": (
        "Regulates Antitrust (Big Tech monopolies like Google, Apple, Microsoft), "
        "Intellectual Property (Patents, Copyright, Trademarks), and Immigration Law."
    ),
    
    "House Committee on Science, Space, and Technology": (
        "Regulates NASA, Department of Energy (Nuclear, Clean Energy Research), "
        "National Labs, NOAA (Weather/Climate), and EPA Environmental Standards. "
        "Also oversees energy infrastructure and AI data center regulations."
    ),
    
    "House Committee on Transportation and Infrastructure": (
        "Regulates Airlines, Railroads, Shipping, Highways, and Infrastructure Construction contracts."
    ),
    
    "House Committee on Agriculture": (
        "Regulates Farming, Food Safety, Agricultural Trade, and USDA contracts."
    ),
    
    "House Committee on Education and the Workforce": (
        "Regulates Labor Laws, Education Policy, and Workforce Development. "
        "Limited corporate regulation except for labor/HR issues."
    ),
    
    "House Committee on Homeland Security": (
        "Regulates Border Security, TSA, Cybersecurity (critical infrastructure), "
        "and Emergency Management contracts."
    ),
    
    "House Committee on Natural Resources": (
        "Regulates Public Lands, Mining, Oil/Gas Drilling on Federal Land, and National Parks."
    ),
    
    "House Committee on Oversight and Accountability": (
        "Investigates government waste and contracts. Broad investigative power but limited direct regulation."
    ),
    
    "House Committee on Small Business": (
        "Advocates for small business policy. Limited regulatory power."
    ),
    
    "House Committee on Veterans' Affairs": (
        "Regulates VA Healthcare and Veterans Benefits. Direct conflict with healthcare companies serving veterans."
    ),
    
    # --- SENATE EQUIVALENTS ---
    "Senate Committee on Appropriations": (
        "Controls ALL government spending and contracts (Senate version). "
        "Direct conflict with defense, pharma, construction."
    ),
    
    "Senate Committee on Armed Services": (
        "Regulates Defense Contractors and Military Policy (Senate version)."
    ),
    
    "Senate Committee on Banking, Housing, and Urban Affairs": (
        "Regulates Banks, Federal Reserve, Insurance, and Housing Finance (Fannie Mae, Freddie Mac)."
    ),
    
    "Senate Committee on Commerce, Science, and Transportation": (
        "Regulates Airlines, Railroads, Telecommunications, Technology, and Consumer Protection."
    ),
    
    "Senate Committee on Energy and Natural Resources": (
        "Regulates Energy Production (Oil, Gas, Nuclear, Renewables) and Public Lands."
    ),
    
    "Senate Committee on Environment and Public Works": (
        "Regulates EPA Environmental Standards, Infrastructure contracts, and Highway construction."
    ),
    
    "Senate Committee on Finance": (
        "Writes Tax Code, Trade Policy, Healthcare Funding (Medicare/Medicaid). Broad influence."
    ),
    
    "Senate Committee on Health, Education, Labor, and Pensions": (
        "Regulates Healthcare Policy, Pharma, Education, and Labor Laws."
    ),
    
    "Senate Committee on Homeland Security and Governmental Affairs": (
        "Regulates Cybersecurity, Border Security, and Government Contracts/Oversight."
    ),
    
    "Senate Committee on the Judiciary": (
        "Regulates Antitrust (Big Tech), Intellectual Property (Patents/Copyright), and Immigration."
    ),

    # --- INTELLIGENCE COMMITTEES ---
    "House Permanent Select Committee on Intelligence": (
        "Oversees CIA, NSA, DIA, and all U.S. Intelligence agencies. Direct conflict with Defense Contractors "
        "(Lockheed Martin, Northrop Grumman, Raytheon, General Dynamics, L3Harris), Cybersecurity companies "
        "(Palantir, Booz Allen, SAIC, Leidos), and Satellite/Aerospace (SpaceX contracts, Boeing). "
        "Members have access to classified briefings on defense programs."
    ),

    "Senate Select Committee on Intelligence": (
        "Oversees CIA, NSA, DIA, and all U.S. Intelligence agencies (Senate version). Direct conflict with "
        "Defense Contractors, Cybersecurity companies, and Aerospace. Members receive classified briefings "
        "on national security matters including defense spending and technology programs."
    ),

    # --- LEADERSHIP ---
    "Leadership": (
        "Role: Speaker / Party Leader / Majority Leader. "
        "JURISDICTION: ABSOLUTE. Controls the schedule for ALL legislation in ALL sectors. "
        "Must be flagged for 'Timing Conflicts' (e.g., buying Tech before a Chips Act vote)."
    ),
}


def get_committee_context(committee_string: str) -> str:
    """
    Convert a committee list string into a formatted context block for the AI prompt.
    
    Args:
        committee_string: String like "House Committee on Judiciary (Member) - Sectors: Tech; 
                         House Committee on Science - Sectors: Energy"
    
    Returns:
        Formatted string like:
        "- **House Committee on the Judiciary**: Regulates Antitrust (Big Tech)...
         - **House Committee on Science, Space, and Technology**: Regulates NASA..."
    
    The function uses fuzzy matching to handle slight name variations and extracts
    the core committee name from strings that include ranks/titles/sectors.
    """
    if not committee_string or committee_string in ['Unknown', 'None', 'None (no committee assignments found)']:
        return "**No committee assignments found.** This politician has no regulatory power."
    
    context_lines = []
    
    # Split by semicolon (the current format) and also handle pipe separator
    import re
    committees = re.split(r'[;|]', committee_string)
    
    for comm_raw in committees:
        comm = comm_raw.strip()
        if not comm:
            continue
        
        # Fuzzy match against our context dictionary
        matched = False
        for key, description in COMMITTEE_CONTEXT.items():
            # Check if the key (full committee name) is contained in the committee string
            # This handles cases like "House Committee on the Judiciary (Ranking Member) - Sectors: Tech"
            if key.lower() in comm.lower():
                context_lines.append(f"- **{key}**: {description}")
                matched = True
                break
        
        # If no match found, include the raw committee name without context
        # (the AI will still see it but won't have guidance)
        if not matched:
            # Extract just the committee name (before any parentheses or " - Sectors:")
            clean_name = re.split(r'\s*[\(\-]', comm)[0].strip()
            if clean_name and clean_name not in ['Subcommittee', 'Member', 'Ranking']:
                context_lines.append(f"- **{clean_name}**: (Jurisdiction not defined in context)")
    
    if not context_lines:
        return "**No recognized committee assignments.** Unable to determine regulatory power."
    
    return "\n".join(context_lines)
