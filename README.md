# RECUPBA

Logiciel hybride de collecte et de synchronisation de données multi-sources.

## Architecture

- `apps/api` : API backend Python et FastAPI
- `apps/web` : interface web React, TypeScript et Vite
- `apps/agent` : agent de collecte Windows (à venir)
- `tests` : tests unitaires et d'intégration (pytest)

## Fonctionnalités disponibles

- Gestion des sources de fichiers : création, consultation, modification, activation et désactivation.
- Inventaire de dossiers : chemins relatifs, tailles, dates de modification, empreintes SHA-256.
- Comparaison des deux derniers inventaires : fichiers nouveaux, modifiés, supprimés et inchangés.
- Historique des inventaires et détail des fichiers de chaque exécution.
- Sauvegarde du contenu des fichiers dans un magasin compressé (gzip) et dédupliqué par SHA-256 :
  un contenu identique n'est stocké qu'une fois, quel que soit le nombre de sauvegardes.
- Vérification d'intégrité d'une sauvegarde (relecture et recalcul de chaque empreinte).
- Restauration complète ou sélective vers un dossier au choix, avec les dates d'origine.
  Par sécurité : restauration dans la source interdite, fichiers existants jamais écrasés sans accord explicite.
- Téléchargement d'un fichier tel qu'il était au moment d'une sauvegarde.
- Journal d'audit des opérations (sources, inventaires, sauvegardes, vérifications, restaurations).
- Clôture automatique, au démarrage, des inventaires interrompus par un arrêt du serveur.
- Interface web : tableau de bord, sources, comparaison, inventaires, sauvegardes, restauration, audit.

## Feuille de route (non réalisé)

1. Sauvegardes planifiées, rétention (suppression des anciennes versions), chiffrement.
2. Connecteurs PostgreSQL, MySQL et Odoo.
3. Synchronisation, reprise sur incident.
4. Authentification et gestion des secrets.
5. Agent de collecte Windows.

## Démarrage

Prérequis : Docker, Python 3.14, Node.js 24.

```powershell
Set-Location "E:\RECUPBA"
Copy-Item .env.example .env   # puis renseigner RECUPBA_DB_PASSWORD
docker compose up -d

# Backend
python -m venv apps\api\.venv
& ".\apps\api\.venv\Scripts\python.exe" -m pip install -r apps\api\requirements.txt -r apps\api\requirements-dev.txt

# Interface web (construite une fois, servie ensuite par l'API)
Set-Location apps\web; npm install; npm run build; Set-Location ..\..

# Lancement
& ".\apps\api\.venv\Scripts\python.exe" -m uvicorn main:app --app-dir apps\api --host 127.0.0.1 --port 8020
```

- Interface : http://127.0.0.1:8020/
- Documentation API : http://127.0.0.1:8020/docs

Les ports 8000 et 8010 sont utilisés par d'autres projets sur ce poste, d'où le port 8020.
Les sauvegardes sont stockées dans `E:\RECUPBA\backups` (variable `RECUPBA_BACKUP_DIR`
pour choisir un autre disque, idéalement différent de celui des sources).
Les migrations SQL (`apps/api/migrations`) sont idempotentes et appliquées au démarrage.

Développement de l'interface avec rechargement à chaud (API lancée sur 8020) :

```powershell
Set-Location "E:\RECUPBA\apps\web"; npm run dev   # http://127.0.0.1:5173
```

## Tests

```powershell
Set-Location "E:\RECUPBA"; & ".\apps\api\.venv\Scripts\python.exe" -m pytest tests -q
```

## Principes de sécurité

- Les sources sont uniquement lues, jamais modifiées.
- Aucune suppression n'est propagée.
- Les opérations importantes sont journalisées dans `audit_events`.
- L'intégrité des fichiers est vérifiée par SHA-256.
