"""Generate a fictitious-but-cohesive NetForge inventory and bundle it as a ZIP.

Designed to (a) demo every feature end-to-end and (b) deliberately leave a
few problems for the AI advisor to surface and for suggest-links to fix.

Run from the repo root:
    python sample-data/generate.py

Output: sample-data/netforge-sample-data.zip (eight CSVs + a README).
"""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

OUT_DIR = Path(__file__).parent
ZIP_PATH = OUT_DIR / "netforge-sample-data.zip"


def csv_bytes(headers: list[str], rows: list[dict]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=headers, delimiter=";", extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buf.getvalue().encode("utf-8")


# ---------------------------------------------------------------------------- #
# 1. Sites
# ---------------------------------------------------------------------------- #
sites = [
    {"code": "PAR", "name": "HQ Paris", "address": "12 rue Mozart, 75017 Paris"},
    {"code": "RBX", "name": "Datacenter Roubaix", "address": "2 rue Kellermann, 59100 Roubaix"},
]

# ---------------------------------------------------------------------------- #
# 2. Rooms
# ---------------------------------------------------------------------------- #
rooms = [
    {"site_code": "PAR", "code": "R001", "description": "Local technique RDC"},
    {"site_code": "PAR", "code": "R101", "description": "Bureaux commerciaux (1er etage)"},
    {"site_code": "PAR", "code": "R102", "description": "Bureaux IT (1er etage)"},
    {"site_code": "PAR", "code": "R201", "description": "Direction (2e etage)"},
    {"site_code": "PAR", "code": "R301", "description": "Salle reunion (3e etage)"},
    {"site_code": "RBX", "code": "DC1", "description": "Datacenter principal"},
    {"site_code": "RBX", "code": "DC2", "description": "Datacenter secondaire"},
    {"site_code": "RBX", "code": "MEET", "description": "Salle de reunion ops"},
]

# ---------------------------------------------------------------------------- #
# 3. VLANs
# ---------------------------------------------------------------------------- #
vlans = [
    {"vlan_id": 10, "name": "MGMT", "description": "Switch management", "color": "#6366f1"},
    {"vlan_id": 20, "name": "USERS", "description": "Standard users", "color": "#10b981"},
    {"vlan_id": 21, "name": "USERS-IT", "description": "IT department", "color": "#0ea5e9"},
    {"vlan_id": 22, "name": "USERS-DIR", "description": "Direction", "color": "#a855f7"},
    {"vlan_id": 30, "name": "WIFI-CORP", "description": "WiFi corporate", "color": "#f59e0b"},
    {"vlan_id": 31, "name": "WIFI-GUEST", "description": "WiFi guests (Internet only)", "color": "#fbbf24"},
    {"vlan_id": 40, "name": "VOICE", "description": "VoIP phones", "color": "#ec4899"},
    {"vlan_id": 50, "name": "PRINTERS", "description": "Network printers", "color": "#64748b"},
    {"vlan_id": 60, "name": "SERVERS", "description": "Server farm", "color": "#dc2626"},
    {"vlan_id": 61, "name": "SERVERS-DB", "description": "Database servers", "color": "#b91c1c"},
    {"vlan_id": 62, "name": "SERVERS-WEB", "description": "Web servers", "color": "#ef4444"},
    {"vlan_id": 70, "name": "IOT", "description": "IoT (cameras, sensors)", "color": "#84cc16"},
    {"vlan_id": 80, "name": "IPMI", "description": "Out-of-band IPMI", "color": "#78716c"},
    {"vlan_id": 90, "name": "DMZ", "description": "Public-facing services", "color": "#f97316"},
    {"vlan_id": 99, "name": "NATIVE", "description": "Trunk native VLAN", "color": "#9ca3af"},
    {"vlan_id": 100, "name": "STORAGE", "description": "iSCSI / NFS storage", "color": "#06b6d4"},
    {"vlan_id": 200, "name": "BACKUP", "description": "Backup traffic", "color": "#0891b2"},
]

# ---------------------------------------------------------------------------- #
# 4. Subnets
# ---------------------------------------------------------------------------- #
subnets = [
    # Paris
    {"cidr": "10.10.10.0/24", "gateway": "10.10.10.1", "vlan_id": 10, "site_code": "PAR", "description": "PAR management", "dhcp_enabled": "false", "dhcp_range_start": "", "dhcp_range_end": ""},
    {"cidr": "10.10.20.0/24", "gateway": "10.10.20.1", "vlan_id": 20, "site_code": "PAR", "description": "PAR users", "dhcp_enabled": "true", "dhcp_range_start": "10.10.20.50", "dhcp_range_end": "10.10.20.200"},
    {"cidr": "10.10.21.0/24", "gateway": "10.10.21.1", "vlan_id": 21, "site_code": "PAR", "description": "IT department - close to saturation", "dhcp_enabled": "true", "dhcp_range_start": "10.10.21.10", "dhcp_range_end": "10.10.21.30"},
    {"cidr": "10.10.22.0/24", "gateway": "10.10.22.1", "vlan_id": 22, "site_code": "PAR", "description": "Direction", "dhcp_enabled": "true", "dhcp_range_start": "10.10.22.10", "dhcp_range_end": "10.10.22.50"},
    {"cidr": "10.10.30.0/24", "gateway": "10.10.30.1", "vlan_id": 30, "site_code": "PAR", "description": "WiFi corporate", "dhcp_enabled": "true", "dhcp_range_start": "10.10.30.50", "dhcp_range_end": "10.10.30.250"},
    {"cidr": "10.10.31.0/24", "gateway": "10.10.31.1", "vlan_id": 31, "site_code": "PAR", "description": "WiFi guests", "dhcp_enabled": "true", "dhcp_range_start": "10.10.31.50", "dhcp_range_end": "10.10.31.250"},
    {"cidr": "10.10.40.0/24", "gateway": "10.10.40.1", "vlan_id": 40, "site_code": "PAR", "description": "VoIP", "dhcp_enabled": "true", "dhcp_range_start": "10.10.40.10", "dhcp_range_end": "10.10.40.250"},
    {"cidr": "10.10.50.0/24", "gateway": "10.10.50.1", "vlan_id": 50, "site_code": "PAR", "description": "Printers", "dhcp_enabled": "false", "dhcp_range_start": "", "dhcp_range_end": ""},
    {"cidr": "10.10.70.0/24", "gateway": "10.10.70.1", "vlan_id": 70, "site_code": "PAR", "description": "IoT cameras + sensors", "dhcp_enabled": "true", "dhcp_range_start": "10.10.70.50", "dhcp_range_end": "10.10.70.250"},
    # Roubaix
    {"cidr": "10.20.10.0/24", "gateway": "10.20.10.1", "vlan_id": 10, "site_code": "RBX", "description": "RBX management", "dhcp_enabled": "false", "dhcp_range_start": "", "dhcp_range_end": ""},
    {"cidr": "10.20.60.0/24", "gateway": "10.20.60.1", "vlan_id": 60, "site_code": "RBX", "description": "Server farm", "dhcp_enabled": "false", "dhcp_range_start": "", "dhcp_range_end": ""},
    {"cidr": "10.20.61.0/24", "gateway": "10.20.61.1", "vlan_id": 61, "site_code": "RBX", "description": "Database servers", "dhcp_enabled": "false", "dhcp_range_start": "", "dhcp_range_end": ""},
    {"cidr": "10.20.62.0/24", "gateway": "10.20.62.1", "vlan_id": 62, "site_code": "RBX", "description": "Web servers", "dhcp_enabled": "false", "dhcp_range_start": "", "dhcp_range_end": ""},
    {"cidr": "10.20.80.0/24", "gateway": "10.20.80.1", "vlan_id": 80, "site_code": "RBX", "description": "Out-of-band IPMI", "dhcp_enabled": "false", "dhcp_range_start": "", "dhcp_range_end": ""},
    {"cidr": "10.20.90.0/29", "gateway": "10.20.90.1", "vlan_id": 90, "site_code": "RBX", "description": "DMZ", "dhcp_enabled": "false", "dhcp_range_start": "", "dhcp_range_end": ""},
    {"cidr": "10.20.100.0/24", "gateway": "10.20.100.1", "vlan_id": 100, "site_code": "RBX", "description": "Storage SAN", "dhcp_enabled": "false", "dhcp_range_start": "", "dhcp_range_end": ""},
    {"cidr": "10.20.200.0/24", "gateway": "10.20.200.1", "vlan_id": 200, "site_code": "RBX", "description": "Backup traffic", "dhcp_enabled": "false", "dhcp_range_start": "", "dhcp_range_end": ""},
]

# ---------------------------------------------------------------------------- #
# 5. Devices
# ---------------------------------------------------------------------------- #
devices = [
    # DB servers
    {"name": "SRV-DB-01", "type": "server", "vendor": "Dell", "model": "PowerEdge R750", "serial": "DB01-7HXC9R2", "site_code": "RBX", "room_code": "DC1", "description": "PostgreSQL primary"},
    {"name": "SRV-DB-02", "type": "server", "vendor": "Dell", "model": "PowerEdge R750", "serial": "DB02-7HXD1K8", "site_code": "RBX", "room_code": "DC1", "description": "PostgreSQL replica"},
    {"name": "SRV-DB-03", "type": "server", "vendor": "Dell", "model": "PowerEdge R750", "serial": "DB03-7HXE3M2", "site_code": "RBX", "room_code": "DC2", "description": "PostgreSQL DR"},
    # Web servers
    {"name": "SRV-WEB-01", "type": "server", "vendor": "Dell", "model": "PowerEdge R650", "serial": "WEB01-9KLM4N3", "site_code": "RBX", "room_code": "DC1", "description": "Nginx front 1"},
    {"name": "SRV-WEB-02", "type": "server", "vendor": "Dell", "model": "PowerEdge R650", "serial": "WEB02-9KLN5P7", "site_code": "RBX", "room_code": "DC1", "description": "Nginx front 2"},
    {"name": "SRV-WEB-03", "type": "server", "vendor": "Dell", "model": "PowerEdge R650", "serial": "WEB03-9KLP6Q1", "site_code": "RBX", "room_code": "DC2", "description": "Nginx front 3"},
    # Other servers
    {"name": "SRV-APP-01", "type": "server", "vendor": "HP", "model": "ProLiant DL380", "serial": "APP01-HXY2Z9", "site_code": "RBX", "room_code": "DC1", "description": "Application backend"},
    {"name": "SRV-APP-02", "type": "server", "vendor": "HP", "model": "ProLiant DL380", "serial": "APP02-HXZ3A1", "site_code": "RBX", "room_code": "DC1", "description": "Application backend"},
    {"name": "SRV-FILE-01", "type": "server", "vendor": "Synology", "model": "RS3621xs+", "serial": "FILE01-NAS9", "site_code": "RBX", "room_code": "DC1", "description": "NAS / file share"},
    {"name": "SRV-BACKUP-01", "type": "server", "vendor": "Dell", "model": "PowerVault ME4", "serial": "BACKUP01-PV4", "site_code": "RBX", "room_code": "DC2", "description": "Veeam repository"},
    {"name": "SRV-MONITOR-01", "type": "server", "vendor": "Dell", "model": "PowerEdge R450", "serial": "MON01-PE45", "site_code": "RBX", "room_code": "DC1", "description": "Prometheus + Grafana"},
    # Desktops & laptops
    {"name": "PC-IT-01", "type": "desktop", "vendor": "Dell", "model": "OptiPlex 7090", "serial": "IT01-OPT9", "site_code": "PAR", "room_code": "R102", "description": "Sysadmin workstation"},
    {"name": "PC-IT-02", "type": "desktop", "vendor": "Dell", "model": "OptiPlex 7090", "serial": "IT02-OPT9", "site_code": "PAR", "room_code": "R102", "description": "Network admin workstation"},
    {"name": "PC-IT-03", "type": "desktop", "vendor": "Dell", "model": "OptiPlex 7090", "serial": "IT03-OPT9", "site_code": "PAR", "room_code": "R102", "description": "Helpdesk workstation"},
    {"name": "PC-COM-01", "type": "desktop", "vendor": "HP", "model": "EliteDesk 800", "serial": "COM01-HP8", "site_code": "PAR", "room_code": "R101", "description": "Sales workstation"},
    {"name": "PC-COM-02", "type": "desktop", "vendor": "HP", "model": "EliteDesk 800", "serial": "COM02-HP8", "site_code": "PAR", "room_code": "R101", "description": "Sales workstation"},
    {"name": "PC-COM-03", "type": "desktop", "vendor": "HP", "model": "EliteDesk 800", "serial": "COM03-HP8", "site_code": "PAR", "room_code": "R101", "description": "Sales workstation"},
    {"name": "PC-COM-04", "type": "desktop", "vendor": "HP", "model": "EliteDesk 800", "serial": "COM04-HP8", "site_code": "PAR", "room_code": "R101", "description": "Sales workstation"},
    {"name": "LAPTOP-DIR-01", "type": "laptop", "vendor": "Apple", "model": "MacBook Pro 14", "serial": "LAP01-MBP4", "site_code": "PAR", "room_code": "R201", "description": "CEO laptop"},
    {"name": "LAPTOP-DIR-02", "type": "laptop", "vendor": "Apple", "model": "MacBook Pro 14", "serial": "LAP02-MBP4", "site_code": "PAR", "room_code": "R201", "description": "CTO laptop"},
    # Access points
    {"name": "AP-PAR-R001", "type": "ap", "vendor": "Aruba", "model": "AP-535", "serial": "AP001-ARB5", "site_code": "PAR", "room_code": "R001", "description": "RDC corporate WiFi"},
    {"name": "AP-PAR-R101", "type": "ap", "vendor": "Aruba", "model": "AP-535", "serial": "AP101-ARB5", "site_code": "PAR", "room_code": "R101", "description": "Sales WiFi"},
    {"name": "AP-PAR-R201", "type": "ap", "vendor": "Aruba", "model": "AP-535", "serial": "AP201-ARB5", "site_code": "PAR", "room_code": "R201", "description": "Direction WiFi"},
    {"name": "AP-PAR-R301", "type": "ap", "vendor": "Aruba", "model": "AP-535", "serial": "AP301-ARB5", "site_code": "PAR", "room_code": "R301", "description": "Meeting room WiFi"},
    # Printers / cameras / misc
    {"name": "PRINTER-COM", "type": "printer", "vendor": "HP", "model": "LaserJet M507", "serial": "PRT-COM-507", "site_code": "PAR", "room_code": "R101", "description": "Sales floor printer"},
    {"name": "PRINTER-IT", "type": "printer", "vendor": "HP", "model": "LaserJet M507", "serial": "PRT-IT-507", "site_code": "PAR", "room_code": "R102", "description": "IT floor printer"},
    {"name": "CAM-ENTRY-01", "type": "camera", "vendor": "Axis", "model": "P1448-LE", "serial": "CAM01-AX48", "site_code": "PAR", "room_code": "R001", "description": "Lobby camera"},
    {"name": "CAM-PARKING-01", "type": "camera", "vendor": "Axis", "model": "P1448-LE", "serial": "CAM02-AX48", "site_code": "PAR", "room_code": "R001", "description": "Parking camera"},
    {"name": "PHONE-RECEP-01", "type": "phone", "vendor": "Yealink", "model": "T46U", "serial": "PHN01-YL46", "site_code": "PAR", "room_code": "R001", "description": "Reception phone"},
    {"name": "UPS-RBX-DC1", "type": "ups", "vendor": "APC", "model": "Smart-UPS SRT 5000", "serial": "UPS01-APC5", "site_code": "RBX", "room_code": "DC1", "description": "DC1 UPS"},
]

# ---------------------------------------------------------------------------- #
# 6. Switches
# ---------------------------------------------------------------------------- #
# Deliberately leave SW-CORE-RBX-02 as a redundancy partner but with NO links —
# the advisor should flag the missing redundancy / the SPOF in the Paris core.
# SW-IPMI-RBX uses a different vendor + version pattern (Aruba 2930F vs Cisco
# 9500) so the naming/inventory inconsistency feature can pick it up.
switches = [
    {"name": "SW-CORE-PAR-01", "vendor": "Cisco", "model": "Catalyst 9500-48Y4C", "serial": "C9500-PAR01", "management_ip": "10.10.10.10", "site_code": "PAR", "room_code": "R001", "rack_position": "U10", "port_count": 48, "firmware_version": "17.12.04"},
    {"name": "SW-EDGE-PAR-R001", "vendor": "Cisco", "model": "Catalyst 9300-48P", "serial": "C9300-R001", "management_ip": "10.10.10.21", "site_code": "PAR", "room_code": "R001", "rack_position": "U12", "port_count": 48, "firmware_version": "17.12.04"},
    {"name": "SW-EDGE-PAR-R101", "vendor": "Cisco", "model": "Catalyst 9300-48P", "serial": "C9300-R101", "management_ip": "10.10.10.22", "site_code": "PAR", "room_code": "R101", "rack_position": "U06", "port_count": 48, "firmware_version": "17.12.04"},
    {"name": "SW-EDGE-PAR-R102", "vendor": "Cisco", "model": "Catalyst 9300-48P", "serial": "C9300-R102", "management_ip": "10.10.10.23", "site_code": "PAR", "room_code": "R102", "rack_position": "U06", "port_count": 48, "firmware_version": "17.09.05"},
    {"name": "SW-EDGE-PAR-R201", "vendor": "Cisco", "model": "Catalyst 9300-24P", "serial": "C9300-R201", "management_ip": "10.10.10.24", "site_code": "PAR", "room_code": "R201", "rack_position": "U04", "port_count": 24, "firmware_version": "17.12.04"},
    {"name": "SW-EDGE-PAR-R301", "vendor": "Cisco", "model": "Catalyst 9300-24P", "serial": "C9300-R301", "management_ip": "10.10.10.25", "site_code": "PAR", "room_code": "R301", "rack_position": "U04", "port_count": 24, "firmware_version": "17.12.04"},
    {"name": "SW-CORE-RBX-01", "vendor": "Cisco", "model": "Catalyst 9500-48Y4C", "serial": "C9500-RBX01", "management_ip": "10.20.10.10", "site_code": "RBX", "room_code": "DC1", "rack_position": "U30", "port_count": 48, "firmware_version": "17.12.04"},
    {"name": "SW-CORE-RBX-02", "vendor": "Cisco", "model": "Catalyst 9500-48Y4C", "serial": "C9500-RBX02", "management_ip": "10.20.10.11", "site_code": "RBX", "room_code": "DC2", "rack_position": "U30", "port_count": 48, "firmware_version": "17.12.04"},
    {"name": "SW-DC1-A", "vendor": "Cisco", "model": "Nexus 9336C-FX2", "serial": "N93-DC1A", "management_ip": "10.20.10.30", "site_code": "RBX", "room_code": "DC1", "rack_position": "U20", "port_count": 36, "firmware_version": "10.3.5"},
    {"name": "SW-DC1-B", "vendor": "Cisco", "model": "Nexus 9336C-FX2", "serial": "N93-DC1B", "management_ip": "10.20.10.31", "site_code": "RBX", "room_code": "DC1", "rack_position": "U22", "port_count": 36, "firmware_version": "10.3.5"},
    {"name": "SW-DC2-A", "vendor": "Cisco", "model": "Nexus 9336C-FX2", "serial": "N93-DC2A", "management_ip": "10.20.10.40", "site_code": "RBX", "room_code": "DC2", "rack_position": "U20", "port_count": 36, "firmware_version": "10.3.5"},
    {"name": "switch-old-ipmi", "vendor": "Aruba", "model": "2930F-48G", "serial": "ARB-IPMI", "management_ip": "10.10.10.99", "site_code": "RBX", "room_code": "DC1", "rack_position": "U02", "port_count": 48, "firmware_version": "WC.16.10.0014"},
]

# ---------------------------------------------------------------------------- #
# 7. IPs — a sampling of assigned addresses so the dashboard / advisor have
#    real numbers to chew on. Status mapping: assigned (linked to a device),
#    reserved (gateways / future use), free is implicit and not enumerated.
# ---------------------------------------------------------------------------- #
ips: list[dict] = [
    # PAR MGMT gateways + management plane
    {"address": "10.10.10.1", "status": "reserved", "hostname": "gw-par-mgmt", "mac": "", "device_name": "", "description": "PAR MGMT gateway"},
    {"address": "10.10.10.10", "status": "assigned", "hostname": "sw-core-par-01.mgmt", "mac": "00:1b:0d:11:11:01", "device_name": "", "description": "Core switch mgmt"},
    {"address": "10.10.10.21", "status": "assigned", "hostname": "sw-edge-r001.mgmt", "mac": "00:1b:0d:11:11:21", "device_name": "", "description": ""},
    {"address": "10.10.10.22", "status": "assigned", "hostname": "sw-edge-r101.mgmt", "mac": "00:1b:0d:11:11:22", "device_name": "", "description": ""},
    {"address": "10.10.10.23", "status": "assigned", "hostname": "sw-edge-r102.mgmt", "mac": "00:1b:0d:11:11:23", "device_name": "", "description": ""},
    {"address": "10.10.10.24", "status": "assigned", "hostname": "sw-edge-r201.mgmt", "mac": "00:1b:0d:11:11:24", "device_name": "", "description": ""},
    {"address": "10.10.10.25", "status": "assigned", "hostname": "sw-edge-r301.mgmt", "mac": "00:1b:0d:11:11:25", "device_name": "", "description": ""},
    {"address": "10.10.10.99", "status": "assigned", "hostname": "switch-old-ipmi.mgmt", "mac": "00:1b:0d:11:11:99", "device_name": "", "description": "Old IPMI switch on PAR MGMT — should move to RBX MGMT"},
    # PAR users (IT)
    {"address": "10.10.21.1", "status": "reserved", "hostname": "gw-it", "mac": "", "device_name": "", "description": "USERS-IT gateway"},
    {"address": "10.10.21.10", "status": "assigned", "hostname": "pc-it-01.lan", "mac": "ac:de:48:00:11:01", "device_name": "PC-IT-01", "description": ""},
    {"address": "10.10.21.11", "status": "assigned", "hostname": "pc-it-02.lan", "mac": "ac:de:48:00:11:02", "device_name": "PC-IT-02", "description": ""},
    {"address": "10.10.21.12", "status": "assigned", "hostname": "pc-it-03.lan", "mac": "ac:de:48:00:11:03", "device_name": "PC-IT-03", "description": ""},
    {"address": "10.10.21.13", "status": "assigned", "hostname": "printer-it.lan", "mac": "ac:de:48:00:11:13", "device_name": "PRINTER-IT", "description": ""},
    # PAR users (sales)
    {"address": "10.10.20.1", "status": "reserved", "hostname": "gw-users", "mac": "", "device_name": "", "description": "USERS gateway"},
    {"address": "10.10.20.50", "status": "assigned", "hostname": "pc-com-01.lan", "mac": "ac:de:48:00:20:01", "device_name": "PC-COM-01", "description": ""},
    {"address": "10.10.20.51", "status": "assigned", "hostname": "pc-com-02.lan", "mac": "ac:de:48:00:20:02", "device_name": "PC-COM-02", "description": ""},
    {"address": "10.10.20.52", "status": "assigned", "hostname": "pc-com-03.lan", "mac": "ac:de:48:00:20:03", "device_name": "PC-COM-03", "description": ""},
    {"address": "10.10.20.53", "status": "assigned", "hostname": "pc-com-04.lan", "mac": "ac:de:48:00:20:04", "device_name": "PC-COM-04", "description": ""},
    # Direction
    {"address": "10.10.22.10", "status": "assigned", "hostname": "laptop-dir-01.lan", "mac": "ac:de:48:00:22:01", "device_name": "LAPTOP-DIR-01", "description": ""},
    {"address": "10.10.22.11", "status": "assigned", "hostname": "laptop-dir-02.lan", "mac": "ac:de:48:00:22:02", "device_name": "LAPTOP-DIR-02", "description": ""},
    # Printers / cameras
    {"address": "10.10.50.10", "status": "assigned", "hostname": "printer-com.lan", "mac": "00:80:77:00:50:10", "device_name": "PRINTER-COM", "description": ""},
    {"address": "10.10.70.10", "status": "assigned", "hostname": "cam-entry-01.iot", "mac": "00:40:8c:00:70:10", "device_name": "CAM-ENTRY-01", "description": ""},
    {"address": "10.10.70.11", "status": "assigned", "hostname": "cam-parking-01.iot", "mac": "00:40:8c:00:70:11", "device_name": "CAM-PARKING-01", "description": ""},
    # APs (mgmt on MGMT VLAN, clients on WIFI VLANs)
    {"address": "10.10.10.50", "status": "assigned", "hostname": "ap-par-r001.mgmt", "mac": "94:b4:0f:00:10:50", "device_name": "AP-PAR-R001", "description": ""},
    {"address": "10.10.10.51", "status": "assigned", "hostname": "ap-par-r101.mgmt", "mac": "94:b4:0f:00:10:51", "device_name": "AP-PAR-R101", "description": ""},
    {"address": "10.10.10.52", "status": "assigned", "hostname": "ap-par-r201.mgmt", "mac": "94:b4:0f:00:10:52", "device_name": "AP-PAR-R201", "description": ""},
    {"address": "10.10.10.53", "status": "assigned", "hostname": "ap-par-r301.mgmt", "mac": "94:b4:0f:00:10:53", "device_name": "AP-PAR-R301", "description": ""},
    # Phones
    {"address": "10.10.40.50", "status": "assigned", "hostname": "phone-recep-01.voice", "mac": "00:15:65:00:40:50", "device_name": "PHONE-RECEP-01", "description": ""},
    # ---- RBX ----
    {"address": "10.20.10.1", "status": "reserved", "hostname": "gw-rbx-mgmt", "mac": "", "device_name": "", "description": "RBX MGMT gateway"},
    {"address": "10.20.10.10", "status": "assigned", "hostname": "sw-core-rbx-01.mgmt", "mac": "00:1b:0d:20:10:10", "device_name": "", "description": ""},
    {"address": "10.20.10.11", "status": "assigned", "hostname": "sw-core-rbx-02.mgmt", "mac": "00:1b:0d:20:10:11", "device_name": "", "description": ""},
    {"address": "10.20.10.30", "status": "assigned", "hostname": "sw-dc1-a.mgmt", "mac": "00:1b:0d:20:10:30", "device_name": "", "description": ""},
    {"address": "10.20.10.31", "status": "assigned", "hostname": "sw-dc1-b.mgmt", "mac": "00:1b:0d:20:10:31", "device_name": "", "description": ""},
    {"address": "10.20.10.40", "status": "assigned", "hostname": "sw-dc2-a.mgmt", "mac": "00:1b:0d:20:10:40", "device_name": "", "description": ""},
    # DB
    {"address": "10.20.61.10", "status": "assigned", "hostname": "srv-db-01.rbx", "mac": "0c:c4:7a:00:61:10", "device_name": "SRV-DB-01", "description": "Postgres primary"},
    {"address": "10.20.61.11", "status": "assigned", "hostname": "srv-db-02.rbx", "mac": "0c:c4:7a:00:61:11", "device_name": "SRV-DB-02", "description": "Postgres replica"},
    {"address": "10.20.61.12", "status": "assigned", "hostname": "srv-db-03.rbx", "mac": "0c:c4:7a:00:61:12", "device_name": "SRV-DB-03", "description": "Postgres DR (DC2)"},
    # Web
    {"address": "10.20.62.10", "status": "assigned", "hostname": "srv-web-01.rbx", "mac": "0c:c4:7a:00:62:10", "device_name": "SRV-WEB-01", "description": ""},
    {"address": "10.20.62.11", "status": "assigned", "hostname": "srv-web-02.rbx", "mac": "0c:c4:7a:00:62:11", "device_name": "SRV-WEB-02", "description": ""},
    {"address": "10.20.62.12", "status": "assigned", "hostname": "srv-web-03.rbx", "mac": "0c:c4:7a:00:62:12", "device_name": "SRV-WEB-03", "description": ""},
    # Other servers
    {"address": "10.20.60.20", "status": "assigned", "hostname": "srv-app-01.rbx", "mac": "0c:c4:7a:00:60:20", "device_name": "SRV-APP-01", "description": ""},
    {"address": "10.20.60.21", "status": "assigned", "hostname": "srv-app-02.rbx", "mac": "0c:c4:7a:00:60:21", "device_name": "SRV-APP-02", "description": ""},
    {"address": "10.20.100.10", "status": "assigned", "hostname": "srv-file-01.rbx", "mac": "00:11:32:00:10:10", "device_name": "SRV-FILE-01", "description": "Synology NAS"},
    {"address": "10.20.200.10", "status": "assigned", "hostname": "srv-backup-01.rbx", "mac": "0c:c4:7a:00:20:10", "device_name": "SRV-BACKUP-01", "description": "Veeam"},
    {"address": "10.20.10.50", "status": "assigned", "hostname": "srv-monitor-01.rbx", "mac": "0c:c4:7a:00:10:50", "device_name": "SRV-MONITOR-01", "description": "Prometheus"},
    # IPMI plane
    {"address": "10.20.80.10", "status": "assigned", "hostname": "srv-db-01.ipmi", "mac": "0c:c4:7a:00:80:10", "device_name": "", "description": "IPMI SRV-DB-01"},
    {"address": "10.20.80.11", "status": "assigned", "hostname": "srv-db-02.ipmi", "mac": "0c:c4:7a:00:80:11", "device_name": "", "description": "IPMI SRV-DB-02"},
    {"address": "10.20.80.20", "status": "assigned", "hostname": "srv-app-01.ipmi", "mac": "0c:c4:7a:00:80:20", "device_name": "", "description": "IPMI SRV-APP-01"},
    # DMZ
    {"address": "10.20.90.2", "status": "reserved", "hostname": "dmz-reverse-proxy", "mac": "", "device_name": "", "description": "Public reverse proxy"},
    {"address": "10.20.90.3", "status": "reserved", "hostname": "dmz-smtp-relay", "mac": "", "device_name": "", "description": "Outbound SMTP relay"},
]

# Fill IT subnet to ~95 % (deliberately) for the capacity insight. Range starts
# at .10 — we go up to .250 with hostnames so the advisor sees the pressure.
for n in range(14, 60):
    ips.append({
        "address": f"10.10.21.{n}",
        "status": "dhcp",
        "hostname": f"it-leased-{n:03d}.lan",
        "mac": f"ac:de:48:01:21:{n:02x}",
        "device_name": "",
        "description": "DHCP lease",
    })

# ---------------------------------------------------------------------------- #
# 8. Ports — labels on the strategic ones so the AI can pattern-match.
#    Note that SW-CORE-RBX-02 has no labels (no recorded links + no hints) so
#    the advisor can flag it as orphaned.
#    SW-EDGE-PAR-R301 carries a "to-SW-CORE-PAR-01:gi1/0/48" hint in `notes`
#    but no actual link in the links.csv → perfect bait for suggest-links.
# ---------------------------------------------------------------------------- #
ports = [
    # Core PAR uplinks (downlinks to edges; fiber)
    {"switch_name": "SW-CORE-PAR-01", "number": 1, "label": "to-SW-EDGE-PAR-R001:48", "mode": "trunk", "native_vlan": 99, "trunk_vlans": "10,20,21,22,30,31,40,50,70", "admin_status": "up", "device_name": "", "connected_ip": "", "notes": "fiber uplink to R001 edge"},
    {"switch_name": "SW-CORE-PAR-01", "number": 2, "label": "to-SW-EDGE-PAR-R101:48", "mode": "trunk", "native_vlan": 99, "trunk_vlans": "10,20,30,40,50", "admin_status": "up", "device_name": "", "connected_ip": "", "notes": "fiber uplink to R101 edge"},
    {"switch_name": "SW-CORE-PAR-01", "number": 3, "label": "to-SW-EDGE-PAR-R102:48", "mode": "trunk", "native_vlan": 99, "trunk_vlans": "10,21,30,40,50", "admin_status": "up", "device_name": "", "connected_ip": "", "notes": "fiber uplink to R102 edge"},
    {"switch_name": "SW-CORE-PAR-01", "number": 4, "label": "to-SW-EDGE-PAR-R201:24", "mode": "trunk", "native_vlan": 99, "trunk_vlans": "10,22,30,40", "admin_status": "up", "device_name": "", "connected_ip": "", "notes": "fiber uplink to R201 edge"},
    {"switch_name": "SW-CORE-PAR-01", "number": 48, "label": "WAN to-SW-CORE-RBX-01:48", "mode": "trunk", "native_vlan": 99, "trunk_vlans": "10,60,61,62,80,100,200", "admin_status": "up", "device_name": "", "connected_ip": "", "notes": "10G fiber WAN to Roubaix"},
    # Edge R001 — Cisco
    {"switch_name": "SW-EDGE-PAR-R001", "number": 1, "label": "AP-PAR-R001", "mode": "access", "native_vlan": 10, "trunk_vlans": "", "admin_status": "up", "device_name": "AP-PAR-R001", "connected_ip": "10.10.10.50", "notes": ""},
    {"switch_name": "SW-EDGE-PAR-R001", "number": 2, "label": "CAM-ENTRY-01", "mode": "access", "native_vlan": 70, "trunk_vlans": "", "admin_status": "up", "device_name": "CAM-ENTRY-01", "connected_ip": "10.10.70.10", "notes": ""},
    {"switch_name": "SW-EDGE-PAR-R001", "number": 3, "label": "CAM-PARKING-01", "mode": "access", "native_vlan": 70, "trunk_vlans": "", "admin_status": "up", "device_name": "CAM-PARKING-01", "connected_ip": "10.10.70.11", "notes": ""},
    {"switch_name": "SW-EDGE-PAR-R001", "number": 4, "label": "PHONE-RECEP-01", "mode": "access", "native_vlan": 40, "trunk_vlans": "", "admin_status": "up", "device_name": "PHONE-RECEP-01", "connected_ip": "10.10.40.50", "notes": ""},
    {"switch_name": "SW-EDGE-PAR-R001", "number": 48, "label": "to-CORE-PAR-01:1", "mode": "trunk", "native_vlan": 99, "trunk_vlans": "10,20,21,22,30,31,40,50,70", "admin_status": "up", "device_name": "", "connected_ip": "", "notes": "uplink to core"},
    # Edge R101 (sales)
    {"switch_name": "SW-EDGE-PAR-R101", "number": 1, "label": "PC-COM-01", "mode": "access", "native_vlan": 20, "trunk_vlans": "", "admin_status": "up", "device_name": "PC-COM-01", "connected_ip": "10.10.20.50", "notes": ""},
    {"switch_name": "SW-EDGE-PAR-R101", "number": 2, "label": "PC-COM-02", "mode": "access", "native_vlan": 20, "trunk_vlans": "", "admin_status": "up", "device_name": "PC-COM-02", "connected_ip": "10.10.20.51", "notes": ""},
    {"switch_name": "SW-EDGE-PAR-R101", "number": 3, "label": "PC-COM-03", "mode": "access", "native_vlan": 20, "trunk_vlans": "", "admin_status": "up", "device_name": "PC-COM-03", "connected_ip": "10.10.20.52", "notes": ""},
    {"switch_name": "SW-EDGE-PAR-R101", "number": 4, "label": "PC-COM-04", "mode": "access", "native_vlan": 20, "trunk_vlans": "", "admin_status": "up", "device_name": "PC-COM-04", "connected_ip": "10.10.20.53", "notes": ""},
    # AP trunks: native = MGMT VLAN (untagged for the AP itself), tagged =
    # the SSIDs the AP bridges to the wire. The native VLAN must NOT also
    # appear in `trunk_vlans` — the backend rejects it as a contradictory
    # tag-and-untag on the same id.
    {"switch_name": "SW-EDGE-PAR-R101", "number": 5, "label": "AP-PAR-R101", "mode": "trunk", "native_vlan": 10, "trunk_vlans": "30,31", "admin_status": "up", "device_name": "AP-PAR-R101", "connected_ip": "10.10.10.51", "notes": ""},
    {"switch_name": "SW-EDGE-PAR-R101", "number": 6, "label": "PRINTER-COM", "mode": "access", "native_vlan": 50, "trunk_vlans": "", "admin_status": "up", "device_name": "PRINTER-COM", "connected_ip": "10.10.50.10", "notes": ""},
    {"switch_name": "SW-EDGE-PAR-R101", "number": 48, "label": "to-CORE-PAR-01:2", "mode": "trunk", "native_vlan": 99, "trunk_vlans": "10,20,30,40,50", "admin_status": "up", "device_name": "", "connected_ip": "", "notes": "uplink to core"},
    # Edge R102 (IT)
    {"switch_name": "SW-EDGE-PAR-R102", "number": 1, "label": "PC-IT-01", "mode": "access", "native_vlan": 21, "trunk_vlans": "", "admin_status": "up", "device_name": "PC-IT-01", "connected_ip": "10.10.21.10", "notes": ""},
    {"switch_name": "SW-EDGE-PAR-R102", "number": 2, "label": "PC-IT-02", "mode": "access", "native_vlan": 21, "trunk_vlans": "", "admin_status": "up", "device_name": "PC-IT-02", "connected_ip": "10.10.21.11", "notes": ""},
    {"switch_name": "SW-EDGE-PAR-R102", "number": 3, "label": "PC-IT-03", "mode": "access", "native_vlan": 21, "trunk_vlans": "", "admin_status": "up", "device_name": "PC-IT-03", "connected_ip": "10.10.21.12", "notes": ""},
    {"switch_name": "SW-EDGE-PAR-R102", "number": 4, "label": "PRINTER-IT", "mode": "access", "native_vlan": 21, "trunk_vlans": "", "admin_status": "up", "device_name": "PRINTER-IT", "connected_ip": "10.10.21.13", "notes": ""},
    {"switch_name": "SW-EDGE-PAR-R102", "number": 48, "label": "to-CORE-PAR-01:3", "mode": "trunk", "native_vlan": 99, "trunk_vlans": "10,21,30,40,50", "admin_status": "up", "device_name": "", "connected_ip": "", "notes": "uplink to core"},
    # Edge R201 (direction)
    {"switch_name": "SW-EDGE-PAR-R201", "number": 1, "label": "LAPTOP-DIR-01 dock", "mode": "access", "native_vlan": 22, "trunk_vlans": "", "admin_status": "up", "device_name": "LAPTOP-DIR-01", "connected_ip": "10.10.22.10", "notes": ""},
    {"switch_name": "SW-EDGE-PAR-R201", "number": 2, "label": "LAPTOP-DIR-02 dock", "mode": "access", "native_vlan": 22, "trunk_vlans": "", "admin_status": "up", "device_name": "LAPTOP-DIR-02", "connected_ip": "10.10.22.11", "notes": ""},
    {"switch_name": "SW-EDGE-PAR-R201", "number": 5, "label": "AP-PAR-R201", "mode": "trunk", "native_vlan": 10, "trunk_vlans": "30,31", "admin_status": "up", "device_name": "AP-PAR-R201", "connected_ip": "10.10.10.52", "notes": ""},
    {"switch_name": "SW-EDGE-PAR-R201", "number": 24, "label": "to-CORE-PAR-01:4", "mode": "trunk", "native_vlan": 99, "trunk_vlans": "10,22,30,40", "admin_status": "up", "device_name": "", "connected_ip": "", "notes": "uplink to core"},
    # Edge R301 — uplink labelled in notes but NO actual link recorded (bait for suggest-links)
    {"switch_name": "SW-EDGE-PAR-R301", "number": 5, "label": "AP-PAR-R301", "mode": "trunk", "native_vlan": 10, "trunk_vlans": "30,31", "admin_status": "up", "device_name": "AP-PAR-R301", "connected_ip": "10.10.10.53", "notes": ""},
    {"switch_name": "SW-EDGE-PAR-R301", "number": 24, "label": "uplink fiber", "mode": "trunk", "native_vlan": 99, "trunk_vlans": "10,22,30,40", "admin_status": "up", "device_name": "", "connected_ip": "", "notes": "uplink to SW-CORE-PAR-01 port gi1/0/48"},
    # Core RBX 01
    {"switch_name": "SW-CORE-RBX-01", "number": 1, "label": "to-SW-DC1-A:36", "mode": "trunk", "native_vlan": 99, "trunk_vlans": "10,60,61,62,80,100,200", "admin_status": "up", "device_name": "", "connected_ip": "", "notes": ""},
    {"switch_name": "SW-CORE-RBX-01", "number": 2, "label": "to-SW-DC1-B:36", "mode": "trunk", "native_vlan": 99, "trunk_vlans": "10,60,61,62,80,100,200", "admin_status": "up", "device_name": "", "connected_ip": "", "notes": ""},
    {"switch_name": "SW-CORE-RBX-01", "number": 3, "label": "to-SW-DC2-A:36", "mode": "trunk", "native_vlan": 99, "trunk_vlans": "10,60,61,62,80,100,200", "admin_status": "up", "device_name": "", "connected_ip": "", "notes": ""},
    {"switch_name": "SW-CORE-RBX-01", "number": 48, "label": "WAN to-SW-CORE-PAR-01:48", "mode": "trunk", "native_vlan": 99, "trunk_vlans": "10,60,61,62,80,100,200", "admin_status": "up", "device_name": "", "connected_ip": "", "notes": "10G fiber WAN to Paris"},
    # Core RBX 02 — explicitly intended as a redundant peer but nothing is
    # plugged in yet. SPOF detection target.
    {"switch_name": "SW-CORE-RBX-02", "number": 1, "label": "reserved redundancy", "mode": "trunk", "native_vlan": 99, "trunk_vlans": "10,60,61,62,80,100,200", "admin_status": "down", "device_name": "", "connected_ip": "", "notes": "intended to mirror RBX-01 paths, not yet patched"},
    # DC1 A — Cisco Nexus
    {"switch_name": "SW-DC1-A", "number": 1, "label": "SRV-DB-01 eth0", "mode": "access", "native_vlan": 61, "trunk_vlans": "", "admin_status": "up", "device_name": "SRV-DB-01", "connected_ip": "10.20.61.10", "notes": ""},
    {"switch_name": "SW-DC1-A", "number": 2, "label": "SRV-DB-02 eth0", "mode": "access", "native_vlan": 61, "trunk_vlans": "", "admin_status": "up", "device_name": "SRV-DB-02", "connected_ip": "10.20.61.11", "notes": ""},
    {"switch_name": "SW-DC1-A", "number": 3, "label": "SRV-WEB-01 eth0", "mode": "access", "native_vlan": 62, "trunk_vlans": "", "admin_status": "up", "device_name": "SRV-WEB-01", "connected_ip": "10.20.62.10", "notes": ""},
    {"switch_name": "SW-DC1-A", "number": 4, "label": "SRV-WEB-02 eth0", "mode": "access", "native_vlan": 62, "trunk_vlans": "", "admin_status": "up", "device_name": "SRV-WEB-02", "connected_ip": "10.20.62.11", "notes": ""},
    {"switch_name": "SW-DC1-A", "number": 36, "label": "to-CORE-RBX-01:1", "mode": "trunk", "native_vlan": 99, "trunk_vlans": "10,60,61,62,80,100,200", "admin_status": "up", "device_name": "", "connected_ip": "", "notes": "uplink to core"},
    # DC1 B
    {"switch_name": "SW-DC1-B", "number": 1, "label": "SRV-APP-01 eth0", "mode": "access", "native_vlan": 60, "trunk_vlans": "", "admin_status": "up", "device_name": "SRV-APP-01", "connected_ip": "10.20.60.20", "notes": ""},
    {"switch_name": "SW-DC1-B", "number": 2, "label": "SRV-APP-02 eth0", "mode": "access", "native_vlan": 60, "trunk_vlans": "", "admin_status": "up", "device_name": "SRV-APP-02", "connected_ip": "10.20.60.21", "notes": ""},
    {"switch_name": "SW-DC1-B", "number": 5, "label": "SRV-FILE-01 eth0", "mode": "access", "native_vlan": 100, "trunk_vlans": "", "admin_status": "up", "device_name": "SRV-FILE-01", "connected_ip": "10.20.100.10", "notes": ""},
    {"switch_name": "SW-DC1-B", "number": 6, "label": "SRV-MONITOR-01 eth0", "mode": "access", "native_vlan": 10, "trunk_vlans": "", "admin_status": "up", "device_name": "SRV-MONITOR-01", "connected_ip": "10.20.10.50", "notes": ""},
    {"switch_name": "SW-DC1-B", "number": 36, "label": "to-CORE-RBX-01:2", "mode": "trunk", "native_vlan": 99, "trunk_vlans": "10,60,61,62,80,100,200", "admin_status": "up", "device_name": "", "connected_ip": "", "notes": "uplink to core"},
    # DC2 A
    {"switch_name": "SW-DC2-A", "number": 1, "label": "SRV-DB-03 eth0", "mode": "access", "native_vlan": 61, "trunk_vlans": "", "admin_status": "up", "device_name": "SRV-DB-03", "connected_ip": "10.20.61.12", "notes": ""},
    {"switch_name": "SW-DC2-A", "number": 2, "label": "SRV-WEB-03 eth0", "mode": "access", "native_vlan": 62, "trunk_vlans": "", "admin_status": "up", "device_name": "SRV-WEB-03", "connected_ip": "10.20.62.12", "notes": ""},
    {"switch_name": "SW-DC2-A", "number": 3, "label": "SRV-BACKUP-01 eth0", "mode": "access", "native_vlan": 200, "trunk_vlans": "", "admin_status": "up", "device_name": "SRV-BACKUP-01", "connected_ip": "10.20.200.10", "notes": ""},
    {"switch_name": "SW-DC2-A", "number": 36, "label": "to-CORE-RBX-01:3", "mode": "trunk", "native_vlan": 99, "trunk_vlans": "10,60,61,62,80,100,200", "admin_status": "up", "device_name": "", "connected_ip": "", "notes": "uplink to core"},
    # Old IPMI Aruba — sloppy labels on purpose to trigger naming/security issues
    {"switch_name": "switch-old-ipmi", "number": 1, "label": "ipmi-db-01", "mode": "access", "native_vlan": 80, "trunk_vlans": "", "admin_status": "up", "device_name": "", "connected_ip": "10.20.80.10", "notes": ""},
    {"switch_name": "switch-old-ipmi", "number": 2, "label": "ipmi-db-02", "mode": "access", "native_vlan": 80, "trunk_vlans": "", "admin_status": "up", "device_name": "", "connected_ip": "10.20.80.11", "notes": ""},
    {"switch_name": "switch-old-ipmi", "number": 3, "label": "ipmi-app-01", "mode": "access", "native_vlan": 80, "trunk_vlans": "", "admin_status": "up", "device_name": "", "connected_ip": "10.20.80.20", "notes": ""},
]

# ---------------------------------------------------------------------------- #
# 9. Links — record real links but deliberately leave a couple missing so
#    suggest-links has something to find:
#      * SW-EDGE-PAR-R301:24 ↔ SW-CORE-PAR-01:??  (hint in notes)
#      * SW-CORE-RBX-02 ↔ anything                (intended redundancy)
# ---------------------------------------------------------------------------- #
links = [
    # Paris core ↔ edges
    {"switch_a": "SW-CORE-PAR-01", "port_a": 1, "switch_b": "SW-EDGE-PAR-R001", "port_b": 48, "link_type": "fiber", "speed_mbps": 10000, "description": "Core ↔ R001 edge"},
    {"switch_a": "SW-CORE-PAR-01", "port_a": 2, "switch_b": "SW-EDGE-PAR-R101", "port_b": 48, "link_type": "fiber", "speed_mbps": 10000, "description": "Core ↔ R101 edge"},
    {"switch_a": "SW-CORE-PAR-01", "port_a": 3, "switch_b": "SW-EDGE-PAR-R102", "port_b": 48, "link_type": "fiber", "speed_mbps": 10000, "description": "Core ↔ R102 edge"},
    {"switch_a": "SW-CORE-PAR-01", "port_a": 4, "switch_b": "SW-EDGE-PAR-R201", "port_b": 24, "link_type": "fiber", "speed_mbps": 1000, "description": "Core ↔ R201 edge"},
    # WAN
    {"switch_a": "SW-CORE-PAR-01", "port_a": 48, "switch_b": "SW-CORE-RBX-01", "port_b": 48, "link_type": "fiber", "speed_mbps": 10000, "description": "WAN PAR↔RBX"},
    # RBX core ↔ DC
    {"switch_a": "SW-CORE-RBX-01", "port_a": 1, "switch_b": "SW-DC1-A", "port_b": 36, "link_type": "fiber", "speed_mbps": 25000, "description": "Core ↔ DC1-A"},
    {"switch_a": "SW-CORE-RBX-01", "port_a": 2, "switch_b": "SW-DC1-B", "port_b": 36, "link_type": "fiber", "speed_mbps": 25000, "description": "Core ↔ DC1-B"},
    {"switch_a": "SW-CORE-RBX-01", "port_a": 3, "switch_b": "SW-DC2-A", "port_b": 36, "link_type": "fiber", "speed_mbps": 10000, "description": "Core ↔ DC2-A"},
]


# ---------------------------------------------------------------------------- #
# Headers — order matters for readability; non-required cols can be empty
# ---------------------------------------------------------------------------- #
ENTRIES = [
    ("sites.csv", ["code", "name", "address"], sites),
    ("rooms.csv", ["site_code", "code", "description"], rooms),
    ("vlans.csv", ["vlan_id", "name", "description", "color"], vlans),
    (
        "subnets.csv",
        ["cidr", "gateway", "vlan_id", "site_code", "description", "dhcp_enabled", "dhcp_range_start", "dhcp_range_end"],
        subnets,
    ),
    (
        "devices.csv",
        ["name", "type", "vendor", "model", "serial", "site_code", "room_code", "description"],
        devices,
    ),
    (
        "switches.csv",
        ["name", "vendor", "model", "serial", "management_ip", "site_code", "room_code", "rack_position", "port_count", "firmware_version"],
        switches,
    ),
    (
        "ips.csv",
        ["address", "status", "hostname", "mac", "device_name", "description"],
        ips,
    ),
    (
        "ports.csv",
        ["switch_name", "number", "label", "mode", "native_vlan", "trunk_vlans", "admin_status", "device_name", "connected_ip", "notes"],
        ports,
    ),
    (
        "links.csv",
        ["switch_a", "port_a", "switch_b", "port_b", "link_type", "speed_mbps", "description"],
        links,
    ),
]


README = """# NetForge — sample inventory

Drop this archive into `/import` → "Tout en un (auto)" — the backend detects each
entity from its headers and respects the dependency order.

Scenario: a French SME with two sites (PAR = HQ Paris, RBX = Datacenter Roubaix),
8 rooms, 12 switches (Cisco Catalyst / Nexus + one legacy Aruba 2930F), 17
VLANs, 17 subnets, ~30 devices and ~80 IPs.

Built-in problems for the AI features to surface:

- **suggest-links** : SW-EDGE-PAR-R301:24 carries the hint
  "uplink to SW-CORE-PAR-01 port gi1/0/48" in `notes` but no link is recorded —
  the model should propose it with high confidence.

- **advisor** :
  - SW-CORE-PAR-01 is the only path between every Paris edge and the WAN → SPOF
    on the Paris core.
  - SW-CORE-RBX-02 is patched + powered but has no recorded link → redundancy
    intent never realised, port 1 even has a "reserved redundancy" label.
  - Subnet 10.10.21.0/24 (USERS-IT) is filled to ~50/254 with DHCP leases — a
    real "you'll be tight in N weeks" capacity warning.
  - "switch-old-ipmi" management IP sits on the PAR MGMT subnet (10.10.10.99)
    while the switch lives in Roubaix DC1 → mis-segmentation + naming
    inconsistency vs every other switch's SW-* convention.
  - Aruba 2930F vs Cisco 9500/9300/Nexus fleet → mixed-vendor / mixed-version
    flag.
"""


def main() -> None:
    files: list[tuple[str, bytes]] = [
        (name, csv_bytes(headers, rows)) for name, headers, rows in ENTRIES
    ]
    files.append(("README.md", README.encode("utf-8")))

    ZIP_PATH.unlink(missing_ok=True)
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in files:
            zf.writestr(name, content)

    print(f"wrote {ZIP_PATH} — {ZIP_PATH.stat().st_size} bytes")
    for name, content in files:
        print(f"  {name:20s} {len(content):>6d} bytes")


if __name__ == "__main__":
    main()
