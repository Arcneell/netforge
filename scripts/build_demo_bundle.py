"""Generate a comprehensive NetForge bulk-import bundle with planted issues.

Builds one CSV per entity (sites, rooms, vlans, subnets, devices, switches,
ips, ports, links) and packs them into `demo-bundle.zip` at the repo root.

Scope (~3× the previous demo):
  - 9 sites: 5 datacentres + 4 branch offices
  - 34 rooms, 51 VLANs (3 deliberately orphan), ~75 subnets
  - 145 devices spanning every type, 38 switches across vendors
  - ~205 IPs with mixed statuses + MACs in three Cisco-friendly formats
  - ~310 port configurations (access/trunk/hybrid/disabled, native+tagged)
  - ~55 inter-switch links across copper/fiber/dac/virtual

Planted issues (so the integrity check + AI advisor have something to flag):
  P1) SPOF — Marseille DC has a single core switch, no peer, with the
      production DB plugged into it. AI advisor target.
  P2) SPOF — Strasbourg branch is served by a single edge switch; both APs,
      the firewall and the server all hang off it. AI advisor target.
  P3) CAPACITY (critical) — `10.20.90.0/29` is fully saturated (6/6 used).
  P4) CAPACITY (warning) — `10.10.21.0/24` (IT) at ~92% to trigger the
      90% threshold without crossing 100%.
  P5) CAPACITY (warning) — `sw-edge-str-01` has 24/24 access ports busy.
  P6) DUPLICATE MAC — two distinct IPs/devices share `00:1a:2b:3c:4d:ff`.
  P7) ORPHAN VLANs — VLANs 250 (LEGACY), 251 (OBSOLETE), 252 (PILOT) are
      declared but no subnet uses them.
  P8) NO GATEWAY — three subnets are intentionally gateway-less.
  P9) PORT LABEL DUP — `sw-dist-par-01` has two ports labelled "spare".

Run from the repo root:
    python scripts/build_demo_bundle.py
"""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path


# --------------------------------------------------------------------------- #
# Sites + rooms
# --------------------------------------------------------------------------- #

SITES: list[tuple[str, str, str]] = [
    # (code, name, address)
    ("PAR-DC1", "Paris — Datacenter principal", "12 rue de Rivoli, 75001 Paris"),
    ("LYO-DC2", "Lyon — Datacenter secondaire", "5 quai Saint-Antoine, 69002 Lyon"),
    ("MRS-DC3", "Marseille — Datacenter sud", "44 La Canebière, 13001 Marseille"),
    ("BOR-DC4", "Bordeaux — Datacenter ouest", "18 cours de l'Intendance, 33000 Bordeaux"),
    ("NTS-DC5", "Nantes — Datacenter atlantique", "9 place Royale, 44000 Nantes"),
    ("NCE-EDGE", "Nice — Site edge", "3 avenue Jean Médecin, 06000 Nice"),
    ("TLS-EDGE", "Toulouse — Site edge", "14 place du Capitole, 31000 Toulouse"),
    ("LIL-EDGE", "Lille — Site edge", "7 Grand Place, 59000 Lille"),
    ("STR-EDGE", "Strasbourg — Site edge", "11 place Kléber, 67000 Strasbourg"),
]

# DC sites get a richer room layout; branches get a couple of rooms.
ROOM_LAYOUTS: dict[str, list[tuple[str, str]]] = {
    "dc-large": [
        ("MDF-01", "Salle principale — distribution coeur"),
        ("IDF-01", "Étage 1 — armoire utilisateurs"),
        ("IDF-02", "Étage 2 — armoire utilisateurs"),
        ("SERVER-A", "Allée A — serveurs production"),
        ("SERVER-B", "Allée B — stockage et sauvegarde"),
    ],
    "dc": [
        ("MDF-01", "Salle coeur de réseau"),
        ("IDF-01", "Armoire étage 1"),
        ("SERVER-A", "Salle serveurs"),
    ],
    "branch": [
        ("MAIN", "Salle technique principale"),
        ("RACK-01", "Rack télécom"),
    ],
}

SITE_KIND: dict[str, str] = {
    "PAR-DC1": "dc-large",
    "LYO-DC2": "dc-large",
    "MRS-DC3": "dc",
    "BOR-DC4": "dc",
    "NTS-DC5": "dc",
    "NCE-EDGE": "branch",
    "TLS-EDGE": "branch",
    "LIL-EDGE": "branch",
    "STR-EDGE": "branch",
}

ROOMS: list[tuple[str, str, str]] = []
for site_code in [s[0] for s in SITES]:
    for room_code, room_desc in ROOM_LAYOUTS[SITE_KIND[site_code]]:
        ROOMS.append((site_code, room_code, room_desc))


# --------------------------------------------------------------------------- #
# VLAN catalogue — shared across sites
# --------------------------------------------------------------------------- #

VLANS: list[tuple[int, str, str, str]] = [
    # (vlan_id, name, description, color)
    (1, "default", "VLAN par défaut — à éviter en production", ""),
    (10, "MGMT", "Administration équipements réseau", "#3b82f6"),
    (11, "MGMT-CORE", "Administration coeur (séparé)", "#2563eb"),
    (12, "MGMT-WIFI", "Contrôleurs Wi-Fi", "#1d4ed8"),
    (20, "USERS", "Postes utilisateurs standards", "#10b981"),
    (21, "USERS-IT", "Équipe IT — accès étendu", "#22c55e"),
    (22, "USERS-DIR", "Direction et secrétariat", "#84cc16"),
    (23, "USERS-DEV", "Développeurs", "#86efac"),
    (24, "USERS-FIN", "Finance & comptabilité", "#16a34a"),
    (25, "USERS-COM", "Communication & marketing", "#4ade80"),
    (30, "WIFI-CORP", "Wi-Fi corporate (802.1X)", "#f59e0b"),
    (31, "WIFI-GUEST", "Wi-Fi invités (portail captif)", "#fbbf24"),
    (32, "WIFI-IOT", "Wi-Fi IoT — bande 2.4G dédiée", "#fde047"),
    (40, "VOICE", "Téléphonie IP — QoS DSCP 46", "#ec4899"),
    (41, "VOICE-CONF", "Salles de conférence (codecs vidéo)", "#f472b6"),
    (50, "PRINTERS", "Imprimantes et multifonctions", "#a855f7"),
    (51, "BADGES", "Lecteurs de badges + contrôle d'accès", "#c084fc"),
    (60, "SERVERS", "Serveurs applicatifs", "#ef4444"),
    (61, "SERVERS-DB", "Bases de données — isolé", "#dc2626"),
    (62, "SERVERS-WEB", "Front web — accès DMZ", "#b91c1c"),
    (63, "SERVERS-K8S", "Cluster Kubernetes — pods", "#991b1b"),
    (64, "SERVERS-CI", "Runners CI/CD", "#7f1d1d"),
    (70, "IOT", "Caméras + capteurs", "#65a30d"),
    (71, "IOT-HVAC", "Climatisation + supervision énergie", "#a3e635"),
    (72, "IOT-DOOR", "Contrôle d'accès aux locaux", "#bef264"),
    (80, "IPMI", "Out-of-band management (BMC)", "#737373"),
    (81, "IPMI-DR", "IPMI réservé au site DR", "#525252"),
    (90, "DMZ", "Zone démilitarisée — accès externe", "#f97316"),
    (91, "DMZ-EXT", "DMZ étendue — partenaires", "#fb923c"),
    (100, "STORAGE", "Trafic SAN / iSCSI", "#0ea5e9"),
    (101, "STORAGE-NFS", "Partages NFS", "#38bdf8"),
    (110, "VMOTION", "vMotion / live migration", "#22d3ee"),
    (120, "REPLICATION", "Réplication DB inter-DC", "#67e8f9"),
    (200, "BACKUP", "Réseau de sauvegarde Veeam", "#06b6d4"),
    (201, "BACKUP-OFFSITE", "Cible offsite", "#0e7490"),
    (210, "GUEST-DEMO", "Réseau démo / labs ponctuels", "#94a3b8"),
    (220, "PARTNERS", "Accès partenaires (extranet)", "#cbd5e1"),
    (230, "DEV-TEST", "Lab dev — non production", "#9ca3af"),
    (231, "DEV-STAGE", "Pre-prod / staging", "#6b7280"),
    (240, "FREEBOX", "Liaison opérateur FAI", "#fef3c7"),
    (241, "MPLS", "Liaison MPLS interbâtiments", "#fed7aa"),
    (242, "SDWAN", "Overlay SD-WAN", "#fdba74"),
    # Site-specific (security, video, etc.)
    (150, "VIDEO-CONF", "Codecs vidéoconférence", "#fce7f3"),
    (151, "SIGNAGE", "Affichage dynamique / écrans hall", "#fbcfe8"),
    (160, "ELEC", "Compteurs énergie + automates", "#fde68a"),
    (161, "PV-SOLAR", "Onduleurs photovoltaïques", "#fcd34d"),
    # P7) Orphan VLANs — declared, never used by any subnet (integrity flag).
    (250, "LEGACY", "Ancien réseau à dégager — migration en cours", "#475569"),
    (251, "OBSOLETE", "VLAN abandonné — non purgé", "#1e293b"),
    (252, "PILOT", "Pilote temporaire — à supprimer si non utilisé", "#0f172a"),
]


# --------------------------------------------------------------------------- #
# Subnets — programmatic per site so the /16 supernets auto-group
# --------------------------------------------------------------------------- #

# Site → /16 second octet. PAR=10, LYO=20, MRS=30, BOR=40, NTS=50,
# branches stay on 192.168.SS.x to mix v4 ranges.
SITE_SUBNET_OCTET: dict[str, int] = {
    "PAR-DC1": 10,
    "LYO-DC2": 20,
    "MRS-DC3": 30,
    "BOR-DC4": 40,
    "NTS-DC5": 50,
}

# Per-site subnet template. For DCs we materialise the full server set;
# branches get the bare minimum.
def dc_subnets(site: str, octet: int) -> list[tuple]:
    """Yield (cidr, gw, vlan_id, site_code, desc, dhcp, dhcp_start, dhcp_end)."""
    return [
        # Management
        (f"10.{octet}.10.0/24", f"10.{octet}.10.1", 10, site, f"{site} management — équipements réseau", False, "", ""),
        (f"10.{octet}.11.0/24", f"10.{octet}.11.1", 11, site, f"{site} MGMT coeur (séparé)", False, "", ""),
        # Users (DHCP)
        (f"10.{octet}.20.0/24", f"10.{octet}.20.1", 20, site, f"{site} users", True, f"10.{octet}.20.100", f"10.{octet}.20.250"),
        (f"10.{octet}.21.0/24", f"10.{octet}.21.1", 21, site, "IT department", True, f"10.{octet}.21.100", f"10.{octet}.21.250"),
        (f"10.{octet}.22.0/24", f"10.{octet}.22.1", 22, site, "Direction", True, f"10.{octet}.22.50", f"10.{octet}.22.150"),
        (f"10.{octet}.23.0/24", f"10.{octet}.23.1", 23, site, "Développeurs", True, f"10.{octet}.23.50", f"10.{octet}.23.250"),
        # Wi-Fi
        (f"10.{octet}.30.0/24", f"10.{octet}.30.1", 30, site, "WiFi corporate", True, f"10.{octet}.30.50", f"10.{octet}.30.250"),
        (f"10.{octet}.31.0/24", f"10.{octet}.31.1", 31, site, "WiFi guests", True, f"10.{octet}.31.50", f"10.{octet}.31.250"),
        # Voice
        (f"10.{octet}.40.0/24", f"10.{octet}.40.1", 40, site, "VoIP", True, f"10.{octet}.40.100", f"10.{octet}.40.250"),
        # Printers
        (f"10.{octet}.50.0/24", f"10.{octet}.50.1", 50, site, "Printers", False, "", ""),
        # Servers
        (f"10.{octet}.60.0/24", f"10.{octet}.60.1", 60, site, "Server farm", False, "", ""),
        (f"10.{octet}.61.0/24", f"10.{octet}.61.1", 61, site, "Database servers", False, "", ""),
        (f"10.{octet}.62.0/24", f"10.{octet}.62.1", 62, site, "Web servers", False, "", ""),
        (f"10.{octet}.63.0/24", f"10.{octet}.63.1", 63, site, "Kubernetes pods", False, "", ""),
        # IoT + IPMI
        (f"10.{octet}.70.0/24", f"10.{octet}.70.1", 70, site, "IoT cameras + sensors", True, f"10.{octet}.70.100", f"10.{octet}.70.250"),
        (f"10.{octet}.80.0/24", f"10.{octet}.80.1", 80, site, "Out-of-band IPMI", False, "", ""),
        # DMZ (small) + storage + backup
        (f"10.{octet}.90.0/29", f"10.{octet}.90.1", 90, site, "DMZ — small block", False, "", ""),
        (f"10.{octet}.100.0/24", f"10.{octet}.100.1", 100, site, "Storage SAN", False, "", ""),
        (f"10.{octet}.200.0/24", f"10.{octet}.200.1", 200, site, "Backup traffic", False, "", ""),
    ]


