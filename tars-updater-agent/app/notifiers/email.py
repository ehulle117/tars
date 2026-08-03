import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import logging
from jinja2 import Environment, FileSystemLoader
from app.config import config

logger = logging.getLogger(__name__)

# Assumes the working directory is the root of the project
env = Environment(loader=FileSystemLoader('templates'))

def send_email(subject, template_name, context):
    smtp_config = config.get("smtp", {})
    if not smtp_config or not smtp_config.get("host") or smtp_config.get("host") == "smtp.example.com":
        logger.warning("SMTP configuration missing or default. Cannot send email.")
        return

    try:
        template = env.get_template(template_name)
        html_content = template.render(**context)

        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = smtp_config.get("from_address")
        msg['To'] = smtp_config.get("to_address")

        msg.attach(MIMEText(html_content, 'html'))

        logger.info(f"Connecting to SMTP server {smtp_config['host']}:{smtp_config['port']}")
        
        server = smtplib.SMTP(smtp_config['host'], smtp_config['port'])
        if smtp_config.get("tls", True):
            server.starttls()
            
        username = smtp_config.get("username")
        password = smtp_config.get("password")
        if username and password:
            server.login(username, password)
            
        server.send_message(msg)
        server.quit()
        logger.info(f"Successfully sent email: {subject}")
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
