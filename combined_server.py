#!/usr/bin/env python3
"""
Combined HTTP Server for OpenWebUI Chatbot
This script serves the webchat.html file and handles proxy requests to bypass CORS restrictions
when accessing the OpenWebUI API from the browser.
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
from pathlib import Path

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


class CombinedHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        # Handle preflight requests
        self.send_response(200)
        self.send_cors_headers()
        self.end_headers()

    def do_GET(self):
        if self.path == '/' or self.path == '/webchat.html':
            # Serve the webchat HTML file
            self.serve_webchat_file()
        elif self.path.startswith('/proxy/'):
            # Handle proxy requests
            print(f"Proxy request received: {self.path}")
            self.handle_proxy_request()
        else:
            # Return 404 for other paths
            print(f"404 - Unknown path: {self.path}")
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")

    def do_POST(self):
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
            if api_endpoint.endswith('chat/completions'):
                target_url = f"{openwebui_url.rstrip('/')}/api/v1/{api_endpoint.lstrip('/')}"
            else:
                # For other requests (like models), use the original path
                target_url = f"{openwebui_url.rstrip('/')}/{api_endpoint.lstrip('/')}"

            try:
                print(f"Forwarding {self.command} request to: {target_url}")
                print(f"Headers: {dict(headers)}")

                if self.command == 'POST':
                    # Read the request body
                    content_length = int(self.headers.get('Content-Length', 0))
                    post_data = self.rfile.read(content_length) if content_length > 0 else b''
                    print(f"POST data: {post_data.decode('utf-8', errors='ignore')[:500]}...")

                    # Create the request to the target API
                    req = urllib.request.Request(
                        target_url,
                        data=post_data,
                        headers=headers,
                        method='POST'
                    )
                else:  # GET request
                    req = urllib.request.Request(
                        target_url,
                        headers=headers,
                        method='GET'
                    )

                print(f"Making request to target API: {target_url}")

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
    print("The server will serve webchat.html and handle proxy requests to your OpenWebUI instance")
    print("Make sure your OpenWebUI instance is running")
    print("Press Ctrl+C to stop the server")

    with socketserver.TCPServer(("", port), CombinedHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down the server...")


if __name__ == "__main__":
    run_combined_server()
