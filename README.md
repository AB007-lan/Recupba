# RECUPBA

Logiciel hybride de collecte et de synchronisation de données multi-sources.

## Architecture

- apps/api : API backend Python et FastAPI
- apps/agent : agent de collecte Windows
- apps/web : interface web React et TypeScript
- packages/contracts : contrats et formats de données partagés
- tests : tests unitaires, intégration, sécurité et acceptation
- scripts : scripts d'administration et de développement
- docs : documentation du projet

## Principes de sécurité

- Ne pas modifier les sources par défaut.
- Ne pas propager les suppressions par défaut.
- Journaliser les opérations importantes.
- Vérifier l'intégrité des données.
