"""
Politician Name Mapping and Resolution
=======================================

Centralized mapping logic for resolving politician names to canonical identities.
Handles name variations, aliases, and nicknames.

This module is used by:
- Scraper staging ingestion
- Promotion scripts (staging -> production)
- Data cleanup/sync utilities

Usage:
    from utils.politician_mapping import resolve_politician_name, get_or_create_politician
    
    canonical_name = resolve_politician_name("Addison McConnell")  # Returns "Mitch McConnell"
    politician_id = get_or_create_politician(client, "Charles Roy")  # Returns ID for "Chip Roy"
"""

from typing import Dict, Optional, Tuple
from supabase_client import SupabaseClient

# Canonical mapping: Trade Name -> (Canonical Name, Bioguide ID)
# This is the single source of truth for politician name resolution
POLITICIAN_ALIASES = {
    # Known aliases (legal names vs. common names)
    "Addison McConnell": ("Mitch McConnell", "M000355"),
    "Charles Roy": ("Chip Roy", "R000614"),
    "Clifford Franklin": ("Scott Franklin", "F000472"),
    "Charles Fleischmann": ("Chuck Fleischmann", "F000459"),
    "Christine Smith": ("Tina Smith", "S001203"),
    "Richard Allen": ("Rick Allen", "A000372"),
    "Rohit Khanna": ("Ro Khanna", "K000389"),
    "Thomas Tuberville": ("Tommy Tuberville", "T000278"),
    "Daniel Newhouse": ("Dan Newhouse", "N000189"),
    "Gerald Connolly": ("Gerry Connolly", "C001078"),
    "Robert Latta": ("Bob Latta", "L000566"),
    "Jacob Auchincloss": ("Jake Auchincloss", "A000370"),
    
    # Middle initial variations
    "Deborah Ross": ("Deborah K. Ross", "R000305"),
    "Gary Peters": ("Gary C. Peters", "P000595"),
    
    # New members (as of late 2024)
    "Anthony Wied": ("Tony Wied", "W000829"),
    "Rob Bresnahan": ("Robert P. Bresnahan Jr.", "B001327"),
    "Robert Bresnahan": ("Robert P. Bresnahan Jr.", "B001327"),
    "David Taylor": ("David J. Taylor", "T000490"),
    "John McGuire": ("John McGuire III", "M001239"),
    
    # Nickname mappings (FMP API uses short names)
    "Tim Moore": ("Timothy Moore", "M001232"),
    "Tim Burchett": ("Timothy Burchett", "B001309"),
    "Tim Kaine": ("Timothy Kaine", "K000384"),
    "Tim Scott": ("Timothy Scott", "S001184"),
    "Tim Walberg": ("Timothy Walberg", "W000798"),
    "Tim Sheehy": ("Timothy Sheehy", "S001234"),  # New senator (may need update)
    
    # Self-mapping for consistency (canonical name -> itself)
    # These are already in correct form but included for lookup
    "Angus King": ("Angus King", "K000383"),
    "Abigail Spanberger": ("Abigail Spanberger", "S001209"),
    "Adam Schiff": ("Adam Schiff", "S001150"),
    "Andrew Garbarino": ("Andrew Garbarino", "G000597"),
    "Blake Moore": ("Blake Moore", "M001213"),
    "Brian Mast": ("Brian Mast", "M001199"),
    "Carol Miller": ("Carol Miller", "M001205"),
}


def resolve_politician_name(trade_name: str) -> Tuple[str, Optional[str]]:
    """
    Resolve a politician name from trades to its canonical form.
    
    Args:
        trade_name: Name as it appears in trade data (may be alias)
        
    Returns:
        Tuple of (canonical_name, bioguide_id)
        If no mapping exists, returns (trade_name, None)
        
    Examples:
        >>> resolve_politician_name("Addison McConnell")
        ("Mitch McConnell", "M000355")
        
        >>> resolve_politician_name("Nancy Pelosi")
        ("Nancy Pelosi", None)  # No alias, passes through
    """
    if trade_name in POLITICIAN_ALIASES:
        return POLITICIAN_ALIASES[trade_name]
    return (trade_name, None)