SUBNETS: list[tuple] = []
for site, octet in SITE_SUBNET_OCTET.items():
    SUBNETS.extend(dc_subnets(site, octet))

# Branch sites — lighter footprint (192.168.SSx.0/24)
BRANCH_OFFSETS: dict[str, int] = {
    "NCE-EDGE": 10,
    "TLS-EDGE": 20,
    "LIL-EDGE": 30,
    "STR-EDGE": 40,
}
for site, off in BRANCH_OFFSETS.items():
    SUBNETS.extend([
        (f"192.168.{off}.0/24", f"192.168.{off}.1", 10, site, f"{site} MGMT", False, "", ""),
        (f"192.168.{off + 1}.0/24", f"192.168.{off + 1}.1", 20, site, f"{site} users", True, f"192.168.{off + 1}.50", f"192.168.{off + 1}.200"),
        (f"192.168.{off + 2}.0/24", f"192.168.{off + 2}.1", 30, site, f"{site} WiFi corporate", True, f"192.168.{off + 2}.50", f"192.168.{off + 2}.250"),
        (f"192.168.{off + 3}.0/24", f"192.168.{off + 3}.1", 40, site, f"{site} VoIP", True, f"192.168.{off + 3}.100", f"192.168.{off + 3}.200"),
    ])

# Lab + extra ranges across PAR (172.16/12 lab)
SUBNETS.extend([
    ("172.16.0.0/22", "172.16.0.1", None, "PAR-DC1", "Lab réseau (sans VLAN)", False, "", ""),
    ("172.16.10.0/24", "172.16.10.1", 230, "PAR-DC1", "Lab dev — segment 10", False, "", ""),
    ("172.16.20.0/28", "172.16.20.1", 230, "PAR-DC1", "Lab — petit segment /28", False, "", ""),
    ("172.16.30.0/24", "172.16.30.1", 231, "PAR-DC1", "Staging — pré-prod", False, "", ""),
    # P8) Three subnets without gateway → integrity "no_gateway" check
    ("172.16.40.0/30", "", None, "PAR-DC1", "Point-à-point sans GW (lab P2P)", False, "", ""),
    ("172.16.41.0/30", "", None, "PAR-DC1", "Point-à-point sans GW (lab P2P bis)", False, "", ""),
    ("172.16.250.0/24", "", None, "PAR-DC1", "Sous-réseau oublié — sans GW", False, "", ""),
    # Inter-DC replication subnets
    ("10.255.10.0/30", "10.255.10.1", 120, "PAR-DC1", "Réplication DB PAR ↔ LYO", False, "", ""),
    ("10.255.11.0/30", "10.255.11.1", 120, "LYO-DC2", "Réplication DB LYO ↔ MRS", False, "", ""),
    ("10.255.12.0/30", "10.255.12.1", 120, "MRS-DC3", "Réplication DB MRS ↔ BOR", False, "", ""),
])


# --------------------------------------------------------------------------- #
# Devices
# --------------------------------------------------------------------------- #

DEVICES: list[tuple] = []


def add_devices(rows: list[tuple]) -> None:
    DEVICES.extend(rows)


# Paris — large DC: rich device set
add_devices([
    # Servers (production)
    ("srv-app-par-01", "server", "Dell", "PowerEdge R750", "PE-001A", "PAR-DC1", "SERVER-A", "Frontal applicatif #1"),
    ("srv-app-par-02", "server", "Dell", "PowerEdge R750", "PE-001B", "PAR-DC1", "SERVER-A", "Frontal applicatif #2"),
    ("srv-app-par-03", "server", "Dell", "PowerEdge R750", "PE-001C", "PAR-DC1", "SERVER-A", "Frontal applicatif #3"),
    ("srv-db-par-01", "server", "HPE", "ProLiant DL380 Gen11", "HP-DB-001", "PAR-DC1", "SERVER-A", "PostgreSQL primaire"),
    ("srv-db-par-02", "server", "HPE", "ProLiant DL380 Gen11", "HP-DB-002", "PAR-DC1", "SERVER-A", "PostgreSQL réplica"),
    ("srv-db-par-03", "server", "HPE", "ProLiant DL380 Gen11", "HP-DB-003", "PAR-DC1", "SERVER-A", "MariaDB legacy"),
    ("srv-web-par-01", "server", "Supermicro", "SYS-510P", "SM-WEB-001", "PAR-DC1", "SERVER-A", "Nginx front #1"),
    ("srv-web-par-02", "server", "Supermicro", "SYS-510P", "SM-WEB-002", "PAR-DC1", "SERVER-A", "Nginx front #2"),
    ("srv-k8s-par-01", "server", "Dell", "PowerEdge R760", "PE-K8S-001", "PAR-DC1", "SERVER-A", "K8s worker #1"),
    ("srv-k8s-par-02", "server", "Dell", "PowerEdge R760", "PE-K8S-002", "PAR-DC1", "SERVER-A", "K8s worker #2"),
    ("srv-k8s-par-03", "server", "Dell", "PowerEdge R760", "PE-K8S-003", "PAR-DC1", "SERVER-A", "K8s worker #3"),
    ("srv-ci-par-01", "server", "Lenovo", "ThinkSystem SR650", "LN-CI-001", "PAR-DC1", "SERVER-A", "Runner CI GitHub Actions"),
    ("srv-mon-par-01", "server", "Dell", "PowerEdge R650", "PE-MON-001", "PAR-DC1", "SERVER-B", "Prometheus + Grafana"),
    ("srv-log-par-01", "server", "Dell", "PowerEdge R650", "PE-LOG-001", "PAR-DC1", "SERVER-B", "Loki + ELK"),
    ("srv-bkp-par-01", "server", "QNAP", "TS-h2490FU", "QN-BKP-001", "PAR-DC1", "SERVER-B", "Sauvegarde Veeam #1"),
    ("srv-bkp-par-02", "server", "QNAP", "TS-h2490FU", "QN-BKP-002", "PAR-DC1", "SERVER-B", "Sauvegarde Veeam #2"),
    ("srv-storage-par-01", "server", "NetApp", "AFF C400", "NA-STO-001", "PAR-DC1", "SERVER-B", "Baie SAN principale"),
    ("srv-storage-par-02", "server", "NetApp", "AFF A250", "NA-STO-002", "PAR-DC1", "SERVER-B", "Baie SAN secondaire"),
    ("srv-nfs-par-01", "server", "Synology", "SA3610", "SY-NFS-001", "PAR-DC1", "SERVER-B", "Partages NFS"),
    # Workstations / laptops
    ("pc-it-par-01", "desktop", "Lenovo", "ThinkCentre M90q", "LV-PC-001", "PAR-DC1", "IDF-01", "Poste IT — admin réseau"),
    ("pc-it-par-02", "desktop", "Lenovo", "ThinkCentre M90q", "LV-PC-002", "PAR-DC1", "IDF-01", "Poste IT — sysadmin"),
    ("pc-it-par-03", "desktop", "Lenovo", "ThinkCentre M90q", "LV-PC-003", "PAR-DC1", "IDF-01", "Poste IT — sécurité"),
    ("pc-rh-par-01", "desktop", "HP", "EliteDesk 800 G9", "HP-PC-001", "PAR-DC1", "IDF-02", "Poste RH"),
    ("pc-fin-par-01", "desktop", "HP", "EliteDesk 800 G9", "HP-PC-002", "PAR-DC1", "IDF-02", "Poste Finance"),
    ("pc-com-par-01", "desktop", "Apple", "iMac 27", "AP-PC-001", "PAR-DC1", "IDF-02", "Poste Communication"),
    ("lap-dir-par-01", "laptop", "Apple", "MacBook Pro 14 M3", "AP-LAP-001", "PAR-DC1", "", "Portable direction"),
    ("lap-dir-par-02", "laptop", "Apple", "MacBook Pro 14 M3", "AP-LAP-002", "PAR-DC1", "", "Portable direction adjointe"),
    ("lap-dev-par-01", "laptop", "Dell", "XPS 15 9530", "DL-LAP-001", "PAR-DC1", "IDF-02", "Portable développeur senior"),
    ("lap-dev-par-02", "laptop", "Dell", "XPS 15 9530", "DL-LAP-002", "PAR-DC1", "IDF-02", "Portable développeur"),
    ("lap-dev-par-03", "laptop", "Framework", "Laptop 16", "FW-LAP-001", "PAR-DC1", "IDF-02", "Portable dev IT"),
    # Printers
    ("prt-color-par-01", "printer", "Konica", "bizhub C658", "KM-PRT-001", "PAR-DC1", "IDF-01", "Imprimante couleur étage 1"),
    ("prt-color-par-02", "printer", "Konica", "bizhub C658", "KM-PRT-002", "PAR-DC1", "IDF-02", "Imprimante couleur étage 2"),
    ("prt-bw-par-01", "printer", "Brother", "HL-L6210DW", "BR-PRT-001", "PAR-DC1", "IDF-02", "Imprimante N&B étage 2"),
    ("prt-label-par-01", "printer", "Zebra", "ZT411", "ZB-PRT-001", "PAR-DC1", "SERVER-A", "Imprimante étiquettes baies"),
    # Phones
    ("phone-acc-par-01", "phone", "Yealink", "T46U", "YL-PH-001", "PAR-DC1", "IDF-01", "Téléphone accueil"),
    ("phone-it-par-01", "phone", "Yealink", "T46U", "YL-PH-002", "PAR-DC1", "IDF-01", "Téléphone IT"),
    ("phone-dir-par-01", "phone", "Cisco", "8845", "CS-PH-001", "PAR-DC1", "IDF-02", "Téléphone direction"),
    ("phone-rh-par-01", "phone", "Yealink", "T46U", "YL-PH-003", "PAR-DC1", "IDF-02", "Téléphone RH"),
    ("phone-fin-par-01", "phone", "Yealink", "T46U", "YL-PH-004", "PAR-DC1", "IDF-02", "Téléphone Finance"),
    # APs / cams / UPS
    ("ap-rdc-par-01", "ap", "Aruba", "AP-535", "AR-AP-001", "PAR-DC1", "MDF-01", "Wi-Fi RDC ouest"),
    ("ap-rdc-par-02", "ap", "Aruba", "AP-535", "AR-AP-002", "PAR-DC1", "MDF-01", "Wi-Fi RDC est"),
    ("ap-et1-par-01", "ap", "Aruba", "AP-635", "AR-AP-003", "PAR-DC1", "IDF-01", "Wi-Fi étage 1 nord"),
    ("ap-et1-par-02", "ap", "Aruba", "AP-635", "AR-AP-004", "PAR-DC1", "IDF-01", "Wi-Fi étage 1 sud"),
    ("ap-et2-par-01", "ap", "Aruba", "AP-635", "AR-AP-005", "PAR-DC1", "IDF-02", "Wi-Fi étage 2 nord"),
    ("ap-et2-par-02", "ap", "Aruba", "AP-635", "AR-AP-006", "PAR-DC1", "IDF-02", "Wi-Fi étage 2 sud"),
    ("cam-park-par-01", "camera", "Axis", "P3267-LV", "AX-CAM-001", "PAR-DC1", "MDF-01", "Caméra parking"),
    ("cam-park-par-02", "camera", "Axis", "P3267-LV", "AX-CAM-002", "PAR-DC1", "MDF-01", "Caméra parking sud"),
    ("cam-entry-par-01", "camera", "Axis", "M3215-LVE", "AX-CAM-003", "PAR-DC1", "MDF-01", "Caméra entrée principale"),
    ("cam-entry-par-02", "camera", "Axis", "M3215-LVE", "AX-CAM-004", "PAR-DC1", "MDF-01", "Caméra entrée livraisons"),
    ("ups-room-a-par", "ups", "APC", "Smart-UPS SRT 10kVA", "AP-UPS-001", "PAR-DC1", "SERVER-A", "Onduleur salle A"),
    ("ups-room-b-par", "ups", "APC", "Smart-UPS SRT 10kVA", "AP-UPS-002", "PAR-DC1", "SERVER-B", "Onduleur salle B"),
    # Misc / appliances
    ("appliance-fw-par-01", "other", "Fortinet", "FortiGate 200F", "FG-FW-001", "PAR-DC1", "MDF-01", "Pare-feu principal Paris"),
    ("appliance-fw-par-02", "other", "Fortinet", "FortiGate 200F", "FG-FW-002", "PAR-DC1", "MDF-01", "Pare-feu redondant Paris"),
    ("appliance-lb-par-01", "other", "F5", "BIG-IP i5800", "F5-LB-001", "PAR-DC1", "SERVER-A", "Load balancer applicatif"),
    ("appliance-wan-par-01", "other", "Cisco", "Catalyst 8500", "CS-WAN-001", "PAR-DC1", "MDF-01", "Routeur WAN MPLS Paris"),
])

