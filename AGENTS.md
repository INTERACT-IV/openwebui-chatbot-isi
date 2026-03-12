# AGENTS.md - Guide de Codage pour Agents

Ce fichier fournit des directives pour les agents travaillant sur le projet OpenWebUI Chatbot.

## Présentation du Projet

Il s'agit d'un serveur HTTP Python qui sert une interface de chat web, gère l'authentification (mot de passe, Google OAuth, Keycloak) et relaie les requêtes API vers une instance OpenWebUI. Il enregistre également les conversations dans Google Sheets.

## Commandes de Build, Lint et Test

### Installation
```bash
pip install -r requirements.txt
```

### Lancement du Serveur
```bash
python combined_server.py
```

Le serveur écoute sur le port 8081 par défaut (configurable via la variable d'environnement `SERVER_PORT`).

### Lancer un Test Unique

**Aucun framework de test formel n'existe dans ce projet.** Pour tester manuellement :
1. Démarrez le serveur : `python combined_server.py`
2. Testez les endpoints avec curl ou un navigateur :
   - Page de connexion : http://localhost:8081/login
   - Interface de chat : http://localhost:8081/
   - Proxy API : http://localhost:8081/proxy/<path>

### Linting

Aucun linter formel n'est configuré. Pour la qualité du code Python, exécutez :
```bash
pip install flake8
flake8 combined_server.py --max-line-length=120
```

### Vérification des Types

Aucun vérificateur de types n'est configuré. Pour en ajouter un :
```bash
pip install mypy
mypy combined_server.py
```

## Conventions de Code

### Principes Généraux

- **Langage** : Python 3.7+
- **Encodage** : UTF-8
- **Longueur de ligne** : Max 120 caractères (limite flexible)
- **Indentation** : 4 espaces

### Importations

```python
# Importations de la bibliothèque standard en premier (par ordre alphabétique)
import datetime
import json
import os
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlencode, parse_qs, urlparse

# Importations tierces
import gspread
from google.oauth2.service_account import Credentials

# Importations locales en dernier
# (aucune dans ce projet)
```

### Conventions de Nommage

- **Fonctions/variables** : `snake_case` (ex: `def handle_login()`, `valid_sessions = {}`)
- **Constantes** : `UPPER_SNAKE_CASE` (ex: `SESSION_COOKIE_NAME`, `PWD_SALT`)
- **Classes** : `PascalCase` (ex: `CombinedHandler`)
- **Méthodes privées** : Préfixer par underscore (ex: `_log_thread()`)

### Indications de Types

Aucune indication de type n'est utilisée actuellement dans le codebase, mais recommandé pour le nouveau code :
```python
def clean_markdown_text(text: str) -> str:
    """Supprime la syntaxe Markdown du texte."""
    if not text:
        return text
    # ...
```

### Docstrings

Utilisez des triples guillemets pour les docstrings. Le codebase existant utilise des docstrings en français :
```python
def parse_markdown_to_segments(text):
    """
    Analyse le texte Markdown en segments avec les informations de formatage.
    Retourne une liste de (texte, gras, italique, est_code).
    """
```

### Gestion des Erreurs

Utilisez des blocs try/except avec des types d'exceptions spécifiques quand possible :
```python
try:
    # Opération qui peut échouer
    result = some_function()
except FileNotFoundError:
    # Gérer une exception spécifique
    print("[ERROR] File not found")
except Exception as e:
    # Capture globale avec journalisation
    print(f"[ERROR] {type(e).__name__}: {e}")
```

Pour les gestionnaires de serveur, utilisez `self.send_error(code, message)` :
```python
self.send_error(404, "File not found")
self.send_error(403, "Forbidden")
self.send_error(500, "Internal server error")
```

### Journalisation

Utilisez des instructions print avec des préfixes pour les différents sous-systèmes :
```python
print(f"[DEBUG] GET {self.path}")
print(f"[SHEETS] Logged for {username}")
print(f"[ERROR] Failed to authenticate: {e}")
```

### Modèles de Réponses HTTP

```python
# Réponse simple
self.send_response(200)
self.send_header('Content-Type', 'application/json')
self.end_headers()
self.wfile.write(json.dumps(data).encode('utf-8'))

# Redirection
self.send_response(302)
self.send_header('Location', '/login')
self.end_headers()

# Erreur
self.send_error(404, "Not found")
```

### Configuration

- Stockez la configuration dans les variables d'environnement
- Utilisez le fichier `.env` pour le développement local (voir `.env.example`)
- Utilisez `python-dotenv` pour charger les fichiers `.env`
- Les constantes sont définies au niveau du module (après les importations)

### Structure des Fichiers

Le projet suit une structure plate :
- `combined_server.py` - Application principale (toute la logique du serveur)
- `login.html` - Modèle de page de connexion
- `webchat.html` - Interface de chat
- `requirements.txt` - Dépendances Python
- `.env.example` - Modèle de variables d'environnement
- `vendor/` - Dépendances intégrées (fallback)

### Considérations de Sécurité

- Ne jamais commiter de secrets dans le contrôle de version
- Utilisez `.env` pour les clés API et identifiants
- Conservez `vendor/` pour les déploiements portables
- Utilisez `hashlib.sha256()` pour le hachage des mots de passe avec sel
- Validez toutes les entrées utilisateur
- Utilisez des cookies HttpOnly pour les sessions

### Dépendances Clés

- `python-dotenv` - Chargement des variables d'environnement
- `gspread` - API Google Sheets
- `google-auth` - Authentification Google
- `google-auth-oauthlib` - Support OAuth2

### Ajout de Nouvelles Fonctionnalités

1. Ajoutez les nouvelles dépendances dans `requirements.txt` (avec pins de version)
2. Documentez les nouvelles variables d'environnement dans `.env.example`
3. Suivez les patterns de code existants pour les gestionnaires et utilitaires
4. Testez manuellement en lançant le serveur et en faisant des requêtes
