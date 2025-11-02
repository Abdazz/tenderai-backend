"""Date and time utility functions."""

import re
from datetime import datetime, timedelta, timezone
from typing import Optional, Union

import pytz

from ..logging import get_logger

logger = get_logger(__name__)


# Burkina Faso timezone
BURKINA_FASO_TZ = pytz.timezone('Africa/Ouagadougou')

# Common French date patterns
FRENCH_DATE_PATTERNS = [
    # DD/MM/YYYY format
    r'(\d{1,2})/(\d{1,2})/(\d{4})',
    # DD-MM-YYYY format  
    r'(\d{1,2})-(\d{1,2})-(\d{4})',
    # DD.MM.YYYY format
    r'(\d{1,2})\.(\d{1,2})\.(\d{4})',
    # DD MMMM YYYY format (French months)
    r'(\d{1,2})\s+(janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s+(\d{4})',
]

# French month names to numbers
FRENCH_MONTHS = {
    'janvier': 1, 'février': 2, 'mars': 3, 'avril': 4, 'mai': 5, 'juin': 6,
    'juillet': 7, 'août': 8, 'septembre': 9, 'octobre': 10, 'novembre': 11, 'décembre': 12
}


def parse_french_date(date_str: str) -> Optional[datetime]:
    """Parse French date string to datetime object.
    
    Args:
        date_str: Date string in various French formats
        
    Returns:
        Parsed datetime object or None if parsing failed
    """
    
    if not date_str:
        return None
    
    date_str = date_str.strip().lower()
    
    try:
        # Try numeric patterns first
        for pattern in FRENCH_DATE_PATTERNS[:3]:  # DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY
            match = re.search(pattern, date_str)
            if match:
                day, month, year = map(int, match.groups())
                return datetime(year, month, day, tzinfo=BURKINA_FASO_TZ)
        
        # Try French month name pattern
        pattern = FRENCH_DATE_PATTERNS[3]  # DD MMMM YYYY
        match = re.search(pattern, date_str)
        if match:
            day = int(match.group(1))
            month_name = match.group(2)
            year = int(match.group(3))
            
            month = FRENCH_MONTHS.get(month_name)
            if month:
                return datetime(year, month, day, tzinfo=BURKINA_FASO_TZ)
        
        # Try ISO format as fallback
        return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
    
    except (ValueError, IndexError) as e:
        logger.debug(
            "Failed to parse French date",
            date_str=date_str,
            error=str(e)
        )
        return None


def parse_deadline(deadline_str: str, reference_date: Optional[datetime] = None) -> Optional[datetime]:
    """Parse deadline string with various formats.
    
    Args:
        deadline_str: Deadline string (e.g., "dans 5 jours", "le 15/12/2024")
        reference_date: Reference date for relative deadlines (default: now)
        
    Returns:
        Parsed deadline datetime or None if parsing failed
    """
    
    if not deadline_str:
        return None
    
    if reference_date is None:
        reference_date = get_burkina_faso_now()
    
    deadline_str = deadline_str.strip().lower()
    
    try:
        # Try absolute date first
        absolute_date = parse_french_date(deadline_str)
        if absolute_date:
            return absolute_date
        
        # Try relative patterns
        # "dans X jours"
        match = re.search(r'dans\s+(\d+)\s+jours?', deadline_str)
        if match:
            days = int(match.group(1))
            return reference_date + timedelta(days=days)
        
        # "dans X semaines"
        match = re.search(r'dans\s+(\d+)\s+semaines?', deadline_str)
        if match:
            weeks = int(match.group(1))
            return reference_date + timedelta(weeks=weeks)
        
        # "dans X mois" (approximate)
        match = re.search(r'dans\s+(\d+)\s+mois', deadline_str)
        if match:
            months = int(match.group(1))
            return reference_date + timedelta(days=months * 30)
        
        # "avant le DD/MM"
        match = re.search(r'avant\s+le\s+(\d{1,2})/(\d{1,2})', deadline_str)
        if match:
            day, month = int(match.group(1)), int(match.group(2))
            year = reference_date.year
            deadline = datetime(year, month, day, tzinfo=BURKINA_FASO_TZ)
            
            # If deadline is in the past, assume next year
            if deadline < reference_date:
                deadline = deadline.replace(year=year + 1)
            
            return deadline
        
        return None
    
    except (ValueError, IndexError) as e:
        logger.debug(
            "Failed to parse deadline",
            deadline_str=deadline_str,
            error=str(e)
        )
        return None


def get_burkina_faso_now() -> datetime:
    """Get current datetime in Burkina Faso timezone.
    
    Returns:
        Current datetime in Africa/Ouagadougou timezone
    """
    return datetime.now(BURKINA_FASO_TZ)