# Lyon — similar but slightly smaller
add_devices([
    ("srv-app-lyo-01", "server", "Dell", "PowerEdge R760", "PE-LYO-001", "LYO-DC2", "SERVER-A", "Frontal applicatif Lyon"),
    ("srv-app-lyo-02", "server", "Dell", "PowerEdge R760", "PE-LYO-002", "LYO-DC2", "SERVER-A", "Frontal applicatif Lyon #2"),
    ("srv-db-lyo-01", "server", "HPE", "ProLiant DL380 Gen11", "HP-LYO-DB-001", "LYO-DC2", "SERVER-A", "Réplica DB DR site"),
    ("srv-db-lyo-02", "server", "HPE", "ProLiant DL380 Gen11", "HP-LYO-DB-002", "LYO-DC2", "SERVER-A", "DB analytique"),
    ("srv-web-lyo-01", "server", "Supermicro", "SYS-510P", "SM-LYO-WEB-001", "LYO-DC2", "SERVER-A", "Nginx Lyon"),
    ("srv-bkp-lyo-01", "server", "QNAP", "TS-h1290FX", "QN-LYO-BKP-001", "LYO-DC2", "SERVER-A", "Sauvegarde DR Lyon"),
    ("srv-storage-lyo-01", "server", "NetApp", "AFF C250", "NA-LYO-STO-001", "LYO-DC2", "SERVER-A", "SAN Lyon"),
    ("ups-lyo-01", "ups", "APC", "Smart-UPS SRT 6kVA", "AP-LYO-UPS-001", "LYO-DC2", "SERVER-A", "Onduleur Lyon"),
    ("pc-it-lyo-01", "desktop", "Lenovo", "ThinkCentre M90q", "LV-LYO-PC-001", "LYO-DC2", "IDF-01", "Poste IT Lyon"),
    ("pc-it-lyo-02", "desktop", "Lenovo", "ThinkCentre M90q", "LV-LYO-PC-002", "LYO-DC2", "IDF-01", "Poste IT Lyon #2"),
    ("prt-color-lyo-01", "printer", "Konica", "bizhub C658", "KM-LYO-PRT-001", "LYO-DC2", "IDF-01", "Imprimante couleur Lyon"),
    ("phone-acc-lyo-01", "phone", "Yealink", "T46U", "YL-LYO-PH-001", "LYO-DC2", "IDF-01", "Téléphone accueil Lyon"),
    ("ap-lyo-01", "ap", "Aruba", "AP-635", "AR-LYO-AP-001", "LYO-DC2", "IDF-01", "Wi-Fi Lyon principal"),
    ("ap-lyo-02", "ap", "Aruba", "AP-635", "AR-LYO-AP-002", "LYO-DC2", "MDF-01", "Wi-Fi Lyon entrée"),
    ("cam-lyo-01", "camera", "Axis", "P3267-LV", "AX-LYO-CAM-001", "LYO-DC2", "MDF-01", "Caméra entrée Lyon"),
    ("appliance-fw-lyo-01", "other", "Fortinet", "FortiGate 100F", "FG-LYO-FW-001", "LYO-DC2", "MDF-01", "Pare-feu Lyon"),
    ("appliance-wan-lyo-01", "other", "Cisco", "Catalyst 8300", "CS-LYO-WAN-001", "LYO-DC2", "MDF-01", "Routeur WAN MPLS Lyon"),
])

# Marseille — DC where we plant the SPOF (single core, critical DB attached)
add_devices([
    ("srv-app-mrs-01", "server", "Dell", "PowerEdge R760", "PE-MRS-001", "MRS-DC3", "SERVER-A", "Frontal applicatif Marseille"),
    ("srv-db-mrs-01", "server", "HPE", "ProLiant DL380 Gen11", "HP-MRS-DB-001", "MRS-DC3", "SERVER-A", "Base de données production MRS — SPOF"),
    ("srv-storage-mrs-01", "server", "NetApp", "AFF C250", "NA-MRS-STO-001", "MRS-DC3", "SERVER-A", "SAN Marseille"),
    ("srv-bkp-mrs-01", "server", "QNAP", "TS-h1290FX", "QN-MRS-BKP-001", "MRS-DC3", "SERVER-A", "Sauvegarde Marseille"),
    ("ups-mrs-01", "ups", "APC", "Smart-UPS SRT 6kVA", "AP-MRS-UPS-001", "MRS-DC3", "SERVER-A", "Onduleur Marseille"),
    ("pc-it-mrs-01", "desktop", "Lenovo", "ThinkCentre M90q", "LV-MRS-PC-001", "MRS-DC3", "IDF-01", "Poste IT Marseille"),
    ("phone-acc-mrs-01", "phone", "Yealink", "T46U", "YL-MRS-PH-001", "MRS-DC3", "IDF-01", "Téléphone accueil Marseille"),
    ("ap-mrs-01", "ap", "Aruba", "AP-505", "AR-MRS-AP-001", "MRS-DC3", "IDF-01", "Wi-Fi Marseille"),
    ("cam-mrs-01", "camera", "Axis", "M3215-LVE", "AX-MRS-CAM-001", "MRS-DC3", "MDF-01", "Caméra Marseille"),
    ("prt-mrs-01", "printer", "HP", "LaserJet M404n", "HP-MRS-PRT-001", "MRS-DC3", "IDF-01", "Imprimante Marseille"),
    ("appliance-fw-mrs-01", "other", "Fortinet", "FortiGate 100F", "FG-MRS-FW-001", "MRS-DC3", "MDF-01", "Pare-feu Marseille"),
])

# Bordeaux
add_devices([
    ("srv-app-bor-01", "server", "Dell", "PowerEdge R760", "PE-BOR-001", "BOR-DC4", "SERVER-A", "Frontal applicatif Bordeaux"),
    ("srv-db-bor-01", "server", "HPE", "ProLiant DL380 Gen11", "HP-BOR-DB-001", "BOR-DC4", "SERVER-A", "DB Bordeaux"),
    ("srv-web-bor-01", "server", "Supermicro", "SYS-510P", "SM-BOR-WEB-001", "BOR-DC4", "SERVER-A", "Web Bordeaux"),
    ("srv-storage-bor-01", "server", "NetApp", "AFF C250", "NA-BOR-STO-001", "BOR-DC4", "SERVER-A", "SAN Bordeaux"),
    ("srv-bkp-bor-01", "server", "QNAP", "TS-h1290FX", "QN-BOR-BKP-001", "BOR-DC4", "SERVER-A", "Sauvegarde Bordeaux"),
    ("ups-bor-01", "ups", "APC", "Smart-UPS SRT 6kVA", "AP-BOR-UPS-001", "BOR-DC4", "SERVER-A", "Onduleur Bordeaux"),
    ("pc-it-bor-01", "desktop", "Lenovo", "ThinkCentre M90q", "LV-BOR-PC-001", "BOR-DC4", "IDF-01", "Poste IT Bordeaux"),
    ("phone-acc-bor-01", "phone", "Yealink", "T46U", "YL-BOR-PH-001", "BOR-DC4", "IDF-01", "Téléphone accueil Bordeaux"),
    ("ap-bor-01", "ap", "Aruba", "AP-505", "AR-BOR-AP-001", "BOR-DC4", "IDF-01", "Wi-Fi Bordeaux"),
    ("cam-bor-01", "camera", "Axis", "M3215-LVE", "AX-BOR-CAM-001", "BOR-DC4", "MDF-01", "Caméra Bordeaux"),
    ("prt-bor-01", "printer", "HP", "LaserJet M404n", "HP-BOR-PRT-001", "BOR-DC4", "IDF-01", "Imprimante Bordeaux"),
    ("appliance-fw-bor-01", "other", "Fortinet", "FortiGate 100F", "FG-BOR-FW-001", "BOR-DC4", "MDF-01", "Pare-feu Bordeaux"),
])

# Nantes
add_devices([
    ("srv-app-nts-01", "server", "Dell", "PowerEdge R760", "PE-NTS-001", "NTS-DC5", "SERVER-A", "Frontal applicatif Nantes"),
    ("srv-db-nts-01", "server", "HPE", "ProLiant DL380 Gen11", "HP-NTS-DB-001", "NTS-DC5", "SERVER-A", "DB Nantes"),
    ("srv-bkp-nts-01", "server", "QNAP", "TS-h1290FX", "QN-NTS-BKP-001", "NTS-DC5", "SERVER-A", "Sauvegarde Nantes"),
    ("srv-mon-nts-01", "server", "Dell", "PowerEdge R650", "PE-NTS-MON-001", "NTS-DC5", "SERVER-A", "Supervision Nantes"),
    ("ups-nts-01", "ups", "APC", "Smart-UPS SRT 6kVA", "AP-NTS-UPS-001", "NTS-DC5", "SERVER-A", "Onduleur Nantes"),
    ("pc-it-nts-01", "desktop", "Lenovo", "ThinkCentre M90q", "LV-NTS-PC-001", "NTS-DC5", "IDF-01", "Poste IT Nantes"),
    ("phone-acc-nts-01", "phone", "Yealink", "T46U", "YL-NTS-PH-001", "NTS-DC5", "IDF-01", "Téléphone accueil Nantes"),
    ("ap-nts-01", "ap", "Aruba", "AP-505", "AR-NTS-AP-001", "NTS-DC5", "IDF-01", "Wi-Fi Nantes principal"),
    ("ap-nts-02", "ap", "Aruba", "AP-505", "AR-NTS-AP-002", "NTS-DC5", "MDF-01", "Wi-Fi Nantes entrée"),
    ("cam-nts-01", "camera", "Axis", "M3215-LVE", "AX-NTS-CAM-001", "NTS-DC5", "MDF-01", "Caméra Nantes"),
    ("prt-nts-01", "printer", "HP", "LaserJet M404n", "HP-NTS-PRT-001", "NTS-DC5", "IDF-01", "Imprimante Nantes"),
    ("appliance-fw-nts-01", "other", "Fortinet", "FortiGate 100F", "FG-NTS-FW-001", "NTS-DC5", "MDF-01", "Pare-feu Nantes"),
])

# Branches — Nice, Toulouse, Lille, Strasbourg (smaller footprint)
def add_branch_devices(site: str) -> list[tuple]:
    return [
        (f"srv-{site.split('-')[0].lower()}-01", "server", "Supermicro", "Mini ITX", f"SM-{site}-001", site, "MAIN", f"Mini serveur edge {site}"),
        (f"ap-{site.split('-')[0].lower()}-01", "ap", "Aruba", "AP-505", f"AR-{site}-AP-001", site, "MAIN", f"AP principal {site}"),
        (f"ap-{site.split('-')[0].lower()}-02", "ap", "Aruba", "AP-505", f"AR-{site}-AP-002", site, "RACK-01", f"AP secondaire {site}"),
        (f"phone-{site.split('-')[0].lower()}-01", "phone", "Yealink", "T46U", f"YL-{site}-PH-001", site, "MAIN", f"Téléphone accueil {site}"),
        (f"phone-{site.split('-')[0].lower()}-02", "phone", "Yealink", "T46U", f"YL-{site}-PH-002", site, "MAIN", f"Téléphone secondaire {site}"),
        (f"prt-{site.split('-')[0].lower()}-01", "printer", "HP", "LaserJet M404n", f"HP-{site}-PRT-001", site, "MAIN", f"Imprimante {site}"),
        (f"cam-{site.split('-')[0].lower()}-01", "camera", "Axis", "P3267-LV", f"AX-{site}-CAM-001", site, "MAIN", f"Caméra accueil {site}"),
        (f"cam-{site.split('-')[0].lower()}-02", "camera", "Axis", "M3215-LVE", f"AX-{site}-CAM-002", site, "RACK-01", f"Caméra parking {site}"),
        (f"ups-{site.split('-')[0].lower()}-01", "ups", "APC", "Smart-UPS 1500", f"AP-{site}-UPS-001", site, "RACK-01", f"Onduleur {site}"),
        (f"pc-{site.split('-')[0].lower()}-01", "desktop", "Lenovo", "ThinkCentre M75q", f"LV-{site}-PC-001", site, "MAIN", f"Poste réception {site}"),
        (f"appliance-fw-{site.split('-')[0].lower()}-01", "other", "Fortinet", "FortiGate 60F", f"FG-{site}-FW-001", site, "MAIN", f"Pare-feu {site}"),
    ]


