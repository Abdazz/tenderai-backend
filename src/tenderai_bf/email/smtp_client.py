"""SMTP email client for TenderAI BF report distribution."""

import smtplib
import socket
from datetime import datetime
from email.encoders import encode_base64
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Dict, List, Optional, Union

from ..config import settings
from ..logging import get_logger, log_email_sent

logger = get_logger(__name__)


class SMTPClient:
    """SMTP client for sending emails with TLS support."""
    
    def __init__(self,
                 host: str = None,
                 port: int = None,
                 username: str = None,
                 password: str = None,
                 use_tls: bool = None,
                 use_ssl: bool = None,
                 timeout: int = None):
        """Initialize SMTP client with configuration."""
        
        self.host = host or settings.smtp.host
        self.port = port or settings.smtp.port
        self.username = username or settings.smtp.user
        self.password = password or settings.smtp.password.get_secret_value()
        self.use_tls = use_tls if use_tls is not None else settings.smtp.use_tls
        self.use_ssl = use_ssl if use_ssl is not None else settings.smtp.use_ssl
        self.timeout = timeout or settings.smtp.timeout
        
        logger.info(
            "SMTP client initialized",
            host=self.host,
            port=self.port,
            use_tls=self.use_tls,
            use_ssl=self.use_ssl
        )
    
    def send_email(self,
                   to_addresses: Union[str, List[str]],
                   subject: str,
                   body_text: str,
                   body_html: Optional[str] = None,
                   cc_addresses: Optional[Union[str, List[str]]] = None,
                   bcc_addresses: Optional[Union[str, List[str]]] = None,
                   attachments: Optional[List[Dict]] = None,
                   from_address: Optional[str] = None,
                   from_name: Optional[str] = None,
                   reply_to: Optional[str] = None) -> bool:
        """Send an email with optional attachments."""
        
        try:
            # Normalize addresses to lists
            if isinstance(to_addresses, str):
                to_addresses = [to_addresses]
            if isinstance(cc_addresses, str):
                cc_addresses = [cc_addresses]
            if isinstance(bcc_addresses, str):
                bcc_addresses = [bcc_addresses]
            
            # Set defaults
            from_address = from_address or settings.email.from_address
            from_name = from_name or settings.email.from_name
            reply_to = reply_to or settings.email.reply_to
            
            # Create message
            msg = MIMEMultipart('mixed')
            
            # Set headers
            if from_name:
                msg['From'] = f"{from_name} <{from_address}>"
            else:
                msg['From'] = from_address
            
            msg['To'] = ', '.join(to_addresses)
            if cc_addresses:
                msg['Cc'] = ', '.join(cc_addresses)
            if reply_to:
                msg['Reply-To'] = reply_to
            
            msg['Subject'] = subject
            msg['Date'] = datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S +0000')
            
            # Create body container
            body_container = MIMEMultipart('alternative')
            
            # Add text version
            text_part = MIMEText(body_text, 'plain', 'utf-8')
            body_container.attach(text_part)
            
            # Add HTML version if provided
            if body_html:
                html_part = MIMEText(body_html, 'html', 'utf-8')
                body_container.attach(html_part)
            
            # Attach body to main message
            msg.attach(body_container)
            
            # Add attachments if provided
            if attachments:
                for attachment in attachments:
                    self._add_attachment(msg, attachment)
            
            # Send email
            success = self._send_message(msg, to_addresses, cc_addresses, bcc_addresses)
            
            if success:
                # Log successful sends
                for address in to_addresses:
                    log_email_sent(address, "sent")
                if cc_addresses:
                    for address in cc_addresses:
                        log_email_sent(address, "sent_cc")
                if bcc_addresses:
                    for address in bcc_addresses:
                        log_email_sent(address, "sent_bcc")
            
            return success
            
        except Exception as e:
            logger.error(
                "Failed to send email",
                to_addresses=to_addresses,
                subject=subject,
                error=str(e),
                exc_info=True
            )
            
            # Log failed sends
            for address in to_addresses or []:
                log_email_sent(address, "failed", error=str(e))
            
            return False
    
    def _add_attachment(self, msg: MIMEMultipart, attachment: Dict) -> None:
        """Add an attachment to the email message."""
        
        try:
            # Extract attachment info
            filename = attachment.get('filename', 'attachment')
            content_type = attachment.get('content_type', 'application/octet-stream')
            data = attachment.get('data')
            
            if data is None:
                logger.error("Attachment data is None", filename=filename)
                return
            
            # Create attachment part
            if content_type.startswith('text/'):
                part = MIMEText(data if isinstance(data, str) else data.decode('utf-8'))
            else:
                part = MIMEApplication(data if isinstance(data, bytes) else data.encode('utf-8'))
            
            # Set headers
            part.add_header(
                'Content-Disposition',
                'attachment',
                filename=filename
            )
            
            if content_type:
                part.set_type(content_type)
            
            # Attach to message
            msg.attach(part)
            
            logger.debug(
                "Attachment added",
                filename=filename,
                content_type=content_type,
                size=len(data) if data else 0
            )
            
        except Exception as e:
            logger.error(
                "Failed to add attachment",
                filename=attachment.get('filename', 'unknown'),
                error=str(e),
                exc_info=True
            )
    
    def _send_message(self,
                      msg: MIMEMultipart,
                      to_addresses: List[str],
                      cc_addresses: Optional[List[str]] = None,
                      bcc_addresses: Optional[List[str]] = None) -> bool:
        """Send the prepared message via SMTP."""
        
        try:
            # Collect all recipients
            all_recipients = to_addresses.copy()
            if cc_addresses:
                all_recipients.extend(cc_addresses)
            if bcc_addresses:
                all_recipients.extend(bcc_addresses)
            
            # Connect to SMTP server
            if self.use_ssl:
                server = smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout)
            else:
                server = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
                if self.use_tls:
                    server.starttls()
            
            # Authentication if credentials provided
            if self.username and self.password:
                server.login(self.username, self.password)
            
            # Send message
            server.sendmail(
                from_addr=settings.email.from_address,
                to_addrs=all_recipients,
                msg=msg.as_string()
            )
            
            # Close connection
            server.quit()
            
            logger.info(
                "Email sent successfully",
                recipients=len(all_recipients),
                to_count=len(to_addresses),
                cc_count=len(cc_addresses) if cc_addresses else 0,
                bcc_count=len(bcc_addresses) if bcc_addresses else 0,
                subject=msg['Subject']
            )
            return True
            
        except smtplib.SMTPAuthenticationError as e:
            logger.error("SMTP authentication failed", error=str(e))
            return False
        except smtplib.SMTPRecipientsRefused as e:
            logger.error("SMTP recipients refused", error=str(e))
            return False
        except smtplib.SMTPServerDisconnected as e:
            logger.error("SMTP server disconnected", error=str(e))
            return False
        except socket.timeout as e:
            logger.error("SMTP timeout", error=str(e))
            return False
        except Exception as e:
            logger.error(
                "SMTP send failed",
                error=str(e),
                exc_info=True
            )
            return False
    
    def test_connection(self) -> bool:
        """Test SMTP connection and authentication."""
        
        try:
            # Connect to SMTP server
            if self.use_ssl:
                server = smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout)
            else:
                server = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
                if self.use_tls:
                    server.starttls()
            
            # Test authentication if credentials provided
            if self.username and self.password:
                server.login(self.username, self.password)
            
            # Close connection
            server.quit()
            
            logger.info("SMTP connection test successful")
            return True
            
        except Exception as e:
            logger.error("SMTP connection test failed", error=str(e))
            return False


