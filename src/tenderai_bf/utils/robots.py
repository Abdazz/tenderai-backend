"""Utility functions for robots.txt parsing and compliance."""

import re
import urllib.robotparser
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

from ..logging import get_logger

logger = get_logger(__name__)


class RobotsChecker:
    """Check robots.txt compliance for web scraping."""
    
    def __init__(self):
        self._cache: Dict[str, urllib.robotparser.RobotFileParser] = {}
    
    def can_fetch(self, url: str, user_agent: str = "*") -> bool:
        """Check if URL can be fetched according to robots.txt.
        
        Args:
            url: The URL to check
            user_agent: User agent string (default: "*")
            
        Returns:
            True if URL can be fetched, False otherwise
        """
        
        try:
            parsed = urlparse(url)
            base_url = f"{parsed.scheme}://{parsed.netloc}"
            
            # Get robots.txt parser
            rp = self._get_robots_parser(base_url)
            if not rp:
                # If no robots.txt or error, assume allowed
                return True
            
            return rp.can_fetch(user_agent, url)
        
        except Exception as e:
            logger.warning(
                "Error checking robots.txt",
                url=url,
                error=str(e)
            )
            # On error, assume allowed to avoid blocking
            return True
    
    def get_crawl_delay(self, url: str, user_agent: str = "*") -> Optional[float]:
        """Get crawl delay from robots.txt.
        
        Args:
            url: Base URL to check
            user_agent: User agent string
            
        Returns:
            Crawl delay in seconds, or None if not specified
        """
        
        try:
            parsed = urlparse(url)
            base_url = f"{parsed.scheme}://{parsed.netloc}"
            
            rp = self._get_robots_parser(base_url)
            if not rp:
                return None
            
            return rp.crawl_delay(user_agent)
        
        except Exception as e:
            logger.warning(
                "Error getting crawl delay",
                url=url,
                error=str(e)
            )
            return None
    
    def get_request_rate(self, url: str, user_agent: str = "*") -> Optional[tuple]:
        """Get request rate from robots.txt.
        
        Args:
            url: Base URL to check
            user_agent: User agent string
            
        Returns:
            Tuple of (requests, seconds) or None if not specified
        """
        
        try:
            parsed = urlparse(url)
            base_url = f"{parsed.scheme}://{parsed.netloc}"
            
            rp = self._get_robots_parser(base_url)
            if not rp:
                return None
            
            return rp.request_rate(user_agent)
        
        except Exception as e:
            logger.warning(
                "Error getting request rate",
                url=url,
                error=str(e)
            )
            return None
    
    def _get_robots_parser(self, base_url: str) -> Optional[urllib.robotparser.RobotFileParser]:
        """Get robots.txt parser for base URL, with caching.
        
        Args:
            base_url: Base URL (scheme + netloc)
            
        Returns:
            RobotFileParser instance or None if error
        """
        
        if base_url in self._cache:
            return self._cache[base_url]
        
        try:
            robots_url = urljoin(base_url, "/robots.txt")
            
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(robots_url)
            rp.read()
            
            self._cache[base_url] = rp
            
            logger.debug(
                "Loaded robots.txt",
                base_url=base_url,
                robots_url=robots_url
            )
            
            return rp
        
        except Exception as e:
            logger.warning(
                "Failed to load robots.txt",
                base_url=base_url,
                error=str(e)
            )
            # Cache None to avoid repeated attempts
            self._cache[base_url] = None
            return None
    
    def clear_cache(self):
        """Clear the robots.txt cache."""
        self._cache.clear()


# Global instance
_robots_checker = RobotsChecker()


def can_fetch_url(url: str, user_agent: str = "*") -> bool:
    """Check if URL can be fetched according to robots.txt.
    
    Args:
        url: The URL to check
        user_agent: User agent string (default: "*")
        
    Returns:
        True if URL can be fetched, False otherwise
    """
    return _robots_checker.can_fetch(url, user_agent)


def get_crawl_delay(url: str, user_agent: str = "*") -> Optional[float]:
    """Get crawl delay from robots.txt.
    
    Args:
        url: Base URL to check
        user_agent: User agent string
        
    Returns:
        Crawl delay in seconds, or None if not specified
    """
    return _robots_checker.get_crawl_delay(url, user_agent)


def get_request_rate(url: str, user_agent: str = "*") -> Optional[tuple]:
    """Get request rate from robots.txt.
    
    Args:
        url: Base URL to check
        user_agent: User agent string
        
    Returns:
        Tuple of (requests, seconds) or None if not specified
    """
    return _robots_checker.get_request_rate(url, user_agent)


def is_respectful_delay(current_delay: float, robots_delay: Optional[float] = None) -> bool:
    """Check if current delay is respectful of robots.txt.
    
    Args:
        current_delay: Current delay between requests in seconds
        robots_delay: Delay specified in robots.txt
        
    Returns:
        True if delay is respectful, False otherwise
    """
    
    if robots_delay is None:
        # No robots.txt delay specified, check if delay is reasonable
        return current_delay >= 1.0  # At least 1 second
    
    return current_delay >= robots_delay


def validate_user_agent(user_agent: str) -> bool:
    """Validate user agent string format.
    
    Args:
        user_agent: User agent string to validate
        
    Returns:
        True if valid format, False otherwise
    """
    
    if not user_agent or len(user_agent.strip()) == 0:
        return False
    
    # Check for basic format: ProductName/Version
    pattern = r'^[a-zA-Z0-9\-_.]+(/[a-zA-Z0-9\-_.]+)?\s*(\([^)]+\))?\s*$'
    return bool(re.match(pattern, user_agent.strip()))


def get_default_user_agent() -> str:
    """Get default user agent for TenderAI BF.
    
    Returns:
        Default user agent string
    """
    return "TenderAI-BF/1.0 (+https://github.com/your-org/tenderai-bf)"