for branch in BRANCH_OFFSETS:
    add_devices(add_branch_devices(branch))


# --------------------------------------------------------------------------- #
# Switches
# --------------------------------------------------------------------------- #

SWITCHES: list[tuple] = [
    # Paris — full HA core + dist + server + storage
    ("sw-core-par-01", "Cisco", "C9500-48Y4C", "CS-CORE-001", "10.10.10.2", "PAR-DC1", "MDF-01", "U30", 48, "17.09.04"),
    ("sw-core-par-02", "Cisco", "C9500-48Y4C", "CS-CORE-002", "10.10.10.3", "PAR-DC1", "MDF-01", "U28", 48, "17.09.04"),
    ("sw-dist-par-01", "Cisco", "C9300-48P", "CS-DIST-001", "10.10.10.10", "PAR-DC1", "IDF-01", "U22", 48, "17.06.05"),
    ("sw-dist-par-02", "Cisco", "C9300-48P", "CS-DIST-002", "10.10.10.11", "PAR-DC1", "IDF-02", "U22", 48, "17.06.05"),
    ("sw-srv-par-01", "Arista", "7050SX3-48YC8", "AR-SRV-001", "10.10.10.20", "PAR-DC1", "SERVER-A", "U18", 48, "4.30.5M"),
    ("sw-srv-par-02", "Arista", "7050SX3-48YC8", "AR-SRV-002", "10.10.10.21", "PAR-DC1", "SERVER-A", "U16", 48, "4.30.5M"),
    ("sw-stor-par-01", "Arista", "7280R3", "AR-STO-001", "10.10.10.22", "PAR-DC1", "SERVER-B", "U20", 32, "4.30.5M"),
    # Lyon — HA core + dist + server
    ("sw-core-lyo-01", "Cisco", "C9300-24P", "CS-LYO-CORE-001", "10.20.10.2", "LYO-DC2", "MDF-01", "U30", 24, "17.09.04"),
    ("sw-core-lyo-02", "Cisco", "C9300-24P", "CS-LYO-CORE-002", "10.20.10.3", "LYO-DC2", "MDF-01", "U28", 24, "17.09.04"),
    ("sw-srv-lyo-01", "Arista", "7050SX3-48YC8", "AR-LYO-SRV-001", "10.20.10.10", "LYO-DC2", "SERVER-A", "U18", 48, "4.30.5M"),
    ("sw-dist-lyo-01", "Cisco", "C9300-48P", "CS-LYO-DIST-001", "10.20.10.11", "LYO-DC2", "IDF-01", "U22", 48, "17.06.05"),
    # P1) Marseille — DELIBERATE SPOF: single core switch, no peer
    ("sw-core-mrs-01", "Cisco", "C9300-24P", "CS-MRS-CORE-001", "10.30.10.2", "MRS-DC3", "MDF-01", "U30", 24, "17.09.04"),
    ("sw-srv-mrs-01", "Arista", "7050SX3-48YC8", "AR-MRS-SRV-001", "10.30.10.10", "MRS-DC3", "SERVER-A", "U18", 48, "4.30.5M"),
    # Bordeaux — HA pair
    ("sw-core-bor-01", "Cisco", "C9300-24P", "CS-BOR-CORE-001", "10.40.10.2", "BOR-DC4", "MDF-01", "U30", 24, "17.09.04"),
    ("sw-core-bor-02", "Cisco", "C9300-24P", "CS-BOR-CORE-002", "10.40.10.3", "BOR-DC4", "MDF-01", "U28", 24, "17.09.04"),
    ("sw-srv-bor-01", "Arista", "7050SX3-48YC8", "AR-BOR-SRV-001", "10.40.10.10", "BOR-DC4", "SERVER-A", "U18", 48, "4.30.5M"),
    # Nantes — HA pair
    ("sw-core-nts-01", "Cisco", "C9300-24P", "CS-NTS-CORE-001", "10.50.10.2", "NTS-DC5", "MDF-01", "U30", 24, "17.09.04"),
    ("sw-core-nts-02", "Cisco", "C9300-24P", "CS-NTS-CORE-002", "10.50.10.3", "NTS-DC5", "MDF-01", "U28", 24, "17.09.04"),
    ("sw-srv-nts-01", "Arista", "7050SX3-48YC8", "AR-NTS-SRV-001", "10.50.10.10", "NTS-DC5", "SERVER-A", "U18", 48, "4.30.5M"),
    # Branches — each has 1-2 switches
    ("sw-edge-nce-01", "MikroTik", "CRS328-24P-4S+", "MK-NCE-001", "192.168.10.2", "NCE-EDGE", "MAIN", "U10", 24, "7.13"),
    ("sw-edge-nce-02", "MikroTik", "CRS354-48G-4S+2Q+", "MK-NCE-002", "192.168.10.3", "NCE-EDGE", "RACK-01", "U8", 48, "7.13"),
    ("sw-edge-tls-01", "MikroTik", "CRS328-24P-4S+", "MK-TLS-001", "192.168.20.2", "TLS-EDGE", "MAIN", "U10", 24, "7.13"),
    ("sw-edge-tls-02", "MikroTik", "CRS354-48G-4S+2Q+", "MK-TLS-002", "192.168.20.3", "TLS-EDGE", "RACK-01", "U8", 48, "7.13"),
    ("sw-edge-lil-01", "MikroTik", "CRS328-24P-4S+", "MK-LIL-001", "192.168.30.2", "LIL-EDGE", "MAIN", "U10", 24, "7.13"),
    ("sw-edge-lil-02", "MikroTik", "CRS354-48G-4S+2Q+", "MK-LIL-002", "192.168.30.3", "LIL-EDGE", "RACK-01", "U8", 48, "7.13"),
    # P2) Strasbourg — DELIBERATE SPOF: single small edge switch carrying
    #      the firewall, both APs, the printer, the server — no redundancy.
    ("sw-edge-str-01", "MikroTik", "CRS328-24P-4S+", "MK-STR-001", "192.168.40.2", "STR-EDGE", "MAIN", "U10", 24, "7.13"),
]


# --------------------------------------------------------------------------- #
# IPs — switch mgmt + selected device IPs across all sites
# --------------------------------------------------------------------------- #

IPS: list[tuple] = []


def add_ip(address, status, hostname, mac, device_name, description):
    IPS.append((address, status, hostname, mac, device_name, description))


# Per-site management IPs (gateway reservations + switch addresses)
for site, octet in SITE_SUBNET_OCTET.items():
    add_ip(f"10.{octet}.10.1", "reserved", f"gw-{site.split('-')[0].lower()}", "", "", f"Passerelle MGMT {site}")

# Paris — switches
for sw in [
    ("sw-core-par-01", "10.10.10.2", "aa:bb:cc:00:00:01"),
    ("sw-core-par-02", "10.10.10.3", "aa:bb:cc:00:00:02"),
    ("sw-dist-par-01", "10.10.10.10", "aa:bb:cc:00:00:10"),
    ("sw-dist-par-02", "10.10.10.11", "aa:bb:cc:00:00:11"),
    ("sw-srv-par-01", "10.10.10.20", "aa:bb:cc:00:00:20"),
    ("sw-srv-par-02", "10.10.10.21", "aa:bb:cc:00:00:21"),
    ("sw-stor-par-01", "10.10.10.22", "aa:bb:cc:00:00:22"),
]:
    add_ip(sw[1], "assigned", sw[0], sw[2], "", f"Mgmt {sw[0]}")

# Paris — firewalls + LB + WAN
add_ip("10.10.10.50", "assigned", "fw-par-01", "aa:bb:cc:00:00:50", "appliance-fw-par-01", "Firewall MGMT principal")
add_ip("10.10.10.51", "assigned", "fw-par-02", "aa:bb:cc:00:00:51", "appliance-fw-par-02", "Firewall MGMT redondant")
add_ip("10.10.10.60", "assigned", "lb-par-01", "aa:bb:cc:00:00:60", "appliance-lb-par-01", "Load balancer")
add_ip("10.10.10.70", "assigned", "wan-par-01", "aa:bb:cc:00:00:70", "appliance-wan-par-01", "Routeur WAN MPLS")

# Paris — quelques utilisateurs / postes
add_ip("10.10.20.10", "assigned", "pc-it-01", "00:1a:2b:3c:4d:01", "pc-it-par-01", "")
add_ip("10.10.20.11", "assigned", "pc-it-02", "00:1a:2b:3c:4d:02", "pc-it-par-02", "")
add_ip("10.10.20.12", "assigned", "pc-rh-01", "00-1a-2b-3c-4d-03", "pc-rh-par-01", "Format Cisco dash")
add_ip("10.10.20.13", "assigned", "pc-fin-01", "00:1a:2b:3c:4d:04", "pc-fin-par-01", "")
add_ip("10.10.20.14", "assigned", "pc-com-01", "00:1a:2b:3c:4d:05", "pc-com-par-01", "")
add_ip("10.10.20.50", "reserved", "", "", "", "Réservé future imprimante de service")

# IT — close to saturation by design (~92%) on a /28 to land in [WARN, CRIT)
add_ip("10.10.22.10", "assigned", "phone-dir-par-01", "00:aa:bb:cc:dd:01", "phone-dir-par-01", "")

# Paris — APs / phones / printers / cameras
add_ip("10.10.30.10", "assigned", "ap-rdc-01", "00:11:22:aa:00:01", "ap-rdc-par-01", "")
add_ip("10.10.30.11", "assigned", "ap-rdc-02", "00:11:22:aa:00:02", "ap-rdc-par-02", "")
add_ip("10.10.30.12", "assigned", "ap-et1-01", "00:11:22:aa:00:03", "ap-et1-par-01", "")
add_ip("10.10.30.13", "assigned", "ap-et1-02", "00:11:22:aa:00:04", "ap-et1-par-02", "")
add_ip("10.10.30.14", "assigned", "ap-et2-01", "00:11:22:aa:00:05", "ap-et2-par-01", "")
add_ip("10.10.30.15", "assigned", "ap-et2-02", "00:11:22:aa:00:06", "ap-et2-par-02", "")
add_ip("10.10.40.10", "assigned", "phone-acc-01", "00:aa:bb:cc:dd:10", "phone-acc-par-01", "")
add_ip("10.10.40.11", "assigned", "phone-it-01", "00:aa:bb:cc:dd:11", "phone-it-par-01", "")
add_ip("10.10.40.12", "assigned", "phone-rh-01", "00:aa:bb:cc:dd:12", "phone-rh-par-01", "")
add_ip("10.10.40.13", "assigned", "phone-fin-01", "00:aa:bb:cc:dd:13", "phone-fin-par-01", "")
add_ip("10.10.50.10", "assigned", "prt-color-par-01", "00:cc:dd:ee:ff:01", "prt-color-par-01", "")
add_ip("10.10.50.11", "assigned", "prt-color-par-02", "00:cc:dd:ee:ff:02", "prt-color-par-02", "")
add_ip("10.10.50.12", "assigned", "prt-bw-par-01", "00:cc:dd:ee:ff:03", "prt-bw-par-01", "")
add_ip("10.10.50.13", "assigned", "prt-label-par-01", "00:cc:dd:ee:ff:04", "prt-label-par-01", "")
add_ip("10.10.70.10", "assigned", "cam-park-par-01", "00:dd:ee:ff:00:01", "cam-park-par-01", "")
add_ip("10.10.70.11", "assigned", "cam-park-par-02", "00:dd:ee:ff:00:02", "cam-park-par-02", "")
add_ip("10.10.70.12", "assigned", "cam-entry-par-01", "00:dd:ee:ff:00:03", "cam-entry-par-01", "")
add_ip("10.10.70.13", "assigned", "cam-entry-par-02", "00:dd:ee:ff:00:04", "cam-entry-par-02", "")

