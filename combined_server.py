#!/usr/bin/env python3
"""
Combined HTTP Server for OpenWebUI Chatbot
This script serves the webchat.html file and handles proxy requests to bypass CORS restrictions
when accessing the OpenWebUI API from the browser.
Includes a login page for authentication.
"""

import http.server
import socketserver
import urllib.request
import urllib.parse
import urllib.error
from http.server import BaseHTTPRequestHandler
import json
import os
import base64
import hashlib
import uuid
import datetime
import threading
from pathlib import Path

# Google Sheets & SSO Logging Setup
try:
    import gspread
    from google.oauth2.service_account import Credentials
    from google.oauth2 import id_token
    from google.auth.transport import requests as google_requests
    GOOGLE_SHEETS_ENABLED = True
except ImportError:
    GOOGLE_SHEETS_ENABLED = False

# Configuration for Google Sheets & SSO
SHEET_ID = "17zDP-13Blgz4r98HyZWgr3h_X0z8qzxkR6Mdb_-4k7Q"
CREDENTIALS_FILE = "chatbot-489108-66c1494dfc80.json"
ALLOWED_DOMAINS = ["interactiv-group.com", "isi-com.com"]

# Authentication constants (hardcoded and hashed)
PWD_SALT = "isicom_salt_2024"
# Valid credentials: user_hash -> pwd_hash
VALID_CREDENTIALS = {
    "55b76f64cfe7594aa21e99793cae85814802fdd7593fc7ebc4ef7ec0e4d59d36": "380ff471a070e6f8b670cc8dd65a0c7247f9a456d9ca36ef545d579dd1eb1d34",
    "300afaccf9e922227853a0160adb8f4d930dfd1cb834fbecbdeeaaec437efaeb": "b4ccbfe66c13e498ccae1178af56cc60c735f0d96297b80c0f148ad57aa67edc",
    "944fbdbe086008c0748938fe2e0e6f1f696ee72eda74d846a6fa6d9bd88413e9": "14f2997f23ca8eb489e1312260bf08e26ab21df0042a57e59752e63b96e26315",
    "6b5c668b07ced04f70ac8c2b4c1c250e7bdb64204a6abd215c5e7bfdbbe4c74d": "bde468b5e8f851d428f9b71908c75cd556708536ac62ab88d75ddd2bceac42c5",
    "09ad855bb174fb45b9423f3a2d1eec669bb7ee7f3a32d76fb27aec6f563d8a48": "40b417e47fd4d6ca8d480853b5f97ba498d81641739cbf4d965a06005a98e601",
    "20471e75d0082c57317cdb33f190f07f0e05148a013ea6129b09b3addd4a3fe2": "eb098533c327c390a8b61705148f78cab661d7802371fdee2df1b6b51a223eda",
    "3676ea8981120cdd98f260cd858675cea3e80c8ddb863fbe99ce1d36c12af3ab": "6e06e42dd19ca30736347029a9a62af53dcff0c0b507c6c3bbb58b7144547e75",
    "d5657f58b5581218803e635f62c3ae6fd403ccc837c9c6bdc5687e479da06af5": "44c50172739b546201010383ea36c33889e3e735e4b3c04acf5c90e385bda109",
}
SESSION_COOKIE_NAME = "chatbot_session"
VALID_SESSIONS = {}  # session_id -> username

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # If python-dotenv is not installed, manually load the .env file
    env_path = Path(__file__).parent / '.env'
    if env_path.exists():
        with open(env_path, 'r') as file:
            for line in file:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()

