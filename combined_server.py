#!/usr/bin/env python3
"""
Serveur HTTP combiné pour le chatbot OpenWebUI
Sert webchat.html, gère l'authentification et proxyfie les requêtes API.
"""

import sys
from pathlib import Path

# Load vendored dependencies if available
vendor_path = Path(__file__).parent / 'vendor'
if vendor_path.exists():
    sys.path.insert(0, str(vendor_path))

import os
import json
import base64
import hashlib
import uuid
import datetime
import urllib.request
import urllib.parse
import urllib.error
import socketserver
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlencode, parse_qs, urlparse

# --- Configuration & SSO Setup ---
try:
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token as google_id_token
    GOOGLE_AUTH_ENABLED = True
except ImportError:
    GOOGLE_AUTH_ENABLED = False

# Constants
SESSION_COOKIE_NAME = "chatbot_session"
PWD_SALT = "isicom_salt_2024"

# Global State
VALID_SESSIONS = {}  # session_id -> username
VALID_CREDENTIALS = {
    "55b76f64cfe7594aa21e99793cae85814802fdd7593fc7ebc4ef7ec0e4d59d36": "380ff471a070e6f8b670cc8dd65a0c7247f9a456d9ca36ef545d579dd1eb1d34",
    "300afaccf9e922227853a0160adb8f4d930dfd1cb834fbecbdeeaaec437efaeb": "b4ccbfe66c13e498ccae1178af56cc60c735f0d96297b80c0f148ad57aa67edc",
    "944fbdbe086008c0748938fe2e0e6f1f696ee72eda74d846a6fa6d9bd88413e9": "14f2997f23ca8eb489e1312260bf08e26ab21df0042a57e59752e63b96e26315",
    "6b5c668b07ced04f70ac8c2b4c1c250e7bdb64204a6abd215c5e7bfdbbe4c74d": "bde468b5e8f851d428f9b71908c75cd556708536ac62ab88d75ddd2bceac42c5",
    "09ad855bb174fb45b9423f3a2d1eec669bb7ee7f3a32d76fb27aec6f563d8a48": "40b417e47fd4d6ca8d480853b5f97ba498d81641739cbf4d965a06005a98e601",
    "20471e75d0082c57317cdb33f190f07f0e05148a013ea6129b09b3addd4a3fe2": "eb098533c327c390a8b61705148f78cab661d7802371fdee2df1b6b51a223eda",
    "3676ea8981120cdd98f260cd858675cea3e80c8ddb863fbe99ce1d36c12af3ab": "6e06e42dd19ca30736347029a9a62af53dcff0c0b507c6c3bbb58b7144547e75",
    "d5657f58b5581218803e635f62c3ae6fd403ccc837c9c6bdc5687e479da06af5": "44c50172739b546201010383ea36c33889e3e735e4b3c04acf5c90e385bda109",
    "57d3e78ca372726126edc1b9663cd48574c243c26ceca87c6da19b3577a43940": "5bcbce1539d068923efe7faa3f0a524ed68b083e2d5b706ddaa070c1bf016de0",
}