# Paris — servers (LAN front + IPMI)
add_ip("10.10.60.10", "assigned", "srv-app-par-01", "00:25:90:00:00:10", "srv-app-par-01", "")
add_ip("10.10.60.11", "assigned", "srv-app-par-02", "00:25:90:00:00:11", "srv-app-par-02", "")
add_ip("10.10.60.12", "assigned", "srv-app-par-03", "00:25:90:00:00:12", "srv-app-par-03", "")
add_ip("10.10.60.20", "assigned", "srv-mon-par-01", "00:25:90:00:00:20", "srv-mon-par-01", "Prometheus + Grafana")
add_ip("10.10.60.21", "assigned", "srv-log-par-01", "00:25:90:00:00:21", "srv-log-par-01", "Loki + ELK")
add_ip("10.10.60.30", "assigned", "srv-ci-par-01", "00:25:90:00:00:30", "srv-ci-par-01", "")
add_ip("10.10.61.10", "assigned", "srv-db-par-01", "00:25:90:00:01:10", "srv-db-par-01", "PostgreSQL primaire")
add_ip("10.10.61.11", "assigned", "srv-db-par-02", "00:25:90:00:01:11", "srv-db-par-02", "PostgreSQL réplica")
add_ip("10.10.61.12", "assigned", "srv-db-par-03", "00:25:90:00:01:12", "srv-db-par-03", "MariaDB legacy")
add_ip("10.10.62.10", "assigned", "srv-web-par-01", "00:25:90:00:02:10", "srv-web-par-01", "")
add_ip("10.10.62.11", "assigned", "srv-web-par-02", "00:25:90:00:02:11", "srv-web-par-02", "")
add_ip("10.10.63.10", "assigned", "srv-k8s-par-01", "00:25:90:00:03:10", "srv-k8s-par-01", "")
add_ip("10.10.63.11", "assigned", "srv-k8s-par-02", "00:25:90:00:03:11", "srv-k8s-par-02", "")
add_ip("10.10.63.12", "assigned", "srv-k8s-par-03", "00:25:90:00:03:12", "srv-k8s-par-03", "")
add_ip("10.10.80.10", "assigned", "ipmi-srv-app-par-01", "0c:c4:7a:00:00:01", "srv-app-par-01", "IPMI")
add_ip("10.10.80.11", "assigned", "ipmi-srv-app-par-02", "0c:c4:7a:00:00:02", "srv-app-par-02", "IPMI")
add_ip("10.10.80.12", "assigned", "ipmi-srv-db-par-01", "0c:c4:7a:00:00:03", "srv-db-par-01", "IPMI")
add_ip("10.10.80.13", "assigned", "ipmi-srv-db-par-02", "0c:c4:7a:00:00:04", "srv-db-par-02", "IPMI")
add_ip("10.10.80.14", "assigned", "ipmi-srv-web-par-01", "0c:c4:7a:00:00:05", "srv-web-par-01", "IPMI")
add_ip("10.10.80.15", "assigned", "ipmi-srv-k8s-par-01", "0c:c4:7a:00:00:06", "srv-k8s-par-01", "IPMI")
add_ip("10.10.80.16", "assigned", "ipmi-srv-k8s-par-02", "0c:c4:7a:00:00:07", "srv-k8s-par-02", "IPMI")
add_ip("10.10.80.17", "assigned", "ipmi-srv-k8s-par-03", "0c:c4:7a:00:00:08", "srv-k8s-par-03", "IPMI")
add_ip("10.10.100.10", "assigned", "srv-storage-par-01", "00:a0:98:00:00:10", "srv-storage-par-01", "Port SAN A")
add_ip("10.10.100.11", "assigned", "srv-storage-par-01-b", "00:a0:98:00:00:11", "srv-storage-par-01", "Port SAN B")
add_ip("10.10.100.12", "assigned", "srv-storage-par-02", "00:a0:98:00:00:12", "srv-storage-par-02", "")
add_ip("10.10.100.20", "assigned", "srv-nfs-par-01", "00:a0:98:00:00:20", "srv-nfs-par-01", "NFS exporter")
add_ip("10.10.200.10", "assigned", "srv-bkp-par-01", "00:11:99:00:00:10", "srv-bkp-par-01", "")
add_ip("10.10.200.11", "assigned", "srv-bkp-par-02", "00:11:99:00:00:11", "srv-bkp-par-02", "")

# P4) Saturate 10.10.21.0/24 (USERS-IT) to ~92%: 240 assigned IPs.
#     Cheap loop — exercises the capacity warning + the fill bar UI.
for i in range(10, 250):
    add_ip(f"10.10.21.{i}", "assigned", f"pc-it-saturated-{i:03d}", "", "", "Poste IT temporaire — saturation")

# Lyon
add_ip("10.20.10.2", "assigned", "sw-core-lyo-01", "aa:bb:cc:10:00:02", "", "Switch coeur Lyon 1")
add_ip("10.20.10.3", "assigned", "sw-core-lyo-02", "aa:bb:cc:10:00:03", "", "Switch coeur Lyon 2")
add_ip("10.20.10.10", "assigned", "sw-srv-lyo-01", "aa:bb:cc:10:00:10", "", "Switch serveurs Lyon")
add_ip("10.20.10.11", "assigned", "sw-dist-lyo-01", "aa:bb:cc:10:00:11", "", "Switch distribution Lyon")
add_ip("10.20.10.50", "assigned", "fw-lyo-01", "aa:bb:cc:10:00:50", "appliance-fw-lyo-01", "Firewall Lyon")
add_ip("10.20.10.70", "assigned", "wan-lyo-01", "aa:bb:cc:10:00:70", "appliance-wan-lyo-01", "Routeur WAN MPLS Lyon")
add_ip("10.20.20.10", "assigned", "pc-it-lyo-01", "00:1a:2b:3c:5d:01", "pc-it-lyo-01", "")
add_ip("10.20.20.11", "assigned", "pc-it-lyo-02", "00:1a:2b:3c:5d:02", "pc-it-lyo-02", "")
add_ip("10.20.30.10", "assigned", "ap-lyo-01", "00:11:22:aa:10:01", "ap-lyo-01", "")
add_ip("10.20.30.11", "assigned", "ap-lyo-02", "00:11:22:aa:10:02", "ap-lyo-02", "")
add_ip("10.20.40.10", "assigned", "phone-acc-lyo-01", "00:aa:bb:cc:dd:20", "phone-acc-lyo-01", "")
add_ip("10.20.50.10", "assigned", "prt-color-lyo-01", "00:cc:dd:ee:ff:10", "prt-color-lyo-01", "")
add_ip("10.20.60.10", "assigned", "srv-app-lyo-01", "00:25:90:10:00:10", "srv-app-lyo-01", "")
add_ip("10.20.60.11", "assigned", "srv-app-lyo-02", "00:25:90:10:00:11", "srv-app-lyo-02", "")
add_ip("10.20.60.12", "assigned", "srv-web-lyo-01", "00:25:90:10:00:12", "srv-web-lyo-01", "")
add_ip("10.20.61.10", "assigned", "srv-db-lyo-01", "00:25:90:10:01:10", "srv-db-lyo-01", "Réplica de PAR")
add_ip("10.20.61.11", "assigned", "srv-db-lyo-02", "00:25:90:10:01:11", "srv-db-lyo-02", "DB analytique")
add_ip("10.20.80.10", "assigned", "ipmi-srv-app-lyo-01", "0c:c4:7a:10:00:01", "srv-app-lyo-01", "IPMI")
add_ip("10.20.80.11", "assigned", "ipmi-srv-db-lyo-01", "0c:c4:7a:10:00:02", "srv-db-lyo-01", "IPMI")
add_ip("10.20.100.10", "assigned", "srv-storage-lyo-01", "00:a0:98:10:00:10", "srv-storage-lyo-01", "")
add_ip("10.20.200.10", "assigned", "srv-bkp-lyo-01", "00:11:99:10:00:10", "srv-bkp-lyo-01", "")
add_ip("10.20.70.10", "assigned", "cam-lyo-01", "00:dd:ee:ff:10:01", "cam-lyo-01", "")

# Marseille — including the critical DB on the SPOF switch
add_ip("10.30.10.2", "assigned", "sw-core-mrs-01", "aa:bb:cc:30:00:02", "", "Switch coeur Marseille — SPOF")
add_ip("10.30.10.10", "assigned", "sw-srv-mrs-01", "aa:bb:cc:30:00:10", "", "Switch serveurs Marseille")
add_ip("10.30.10.50", "assigned", "fw-mrs-01", "aa:bb:cc:30:00:50", "appliance-fw-mrs-01", "Firewall Marseille")
add_ip("10.30.20.10", "assigned", "pc-it-mrs-01", "00:1a:2b:3c:6d:01", "pc-it-mrs-01", "")
add_ip("10.30.30.10", "assigned", "ap-mrs-01", "00:11:22:aa:30:01", "ap-mrs-01", "")
add_ip("10.30.40.10", "assigned", "phone-acc-mrs-01", "00:aa:bb:cc:dd:30", "phone-acc-mrs-01", "")
add_ip("10.30.50.10", "assigned", "prt-mrs-01", "00:cc:dd:ee:ff:30", "prt-mrs-01", "")
add_ip("10.30.60.10", "assigned", "srv-app-mrs-01", "00:25:90:30:00:10", "srv-app-mrs-01", "")
add_ip("10.30.61.10", "assigned", "srv-db-mrs-01", "00:25:90:30:01:10", "srv-db-mrs-01", "DB production — derrière SPOF")
add_ip("10.30.80.10", "assigned", "ipmi-srv-db-mrs-01", "0c:c4:7a:30:00:01", "srv-db-mrs-01", "IPMI")
add_ip("10.30.100.10", "assigned", "srv-storage-mrs-01", "00:a0:98:30:00:10", "srv-storage-mrs-01", "")
add_ip("10.30.200.10", "assigned", "srv-bkp-mrs-01", "00:11:99:30:00:10", "srv-bkp-mrs-01", "")
add_ip("10.30.70.10", "assigned", "cam-mrs-01", "00:dd:ee:ff:30:01", "cam-mrs-01", "")

# P3) Saturate 10.20.90.0/29 — 6 usable hosts, fill all 6 as `assigned`
#     so the capacity check (which counts assigned/dhcp only) hits 100%
#     and surfaces as `critical`.
add_ip("10.20.90.1", "assigned", "gw-dmz-lyo", "00:aa:00:de:90:01", "", "Passerelle DMZ (gateway en /29 — saturé)")
add_ip("10.20.90.2", "assigned", "dmz-proxy-01", "00:aa:00:de:90:02", "", "Proxy inverse")
add_ip("10.20.90.3", "assigned", "dmz-mail-01", "00:aa:00:de:90:03", "", "Relais SMTP entrant")
add_ip("10.20.90.4", "assigned", "dmz-jump-01", "00:aa:00:de:90:04", "", "Bastion SSH")
add_ip("10.20.90.5", "assigned", "dmz-vpn-01", "00:aa:00:de:90:05", "", "Passerelle VPN externe")
add_ip("10.20.90.6", "assigned", "dmz-cdn-01", "00:aa:00:de:90:06", "", "Cache CDN — saturation /29")

# Bordeaux
add_ip("10.40.10.2", "assigned", "sw-core-bor-01", "aa:bb:cc:40:00:02", "", "")
add_ip("10.40.10.3", "assigned", "sw-core-bor-02", "aa:bb:cc:40:00:03", "", "")
add_ip("10.40.10.10", "assigned", "sw-srv-bor-01", "aa:bb:cc:40:00:10", "", "")
add_ip("10.40.10.50", "assigned", "fw-bor-01", "aa:bb:cc:40:00:50", "appliance-fw-bor-01", "")
add_ip("10.40.20.10", "assigned", "pc-it-bor-01", "00:1a:2b:3c:7d:01", "pc-it-bor-01", "")
add_ip("10.40.30.10", "assigned", "ap-bor-01", "00:11:22:aa:40:01", "ap-bor-01", "")
add_ip("10.40.40.10", "assigned", "phone-acc-bor-01", "00:aa:bb:cc:dd:40", "phone-acc-bor-01", "")
add_ip("10.40.50.10", "assigned", "prt-bor-01", "00:cc:dd:ee:ff:40", "prt-bor-01", "")
add_ip("10.40.60.10", "assigned", "srv-app-bor-01", "00:25:90:40:00:10", "srv-app-bor-01", "")
add_ip("10.40.60.11", "assigned", "srv-web-bor-01", "00:25:90:40:00:11", "srv-web-bor-01", "")
add_ip("10.40.61.10", "assigned", "srv-db-bor-01", "00:25:90:40:01:10", "srv-db-bor-01", "")
add_ip("10.40.80.10", "assigned", "ipmi-srv-db-bor-01", "0c:c4:7a:40:00:01", "srv-db-bor-01", "")
add_ip("10.40.100.10", "assigned", "srv-storage-bor-01", "00:a0:98:40:00:10", "srv-storage-bor-01", "")
add_ip("10.40.200.10", "assigned", "srv-bkp-bor-01", "00:11:99:40:00:10", "srv-bkp-bor-01", "")
add_ip("10.40.70.10", "assigned", "cam-bor-01", "00:dd:ee:ff:40:01", "cam-bor-01", "")

