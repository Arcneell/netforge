# 01 — Vision

## Pourquoi Netforge

Aujourd'hui, l'infra réseau Mooland est documentée dans des fichiers Excel, des post-it, des notes dispersées, et la mémoire des admins. Quand un problème arrive ("le téléphone du bureau compta ne marche plus"), il faut fouiller pour retrouver :

- quel switch sert ce bureau,
- sur quel port est branché le câble,
- quel VLAN est configuré,
- quelle IP est attribuée,
- qui d'autre est dans ce subnet.

Netforge centralise tout ça dans une interface web unique, avec une vue graphique pour les diagnostics visuels.

## Objectifs

1. **Source unique de vérité** pour l'adressage IP et la topologie switch.
2. **Diagnostic rapide** : retrouver en < 10 secondes l'équipement branché sur un port donné.
3. **Planification** : voir les IP libres dans un subnet avant d'en attribuer une nouvelle.
4. **Cartographie** : visualiser les liens inter-switches pour comprendre les chemins réseau.
5. **Traçabilité** : qui a modifié quoi, quand, pourquoi (audit log).

## Public cible

- **Utilisateur principal** : Nathan (admin sys Mooland) — saisie, consultation quotidienne.
- **Lecture** : tuteur, futurs alternants, prestataires ponctuels — consultation seule.
- **Personne d'extérieur** : aucune. L'outil est interne, accessible uniquement via auth M365.

## Scope v1 (MVP)

### Inclus
- Gestion des **subnets** (IPv4, CIDR, passerelle, VLAN associé, description).
- Gestion des **VLANs** (ID, nom, description, subnets associés).
- Gestion des **IPs** dans un subnet (réservées, attribuées, libres) avec hostname, MAC, équipement lié.
- Gestion des **switches** (modèle, localisation, IP management, nombre de ports).
- Gestion des **ports** par switch (numéro, label, VLAN access/trunk, état, équipement connecté).
- Gestion des **liens** entre switches (uplink/downlink) pour calculer la topologie.
- **Vue topologie** graphique avec Cytoscape.js (drag, zoom, clic sur un nœud → détails).
- **Import CSV** par type d'entité (amorçage rapide depuis les fichiers Excel existants).
- **Export CSV** de chaque table (backup / partage hors-outil).
- **Auth Entra ID** multi-utilisateurs, 2 rôles : `viewer` (lecture) et `admin` (écriture).
- **Audit log** : chaque modification est tracée (qui, quand, avant → après).
- **Recherche globale** : barre de recherche qui cherche sur IP, hostname, MAC, nom de switch, label de port.

### Exclus v1
- Auto-discovery SNMP des switches (scope v2).
- Intégration Zabbix (scope v2).
- Provisioning (push de config sur les switches) — jamais, trop risqué.
- IPv6 — le parc Mooland est full IPv4.
- Multi-tenant — un seul parc.
- API publique / externe — l'API existe mais n'est pas exposée.

## Scope v2 (après validation MVP)

- **SNMP polling** : scan périodique des switches Aruba pour remplir automatiquement les tables port/MAC/VLAN.
- **Sync Zabbix** : lecture de l'inventaire Zabbix pour enrichir les fiches équipement.
- **Inventaire équipements étendu** : serveurs, imprimantes, APs, téléphones Fanvil avec fiche complète (modèle, série, contrat support).
- **Alertes** : notification Telegram si un port passe down, si un subnet arrive à saturation (> 90% utilisé).

## Hors-scope définitif

- **Push de config** sur les switches : risque trop élevé, on reste en lecture.
- **DHCP server intégré** : Mooland a déjà Windows DHCP, on ne re-implémente pas.
- **DNS management** : idem, AD DNS suffit.
- **Facturation / TCO** : ce n'est pas un CMDB commercial.

## Métriques de succès

- Temps de diagnostic d'un problème réseau divisé par 3 vs aujourd'hui (benchmark subjectif).
- 100% des subnets et VLANs de prod saisis dans les 2 semaines post-mise-en-prod.
- Tous les switches de la salle serveur + switches d'étage documentés port par port.
- Zéro incident lié à un manque de visibilité réseau sur 6 mois post-v1.
