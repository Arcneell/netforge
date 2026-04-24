# 03 — Modèle de données

Le schéma utilise PostgreSQL 16. Les types `INET`, `CIDR` et `MACADDR` sont natifs — on ne les stocke pas en `VARCHAR`.

## Diagramme ER (synthétique)

```
sites (1) ──< (N) rooms (1) ──< (N) switches (1) ──< (N) ports
                                     │                      │
                                     │                      └─< links (switch-to-switch)
                                     │
vlans (N) ──< vlan_subnet >── (N) subnets (1) ──< (N) ips
                                     │                      │
                                     │                      └──> devices (FK optionnelle)
                                     │
                                     └──> vlan par port (access/trunk) via table `port_vlan`

users, audit_log (transverse)
```

## Tables détaillées

### `sites`
Les sites physiques (agences, sièges, datacenters).

| Colonne | Type | Contrainte | Description |
|---------|------|-----------|-------------|
| id | serial | PK | |
| code | varchar(20) | UNIQUE NOT NULL | Code court, ex: `PAR`, `LYON` |
| name | varchar(200) | NOT NULL | Nom complet, ex: `Siège Paris` |
| address | text | | Adresse postale |
| created_at | timestamptz | DEFAULT now() | |
| updated_at | timestamptz | DEFAULT now() | |

### `rooms`
Salles / locaux techniques / baies dans un site.

| Colonne | Type | Contrainte | Description |
|---------|------|-----------|-------------|
| id | serial | PK | |
| site_id | int | FK → sites(id) ON DELETE RESTRICT | |
| code | varchar(50) | NOT NULL | Ex: `SALLE-SRV-01`, `BAIE-A` |
| description | text | | |
| UNIQUE (site_id, code) | | | |

### `vlans`
VLANs du parc.

| Colonne | Type | Contrainte | Description |
|---------|------|-----------|-------------|
| id | serial | PK | |
| vlan_id | int | UNIQUE NOT NULL CHECK (vlan_id BETWEEN 1 AND 4094) | |
| name | varchar(100) | NOT NULL | Ex: `VLAN-USERS`, `VLAN-VOIP` |
| description | text | | |
| color | varchar(7) | | Hex `#RRGGBB` pour affichage |

### `subnets`
Sous-réseaux IPv4.

| Colonne | Type | Contrainte | Description |
|---------|------|-----------|-------------|
| id | serial | PK | |
| cidr | cidr | NOT NULL | Ex: `10.0.30.0/24` |
| gateway | inet | | Passerelle |
| vlan_id | int | FK → vlans(id) ON DELETE SET NULL | Le VLAN principal du subnet |
| site_id | int | FK → sites(id) ON DELETE RESTRICT | |
| description | text | | |
| dhcp_enabled | bool | DEFAULT false | Info indicative (DHCP géré par Windows) |
| dhcp_range_start | inet | | |
| dhcp_range_end | inet | | |
| created_at | timestamptz | DEFAULT now() | |
| updated_at | timestamptz | DEFAULT now() | |

**Contrainte clé** — pas de chevauchement :
```sql
ALTER TABLE subnets ADD CONSTRAINT subnets_no_overlap
  EXCLUDE USING gist (cidr inet_ops WITH &&);
```

### `ips`
Adresses IP individuelles (réservées, attribuées).

| Colonne | Type | Contrainte | Description |
|---------|------|-----------|-------------|
| id | serial | PK | |
| subnet_id | int | FK → subnets(id) ON DELETE CASCADE | |
| address | inet | NOT NULL UNIQUE | |
| hostname | varchar(255) | | FQDN ou nom court |
| mac | macaddr | | MAC si connue |
| device_id | int | FK → devices(id) ON DELETE SET NULL | |
| status | enum | NOT NULL | `reserved`, `assigned`, `dhcp` |
| description | text | | |
| created_at | timestamptz | DEFAULT now() | |
| updated_at | timestamptz | DEFAULT now() | |

**Contrainte métier** (trigger ou CHECK) :
```sql
-- address doit être contenue dans le subnet du subnet_id
CREATE FUNCTION check_ip_in_subnet() RETURNS trigger AS $$
BEGIN
  IF NEW.address <<= (SELECT cidr FROM subnets WHERE id = NEW.subnet_id) THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'IP % not in subnet', NEW.address;
END;
$$ LANGUAGE plpgsql;
```

### `devices`
Équipements physiques ou virtuels qui portent une IP ou sont branchés sur un port.

| Colonne | Type | Contrainte | Description |
|---------|------|-----------|-------------|
| id | serial | PK | |
| name | varchar(255) | NOT NULL | Hostname principal |
| type | enum | NOT NULL | `server`, `desktop`, `laptop`, `printer`, `phone`, `ap`, `camera`, `ups`, `other` |
| vendor | varchar(100) | | `HP`, `Lenovo`, `Fanvil`, `Aruba`... |
| model | varchar(100) | | |
| serial | varchar(100) | | |
| room_id | int | FK → rooms(id) ON DELETE SET NULL | |
| description | text | | |

### `switches`
Switches spécifiquement — hérite conceptuellement de `devices` mais table séparée car champs spécifiques.