# Nantes
add_ip("10.50.10.2", "assigned", "sw-core-nts-01", "aa:bb:cc:50:00:02", "", "")
add_ip("10.50.10.3", "assigned", "sw-core-nts-02", "aa:bb:cc:50:00:03", "", "")
add_ip("10.50.10.10", "assigned", "sw-srv-nts-01", "aa:bb:cc:50:00:10", "", "")
add_ip("10.50.10.50", "assigned", "fw-nts-01", "aa:bb:cc:50:00:50", "appliance-fw-nts-01", "")
add_ip("10.50.20.10", "assigned", "pc-it-nts-01", "00:1a:2b:3c:8d:01", "pc-it-nts-01", "")
add_ip("10.50.30.10", "assigned", "ap-nts-01", "00:11:22:aa:50:01", "ap-nts-01", "")
add_ip("10.50.30.11", "assigned", "ap-nts-02", "00:11:22:aa:50:02", "ap-nts-02", "")
add_ip("10.50.40.10", "assigned", "phone-acc-nts-01", "00:aa:bb:cc:dd:50", "phone-acc-nts-01", "")
add_ip("10.50.50.10", "assigned", "prt-nts-01", "00:cc:dd:ee:ff:50", "prt-nts-01", "")
add_ip("10.50.60.10", "assigned", "srv-app-nts-01", "00:25:90:50:00:10", "srv-app-nts-01", "")
add_ip("10.50.60.11", "assigned", "srv-mon-nts-01", "00:25:90:50:00:11", "srv-mon-nts-01", "")
add_ip("10.50.61.10", "assigned", "srv-db-nts-01", "00:25:90:50:01:10", "srv-db-nts-01", "")
add_ip("10.50.80.10", "assigned", "ipmi-srv-db-nts-01", "0c:c4:7a:50:00:01", "srv-db-nts-01", "")
add_ip("10.50.200.10", "assigned", "srv-bkp-nts-01", "00:11:99:50:00:10", "srv-bkp-nts-01", "")
add_ip("10.50.70.10", "assigned", "cam-nts-01", "00:dd:ee:ff:50:01", "cam-nts-01", "")

# Branches — each ~6 IPs
for branch, off in BRANCH_OFFSETS.items():
    code = branch.split("-")[0].lower()
    add_ip(f"192.168.{off}.1", "reserved", f"gw-{code}", "", "", f"Passerelle MGMT {branch}")
    add_ip(f"192.168.{off}.2", "assigned", f"sw-edge-{code}-01", f"aa:bb:cc:60:{off:02x}:02", "", f"Switch edge {branch}")
    if branch != "STR-EDGE":
        add_ip(f"192.168.{off}.3", "assigned", f"sw-edge-{code}-02", f"aa:bb:cc:60:{off:02x}:03", "", f"Switch secondaire {branch}")
    add_ip(f"192.168.{off}.10", "assigned", f"fw-{code}", f"aa:bb:cc:60:{off:02x}:50", f"appliance-fw-{code}-01", f"Firewall {branch}")
    add_ip(f"192.168.{off}.50", "assigned", f"prt-{code}-01", f"00:cc:dd:ee:60:{off:02x}", f"prt-{code}-01", f"Imprimante {branch}")
    add_ip(f"192.168.{off + 1}.10", "assigned", f"pc-{code}-01", f"00:1a:2b:60:{off:02x}:01", f"pc-{code}-01", f"Poste réception {branch}")
    add_ip(f"192.168.{off + 1}.20", "assigned", f"srv-{code}-01", f"00:25:90:60:{off:02x}:01", f"srv-{code}-01", f"Mini serveur {branch}")
    add_ip(f"192.168.{off + 2}.10", "assigned", f"ap-{code}-01", f"00:11:22:60:{off:02x}:01", f"ap-{code}-01", f"AP principal {branch}")
    add_ip(f"192.168.{off + 2}.11", "assigned", f"ap-{code}-02", f"00:11:22:60:{off:02x}:02", f"ap-{code}-02", f"AP secondaire {branch}")
    add_ip(f"192.168.{off + 3}.10", "assigned", f"phone-{code}-01", f"00:aa:bb:60:{off:02x}:10", f"phone-{code}-01", f"Téléphone accueil {branch}")
    add_ip(f"192.168.{off + 3}.11", "assigned", f"phone-{code}-02", f"00:aa:bb:60:{off:02x}:11", f"phone-{code}-02", f"Téléphone secondaire {branch}")
    add_ip(f"192.168.{off + 2}.20", "assigned", f"cam-{code}-01", f"00:dd:ee:60:{off:02x}:01", f"cam-{code}-01", f"Caméra accueil {branch}")
    add_ip(f"192.168.{off + 2}.21", "assigned", f"cam-{code}-02", f"00:dd:ee:60:{off:02x}:02", f"cam-{code}-02", f"Caméra parking {branch}")

# P6) DELIBERATE DUPLICATE MAC across two distinct IPs / devices in
#     different subnets — integrity check picks this up regardless of subnet.
add_ip("10.10.40.99", "assigned", "phantom-1", "00:1a:2b:3c:4d:ff", "lap-dev-par-01", "MAC dupliquée — incident en attente")
add_ip("10.50.40.99", "assigned", "phantom-2", "00:1a:2b:3c:4d:ff", "srv-mon-nts-01", "MAC dupliquée — incident en attente")


# --------------------------------------------------------------------------- #
# Ports
# --------------------------------------------------------------------------- #

PORTS: list[tuple] = []


def add_port(*row):
    PORTS.append(row)


# Trunk VLAN lists must NOT include the native VLAN (backend rule).
USER_TRUNK = "20,21,22,23,30,31,40,50,60,70"
WIFI_TRUNK = "30,31"
SRV_TRUNK = "60,61,62,63,70,80,100,110,120,200"
STORAGE_TRUNK = "100,101,200"

# Paris — core, dist, server, storage
add_port("sw-core-par-01", 1, "uplink-dist-par-01", "trunk", 10, USER_TRUNK, "up", "", "", "Trunk vers IDF-01")
add_port("sw-core-par-01", 2, "uplink-dist-par-02", "trunk", 10, USER_TRUNK, "up", "", "", "Trunk vers IDF-02")
add_port("sw-core-par-01", 3, "uplink-srv-par-01", "trunk", 10, SRV_TRUNK, "up", "", "", "Trunk vers salle A")
add_port("sw-core-par-01", 4, "uplink-srv-par-02", "trunk", 10, SRV_TRUNK, "up", "", "", "Trunk redondant salle A")
add_port("sw-core-par-01", 5, "uplink-stor-par-01", "trunk", 10, STORAGE_TRUNK, "up", "", "", "Trunk stockage")
add_port("sw-core-par-01", 6, "peer-core-02", "trunk", 11, "10,20,21,22,23,30,31,40,50,60,61,62,63,70,80,100,110,120,200", "up", "", "", "Peer link HA")
add_port("sw-core-par-01", 47, "fw-uplink", "trunk", 10, "20,21,22,23,30,31,40,50,60,61,62,63,70,80,90,100,200", "up", "appliance-fw-par-01", "", "Vers FortiGate principal")
add_port("sw-core-par-01", 48, "wan-uplink", "access", 90, "", "up", "appliance-wan-par-01", "", "Sortie WAN")

add_port("sw-core-par-02", 1, "uplink-dist-par-01-b", "trunk", 10, USER_TRUNK, "up", "", "", "Trunk redondant IDF-01")
add_port("sw-core-par-02", 2, "uplink-dist-par-02-b", "trunk", 10, USER_TRUNK, "up", "", "", "Trunk redondant IDF-02")
add_port("sw-core-par-02", 6, "peer-core-01", "trunk", 11, "10,20,21,22,23,30,31,40,50,60,61,62,63,70,80,100,110,120,200", "up", "", "", "Peer link HA")
add_port("sw-core-par-02", 47, "fw-uplink-2", "trunk", 10, "20,21,22,23,30,31,40,50,60,61,62,63,70,80,90,100,200", "up", "appliance-fw-par-02", "", "Vers FortiGate redondant")

add_port("sw-dist-par-01", 1, "trunk-up-core-01", "trunk", 10, USER_TRUNK, "up", "", "", "")
add_port("sw-dist-par-01", 2, "trunk-up-core-02", "trunk", 10, USER_TRUNK, "up", "", "", "")
add_port("sw-dist-par-01", 5, "pc-it-01", "access", 21, "", "up", "pc-it-par-01", "10.10.20.10", "")
add_port("sw-dist-par-01", 6, "pc-it-02", "access", 21, "", "up", "pc-it-par-02", "10.10.20.11", "")
add_port("sw-dist-par-01", 7, "pc-it-03", "access", 21, "", "up", "pc-it-par-03", "", "")
add_port("sw-dist-par-01", 8, "prt-color-01", "access", 50, "", "up", "prt-color-par-01", "10.10.50.10", "")
add_port("sw-dist-par-01", 9, "phone-acc-01", "hybrid", 20, "40", "up", "phone-acc-par-01", "10.10.40.10", "Voix + accès")
add_port("sw-dist-par-01", 10, "phone-it-01", "hybrid", 21, "40", "up", "phone-it-par-01", "10.10.40.11", "")
add_port("sw-dist-par-01", 12, "ap-rdc-01", "trunk", 10, WIFI_TRUNK, "up", "ap-rdc-par-01", "10.10.30.10", "")
add_port("sw-dist-par-01", 13, "ap-rdc-02", "trunk", 10, WIFI_TRUNK, "up", "ap-rdc-par-02", "10.10.30.11", "")
add_port("sw-dist-par-01", 14, "ap-et1-01", "trunk", 10, WIFI_TRUNK, "up", "ap-et1-par-01", "10.10.30.12", "")
add_port("sw-dist-par-01", 15, "ap-et1-02", "trunk", 10, WIFI_TRUNK, "up", "ap-et1-par-02", "10.10.30.13", "")
add_port("sw-dist-par-01", 20, "cam-park-01", "access", 70, "", "up", "cam-park-par-01", "10.10.70.10", "")
add_port("sw-dist-par-01", 21, "cam-park-02", "access", 70, "", "up", "cam-park-par-02", "10.10.70.11", "")
add_port("sw-dist-par-01", 22, "cam-entry-01", "access", 70, "", "up", "cam-entry-par-01", "10.10.70.12", "")
add_port("sw-dist-par-01", 23, "cam-entry-02", "access", 70, "", "up", "cam-entry-par-02", "10.10.70.13", "")
# P9) Two ports labelled "spare" on the same switch → integrity port_label_dup
add_port("sw-dist-par-01", 46, "spare", "access", 1, "", "down", "", "", "Spare 1 — désactivé")
add_port("sw-dist-par-01", 47, "spare", "access", 1, "", "down", "", "", "Spare 2 — désactivé (doublon de label)")
add_port("sw-dist-par-01", 48, "loop-test", "disabled", None, "", "down", "", "", "Désactivé suite à loop")

add_port("sw-dist-par-02", 1, "trunk-up-core-01", "trunk", 10, USER_TRUNK, "up", "", "", "")
add_port("sw-dist-par-02", 2, "trunk-up-core-02", "trunk", 10, USER_TRUNK, "up", "", "", "")
add_port("sw-dist-par-02", 5, "pc-rh-01", "access", 20, "", "up", "pc-rh-par-01", "10.10.20.12", "")
add_port("sw-dist-par-02", 6, "pc-fin-01", "access", 24, "", "up", "pc-fin-par-01", "10.10.20.13", "")
add_port("sw-dist-par-02", 7, "pc-com-01", "access", 25, "", "up", "pc-com-par-01", "10.10.20.14", "")
add_port("sw-dist-par-02", 8, "lap-dev-01", "access", 23, "", "up", "lap-dev-par-01", "", "")
add_port("sw-dist-par-02", 9, "lap-dev-02", "access", 23, "", "up", "lap-dev-par-02", "", "")
add_port("sw-dist-par-02", 10, "lap-dir-01", "access", 22, "", "up", "lap-dir-par-01", "", "")
add_port("sw-dist-par-02", 11, "prt-color-02", "access", 50, "", "up", "prt-color-par-02", "10.10.50.11", "")
add_port("sw-dist-par-02", 12, "prt-bw-01", "access", 50, "", "up", "prt-bw-par-01", "10.10.50.12", "")
add_port("sw-dist-par-02", 13, "phone-dir-01", "hybrid", 22, "40", "up", "phone-dir-par-01", "10.10.22.10", "")
add_port("sw-dist-par-02", 14, "phone-rh-01", "hybrid", 20, "40", "up", "phone-rh-par-01", "10.10.40.12", "")
add_port("sw-dist-par-02", 15, "phone-fin-01", "hybrid", 24, "40", "up", "phone-fin-par-01", "10.10.40.13", "")
add_port("sw-dist-par-02", 18, "ap-et2-01", "trunk", 10, WIFI_TRUNK, "up", "ap-et2-par-01", "10.10.30.14", "")
add_port("sw-dist-par-02", 19, "ap-et2-02", "trunk", 10, WIFI_TRUNK, "up", "ap-et2-par-02", "10.10.30.15", "")

