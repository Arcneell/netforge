# 08 — Import / Export CSV

L'import CSV est **le** chemin privilégié pour amorcer Netforge à partir des fichiers Excel existants. Un fichier par type d'entité. Séparateur `;` (compatible Excel FR), encodage `UTF-8 BOM`.

## Règles communes

- Première ligne = en-têtes, respecter la casse.
- Colonnes marquées *obligatoires* doivent être remplies.
- Les colonnes marquées *référence* (ex: `site_code`, `vlan_id`) font un lookup sur l'entité existante — si introuvable, l'import échoue pour cette ligne.
- Mode d'import au choix : **create_only**, **update_only**, **upsert** (clé déterminée par entité, cf tableaux).
- Dry-run disponible : le backend parse, valide, retourne le rapport sans écrire.

## Formats

### Sites (`sites.csv`)

| Colonne | Obligatoire | Exemple | Commentaire |
|---------|-------------|---------|-------------|
| code | oui | `PAR` | Clé d'upsert |
| name | oui | `Siège Paris` | |
| address | non | `12 rue X, 75001 Paris` | |

### Rooms (`rooms.csv`)

| Colonne | Obligatoire | Exemple | Commentaire |
|---------|-------------|---------|-------------|
| site_code | oui (ref) | `PAR` | Doit exister |
| code | oui | `SALLE-SRV-01` | Clé d'upsert avec `site_code` |
| description | non | `Baie A, U1-U42` | |

### VLANs (`vlans.csv`)

| Colonne | Obligatoire | Exemple | Commentaire |
|---------|-------------|---------|-------------|
| vlan_id | oui | `30` | Clé d'upsert, 1-4094 |
| name | oui | `VLAN-VOIP` | |
| description | non | `Téléphonie Fanvil` | |
| color | non | `#F97316` | Hex |

### Subnets (`subnets.csv`)

| Colonne | Obligatoire | Exemple | Commentaire |
|---------|-------------|---------|-------------|
| cidr | oui | `10.0.30.0/24` | Clé d'upsert |
| gateway | non | `10.0.30.1` | Doit être dans le CIDR |
| vlan_id | non (ref) | `30` | VLAN number |
| site_code | oui (ref) | `PAR` | |
| description | non | `Téléphonie étage 1` | |
| dhcp_enabled | non | `true` | bool |
| dhcp_range_start | non | `10.0.30.50` | |
| dhcp_range_end | non | `10.0.30.200` | |

### IPs (`ips.csv`)

| Colonne | Obligatoire | Exemple | Commentaire |
|---------|-------------|---------|-------------|
| address | oui | `10.0.30.47` | Clé d'upsert |
| status | oui | `assigned` | `reserved`, `assigned`, `dhcp` |
| hostname | non | `fanvil-accueil-01` | |
| mac | non | `aa:bb:cc:dd:ee:ff` | Formats acceptés : `aa:bb:...`, `aa-bb-...`, `aabb.ccdd...` |
| device_name | non (ref) | `fanvil-accueil-01` | Si fourni, lookup sur `devices.name` ; créé si absent + `auto_create_device=true` |
| description | non | `Téléphone Fanvil X3U accueil` | |

Note : le `subnet_id` est déduit automatiquement de l'IP (cherche le subnet qui contient l'adresse).

### Devices (`devices.csv`)

| Colonne | Obligatoire | Exemple | Commentaire |
|---------|-------------|---------|-------------|
| name | oui | `srv-ad-01` | Clé d'upsert |
| type | oui | `server` | enum |
| vendor | non | `Dell` | |
| model | non | `PowerEdge R640` | |
| serial | non | `7X8Y9Z0` | |
| site_code | non (ref) | `PAR` | |
| room_code | non (ref) | `SALLE-SRV-01` | |
| description | non | `Contrôleur de domaine principal` | |

### Switches (`switches.csv`)

| Colonne | Obligatoire | Exemple | Commentaire |
|---------|-------------|---------|-------------|
| name | oui | `SW-SRV-01` | Clé d'upsert |
| vendor | non | `Aruba` | |
| model | non | `2930F-48G` | |
| serial | non | `CN12AB3DEF` | |
| management_ip | non | `10.0.10.251` | |
| site_code | oui (ref) | `PAR` | |
| room_code | oui (ref) | `SALLE-SRV-01` | |
| rack_position | non | `U12` | |
| port_count | oui | `48` | À la création, génère N ports |
| firmware_version | non | `WC.16.10.0023` | |

**Important** : si un switch est **créé**, les ports 1..N sont auto-générés vides. Si le switch existe déjà (upsert), `port_count` ne peut pas être diminué sans confirmation explicite.

### Ports (`ports.csv`)

| Colonne | Obligatoire | Exemple | Commentaire |
|---------|-------------|---------|-------------|
| switch_name | oui (ref) | `SW-SRV-01` | |
| number | oui | `14` | Clé d'upsert avec `switch_name` |
| label | non | `Bureau compta 3` | |
| mode | non | `access` | `access`, `trunk`, `hybrid`, `disabled` — défaut `access` |
| native_vlan | non (ref) | `30` | VLAN number |
| trunk_vlans | non | `10,20,30` | Liste séparée virgules |
| admin_status | non | `up` | défaut `up` |
| device_name | non (ref) | `fanvil-accueil-01` | Équipement connecté |
| connected_ip | non | `10.0.30.47` | IP vue sur ce port |
| notes | non | `Câble bleu B14` | |

### Links (`links.csv`)

| Colonne | Obligatoire | Exemple | Commentaire |
|---------|-------------|---------|-------------|
| switch_a | oui (ref) | `SW-SRV-01` | |
| port_a | oui | `48` | |
| switch_b | oui (ref) | `SW-ETAGE-01` | |
| port_b | oui | `24` | |
| link_type | non | `fiber` | `copper`, `fiber`, `dac`, `virtual` — défaut `copper` |
| speed_mbps | non | `10000` | |
| description | non | `Uplink étage 1` | |

## Comportement

### Upsert
- Clé d'upsert (colonne ou combinaison) explicitée dans chaque tableau.
- Si l'entité existe → update des colonnes fournies (colonnes vides = pas touchées).
- Si elle n'existe pas → création.

### Erreurs
- Le backend parse tout le fichier, applique les mutations dans une **transaction**.
- En cas d'erreur, **rollback complet** et retour d'un rapport détaillé ligne par ligne.
- Rapport :
```json
{
  "parsed_rows": 124,
  "ok_rows": 120,
  "error_rows": [
    { "line": 17, "column": "vlan_id", "value": "999", "error": "VLAN 999 not found" },
    { "line": 23, "column": "address", "value": "10.0.99.5", "error": "No subnet contains this IP" }
  ],
  "applied": false  // true si dry_run=false et pas d'erreur
}
```

### Ordre d'import recommandé

Pour une installation from scratch, importer dans cet ordre (dépendances) :

1. `sites.csv`
2. `rooms.csv`
3. `vlans.csv`
4. `subnets.csv`
5. `devices.csv`
6. `switches.csv`
7. `ports.csv`
8. `ips.csv` (après devices pour le lookup `device_name`)
9. `links.csv`

## Export

`GET /api/exports/{entity}?format=csv` retourne un fichier avec le même format que l'import. Permet des round-trips propres (export → modif Excel → re-import en upsert).

Pour les admins, un endpoint `GET /api/exports/all` génère un zip avec toutes les tables — sert de backup logique complémentaire au `pg_dump`.