def to_burkina_faso_time(dt: datetime) -> datetime:
    """Convert datetime to Burkina Faso timezone.
    
    Args:
        dt: Datetime object to convert
        
    Returns:
        Datetime in Burkina Faso timezone
    """
    if dt.tzinfo is None:
        # Assume UTC if no timezone
        dt = dt.replace(tzinfo=timezone.utc)
    
    return dt.astimezone(BURKINA_FASO_TZ)


def format_french_date(dt: datetime) -> str:
    """Format datetime in French format.
    
    Args:
        dt: Datetime object to format
        
    Returns:
        Formatted date string in French
    """
    
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=BURKINA_FASO_TZ)
    
    dt_local = to_burkina_faso_time(dt)
    
    # French month names
    month_names = [
        '', 'janvier', 'février', 'mars', 'avril', 'mai', 'juin',
        'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre'
    ]
    
    day = dt_local.day
    month = month_names[dt_local.month]
    year = dt_local.year
    
    return f"{day} {month} {year}"


def format_deadline(dt: datetime, reference_date: Optional[datetime] = None) -> str:
    """Format deadline with relative description.
    
    Args:
        dt: Deadline datetime
        reference_date: Reference date (default: now)
        
    Returns:
        Formatted deadline string with relative info
    """
    
    if reference_date is None:
        reference_date = get_burkina_faso_now()
    
    # Ensure both dates are timezone-aware
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=BURKINA_FASO_TZ)
    if reference_date.tzinfo is None:
        reference_date = reference_date.replace(tzinfo=BURKINA_FASO_TZ)
    
    # Convert to same timezone
    dt_local = to_burkina_faso_time(dt)
    ref_local = to_burkina_faso_time(reference_date)
    
    # Calculate difference
    delta = dt_local.date() - ref_local.date()
    days_diff = delta.days
    
    # Format base date
    formatted_date = format_french_date(dt_local)
    
    # Add relative info
    if days_diff == 0:
        return f"{formatted_date} (aujourd'hui)"
    elif days_diff == 1:
        return f"{formatted_date} (demain)"
    elif days_diff == -1:
        return f"{formatted_date} (hier)"
    elif days_diff > 0:
        if days_diff <= 7:
            return f"{formatted_date} (dans {days_diff} jours)"
        elif days_diff <= 30:
            weeks = days_diff // 7
            return f"{formatted_date} (dans {weeks} semaine{'s' if weeks > 1 else ''})"
        else:
            months = days_diff // 30
            return f"{formatted_date} (dans {months} mois)"
    else:  # Past date
        days_diff = abs(days_diff)
        if days_diff <= 7:
            return f"{formatted_date} (il y a {days_diff} jours)"
        elif days_diff <= 30:
            weeks = days_diff // 7
            return f"{formatted_date} (il y a {weeks} semaine{'s' if weeks > 1 else ''})"
        else:
            months = days_diff // 30
            return f"{formatted_date} (il y a {months} mois)"


def is_business_day(dt: datetime) -> bool:
    """Check if datetime is a business day (Monday-Friday).
    
    Args:
        dt: Datetime to check
        
    Returns:
        True if business day, False otherwise
    """
    dt_local = to_burkina_faso_time(dt)
    return dt_local.weekday() < 5  # Monday=0, Friday=4


def get_next_business_day(dt: Optional[datetime] = None) -> datetime:
    """Get next business day from given date.
    
    Args:
        dt: Reference date (default: now)
        
    Returns:
        Next business day datetime
    """
    if dt is None:
        dt = get_burkina_faso_now()
    
    dt_local = to_burkina_faso_time(dt)
    
    # Start from next day
    next_day = dt_local + timedelta(days=1)
    
    # Find next business day
    while not is_business_day(next_day):
        next_day += timedelta(days=1)
    
    return next_day


def time_until_deadline(deadline: datetime, reference_date: Optional[datetime] = None) -> timedelta:
    """Calculate time remaining until deadline.
    
    Args:
        deadline: Deadline datetime
        reference_date: Reference date (default: now)
        
    Returns:
        Time remaining as timedelta
    """
    if reference_date is None:
        reference_date = get_burkina_faso_now()
    
    return deadline - reference_date


def is_deadline_urgent(deadline: datetime, urgency_days: int = 7) -> bool:
    """Check if deadline is urgent (within specified days).
    
    Args:
        deadline: Deadline datetime
        urgency_days: Number of days to consider urgent (default: 7)
        
    Returns:
        True if deadline is urgent, False otherwise
    """
    remaining = time_until_deadline(deadline)
    return remaining.total_seconds() > 0 and remaining.days <= urgency_days