def _generate_report_email_body(stats: Dict, report_url: str, run_id: str) -> tuple[str, str]:
    """Generate French email body for report distribution."""
    
    # Extract statistics
    sources_checked = stats.get('sources_checked', 0)
    relevant_items = stats.get('relevant_items', 0)
    total_items = stats.get('items_parsed', 0)
    
    # Generate timestamp
    timestamp = datetime.utcnow().strftime('%d/%m/%Y à %H:%M UTC')
    
    # Text version
    text_body = f"""Bonjour,

Voici le rapport quotidien de veille des appels d'offres IT/Ingénierie pour YULCOM Burkina.

RÉSUMÉ DE L'EXÉCUTION
━━━━━━━━━━━━━━━━━━━━━
• Sources consultées : {sources_checked}
• Avis trouvés au total : {total_items}
• Avis pertinents IT/Ingénierie : {relevant_items}
• Généré le : {timestamp}
• ID d'exécution : {run_id}

Le rapport complet est disponible en pièce jointe au format Word (.docx).


━━━━━━━━━━━━━━━━━━━━━

Pour toute question ou support technique, n'hésitez pas à nous contacter.

Cordialement,
L'équipe TenderAI BF
YULCOM Technologies

---
Cet email a été généré automatiquement par le système TenderAI.
Pour vous désabonner ou modifier vos préférences, contactez l'administrateur.
"""
    
    # HTML version
    html_body = f"""
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RFP Watch - Rapport Quotidien</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 600px;
            margin: 0 auto;
            padding: 20px;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 8px 8px 0 0;
            text-align: center;
        }}
        .logo {{
            max-width: 200px;
            height: auto;
            margin-bottom: 15px;
        }}
        .content {{
            background: #f8f9fa;
            border: 1px solid #dee2e6;
            border-top: none;
            padding: 20px;
            border-radius: 0 0 8px 8px;
        }}
        .stats {{
            background: white;
            border-radius: 6px;
            padding: 15px;
            margin: 15px 0;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .stat-item {{
            display: flex;
            justify-content: space-between;
            margin: 8px 0;
            padding: 5px 0;
            border-bottom: 1px solid #eee;
        }}
        .stat-item:last-child {{
            border-bottom: none;
        }}
        .stat-label {{
            font-weight: 500;
        }}
        .stat-value {{
            color: #007bff;
            font-weight: 600;
        }}
        .download-btn {{
            display: inline-block;
            background: #28a745;
            color: white;
            padding: 12px 24px;
            text-decoration: none;
            border-radius: 6px;
            margin: 15px 0;
            font-weight: 500;
        }}
        .footer {{
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid #dee2e6;
            font-size: 0.9em;
            color: #6c757d;
        }}
    </style>
</head>
<body>
    <div class="header">"""
    
    # Add logo if configured
    if settings.email.logo_url:
        html_body += f'\n        <img src="{settings.email.logo_url}" alt="YULCOM Logo" class="logo">\n'
    
    html_body += f"""        <h1>🔍 TenderAI – YULCOM Technologies</h1>
        <p>Rapport quotidien de veille des appels d'offres</p>
    </div>
    
    <div class="content">
        <p>Bonjour,</p>
        
        <p>Voici le rapport quotidien de veille des appels d'offres IT/Ingénierie au Burkina Faso.</p>
        
        <div class="stats">
            <h3>📊 Résumé de l'exécution</h3>
            <div class="stat-item">
                <span class="stat-label">Sources consultées :</span>
                <span class="stat-value">{sources_checked}</span>
            </div>
            <div class="stat-item">
                <span class="stat-label">Avis trouvés au total :</span>
                <span class="stat-value">{total_items}</span>
            </div>
            <div class="stat-item">
                <span class="stat-label">Avis pertinents IT/Ingénierie :</span>
                <span class="stat-value">{relevant_items}</span>
            </div>
            <div class="stat-item">
                <span class="stat-label">Généré le :</span>
                <span class="stat-value">{timestamp}</span>
            </div>
            <div class="stat-item">
                <span class="stat-label">ID d'exécution :</span>
                <span class="stat-value">{run_id}</span>
            </div>
        </div>
        
        <p>Le rapport complet est disponible en <strong>pièce jointe</strong> au format Word (.docx).</p>
        
        
        <div class="footer">
            <p>Pour toute question ou support technique, n'hésitez pas à nous contacter.</p>
            <p><strong>Cordialement,</strong><br>
            L'équipe TenderAI<br>
            YULCOM Technologies</p>
            
            <hr style="margin: 20px 0;">
            <p style="font-size: 0.8em;">
                Cet email a été généré automatiquement par le système TenderAI BF.<br>
                Pour vous désabonner ou modifier vos préférences, contactez l'administrateur.
            </p>
        </div>
    </div>
</body>
</html>
"""
    
    return text_body, html_body