# --- Utilities ---
def load_env():
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        env_path = Path(__file__).parent / '.env'
        if env_path.exists():
            with open(env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        k, v = line.split('=', 1)
                        os.environ[k.strip()] = v.strip()

load_env()

# Load allowed domains from environment variable (after .env is loaded)
ALLOWED_DOMAINS = [d.strip() for d in os.environ.get('GOOGLE_ALLOWED_DOMAINS', '').split(',') if d.strip()]

# Keycloak configuration
KEYCLOAK_ISSUER = os.environ.get('KEYCLOAK_ISSUER', '')
KEYCLOAK_CLIENT_ID = os.environ.get('KEYCLOAK_CLIENT_ID', '')
KEYCLOAK_CLIENT_SECRET = os.environ.get('KEYCLOAK_CLIENT_SECRET', '')
KEYCLOAK_REDIRECT_URI = os.environ.get('KEYCLOAK_REDIRECT_URI', '')

# Derive Keycloak endpoints from issuer
KEYCLOAK_AUTH_URL = f"{KEYCLOAK_ISSUER}/protocol/openid-connect/auth" if KEYCLOAK_ISSUER else ''
KEYCLOAK_TOKEN_URL = f"{KEYCLOAK_ISSUER}/protocol/openid-connect/token" if KEYCLOAK_ISSUER else ''
KEYCLOAK_USERINFO_URL = f"{KEYCLOAK_ISSUER}/protocol/openid-connect/userinfo" if KEYCLOAK_ISSUER else ''
KEYCLOAK_LOGOUT_URL = f"{KEYCLOAK_ISSUER}/protocol/openid-connect/logout" if KEYCLOAK_ISSUER else ''

# State for OAuth2 flow (state -> session_id mapping)
OAUTH_STATES = {}  # state -> session_id


# --- Server Handler ---
class CombinedHandler(BaseHTTPRequestHandler):
    def get_cookie(self, name):
        cookies = self.headers.get('Cookie', '')
        for cookie in cookies.split(';'):
            if '=' in cookie:
                k, v = cookie.strip().split('=', 1)
                if k == name: return v
        return None

    def get_username(self):
        return VALID_SESSIONS.get(self.get_cookie(SESSION_COOKIE_NAME))

    def is_authenticated(self):
        return self.get_cookie(SESSION_COOKIE_NAME) in VALID_SESSIONS

    def send_cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-API-Key, X-OpenWebUI-URL')

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_cors_headers()
        self.end_headers()

    def do_GET(self):
        print(f"[DEBUG] GET {self.path}")
        cookie_value = self.get_cookie(SESSION_COOKIE_NAME)
        print(f"[DEBUG] Session cookie: {cookie_value}")
        print(f"[DEBUG] Is authenticated: {cookie_value in VALID_SESSIONS if cookie_value else False}")

        # Parse path without query parameters for route matching
        parsed_path = urlparse(self.path).path

        if parsed_path in ['/login', '/login.html']:
            if self.is_authenticated():
                print(f"[DEBUG] Already authenticated, redirecting to /")
                self.redirect('/')
            else:
                self.serve_file("login.html")
            return

        # Allow Keycloak auth endpoints without authentication
        if parsed_path == '/auth/keycloak':
            self.handle_keycloak_login()
            return
        elif parsed_path == '/auth/callback':
            self.handle_keycloak_callback()
            return

        if not self.is_authenticated():
            print(f"[DEBUG] Not authenticated, redirecting to /login")
            self.redirect('/login')
            return

        if parsed_path in ['/', '/webchat.html']:
            print(f"[DEBUG] Serving webchat.html")
            self.serve_file("webchat.html")
        elif parsed_path.startswith('/proxy/'):
            self.handle_proxy_request()
        elif parsed_path == '/logout':
            self.handle_logout()
        else:
            self.send_error(404)

    def do_POST(self):
        parsed_path = urlparse(self.path).path
        if parsed_path == '/login':
            self.handle_login()
        elif parsed_path == '/auth/google':
            self.handle_google_auth()
        elif self.is_authenticated() and parsed_path.startswith('/proxy/'):
            self.handle_proxy_request()
        else:
            self.send_error(403 if not self.is_authenticated() else 404)

    def redirect(self, location, cookie=None):
        self.send_response(302)
        self.send_header('Location', location)
        if cookie:
            self.send_header('Set-Cookie', cookie)
            print(f"[DEBUG] Setting cookie: {cookie}")
        self.end_headers()
        # Explicitly return to avoid further processing
        return

    def serve_file(self, filename):
        try:
            path = Path(__file__).parent / filename
            with open(path, 'rb') as f:
                content = f.read()
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            if filename == "webchat.html": self.send_cors_headers()
            self.end_headers()
            self.wfile.write(content)
        except FileNotFoundError:
            self.send_error(404, f"{filename} not found")

    def handle_logout(self):
        sid = self.get_cookie(SESSION_COOKIE_NAME)
        if sid in VALID_SESSIONS: del VALID_SESSIONS[sid]
        self.redirect('/login', f"{SESSION_COOKIE_NAME}=; Max-Age=0; Path=/")

    def handle_login(self):
        content_length = int(self.headers.get('Content-Length', 0))
        data = self.rfile.read(content_length).decode('utf-8')
        is_json = self.headers.get('Content-Type') == 'application/json'
        
        params = json.loads(data) if is_json else {k: v[0] for k, v in urllib.parse.parse_qs(data).items()}
        username = params.get('username', '')
        password = params.get('password', '')

        u_hash = hashlib.sha256((username + PWD_SALT).encode()).hexdigest()
        p_hash = hashlib.sha256((password + PWD_SALT).encode()).hexdigest()

        user_exists = u_hash in VALID_CREDENTIALS
        pwd_ok = user_exists and VALID_CREDENTIALS[u_hash] == p_hash

        if user_exists and pwd_ok:
            sid = str(uuid.uuid4())
            VALID_SESSIONS[sid] = username
            cookie = f"{SESSION_COOKIE_NAME}={sid}; Path=/; HttpOnly; SameSite=Lax"
            if is_json:
                self.send_json({'status': 'success', 'redirect': '/'}, cookie)
            else:
                self.redirect('/', cookie)
        else:
            err_msg = "Nom d'utilisateur incorrect" if not user_exists else "Mot de passe incorrect"
            errors = ["username"] if not user_exists else ["password"]
            if is_json:
                self.send_json({'status': 'error', 'message': err_msg, 'errors': errors}, status=401)
            else:
                self.redirect('/login?error=1')

    def handle_google_auth(self):
        if not GOOGLE_AUTH_ENABLED:
            self.send_error(500, "Google Auth module not available")
            return
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            token = json.loads(self.rfile.read(content_length))['credential']
            client_id = os.environ.get('GOOGLE_CLIENT_ID')

            idinfo = google_id_token.verify_token(token, google_requests.Request(), audience=client_id)
            email = idinfo.get('email', '')
            domain = email.split('@')[-1]

            if domain in ALLOWED_DOMAINS:
                sid = str(uuid.uuid4())
                VALID_SESSIONS[sid] = f"{idinfo.get('name', email)} ({email})"
                self.send_json({'status': 'success'}, f"{SESSION_COOKIE_NAME}={sid}; Path=/; HttpOnly")
            else:
                self.send_error(403, "Domain not allowed")
        except Exception as e:
            self.send_error(400, str(e))

    def handle_keycloak_login(self):
        """Redirect to Keycloak for authentication"""
        if not KEYCLOAK_AUTH_URL or not KEYCLOAK_CLIENT_ID:
            print("[ERROR] Keycloak configuration missing!")
            print(f"  KEYCLOAK_ISSUER: {KEYCLOAK_ISSUER}")
            print(f"  KEYCLOAK_CLIENT_ID: {KEYCLOAK_CLIENT_ID}")
            print(f"  KEYCLOAK_AUTH_URL: {KEYCLOAK_AUTH_URL}")
            self.send_response(500)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            error_html = """<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <title>Erreur de configuration</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; }
        .error { background: #f8d7da; border: 1px solid #f5c6cb; color: #721c24; padding: 15px; border-radius: 5px; }
        h1 { color: #721c24; }
        a { color: #717AB9; }
    </style>
</head>
<body>
    <h1>Erreur de configuration Keycloak</h1>
    <div class="error">
        <p>L'authentification Keycloak n'est pas configurée correctement.</p>
        <p>Veuillez définir les variables d'environnement suivantes dans un fichier <code>.env</code> :</p>
        <ul>
            <li><code>KEYCLOAK_ISSUER</code></li>
            <li><code>KEYCLOAK_CLIENT_ID</code></li>
            <li><code>KEYCLOAK_CLIENT_SECRET</code></li>
            <li><code>KEYCLOAK_REDIRECT_URI</code></li>
        </ul>
    </div>
    <p><a href="/login">← Retour à la connexion</a></p>
</body>
</html>"""
            self.wfile.write(error_html.encode('utf-8'))
            return

        # Generate state parameter for CSRF protection
        state = str(uuid.uuid4())
        session_id = str(uuid.uuid4())
        OAUTH_STATES[state] = session_id

        # Build authorization URL
        params = {
            'client_id': KEYCLOAK_CLIENT_ID,
            'redirect_uri': KEYCLOAK_REDIRECT_URI,
            'response_type': 'code',
            'scope': 'openid email profile',
            'state': state,
        }
        auth_url = f"{KEYCLOAK_AUTH_URL}?{urlencode(params)}"
        self.redirect(auth_url)

    def handle_keycloak_callback(self):
        """Handle callback from Keycloak after authentication"""
        try:
            # Parse query parameters
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)

            print(f"[DEBUG] Callback received. Query: {parsed.query}")

            # Check for error
            if 'error' in params:
                error = params.get('error', ['Unknown error'])[0]
                print(f"[ERROR] Auth error: {error}")
                self.send_error(400, f"Authentication error: {error}")
                return

            # Get code and state
            code = params.get('code', [None])[0]
            state = params.get('state', [None])[0]

            print(f"[DEBUG] Code: {code is not None}, State: {state is not None}")

            if not code or not state:
                print(f"[ERROR] Missing code or state")
                self.send_error(400, "Missing code or state parameter")
                return

            # Validate state
            if state not in OAUTH_STATES:
                print(f"[ERROR] Invalid state. Available states: {list(OAUTH_STATES.keys())}")
                self.send_error(400, "Invalid state parameter")
                return

            session_id = OAUTH_STATES.pop(state)
            print(f"[DEBUG] Session ID: {session_id}")

            # Exchange code for token
            token_data = self.exchange_code_for_token(code)
            if not token_data:
                print(f"[ERROR] Failed to exchange code for token")
                self.send_error(500, "Failed to exchange code for token")
                return

            print(f"[DEBUG] Token obtained successfully")

            # Get user info
            access_token = token_data.get('access_token', '')
            user_info = self.get_user_info(access_token)
            if not user_info:
                print(f"[ERROR] Failed to get user info")
                self.send_error(500, "Failed to get user info")
                return

            print(f"[DEBUG] User info: {user_info.get('email', 'no email')}")

            # Create session
            email = user_info.get('email', '')
            name = user_info.get('name', user_info.get('preferred_username', email))
            username = f"{name} ({email})" if email else name

            VALID_SESSIONS[session_id] = username
            print(f"[DEBUG] Session created: {session_id} -> {username}")
            print(f"[DEBUG] VALID_SESSIONS now contains: {list(VALID_SESSIONS.keys())}")

            # Add Secure flag for HTTPS
            cookie = f"{SESSION_COOKIE_NAME}={session_id}; Path=/; HttpOnly; SameSite=Lax"
            # Only add Secure flag if BOTH Keycloak AND local server are HTTPS
            is_https = KEYCLOAK_ISSUER and KEYCLOAK_ISSUER.startswith('https://')
            # Don't add Secure for local HTTP development
            if is_https and os.environ.get('SERVER_HTTPS', '').lower() == 'true':
                cookie += "; Secure"
            print(f"[DEBUG] Setting cookie: {cookie}")

            # Redirect to / (which will serve webchat.html for authenticated users)
            self.send_response(302)
            self.send_header('Location', '/')
            self.send_header('Set-Cookie', cookie)
            self.end_headers()
            print(f"[DEBUG] Redirecting to /")
            print(f"[DEBUG] === CALLBACK COMPLETED ===")
            return

        except Exception as e:
            print(f"[ERROR] Exception in callback: {e}")
            import traceback
            traceback.print_exc()
            self.send_error(400, str(e))

    def exchange_code_for_token(self, code):
        """Exchange authorization code for access token"""
        try:
            data = urlencode({
                'grant_type': 'authorization_code',
                'client_id': KEYCLOAK_CLIENT_ID,
                'client_secret': KEYCLOAK_CLIENT_SECRET,
                'code': code,
                'redirect_uri': KEYCLOAK_REDIRECT_URI,
            }).encode('utf-8')

            req = urllib.request.Request(KEYCLOAK_TOKEN_URL, data=data, method='POST')
            req.add_header('Content-Type', 'application/x-www-form-urlencoded')

            with urllib.request.urlopen(req, timeout=30) as res:
                return json.loads(res.read().decode('utf-8'))
        except Exception as e:
            print(f"Token exchange error: {e}")
            return None

    def get_user_info(self, access_token):
        """Get user info from Keycloak"""
        try:
            req = urllib.request.Request(KEYCLOAK_USERINFO_URL)
            req.add_header('Authorization', f'Bearer {access_token}')

            with urllib.request.urlopen(req, timeout=30) as res:
                return json.loads(res.read().decode('utf-8'))
        except Exception as e:
            print(f"User info error: {e}")
            return None

    def handle_proxy_request(self):
        api_endpoint = self.path[len('/proxy/'):]
        api_key = os.environ.get('OPENWEBUI_API_KEY')
        base_url = os.environ.get('DEFAULT_OPENWEBUI_URL')

        if not api_key or not base_url:
            self.send_error(500, "Server configuration missing API Key or URL")
            return

        target_url = f"{base_url.rstrip('/')}/api/v1/{api_endpoint.lstrip('/')}" if 'chat/completions' in api_endpoint else f"{base_url.rstrip('/')}/{api_endpoint.lstrip('/')}"

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
            'User-Agent': 'ChatbotProxy/1.0'
        }

        try:
            req_body = b''
            if self.command == 'POST':
                content_length = int(self.headers.get('Content-Length', 0))
                req_body = self.rfile.read(content_length)

            req = urllib.request.Request(target_url, data=req_body if req_body else None, headers=headers, method=self.command)

            with urllib.request.urlopen(req, timeout=300) as res:
                res_data = res.read()
                self.send_response(res.getcode())
                for h, v in res.headers.items():
                    if h.lower() not in ['connection', 'transfer-encoding', 'content-length']:
                        self.send_header(h, v)
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(res_data)

                # Journalisation asynchrone
                if 'chat/completions' in api_endpoint and res.getcode() == 200:
                    self.extract_and_log(req_body, res_data)

        except urllib.error.HTTPError as e:
            self.send_json({'error': str(e.reason), 'code': e.code}, status=e.code)
        except Exception as e:
            self.send_error(500, str(e))

    def extract_and_log(self, req_body, res_data):
        try:
            question = json.loads(req_body)['messages'][-1]['content']
            answer = ""
            res_text = res_data.decode('utf-8')
            
            # Check if streaming response (contains 'data: ' lines)
            if 'data: ' in res_text:
                for line in res_text.splitlines():
                    if line.startswith('data: '):
                        data = line[6:]
                        if data == '[DONE]': continue
                        try:
                            chunk = json.loads(data)
                            content = chunk.get('choices', [{}])[0].get('delta', {}).get('content', '')
                            if content:
                                answer += content
                        except json.JSONDecodeError:
                            continue
            else:
                # Réponse non-streaming (JSON direct)
                try:
                    res_json = json.loads(res_text)
                    answer = res_json.get('choices', [{}])[0].get('message', {}).get('content', '')
                except json.JSONDecodeError:
                    print(f"[LOG] Échec de l'analyse de la réponse non-streaming")
                    return

            if not answer:
                print(f"[LOG] Aucune réponse extraite")
                return

            username = self.get_username() or "unknown"
            print(f"[LOG] Extrait Q : {question[:50]}... R : {answer[:50]}...")
        except Exception as e:
            print(f"[LOG] Erreur dans extract_and_log : {e}")

    def send_json(self, data, cookie=None, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        if cookie: self.send_header('Set-Cookie', cookie)
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

def run():
    port = int(os.environ.get('SERVER_PORT', 8081))
    os.chdir(Path(__file__).parent)
    print(f"Server: chatbot.isi-com.cloud (internal port {port})")

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", port), CombinedHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopping...")

if __name__ == "__main__":
    run()
