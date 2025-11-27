import base64
from email.mime.text import MIMEText
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from requests import HTTPError
from app.settings import JSON_FILES, logger


import base64
from email.message import EmailMessage
from google.oauth2.credentials import Credentials

import google.auth
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send"
]

async def send_email(recipient: str, mail_subject: str, jwt_token: str):
    #creds, _ = google.auth.default()

    try:
        creds = Credentials.from_authorized_user_file(JSON_FILES / 'client_secret_gmail.json', SCOPES)
        #flow = InstalledAppFlow.from_client_secrets_file(JSON_FILES / 'client_secret_gmail.json', SCOPES)
        #creds = flow.run_local_server(port=42607)

        service = build("gmail", "v1", credentials=creds)
        message = EmailMessage()

        content = f"""
        Hello,

        Here is your password reset token:
        {jwt_token}

        Send it back to the /auth/password-reset/confirm endpoint with your new password.

        If you didn't request this, please ignore this email.
        """.strip()

        message.set_content(content)

        message["To"] = recipient
        message["From"] = "gduser2@workspacesamples.dev"
        message["Subject"] = "Automated draft"

        # encoded message
        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

        create_message = {"raw": encoded_message}
        # pylint: disable=E1101
        send_message = (
            service.users()
            .messages()
            .send(userId="me", body=create_message)
            .execute()
        )
        print(f'Message Id: {send_message["id"]}')
    except HttpError as error:
        print(f"An error occurred: {error}")
        send_message = None
    return send_message
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    # flow = InstalledAppFlow.from_client_secrets_file(JSON_FILES / 'client_secret_gmail.json', SCOPES)
    # creds = flow.run_local_server(port=0)
    # service = build('gmail', 'v1', credentials=creds)

    # message = MIMEText(
    # f"""
    # Hello,

    # Here is your password reset token:
    # {jwt_token}

    # Send it back to the /auth/password-reset/confirm endpoint with your new password.

    # If you didn't request this, please ignore this email.
    # """
    # )
    # message['to'] = recipient
    # message['subject'] = mail_subject

    # create_message = {'raw': base64.urlsafe_b64encode(message.as_bytes()).decode()}
    # try:
    #     message = (service.users().messages().send(userId="me", body=create_message).execute())
    #     # message.execute()
    #     logger.info(f'Sent {mail_subject} email to {message["to"]}: {message["id"]}')
    # except HTTPError as error:
    #     logger.error(f'An error occurred during {mail_subject} email sending to {message["to"]}: {error}')
    #     message = None