def evaluate_response_quality(question, answer):
    """Asks the LLM to evaluate the quality of its own response."""
    try:
        api_key = os.environ.get('OPENWEBUI_API_KEY')
        base_url = os.environ.get('DEFAULT_OPENWEBUI_URL')
        if not api_key or not base_url:
            return "N/A"

        prompt = f"Évalue la qualité et la pertinence de la réponse suivante à la question posée (basée sur des documents ISI-COM). Réponds UNIQUEMENT par un nombre entre 0 et 100, sans aucun autre texte.\n\nQuestion: {question}\nRéponse: {answer}\n\nQualité (%):"
        
        payload = {
            "model": "rag-isi-com",
            "messages": [{"role": "user", "content": prompt}],
            "stream": False
        }
        
        target_url = f"{base_url.rstrip('/')}/api/v1/chat/completions"
        req = urllib.request.Request(
            target_url,
            data=json.dumps(payload).encode('utf-8'),
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            method='POST'
        )
        
        with urllib.request.urlopen(req, timeout=30) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            score = res_data['choices'][0]['message']['content'].strip()
            # Nettoyage au cas où l'IA mettrait du texte autour du chiffre
            import re
            match = re.search(r'(\d+)', score)
            return f"{match.group(1)}%" if match else score
    except Exception as e:
        print(f"[EVAL] Erreur lors de l'évaluation: {str(e)}")
        return "Error"

def log_to_sheets(username, question, answer):
    """Logs the interaction and its quality to Google Sheets in a separate thread."""
    if not GOOGLE_SHEETS_ENABLED:
        print("[SHEETS] ATTENTION: Bibliothèques gspread/google-auth non installées.")
        return

    def _log_thread():
        print(f"[SHEETS] Évaluation et logging pour: {username}")
        # 1. Évaluation de la qualité
        quality_score = evaluate_response_quality(question, answer)
        
        try:
            scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
            if not os.path.exists(CREDENTIALS_FILE):
                print(f"[SHEETS] ERREUR: Fichier de clé {CREDENTIALS_FILE} introuvable.")
                return
                
            creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
            client = gspread.authorize(creds)
            
            spreadsheet = client.open_by_key(SHEET_ID)
            sheet = spreadsheet.get_worksheet(0)
            
            # Check if headers are needed or need update
            values = sheet.get_all_values()
            if not values:
                print("[SHEETS] Création des en-têtes...")
                sheet.append_row(["Timestamp", "User", "Question", "Answer", "Qualité (%)"])
            elif "Qualité (%)" not in values[0]:
                print("[SHEETS] Mise à jour des en-têtes pour inclure la Qualité...")
                sheet.update_cell(1, 5, "Qualité (%)")
            
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[SHEETS] Écriture de la ligne avec score: {quality_score}")
            sheet.append_row([timestamp, username, question, answer, quality_score])
            print(f"[SHEETS] ✅ Succès !")
        except Exception as e:
            print(f"[SHEETS] ❌ ERREUR DETECTEE: {type(e).__name__} - {str(e)}")

    thread = threading.Thread(target=_log_thread)
    thread.start()

class CombinedHandler(BaseHTTPRequestHandler):
    def get_cookie(self, name):
        cookies = self.headers.get('Cookie')
        if cookies:
            for cookie in cookies.split(';'):
                if '=' in cookie:
                    k, v = cookie.strip().split('=', 1)
                    if k == name:
                        return v
        return None

    def get_username(self):
        session_id = self.get_cookie(SESSION_COOKIE_NAME)
        return VALID_SESSIONS.get(session_id)

    def is_authenticated(self):
        session_id = self.get_cookie(SESSION_COOKIE_NAME)
        return session_id in VALID_SESSIONS

    def do_OPTIONS(self):