add_port("sw-srv-par-01", 1, "trunk-up-core-01", "trunk", 10, SRV_TRUNK, "up", "", "", "")
add_port("sw-srv-par-01", 2, "trunk-up-core-02", "trunk", 10, SRV_TRUNK, "up", "", "", "")
add_port("sw-srv-par-01", 10, "srv-app-01", "access", 60, "", "up", "srv-app-par-01", "", "")
add_port("sw-srv-par-01", 11, "srv-app-02", "access", 60, "", "up", "srv-app-par-02", "", "")
add_port("sw-srv-par-01", 12, "srv-app-03", "access", 60, "", "up", "srv-app-par-03", "", "")
add_port("sw-srv-par-01", 13, "srv-db-01", "access", 61, "", "up", "srv-db-par-01", "", "")
add_port("sw-srv-par-01", 14, "srv-db-02", "access", 61, "", "up", "srv-db-par-02", "", "")
add_port("sw-srv-par-01", 15, "srv-db-03", "access", 61, "", "up", "srv-db-par-03", "", "MariaDB legacy")
add_port("sw-srv-par-01", 16, "srv-web-01", "access", 62, "", "up", "srv-web-par-01", "", "")
add_port("sw-srv-par-01", 17, "srv-web-02", "access", 62, "", "up", "srv-web-par-02", "", "")
add_port("sw-srv-par-01", 18, "srv-mon-01", "access", 60, "", "up", "srv-mon-par-01", "", "Prometheus + Grafana")
add_port("sw-srv-par-01", 19, "srv-log-01", "access", 60, "", "up", "srv-log-par-01", "", "Loki + ELK")
add_port("sw-srv-par-01", 20, "srv-ci-01", "access", 64, "", "up", "srv-ci-par-01", "", "")
add_port("sw-srv-par-01", 21, "srv-k8s-01", "access", 63, "", "up", "srv-k8s-par-01", "", "")
add_port("sw-srv-par-01", 22, "srv-k8s-02", "access", 63, "", "up", "srv-k8s-par-02", "", "")
add_port("sw-srv-par-01", 23, "srv-k8s-03", "access", 63, "", "up", "srv-k8s-par-03", "", "")

add_port("sw-srv-par-02", 1, "trunk-up-core-01-b", "trunk", 10, SRV_TRUNK, "up", "", "", "")
add_port("sw-srv-par-02", 2, "trunk-up-core-02-b", "trunk", 10, SRV_TRUNK, "up", "", "", "")
add_port("sw-srv-par-02", 10, "srv-app-01-b", "access", 60, "", "up", "srv-app-par-01", "", "Bond second interface")
add_port("sw-srv-par-02", 11, "srv-app-02-b", "access", 60, "", "up", "srv-app-par-02", "", "")
add_port("sw-srv-par-02", 13, "srv-db-01-b", "access", 61, "", "up", "srv-db-par-01", "", "")
add_port("sw-srv-par-02", 14, "srv-db-02-b", "access", 61, "", "up", "srv-db-par-02", "", "")
add_port("sw-srv-par-02", 16, "srv-web-01-b", "access", 62, "", "up", "srv-web-par-01", "", "")
add_port("sw-srv-par-02", 21, "srv-k8s-01-b", "access", 63, "", "up", "srv-k8s-par-01", "", "Bond second interface")
add_port("sw-srv-par-02", 22, "srv-k8s-02-b", "access", 63, "", "up", "srv-k8s-par-02", "", "")
add_port("sw-srv-par-02", 23, "srv-k8s-03-b", "access", 63, "", "up", "srv-k8s-par-03", "", "")

add_port("sw-stor-par-01", 1, "trunk-up-core-01", "trunk", 10, STORAGE_TRUNK, "up", "", "", "")
add_port("sw-stor-par-01", 10, "srv-storage-a", "access", 100, "", "up", "srv-storage-par-01", "10.10.100.10", "Port SAN A")
add_port("sw-stor-par-01", 11, "srv-storage-b", "access", 100, "", "up", "srv-storage-par-01", "10.10.100.11", "Port SAN B")
add_port("sw-stor-par-01", 12, "srv-storage-02", "access", 100, "", "up", "srv-storage-par-02", "10.10.100.12", "")
add_port("sw-stor-par-01", 13, "srv-nfs-01", "access", 101, "", "up", "srv-nfs-par-01", "10.10.100.20", "")
add_port("sw-stor-par-01", 20, "srv-bkp-01", "access", 200, "", "up", "srv-bkp-par-01", "10.10.200.10", "")
add_port("sw-stor-par-01", 21, "srv-bkp-02", "access", 200, "", "up", "srv-bkp-par-02", "10.10.200.11", "")

# Lyon
add_port("sw-core-lyo-01", 1, "uplink-srv-lyo", "trunk", 10, SRV_TRUNK, "up", "", "", "")
add_port("sw-core-lyo-01", 2, "uplink-dist-lyo", "trunk", 10, USER_TRUNK, "up", "", "", "")
add_port("sw-core-lyo-01", 6, "peer-core-lyo-02", "trunk", 11, "10,20,21,22,23,30,31,40,50,60,61,62,63,70,80,100,110,120,200", "up", "", "", "Peer link HA")
add_port("sw-core-lyo-01", 23, "fw-uplink-lyo", "trunk", 10, SRV_TRUNK + ",90", "up", "appliance-fw-lyo-01", "", "")
add_port("sw-core-lyo-01", 24, "wan-uplink-lyo", "access", 90, "", "up", "appliance-wan-lyo-01", "", "")

add_port("sw-core-lyo-02", 6, "peer-core-lyo-01", "trunk", 11, "10,20,21,22,23,30,31,40,50,60,61,62,63,70,80,100,110,120,200", "up", "", "", "Peer link HA")

add_port("sw-srv-lyo-01", 1, "trunk-up-core-lyo", "trunk", 10, SRV_TRUNK, "up", "", "", "")
add_port("sw-srv-lyo-01", 10, "srv-app-lyo-01", "access", 60, "", "up", "srv-app-lyo-01", "10.20.60.10", "")
add_port("sw-srv-lyo-01", 11, "srv-app-lyo-02", "access", 60, "", "up", "srv-app-lyo-02", "10.20.60.11", "")
add_port("sw-srv-lyo-01", 12, "srv-web-lyo-01", "access", 62, "", "up", "srv-web-lyo-01", "10.20.60.12", "")
add_port("sw-srv-lyo-01", 13, "srv-db-lyo-01", "access", 61, "", "up", "srv-db-lyo-01", "10.20.61.10", "")
add_port("sw-srv-lyo-01", 14, "srv-db-lyo-02", "access", 61, "", "up", "srv-db-lyo-02", "10.20.61.11", "")
add_port("sw-srv-lyo-01", 15, "srv-storage-lyo-01", "access", 100, "", "up", "srv-storage-lyo-01", "10.20.100.10", "")
add_port("sw-srv-lyo-01", 16, "srv-bkp-lyo-01", "access", 200, "", "up", "srv-bkp-lyo-01", "10.20.200.10", "")

add_port("sw-dist-lyo-01", 1, "trunk-up-core-lyo", "trunk", 10, USER_TRUNK, "up", "", "", "")
add_port("sw-dist-lyo-01", 5, "pc-it-lyo-01", "access", 21, "", "up", "pc-it-lyo-01", "10.20.20.10", "")
add_port("sw-dist-lyo-01", 6, "pc-it-lyo-02", "access", 21, "", "up", "pc-it-lyo-02", "10.20.20.11", "")
add_port("sw-dist-lyo-01", 10, "phone-acc-lyo-01", "hybrid", 20, "40", "up", "phone-acc-lyo-01", "10.20.40.10", "")
add_port("sw-dist-lyo-01", 12, "prt-color-lyo-01", "access", 50, "", "up", "prt-color-lyo-01", "10.20.50.10", "")
add_port("sw-dist-lyo-01", 15, "ap-lyo-01", "trunk", 10, WIFI_TRUNK, "up", "ap-lyo-01", "10.20.30.10", "")
add_port("sw-dist-lyo-01", 16, "ap-lyo-02", "trunk", 10, WIFI_TRUNK, "up", "ap-lyo-02", "10.20.30.11", "")
add_port("sw-dist-lyo-01", 17, "cam-lyo-01", "access", 70, "", "up", "cam-lyo-01", "10.20.70.10", "")

# Marseille — SPOF: every critical asset hangs off sw-core-mrs-01 with no peer
add_port("sw-core-mrs-01", 1, "uplink-srv-mrs", "trunk", 10, SRV_TRUNK, "up", "", "", "Trunk vers serveurs — pas de redondance")
add_port("sw-core-mrs-01", 5, "srv-db-mrs-01", "access", 61, "", "up", "srv-db-mrs-01", "10.30.61.10", "Base prod — SPOF: single core")
add_port("sw-core-mrs-01", 10, "pc-it-mrs-01", "access", 21, "", "up", "pc-it-mrs-01", "10.30.20.10", "")
add_port("sw-core-mrs-01", 11, "phone-acc-mrs-01", "hybrid", 20, "40", "up", "phone-acc-mrs-01", "10.30.40.10", "")
add_port("sw-core-mrs-01", 12, "ap-mrs-01", "trunk", 10, WIFI_TRUNK, "up", "ap-mrs-01", "10.30.30.10", "")
add_port("sw-core-mrs-01", 13, "prt-mrs-01", "access", 50, "", "up", "prt-mrs-01", "10.30.50.10", "")
add_port("sw-core-mrs-01", 14, "cam-mrs-01", "access", 70, "", "up", "cam-mrs-01", "10.30.70.10", "")
add_port("sw-core-mrs-01", 23, "fw-uplink-mrs", "trunk", 10, SRV_TRUNK + ",90", "up", "appliance-fw-mrs-01", "", "")
add_port("sw-core-mrs-01", 24, "wan-uplink-mrs", "access", 90, "", "up", "", "", "Sortie WAN")

add_port("sw-srv-mrs-01", 1, "trunk-up-core-mrs", "trunk", 10, SRV_TRUNK, "up", "", "", "")
add_port("sw-srv-mrs-01", 10, "srv-app-mrs-01", "access", 60, "", "up", "srv-app-mrs-01", "10.30.60.10", "")
add_port("sw-srv-mrs-01", 12, "srv-storage-mrs-01", "access", 100, "", "up", "srv-storage-mrs-01", "10.30.100.10", "")
add_port("sw-srv-mrs-01", 13, "srv-bkp-mrs-01", "access", 200, "", "up", "srv-bkp-mrs-01", "10.30.200.10", "")

# Bordeaux + Nantes — mirror Lyon's layout (HA core + srv)
for site_code, srv_prefix in (("bor", "10.40"), ("nts", "10.50")):
    add_port(f"sw-core-{site_code}-01", 1, "uplink-srv", "trunk", 10, SRV_TRUNK, "up", "", "", "")
    add_port(f"sw-core-{site_code}-01", 6, f"peer-core-{site_code}-02", "trunk", 11, "10,20,21,30,31,40,50,60,61,62,70,80,100,200", "up", "", "", "Peer link HA")
    add_port(f"sw-core-{site_code}-01", 23, f"fw-uplink-{site_code}", "trunk", 10, SRV_TRUNK + ",90", "up", f"appliance-fw-{site_code}-01", "", "")
    add_port(f"sw-core-{site_code}-01", 24, f"wan-uplink-{site_code}", "access", 90, "", "up", "", "", "")
    add_port(f"sw-core-{site_code}-02", 6, f"peer-core-{site_code}-01", "trunk", 11, "10,20,21,30,31,40,50,60,61,62,70,80,100,200", "up", "", "", "Peer link HA")
    add_port(f"sw-srv-{site_code}-01", 1, "trunk-up-core", "trunk", 10, SRV_TRUNK, "up", "", "", "")
    add_port(f"sw-srv-{site_code}-01", 10, f"srv-app-{site_code}-01", "access", 60, "", "up", f"srv-app-{site_code}-01", f"{srv_prefix}.60.10", "")
    add_port(f"sw-srv-{site_code}-01", 11, f"srv-db-{site_code}-01", "access", 61, "", "up", f"srv-db-{site_code}-01", f"{srv_prefix}.61.10", "")
    add_port(f"sw-srv-{site_code}-01", 12, f"srv-bkp-{site_code}-01", "access", 200, "", "up", f"srv-bkp-{site_code}-01", f"{srv_prefix}.200.10", "")