def send_report_email(report_data: bytes, 
                      report_url: str,
                      run_id: str,
                      stats: Dict,
                      recipients: Optional[List[str]] = None) -> bool:
    """Send the daily report email with attachment."""
    
    try:
        # Get SMTP client
        smtp_client = SMTPClient()
        
        # Determine recipients
        if not recipients:
            recipients = [settings.email.to_address]
        
        # Generate timestamp for filename and subject
        timestamp = datetime.utcnow()
        timestamp_str = timestamp.strftime('%Y-%m-%d-%H-%M')
        
        # Generate subject
        subject = f"{settings.email.subject_prefix} – {timestamp_str}"
        
        # Generate email body
        text_body, html_body = _generate_report_email_body(stats, report_url, run_id)
        
        # Prepare attachment
        attachments = [{
            'filename': f"RFP_Watch_BF_{timestamp_str}.docx",
            'content_type': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'data': report_data
        }]
        
        # Send email
        success = smtp_client.send_email(
            to_addresses=recipients,
            subject=subject,
            body_text=text_body,
            body_html=html_body,
            attachments=attachments,
            from_address=settings.email.from_address,
            from_name=settings.email.from_name,
            reply_to=settings.email.reply_to
        )
        
        if success:
            logger.info(
                "Report email sent successfully",
                recipients=len(recipients),
                run_id=run_id,
                report_size=len(report_data)
            )
        
        return success
        
    except Exception as e:
        logger.error(
            "Failed to send report email",
            run_id=run_id,
            error=str(e),
            exc_info=True
        )
        return False


def test_email_configuration() -> bool:
    """Test email configuration by sending a test message."""
    
    try:
        smtp_client = SMTPClient()
        
        # Test connection first
        if not smtp_client.test_connection():
            return False
        
        # Send test email
        test_subject = "TenderAI BF - Test de configuration email"
        test_body = f"""Bonjour,

Ceci est un email de test pour vérifier la configuration SMTP de TenderAI BF.

Configuration testée :
• Serveur SMTP : {settings.smtp.host}:{settings.smtp.port}
• TLS activé : {settings.smtp.use_tls}
• SSL activé : {settings.smtp.use_ssl}
• Heure du test : {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}

Si vous recevez cet email, la configuration est fonctionnelle.

Cordialement,
L'équipe TenderAI BF
"""
        
        success = smtp_client.send_email(
            to_addresses=settings.email.to_address,
            subject=test_subject,
            body_text=test_body,
            from_address=settings.email.from_address,
            from_name=f"{settings.email.from_name} (Test)"
        )
        
        return success
        
    except Exception as e:
        logger.error("Email configuration test failed", error=str(e))
        return False