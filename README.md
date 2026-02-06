# Installation et Lancement du Chatbot OpenWebUI

Ce document explique comment installer et lancer l'application de chatbot OpenWebUI.

## Prérequis

- Python 3.7 ou supérieur
- pip (gestionnaire de paquets Python)
- Accès à une instance OpenWebUI avec une clé API valide

## Étapes d'installation

### 1. Cloner ou télécharger le projet

Si vous avez accédé au projet via un dépôt Git :
```bash
git clone <url_du_depot>
cd openwebui-chatbot
```

Sinon, assurez-vous d'avoir tous les fichiers du projet dans un dossier local.

### 2. Installer les dépendances Python

L'application nécessite certaines dépendances Python spécifiées dans le fichier `requirements.txt`. Installez-les avec pip :

```bash
pip install -r requirements.txt
```

Vous pouvez également installer manuellement les dépendances requises :
- python-dotenv

Pour installer manuellement :
```bash
pip install python-dotenv
```

### 3. Configurer les variables d'environnement

Copiez le fichier `.env.example` (ou créez un nouveau fichier) en tant que `.env` et configurez vos paramètres :

```bash
cp .env.example .env
```

Éditez ensuite le fichier `.env` :

```
# Clé API OpenWebUI (requise)
OPENWEBUI_API_KEY=votre_cle_api_ici

# URL de base OpenWebUI par défaut (optionnel, peut être remplacé par l'utilisateur)
DEFAULT_OPENWEBUI_URL=https://votre-instance-openwebui.fr/
```

Remplacez `votre_cle_api_ici` par votre clé API OpenWebUI réelle, et mettez à jour l'URL si nécessaire.

## Lancement de l'application

Pour lancer le serveur, exécutez la commande suivante dans le répertoire du projet :

```bash
python combined_server.py
```

Par défaut, le serveur démarrera sur le port 8081. Vous verrez un message indiquant que le serveur est en cours d'exécution :

```
Starting combined server on http://localhost:8081
Serving webchat and handling proxy requests from: /chemin/vers/le/projet
The server will serve webchat.html and forward API requests to your OpenWebUI instance
Make sure your OpenWebUI instance is running
Press Ctrl+C to stop the server
```

## Utilisation

1. Ouvrez votre navigateur web et rendez-vous à l'adresse : http://localhost:8081
2. L'interface de chat s'affiche automatiquement
3. Commencez à taper votre message dans le champ de saisie en bas de l'écran
4. Cliquez sur "Envoyer" ou appuyez sur Entrée pour envoyer votre message

L'application utilisera la configuration définie dans le fichier `.env` pour se connecter à votre instance OpenWebUI.

## Configuration avancée

### Changement de port

Pour exécuter le serveur sur un port différent, vous pouvez définir la variable d'environnement `SERVER_PORT` dans le fichier `.env` :

```
SERVER_PORT=8082  # Remplacez 8082 par le port souhaité
```

Ou lancez le serveur avec la variable d'environnement définie :

```bash
SERVER_PORT=8082 python combined_server.py
```

Le port par défaut est 8081 si aucune variable n'est définie.

### Variables d'environnement

- `OPENWEBUI_API_KEY` : Clé API requise pour accéder à l'instance OpenWebUI
- `DEFAULT_OPENWEBUI_URL` : URL de base de votre instance OpenWebUI (optionnel)
- `SERVER_PORT` : Port sur lequel le serveur écoutera (par défaut: 8081)

## Dépannage

### Problèmes de connexion

- Vérifiez que votre instance OpenWebUI est accessible
- Assurez-vous que la clé API est correcte
- Confirmez que l'URL OpenWebUI dans le fichier `.env` est valide

### Erreurs CORS

L'application inclut un mécanisme de proxy pour résoudre les problèmes CORS. Si vous rencontrez toujours des erreurs liées à CORS, vérifiez la configuration de votre serveur OpenWebUI.

### Problèmes de certificat SSL

Si vous utilisez une URL HTTPS avec un certificat auto-signé, vous pourriez rencontrer des erreurs. Dans ce cas, vous devrez peut-être configurer votre environnement Python pour ignorer les vérifications de certificat (à utiliser avec précaution dans un environnement de développement uniquement).

## Arrêt du serveur

Pour arrêter le serveur, appuyez sur `Ctrl+C` dans le terminal où le serveur est en cours d'exécution.

