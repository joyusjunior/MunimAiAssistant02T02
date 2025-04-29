import os
from flask import Flask, redirect, url_for, session, request, render_template
from flask_login import LoginManager, UserMixin, login_user, current_user
from google_auth_oauthlib.flow import Flow
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

# OAuth Config
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'  # Remove in production!
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')
client_secrets_path = 'client_secret.json'

flow = Flow.from_client_secrets_file(
    client_secrets_file=client_secrets_path,
    scopes=[
        'openid',
        'https://www.googleapis.com/auth/userinfo.email',
        'https://www.googleapis.com/auth/drive.file'
    ],
    redirect_uri='https://munimaiassistant02t02.onrender.com/callback'
)

@login_manager.user_loader
def load_user(user_id):
    return User(session.get('user')['id'], session.get('user')['email'])

@app.route('/')
def home():
    return render_template('index.html', user=current_user)

@app.route('/login')
def login():
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true'
    )
    session['state'] = state
    return redirect(authorization_url)

@app.route('/callback')
def callback():
    # Debug: Print the incoming request URL
    print(f"Incoming callback URL: {request.url}")
    
    # Check for errors first
    if 'error' in request.args:
        return f"OAuth error: {request.args.get('error')}"
    
    # Verify the state parameter
    if request.args.get('state') != session.get('state'):
        return "State mismatch", 400
    
    # Ensure code exists
    if 'code' not in request.args:
        return "Missing authorization code", 400
    
    try:
        # Exchange code for tokens
        flow.fetch_token(authorization_response=request.url)
        
        # Rest of your callback logic...
        credentials = flow.credentials
        session['credentials'] = {
            'token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri,
            'scopes': credentials.scopes
        }

        userinfo = build('oauth2', 'v2', credentials=credentials).userinfo().get().execute()
        user = User(userinfo['id'], userinfo['email'])
        login_user(user)
        session['user'] = {
            'id': userinfo['id'],
            'email': userinfo['email'],
            'name': userinfo.get('name', '')
        }
        
        return redirect(url_for('dashboard'))
        
    except Exception as e:
        print(f"Callback error: {str(e)}")
        return redirect(url_for('home'))

@app.route('/dashboard')
def dashboard():
    if not current_user.is_authenticated:
        return redirect(url_for('login'))
    
    return render_template('dashboard.html', user=session['user'])

if __name__ == '__main__':
    app.run(ssl_context='adhoc')