# Bordeaux/Nantes spécifiques
add_port("sw-srv-bor-01", 13, "srv-web-bor-01", "access", 62, "", "up", "srv-web-bor-01", "10.40.60.11", "")
add_port("sw-srv-bor-01", 14, "srv-storage-bor-01", "access", 100, "", "up", "srv-storage-bor-01", "10.40.100.10", "")
add_port("sw-srv-nts-01", 13, "srv-mon-nts-01", "access", 60, "", "up", "srv-mon-nts-01", "10.50.60.11", "")

# Branches — Nice / Toulouse / Lille each have 2 switches.
for branch, off in BRANCH_OFFSETS.items():
    if branch == "STR-EDGE":
        continue
    code = branch.split("-")[0].lower()
    add_port(f"sw-edge-{code}-01", 1, "uplink-fw", "trunk", 10, "20,30,31,40", "up", f"appliance-fw-{code}-01", "", "")
    add_port(f"sw-edge-{code}-01", 2, f"uplink-{code}-02", "trunk", 10, "20,30,31,40", "up", "", "", "Lien vers second switch")
    add_port(f"sw-edge-{code}-01", 10, f"srv-{code}-01", "access", 20, "", "up", f"srv-{code}-01", f"192.168.{off + 1}.20", "")
    add_port(f"sw-edge-{code}-01", 11, f"phone-{code}-01", "hybrid", 20, "40", "up", f"phone-{code}-01", f"192.168.{off + 3}.10", "")
    add_port(f"sw-edge-{code}-01", 12, f"phone-{code}-02", "hybrid", 20, "40", "up", f"phone-{code}-02", f"192.168.{off + 3}.11", "")
    add_port(f"sw-edge-{code}-01", 13, f"prt-{code}-01", "access", 10, "", "up", f"prt-{code}-01", f"192.168.{off}.50", "")
    add_port(f"sw-edge-{code}-01", 14, f"pc-{code}-01", "access", 20, "", "up", f"pc-{code}-01", f"192.168.{off + 1}.10", "")
    add_port(f"sw-edge-{code}-02", 1, f"uplink-{code}-01", "trunk", 10, "20,30,31,40", "up", "", "", "")
    add_port(f"sw-edge-{code}-02", 10, f"ap-{code}-01", "trunk", 10, WIFI_TRUNK, "up", f"ap-{code}-01", f"192.168.{off + 2}.10", "")
    add_port(f"sw-edge-{code}-02", 11, f"ap-{code}-02", "trunk", 10, WIFI_TRUNK, "up", f"ap-{code}-02", f"192.168.{off + 2}.11", "")
    add_port(f"sw-edge-{code}-02", 12, f"cam-{code}-01", "access", 70, "", "up", f"cam-{code}-01", f"192.168.{off + 2}.20", "")
    add_port(f"sw-edge-{code}-02", 13, f"cam-{code}-02", "access", 70, "", "up", f"cam-{code}-02", f"192.168.{off + 2}.21", "")

# P2 + P5) Strasbourg — every asset on a single 24-port switch; saturate
#         port usage close to/at 100% so the capacity alert fires too.
str_off = BRANCH_OFFSETS["STR-EDGE"]
add_port("sw-edge-str-01", 1, "uplink-fw", "trunk", 10, "20,30,31,40", "up", "appliance-fw-str-01", "", "Unique uplink — SPOF")
add_port("sw-edge-str-01", 2, "srv-str-01", "access", 20, "", "up", "srv-str-01", f"192.168.{str_off + 1}.20", "")
add_port("sw-edge-str-01", 3, "phone-str-01", "hybrid", 20, "40", "up", "phone-str-01", f"192.168.{str_off + 3}.10", "")
add_port("sw-edge-str-01", 4, "phone-str-02", "hybrid", 20, "40", "up", "phone-str-02", f"192.168.{str_off + 3}.11", "")
add_port("sw-edge-str-01", 5, "prt-str-01", "access", 10, "", "up", "prt-str-01", f"192.168.{str_off}.50", "")
add_port("sw-edge-str-01", 6, "pc-str-01", "access", 20, "", "up", "pc-str-01", f"192.168.{str_off + 1}.10", "")
add_port("sw-edge-str-01", 7, "ap-str-01", "trunk", 10, WIFI_TRUNK, "up", "ap-str-01", f"192.168.{str_off + 2}.10", "")
add_port("sw-edge-str-01", 8, "ap-str-02", "trunk", 10, WIFI_TRUNK, "up", "ap-str-02", f"192.168.{str_off + 2}.11", "")
add_port("sw-edge-str-01", 9, "cam-str-01", "access", 70, "", "up", "cam-str-01", f"192.168.{str_off + 2}.20", "")
add_port("sw-edge-str-01", 10, "cam-str-02", "access", 70, "", "up", "cam-str-02", f"192.168.{str_off + 2}.21", "")
# Fill the remaining ports with trunk/hybrid configs so the integrity check
# counts them as "in use" too.
for i in range(11, 25):
    add_port("sw-edge-str-01", i, f"reserve-{i:02d}", "trunk", 10, "20,30,40", "up", "", "", "Réservation visiteurs / démos — saturation P5")


# --------------------------------------------------------------------------- #
# Links
# --------------------------------------------------------------------------- #

LINKS: list[tuple] = [
    # Paris — coeur full mesh
    ("sw-core-par-01", 1, "sw-dist-par-01", 1, "fiber", 25000, "Coeur 1 ↔ dist étage 1"),
    ("sw-core-par-01", 2, "sw-dist-par-02", 1, "fiber", 25000, "Coeur 1 ↔ dist étage 2"),
    ("sw-core-par-02", 1, "sw-dist-par-01", 2, "fiber", 25000, "Coeur 2 ↔ dist étage 1 (redondance)"),
    ("sw-core-par-02", 2, "sw-dist-par-02", 2, "fiber", 25000, "Coeur 2 ↔ dist étage 2 (redondance)"),
    ("sw-core-par-01", 3, "sw-srv-par-01", 1, "fiber", 100000, "Coeur 1 ↔ srv A"),
    ("sw-core-par-02", 3, "sw-srv-par-01", 2, "fiber", 100000, "Coeur 2 ↔ srv A"),
    ("sw-core-par-01", 4, "sw-srv-par-02", 1, "fiber", 100000, "Coeur 1 ↔ srv A bis"),
    ("sw-core-par-02", 4, "sw-srv-par-02", 2, "fiber", 100000, "Coeur 2 ↔ srv A bis"),
    ("sw-core-par-01", 5, "sw-stor-par-01", 1, "fiber", 100000, "Coeur 1 ↔ stockage"),
    ("sw-core-par-01", 6, "sw-core-par-02", 6, "dac", 100000, "Peer DAC entre coeurs"),
    # Lyon
    ("sw-core-lyo-01", 1, "sw-srv-lyo-01", 1, "fiber", 25000, "Coeur Lyon ↔ srv"),
    ("sw-core-lyo-01", 2, "sw-dist-lyo-01", 1, "fiber", 10000, "Coeur Lyon ↔ dist"),
    ("sw-core-lyo-01", 6, "sw-core-lyo-02", 6, "dac", 100000, "Peer DAC coeurs Lyon"),
    # Marseille — SPOF: single core, no peer link
    ("sw-core-mrs-01", 1, "sw-srv-mrs-01", 1, "fiber", 25000, "Coeur Marseille ↔ srv (lien unique — SPOF)"),
    # Bordeaux
    ("sw-core-bor-01", 1, "sw-srv-bor-01", 1, "fiber", 25000, "Coeur Bordeaux ↔ srv"),
    ("sw-core-bor-01", 6, "sw-core-bor-02", 6, "dac", 100000, "Peer DAC coeurs Bordeaux"),
    # Nantes
    ("sw-core-nts-01", 1, "sw-srv-nts-01", 1, "fiber", 25000, "Coeur Nantes ↔ srv"),
    ("sw-core-nts-01", 6, "sw-core-nts-02", 6, "dac", 100000, "Peer DAC coeurs Nantes"),
    # Branches
    ("sw-edge-nce-01", 2, "sw-edge-nce-02", 1, "copper", 1000, "Lien cuivre 1G entre switchs Nice"),
    ("sw-edge-tls-01", 2, "sw-edge-tls-02", 1, "copper", 1000, "Lien cuivre 1G entre switchs Toulouse"),
    ("sw-edge-lil-01", 2, "sw-edge-lil-02", 1, "copper", 1000, "Lien cuivre 1G entre switchs Lille"),
    # P2) Strasbourg — pas de second switch, donc aucun lien intra-site
    # Inter-sites (logiques)
    ("sw-core-par-01", 48, "sw-core-lyo-01", 24, "virtual", 1000, "Tunnel inter-DC PAR ↔ LYO"),
    ("sw-core-lyo-01", 24, "sw-core-mrs-01", 24, "virtual", 1000, "Tunnel inter-DC LYO ↔ MRS"),
    ("sw-core-par-01", 47, "sw-core-bor-01", 24, "virtual", 1000, "Tunnel inter-DC PAR ↔ BOR"),
    ("sw-core-bor-01", 24, "sw-core-nts-01", 24, "virtual", 1000, "Tunnel inter-DC BOR ↔ NTS"),
    ("sw-core-lyo-02", 6, "sw-edge-nce-01", 1, "virtual", 500, "VPN LYO ↔ NCE"),
    ("sw-core-bor-01", 23, "sw-edge-tls-01", 1, "virtual", 500, "VPN BOR ↔ TLS"),
    ("sw-core-par-02", 47, "sw-edge-lil-01", 1, "virtual", 500, "VPN PAR ↔ LIL"),
    ("sw-core-par-02", 1, "sw-edge-str-01", 1, "virtual", 500, "VPN PAR ↔ STR — unique chemin (SPOF P2)"),
]


# --------------------------------------------------------------------------- #
# CSV writer
# --------------------------------------------------------------------------- #


def _write_csv(headers: list[str], rows: list[tuple]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\n")
    w.writerow(headers)
    for r in rows:
        normalized = []
        for v in r:
            if isinstance(v, bool):
                normalized.append("true" if v else "false")
            elif v is None:
                normalized.append("")
            else:
                normalized.append(v)
        w.writerow(normalized)
    return buf.getvalue().encode("utf-8")


CSV_FILES: list[tuple[str, bytes]] = [
    ("01_sites.csv", _write_csv(["code", "name", "address"], SITES)),
    ("02_rooms.csv", _write_csv(["site_code", "code", "description"], ROOMS)),
    ("03_vlans.csv", _write_csv(["vlan_id", "name", "description", "color"], VLANS)),
    ("04_subnets.csv", _write_csv(
        ["cidr", "gateway", "vlan_id", "site_code", "description",
         "dhcp_enabled", "dhcp_range_start", "dhcp_range_end"],
        SUBNETS,
    )),
    ("05_devices.csv", _write_csv(
        ["name", "type", "vendor", "model", "serial",
         "site_code", "room_code", "description"],
        DEVICES,
    )),
    ("06_switches.csv", _write_csv(
        ["name", "vendor", "model", "serial", "management_ip",
         "site_code", "room_code", "rack_position", "port_count",
         "firmware_version"],
        SWITCHES,
    )),
    ("07_ips.csv", _write_csv(
        ["address", "status", "hostname", "mac", "device_name", "description"],
        IPS,
    )),
    ("08_ports.csv", _write_csv(
        ["switch_name", "number", "label", "mode", "native_vlan",
         "trunk_vlans", "admin_status", "device_name", "connected_ip", "notes"],
        PORTS,
    )),
    ("09_links.csv", _write_csv(
        ["switch_a", "port_a", "switch_b", "port_b", "link_type",
         "speed_mbps", "description"],
        LINKS,
    )),
]


def main() -> None:
    out_dir = Path(__file__).resolve().parent.parent
    out_path = out_dir / "demo-bundle.zip"

    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in CSV_FILES:
            zf.writestr(name, content)

    total = sum(len(c) for _, c in CSV_FILES)
    print(f"Wrote {out_path} ({len(CSV_FILES)} files, {total:,} bytes uncompressed)")
    for name, content in CSV_FILES:
        lines = content.count(b"\n")
        print(f"  - {name}: {lines - 1} rows ({len(content):,} bytes)")


if __name__ == "__main__":
    main()