# ... (rest of do_OPTIONS)
        # Handle preflight requests
        self.send_response(200)
        self.send_cors_headers()
        self.end_headers()

    def do_GET(self):
        if self.path == '/login' or self.path == '/login.html':
            if self.is_authenticated():
                self.send_response(302)
                self.send_header('Location', '/')
                self.end_headers()
            else:
                self.serve_login_file()
            return

        if not self.is_authenticated():
            self.send_response(302)
            self.send_header('Location', '/login')
            self.end_headers()
            return

        if self.path == '/' or self.path == '/webchat.html':
            # Serve the webchat HTML file
            self.serve_webchat_file()
        elif self.path.startswith('/proxy/'):
            # Handle proxy requests
            print(f"Proxy request received: {self.path}")
            self.handle_proxy_request()
        elif self.path == '/logout':
            session_id = self.get_cookie(SESSION_COOKIE_NAME)
            if session_id in VALID_SESSIONS:
                del VALID_SESSIONS[session_id]
            self.send_response(302)
            self.send_header('Set-Cookie', f"{SESSION_COOKIE_NAME}=; Max-Age=0; Path=/")
            self.send_header('Location', '/login')
            self.end_headers()
        else:
            # Return 404 for other paths
            print(f"404 - Unknown path: {self.path}")
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")

    def do_POST(self):
        if self.path == '/login':
            self.handle_login()
            return
        elif self.path == '/auth/google':
            self.handle_google_auth()
            return

        if not self.is_authenticated():
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"Forbidden")
            return

        if self.path.startswith('/proxy/'):
            # Handle proxy requests
            print(f"Proxy POST request received: {self.path}")
            self.handle_proxy_request()
        else:
            # Return 404 for other paths
            print(f"404 - Unknown POST path: {self.path}")
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")

    def handle_google_auth(self):
        """Verifies Google ID Token and checks domain ownership"""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = json.loads(self.rfile.read(content_length).decode('utf-8'))
            token = post_data.get('credential')
            
            # Google Client ID from environment
            client_id = os.environ.get('GOOGLE_CLIENT_ID')
            if not client_id:
                print("[AUTH] ERREUR: GOOGLE_CLIENT_ID non défini dans le fichier .env")
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b"Server configuration error (Missing Client ID)")
                return

            # Verify the token
            idinfo = id_token.verify_oauth2_token(token, google_requests.Request(), client_id)
            
            email = idinfo.get('email')
            domain = email.split('@')[-1] if email else ""
            
            if domain in ALLOWED_DOMAINS:
                session_id = str(uuid.uuid4())
                username = idinfo.get('name', email)
                # Store the full name and email for the log
                VALID_SESSIONS[session_id] = f"{username} ({email})"
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Set-Cookie', f"{SESSION_COOKIE_NAME}={session_id}; Path=/; HttpOnly")
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'success'}).encode())
                print(f"[AUTH] Connexion SSO réussie pour: {email}")
            else:
                print(f"[AUTH] Tentative de connexion refusée pour le domaine: {domain}")
                self.send_response(403)
                self.end_headers()
                self.wfile.write(b"Domain not allowed")
                
        except Exception as e:
            print(f"[AUTH] Erreur SSO: {str(e)}")
            self.send_response(400)
            self.end_headers()
            self.wfile.write(f"Invalid token: {str(e)}".encode())

    def handle_login(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length).decode('utf-8')

        # Determine if it's JSON or Form data
        is_json = self.headers.get('Content-Type') == 'application/json'
        if is_json:
            try:
                params = json.loads(post_data)
            except:
                params = {}
        else:
            params_raw = urllib.parse.parse_qs(post_data)
            params = {k: v[0] for k, v in params_raw.items()}

        username = params.get('username', '')
        password = params.get('password', '')

        user_hash = hashlib.sha256((username + PWD_SALT).encode()).hexdigest()
        pwd_hash = hashlib.sha256((password + PWD_SALT).encode()).hexdigest()

        user_exists = user_hash in VALID_CREDENTIALS
        password_correct = user_exists and VALID_CREDENTIALS[user_hash] == pwd_hash

        if user_exists and password_correct:
            session_id = str(uuid.uuid4())
            VALID_SESSIONS[session_id] = username

            if is_json:
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Set-Cookie', f"{SESSION_COOKIE_NAME}={session_id}; Path=/; HttpOnly")
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'success', 'redirect': '/'}).encode())
            else:
                self.send_response(302)
                self.send_header('Set-Cookie', f"{SESSION_COOKIE_NAME}={session_id}; Path=/; HttpOnly")
                self.send_header('Location', '/')
                self.end_headers()
        else:
            if is_json:
                self.send_response(401)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                # Déterminer quelles erreurs afficher
                errors = []
                if not user_exists:
                    errors.append("username")
                    error_message = "Nom d'utilisateur incorrect"
                elif not password_correct:
                    errors.append("password")
                    error_message = "Mot de passe incorrect"
                else:
                    error_message = "Identifiants incorrects"
                
                self.wfile.write(json.dumps({
                    'status': 'error', 
                    'message': error_message, 
                    'error_type': 'invalid_credentials',
                    'errors': errors
                }).encode())
            else:
                self.send_response(302)
                self.send_header('Location', '/login?error=1')
                self.end_headers()

    def serve_login_file(self):
        """Serve the login.html file"""
        try:
            current_dir = Path(__file__).parent
            login_path = current_dir / "login.html"
            
            # If login.html doesn't exist, we serve a hardcoded one or fail
            if not login_path.exists():
                self.create_default_login_page(login_path)

            with open(login_path, 'rb') as f:
                content = f.read()

            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_error(500, f"Error serving login page: {str(e)}")

    def create_default_login_page(self, path):
        """Create a default login.html page"""
        content = """
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Chatbot - Login</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; background-color: #f0f2f5; }
        .login-container { background: white; padding: 2rem; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); width: 100%; max-width: 400px; }
        h1 { text-align: center; color: #1a73e8; margin-bottom: 1.5rem; }
        .form-group { margin-bottom: 1rem; }
        label { display: block; margin-bottom: 0.5rem; color: #555; }
        input { width: 100%; padding: 0.75rem; border: 1px solid #ddd; border-radius: 4px; box-sizing: border-box; }
        button { width: 100%; padding: 0.75rem; background-color: #1a73e8; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 1rem; margin-top: 1rem; }
        button:hover { background-color: #1557b0; }
        .error { color: #d93025; background: #f8d7da; padding: 0.5rem; border-radius: 4px; margin-bottom: 1rem; text-align: center; }
        #error-msg { display: none; }
    </style>
</head>
<body>
    <div class="login-container">
        <h1>Connexion Chatbot</h1>
        <div id="error-msg" class="error">Identifiants incorrects</div>
        <form action="/login" method="POST">
            <div class="form-group">
                <label for="username">Utilisateur</label>
                <input type="text" id="username" name="username" required autofocus>
            </div>
            <div class="form-group">
                <label for="password">Mot de passe</label>
                <input type="password" id="password" name="password" required>
            </div>
            <button type="submit">Se connecter</button>
        </form>
    </div>
    <script>
        const urlParams = new URLSearchParams(window.location.search);
        if (urlParams.has('error')) {
            document.getElementById('error-msg').style.display = 'block';
        }
    </script>
</body>
</html>
        """
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)

    def serve_webchat_file(self):
        """Serve the webchat.html file"""
        try:
            # Get the directory containing this script
            current_dir = Path(__file__).parent
            webchat_path = current_dir / "webchat.html"

            with open(webchat_path, 'rb') as f:
                content = f.read()

            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(content)
        except FileNotFoundError:
            self.send_error(404, "webchat.html not found")

    def handle_proxy_request(self):
        """Handle proxy requests to the OpenWebUI API"""
        # Extract the target API endpoint from the path
        if self.path.startswith('/proxy/'):
            # Remove '/proxy/' prefix to get the actual API endpoint
            api_endpoint = self.path[len('/proxy/'):]

            # Get the OpenWebUI URL from the query parameters or headers
            openwebui_url = self.headers.get('X-OpenWebUI-URL')

            # First, check if we have a server-side API key configured via environment variable
            server_api_key = os.environ.get('OPENWEBUI_API_KEY')

            # If server has an API key configured, use it directly
            if server_api_key:
                api_key = server_api_key
            else:
                # If no server-side key is configured, check for client-provided key
                encoded_api_key = self.headers.get('X-API-Key')
                if not encoded_api_key:
                    self.send_error(400, "Missing X-API-Key header or server-side OPENWEBUI_API_KEY environment variable")
                    return

                try:
                    api_key = base64.b64decode(encoded_api_key).decode('utf-8')
                except Exception as e:
                    self.send_error(400, f"Invalid API key encoding: {str(e)}")
                    return

            # Check if we have the OpenWebUI URL from environment variable if not provided in headers
            if not openwebui_url:
                default_openwebui_url = os.environ.get('DEFAULT_OPENWEBUI_URL')
                if default_openwebui_url:
                    openwebui_url = default_openwebui_url
                else:
                    self.send_error(400, "Missing X-OpenWebUI-URL header or DEFAULT_OPENWEBUI_URL environment variable")
                    return

            # Prepare headers for the target request
            headers = {
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }

            # For chat completion requests, use the specific api/v1 endpoint
            is_chat = api_endpoint.endswith('chat/completions')
            if is_chat:
                target_url = f"{openwebui_url.rstrip('/')}/api/v1/{api_endpoint.lstrip('/')}"
            else:
                # For other requests (like models), use the original path
                target_url = f"{openwebui_url.rstrip('/')}/{api_endpoint.lstrip('/')}"

            try:
                print(f"Forwarding {self.command} request to: {target_url}")

                request_body = b''
                if self.command == 'POST':
                    # Read the request body
                    content_length = int(self.headers.get('Content-Length', 0))
                    request_body = self.rfile.read(content_length) if content_length > 0 else b''
                    
                    # Create the request to the target API
                    req = urllib.request.Request(
                        target_url,
                        data=request_body,
                        headers=headers,
                        method='POST'
                    )
                else:  # GET request
                    req = urllib.request.Request(
                        target_url,
                        headers=headers,
                        method='GET'
                    )

                # Make the request to the target API with increased timeout
                with urllib.request.urlopen(req, timeout=300) as response:
                    # Read the response
                    response_data = response.read()
                    response_status = response.getcode()
                    response_headers = response.headers

                    # Send the response back to the client
                    self.send_response(response_status)

                    # Copy relevant headers from the target response
                    for header, value in response_headers.items():
                        if header.lower() not in ['connection', 'transfer-encoding']:  # Skip hop-by-hop headers
                            self.send_header(header, value)

                    # Add CORS headers
                    self.send_cors_headers()

                    self.end_headers()
                    self.wfile.write(response_data)

                    # Handle Logging to Sheets if it's a chat completion
                    if is_chat and response_status == 200:
                        try:
                            # Extract question
                            req_json = json.loads(request_body)
                            question = req_json.get('messages', [])[-1].get('content', '')
                            
                            # Extract answer from streamed response
                            answer = ""
                            response_text = response_data.decode('utf-8')
                            for line in response_text.splitlines():
                                if line.startswith('data: '):
                                    data_str = line[len('data: '):]
                                    if data_str == '[DONE]':
                                        continue
                                    try:
                                        chunk = json.loads(data_str)
                                        if chunk.get('choices') and chunk['choices'][0].get('delta', {}).get('content'):
                                            answer += chunk['choices'][0]['delta']['content']
                                    except:
                                        pass
                            
                            username = self.get_username() or "unknown"
                            log_to_sheets(username, question, answer)
                        except Exception as log_err:
                            print(f"Logging error: {str(log_err)}")

                    return  # Success, exit the function

            except urllib.error.HTTPError as e:
                print(f"Request failed for {target_url}: {e.code} - {e.reason}")
                self.send_response(e.code)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()

                error_response = {
                    'error': {
                        'message': f"Request failed: {str(e.reason)}",
                        'type': 'http_error',
                        'code': e.code
                    }
                }
                self.wfile.write(json.dumps(error_response).encode())
                return

            except urllib.error.URLError as e:
                print(f"URL Error for {target_url}: {e.reason}")
                self.send_error(500, f"URL Error: {str(e.reason)}")
                return

            except Exception as e:
                print(f"General error for {target_url}: {str(e)}")
                self.send_error(500, f"Request failed with error: {str(e)}")
                return
        else:
            self.send_error(400, "Invalid proxy path")

    def send_cors_headers(self):
        """Add CORS headers to the response"""
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-API-Key, X-OpenWebUI-URL')

    def log_message(self, format, *args):
        """Override to customize logging"""
        print(f"[SERVER] {format % args}")


def run_combined_server():
    """
    Runs the combined server to serve webchat.html and handle proxy requests
    """
    # Get port from environment variable, default to 8081 if not specified
    port = int(os.environ.get('SERVER_PORT', 8081))
    
    # Change to the directory containing the files
    current_dir = Path(__file__).parent
    os.chdir(current_dir)

    print(f"Starting combined server on http://localhost:{port}")
    print(f"Serving webchat and handling proxy requests from: {current_dir}")
    print("Press Ctrl+C to stop the server")

    with socketserver.TCPServer(("", port), CombinedHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down the server...")


if __name__ == "__main__":
    run_combined_server()
