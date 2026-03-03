#!/usr/bin/env python3
"""
Combined HTTP Server for OpenWebUI Chatbot
Serves webchat.html, handles authentication, and proxies API requests.
"""

import os
import json
import base64
import hashlib
import uuid
import datetime
import threading
import urllib.request
import urllib.parse
import urllib.error
import socketserver
from http.server import BaseHTTPRequestHandler
from pathlib import Path

# --- Configuration & SSO Setup ---
try:
    import gspread
    from google.oauth2.service_account import Credentials
    from google.auth.transport import requests as google_requests
    import google.oauth2.id_token as id_token
    GOOGLE_SHEETS_ENABLED = True
except ImportError:
    GOOGLE_SHEETS_ENABLED = False

# Constants
SHEET_ID = "17zDP-13Blgz4r98HyZWgr3h_X0z8qzxkR6Mdb_-4k7Q"
CREDENTIALS_FILE = "chatbot-489108-66c1494dfc80.json"
ALLOWED_DOMAINS = ["interactiv-group.com", "isi-com.com"]
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

def evaluate_response_quality(question, answer):
    """Asks the LLM to evaluate the quality of its own response."""
    try:
        api_key = os.environ.get('OPENWEBUI_API_KEY')
        base_url = os.environ.get('DEFAULT_OPENWEBUI_URL')
        if not api_key or not base_url: return "N/A"

        payload = {
            "model": "rag-isi-com",
            "messages": [{"role": "user", "content": f"Évalue la qualité (0-100) de cette réponse à la question posée. Réponds uniquement par le chiffre.\nQ: {question}\nR: {answer}"}],
            "stream": False
        }
        
        target_url = f"{base_url.rstrip('/')}/api/v1/chat/completions"
        req = urllib.request.Request(
            target_url,
            data=json.dumps(payload).encode('utf-8'),
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            method='POST'
        )
        
        with urllib.request.urlopen(req, timeout=30) as res:
            res_data = json.loads(res.read().decode('utf-8'))
            score = res_data['choices'][0]['message']['content'].strip()
            import re
            match = re.search(r'(\d+)', score)
            return f"{match.group(1)}%" if match else "N/A"
    except Exception as e:
        print(f"[EVAL] Error: {e}")
        return "Error"

def log_to_sheets(username, question, answer):
    """Logs the interaction to Google Sheets."""
    print(f"[SHEETS] Attempting to log for {username}")
    
    if not GOOGLE_SHEETS_ENABLED:
        print(f"[SHEETS] Google Sheets not enabled (missing dependencies)")
        return
    
    if not os.path.exists(CREDENTIALS_FILE):
        print(f"[SHEETS] Credentials file not found: {CREDENTIALS_FILE}")
        return

    def _log_thread():
        quality_score = evaluate_response_quality(question, answer)
        try:
            print(f"[SHEETS] Starting sheet operation...")
            scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
            creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
            client = gspread.authorize(creds)
            sheet = client.open_by_key(SHEET_ID).get_worksheet(0)
            print(f"[SHEETS] Connected to sheet: {SHEET_ID}")

            if not sheet.get_all_values():
                sheet.append_row(["Timestamp", "User", "Question", "Answer", "Qualité (%)"])
                print(f"[SHEETS] Created header row")

            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            sheet.append_row([timestamp, username, question, answer, quality_score])
            print(f"[SHEETS] Logged for {username} (Score: {quality_score})")
        except Exception as e:
            print(f"[SHEETS] Error: {type(e).__name__}: {e}")

    threading.Thread(target=_log_thread).start()

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
        if self.path in ['/login', '/login.html']:
            if self.is_authenticated():
                self.redirect('/')
            else:
                self.serve_file("login.html")
            return

        if not self.is_authenticated():
            self.redirect('/login')
            return

        if self.path in ['/', '/webchat.html']:
            self.serve_file("webchat.html")
        elif self.path.startswith('/proxy/'):
            self.handle_proxy_request()
        elif self.path == '/logout':
            self.handle_logout()
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == '/login':
            self.handle_login()
        elif self.path == '/auth/google':
            self.handle_google_auth()
        elif self.is_authenticated() and self.path.startswith('/proxy/'):
            self.handle_proxy_request()
        else:
            self.send_error(403 if not self.is_authenticated() else 404)

    def redirect(self, location, cookie=None):
        self.send_response(302)
        self.send_header('Location', location)
        if cookie: self.send_header('Set-Cookie', cookie)
        self.end_headers()

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
            cookie = f"{SESSION_COOKIE_NAME}={sid}; Path=/; HttpOnly"
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
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            token = json.loads(self.rfile.read(content_length))['credential']
            client_id = os.environ.get('GOOGLE_CLIENT_ID')
            
            idinfo = id_token.verify_oauth2_token(token, google_requests.Request(), client_id)
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

                # Async Logging
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
                # Non-streaming response (direct JSON)
                try:
                    res_json = json.loads(res_text)
                    answer = res_json.get('choices', [{}])[0].get('message', {}).get('content', '')
                except json.JSONDecodeError:
                    print(f"[LOG] Failed to parse non-streaming response")
                    return
            
            if not answer:
                print(f"[LOG] No answer extracted")
                return
                
            username = self.get_username() or "unknown"
            print(f"[LOG] Extracted Q: {question[:50]}... A: {answer[:50]}...")
            log_to_sheets(username, question, answer)
        except Exception as e:
            print(f"[LOG] Error in extract_and_log: {e}")

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
