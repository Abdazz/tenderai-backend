"""Email utilities."""

from .smtp_client import SMTPClient, send_report_email


def test_email_configuration() -> bool:
    """Test if email is properly configured.
    
    Returns:
        bool: True if email is configured, False otherwise.
    """
    try:
        from ..config import settings
        
        # Check if required SMTP settings are present and valid
        smtp = settings.smtp
        
        if not smtp.host or smtp.host == "smtp.example.com":
            return False
        
        if not smtp.user or smtp.user == "user@example.com":
            return False
            
        if not smtp.password or smtp.password == "your-smtp-password":
            return False
        
        # All required settings are present and look configured
        return True
        
    except Exception:
        return False


def send_email(to_address: str, subject: str, body: str, html_body: str = None) -> bool:
    """Send an email using the configured SMTP settings.
    
    Args:
        to_address: Recipient email address
        subject: Email subject
        body: Plain text body
        html_body: Optional HTML body
        
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        client = SMTPClient()
        return client.send_email(
            to_addresses=to_address,  # Changed from to_address to to_addresses
            subject=subject,
            body_text=body,  # Changed from body to body_text
            body_html=html_body  # Changed from html_body to body_html
        )
    except Exception as e:
        from ..logging import get_logger
        logger = get_logger(__name__)
        logger.error(f"Failed to send email: {e}")
        return False


__all__ = ["SMTPClient", "send_report_email", "test_email_configuration", "send_email"]