def get_or_create_politician(
    client: SupabaseClient,
    trade_name: str,
    party: Optional[str] = None,
    state: Optional[str] = None,
    chamber: Optional[str] = 'House',  # Default to House
    create_if_missing: bool = False
) -> Optional[int]:
    """
    Get politician ID from database, optionally creating if missing.
    
    Args:
        client: Supabase client instance
        trade_name: Name as it appears in trade data
        party: Political party (for creation)
        state: State code (for creation)
        chamber: Chamber (House/Senate) (for creation)
        create_if_missing: If True, insert new politician if not found
        
    Returns:
        Politician ID (integer) or None if not found and create_if_missing=False
        
    Raises:
        ValueError: If politician needs creation but party/state missing
    """
    # Resolve to canonical name
    canonical_name, bioguide_id = resolve_politician_name(trade_name)
    
    # Look up by canonical name
    result = client.supabase.table('politicians')\
        .select('id')\
        .eq('name', canonical_name)\
        .limit(1)\
        .execute()
    
    if result.data:
        return result.data[0]['id']
    
    # Try looking up by Bioguide ID if we have one (in case name varies)
    if bioguide_id:
        result = client.supabase.table('politicians')\
            .select('id')\
            .eq('bioguide_id', bioguide_id)\
            .limit(1)\
            .execute()
        if result.data:
            return result.data[0]['id']
    
    # Not found - should we create?
    if not create_if_missing:
        return None
    
    # Validate required fields
    if not party or not state:
        raise ValueError(
            f"Cannot create politician '{canonical_name}' without party and state. "
            f"Provided: party={party}, state={state}"
        )
    
    # Generate bioguide if not in alias map
    if not bioguide_id:
        import random
        import string
        suffix = ''.join(random.choices(string.digits, k=6))
        bioguide_id = f"TMP{suffix}"
    
    # Insert new politician
    insert_result = client.supabase.table('politicians').insert({
        'name': canonical_name,
        'bioguide_id': bioguide_id,
        'party': party,
        'state': state,
        'chamber': chamber
    }).execute()
    
    if insert_result.data:
        return insert_result.data[0]['id']
    
    return None


def lookup_politician_metadata(
    client: SupabaseClient,
    trade_name: str
) -> Optional[dict]:
    """
    Look up politician metadata (party, state, canonical name) from the database.
    
    This is used by scrapers to enrich trade data with proper metadata.
    
    Args:
        client: Supabase client instance
        trade_name: Name as it appears in trade data
        
    Returns:
        Dictionary with keys: name, party, state, chamber, politician_id
        Or None if politician not found
    """
    # Resolve to canonical name first
    canonical_name, bioguide_id = resolve_politician_name(trade_name)
    
    # Look up by canonical name
    result = client.supabase.table('politicians')\
        .select('id, name, party, state, chamber')\
        .eq('name', canonical_name)\
        .limit(1)\
        .execute()
    
    if result.data:
        politician = result.data[0]
        return {
            'politician_id': politician['id'],
            'name': politician['name'],
            'party': politician['party'],
            'state': politician['state'],
            'chamber': politician['chamber']
        }
    
    # Try by bioguide ID if we have one
    if bioguide_id:
        result = client.supabase.table('politicians')\
            .select('id, name, party, state, chamber')\
            .eq('bioguide_id', bioguide_id)\
            .limit(1)\
            .execute()
        
        if result.data:
            politician = result.data[0]
            return {
                'politician_id': politician['id'],
                'name': politician['name'],
                'party': politician['party'],
                'state': politician['state'],
                'chamber': politician['chamber']
            }
    
    # Not found - return None (caller can decide to skip or create)
    return None


def update_trade_politician_names(client: SupabaseClient, dry_run: bool = True) -> Dict[str, int]:
    """
    Update all trade records to use canonical politician names.
    
    This is a maintenance utility to normalize existing data.
    
    Args:
        client: Supabase client instance
        dry_run: If True, only report changes without updating
        
    Returns:
        Dictionary mapping alias -> count of trades updated
    """
    results = {}
    
    for alias, (canonical, _) in POLITICIAN_ALIASES.items():
        # Skip self-mappings (where alias == canonical)
        if alias == canonical:
            continue
            
        # Count trades with this alias
        count_result = client.supabase.table('congress_trades')\
            .select('id', count='exact')\
            .eq('politician', alias)\
            .execute()
        
        count = count_result.count if hasattr(count_result, 'count') else len(count_result.data)
        
        if count > 0:
            results[alias] = count
            
            if not dry_run:
                # Update to canonical name
                client.supabase.table('congress_trades')\
                    .update({'politician': canonical})\
                    .eq('politician', alias)\
                    .execute()
    
    return results