| Colonne | Type | Contrainte | Description |
|---------|------|-----------|-------------|
| id | serial | PK | |
| name | varchar(100) | UNIQUE NOT NULL | Ex: `SW-SRV-01` |
| vendor | varchar(50) | | `Aruba`, `HP`, `Cisco` |
| model | varchar(100) | | Ex: `Aruba 2930F-48G` |
| serial | varchar(100) | | |
| management_ip | inet | | IP de management |
| room_id | int | FK → rooms(id) ON DELETE RESTRICT | |
| rack_position | varchar(20) | | Ex: `U12` |
| port_count | int | NOT NULL CHECK (port_count > 0) | Nombre total de ports |
| firmware_version | varchar(50) | | |
| snmp_community | varchar(100) | | Chiffré au repos (pgcrypto) — pour v2 |
| description | text | | |
| created_at | timestamptz | DEFAULT now() | |
| updated_at | timestamptz | DEFAULT now() | |

### `ports`
Ports d'un switch. Créés automatiquement à la création du switch (trigger ou service).

| Colonne | Type | Contrainte | Description |
|---------|------|-----------|-------------|
| id | serial | PK | |
| switch_id | int | FK → switches(id) ON DELETE CASCADE | |
| number | int | NOT NULL | Numéro de port (1, 2, ...) |
| label | varchar(100) | | Libellé libre, ex: `Bureau compta 3` |
| mode | enum | NOT NULL DEFAULT 'access' | `access`, `trunk`, `hybrid`, `disabled` |
| native_vlan_id | int | FK → vlans(id) ON DELETE SET NULL | VLAN natif pour access, natif trunk |
| admin_status | enum | NOT NULL DEFAULT 'up' | `up`, `down` |
| connected_device_id | int | FK → devices(id) ON DELETE SET NULL | Équipement branché |
| connected_ip_id | int | FK → ips(id) ON DELETE SET NULL | IP vue sur ce port (si connue) |
| notes | text | | |
| UNIQUE (switch_id, number) | | | |

### `port_vlan`
Table de liaison pour les ports en mode `trunk` — liste des VLANs tagués.

| Colonne | Type | Contrainte | Description |
|---------|------|-----------|-------------|
| port_id | int | FK → ports(id) ON DELETE CASCADE | |
| vlan_id | int | FK → vlans(id) ON DELETE CASCADE | |
| PRIMARY KEY (port_id, vlan_id) | | | |

### `links`
Liens entre deux ports de switches (uplinks, cascades).

| Colonne | Type | Contrainte | Description |
|---------|------|-----------|-------------|
| id | serial | PK | |
| port_a_id | int | FK → ports(id) ON DELETE CASCADE NOT NULL | |
| port_b_id | int | FK → ports(id) ON DELETE CASCADE NOT NULL | |
| link_type | enum | NOT NULL | `copper`, `fiber`, `dac`, `virtual` |
| speed_mbps | int | | `1000`, `10000`... |
| description | text | | |
| CHECK (port_a_id <> port_b_id) | | | |
| UNIQUE (port_a_id, port_b_id) | | | |

**Symétrie** : on stocke `(a, b)` avec `a < b` pour éviter les doublons inverses (contrainte via trigger ou service).

### `users`
Utilisateurs Netforge, provisionnés à la première connexion Entra ID (JIT).

| Colonne | Type | Contrainte | Description |
|---------|------|-----------|-------------|
| id | serial | PK | |
| entra_oid | uuid | UNIQUE NOT NULL | `oid` claim du token Entra |
| email | varchar(255) | NOT NULL | |
| display_name | varchar(255) | | |
| role | enum | NOT NULL DEFAULT 'viewer' | `viewer`, `admin` |
| last_login_at | timestamptz | | |
| created_at | timestamptz | DEFAULT now() | |

### `audit_log`
Trace complète des écritures.

| Colonne | Type | Contrainte | Description |
|---------|------|-----------|-------------|
| id | bigserial | PK | |
| user_id | int | FK → users(id) ON DELETE SET NULL | |
| action | enum | NOT NULL | `create`, `update`, `delete` |
| entity | varchar(50) | NOT NULL | `subnet`, `ip`, `switch`, `port`... |
| entity_id | int | | |
| changes | jsonb | | `{ "before": {...}, "after": {...} }` |
| ip_address | inet | | IP source de la requête |
| user_agent | text | | |
| created_at | timestamptz | DEFAULT now() NOT NULL | |

**Index** : `(entity, entity_id)`, `(user_id)`, `(created_at DESC)`.

## Résumé des relations critiques

- `subnet.vlan_id` → un subnet a 0 ou 1 VLAN "principal".
- `port.native_vlan_id` → un port a 0 ou 1 VLAN natif/access.
- `port_vlan` → un port en trunk a N VLANs tagués.
- `ip.device_id` → une IP pointe sur 0 ou 1 device.
- `port.connected_device_id` → un port voit 0 ou 1 device.
- Un device peut avoir plusieurs IPs (via `ips.device_id`) et être branché sur plusieurs ports (rare mais possible — LAG).

## Migrations

Toutes les modifications de schéma passent par **Alembic**. Les migrations sont versionnées dans `backend/alembic/versions/` et numérotées. Aucune modification manuelle en prod.

La migration initiale `0001_initial.py` crée toutes les tables ci-dessus, les contraintes GiST et les triggers. Elle est accompagnée d'une migration `0002_seed.py` qui insère des données de départ (VLANs standards 1/10/20/30, un site "Siège" par défaut).
