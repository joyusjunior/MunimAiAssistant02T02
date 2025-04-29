from app import app

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
app.secret_key = os.environ.get('SECRET_KEY') or 'dev'  # Must be set properly
app.config['SESSION_COOKIE_SECURE'] = True  # Required for HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
