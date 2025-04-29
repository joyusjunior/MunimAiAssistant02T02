import os
from flask import Flask, render_template, redirect, url_for, session, request
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required
from google.oauth2 import id_token
from google_auth_oauthlib.flow import Flow
from google.auth.transport import requests
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY')

# Flask-Login setup
login_manager = LoginManager(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, id_, email):
        self.id = id_
        self.email = email

# Google OAuth
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')
flow = Flow.from_client_secrets_file(
    'client_secret.json',
    scopes=['openid', 'https://www.googleapis.com/auth/userinfo.email', 'https://www.googleapis.com/auth/drive.file'],
    redirect_uri='http://localhost:5000/callback'  # Change to Render URL when deploying
)

@login_manager.user_loader
def load_user(user_id):
    return User(session['user']['id'], session['user']['email'])

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/login')
def login():
    auth_url, _ = flow.authorization_url(prompt='consent')
    return redirect(auth_url)

@app.route('/callback')
def callback():
    flow.fetch_token(authorization_response=request.url)
    credentials = flow.credentials
    session['credentials'] = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }

    userinfo = build('oauth2', 'v2', credentials=credentials).userinfo().get().execute()
    user = User(id_=userinfo['id'], email=userinfo['email'])
    login_user(user)
    session['user'] = {'id': userinfo['id'], 'email': userinfo['email'], 'name': userinfo.get('name', '')}
    
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
@login_required
def dashboard():
    credentials = google.oauth2.credentials.Credentials(**session['credentials'])
    drive_service = build('drive', 'v3', credentials=credentials)
    
    # Create a folder for the user (if it doesn't exist)
    folder_name = f"MunimAI_{session['user']['id']}"
    folders = drive_service.files().list(
        q=f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder'",
        spaces='drive'
    ).execute().get('files', [])
    
    if not folders:
        folder = drive_service.files().create(body={
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder'
        }).execute()
    else:
        folder = folders[0]
    
    return render_template('dashboard.html', user=session['user'], folder=folder)

@app.route('/logout')
def logout():
    logout_user()
    session.clear()
    return redirect(url_for('home'))

if __name__ == '__main__':
    app.run(debug=True)
