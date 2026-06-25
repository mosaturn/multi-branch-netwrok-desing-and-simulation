"""
main.py
-------
Entry point of the TechLink Solutions Network Automation System.

Orchestrates:
1. Loading devices.json
2. Configuring all routers and switches
3. Starting the monitoring loop

Configuration:
    Set MOCK_MODE = True  for simulation (no real devices needed)
    Set MOCK_MODE = False for real SSH connections via Netmiko
"""

# ─── UTF-8 Fix for Windows Terminal ─────────────────────────────────────────
# Windows terminal uses cp1252 encoding by default which cannot display
# Unicode characters (arrows, checkmarks, etc.) used in log messages.
# This forces Python to use UTF-8 for all terminal output.

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# ─── Imports ─────────────────────────────────────────────────────────────────

import json
import logging
from configure import NetworkConfigurator
from monitor import NetworkMonitor

# ─── Configuration ───────────────────────────────────────────────────────────

MOCK_MODE         = True  # True = simulation mode | False = real SSH mode
MONITOR_INTERVAL  = 10    # seconds between monitoring cycles
FAIL_AFTER        = 30    # seconds before mock link failure is triggered
RECOVER_AFTER     = 30    # seconds after failure before mock recovery

# ─── Logging Setup ──────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("network_log.txt", mode="w", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)   # uses the UTF-8 wrapped stdout
    ]
)

# ─── Load Devices ────────────────────────────────────────────────────────────

def load_devices(filepath="config.json"):
    """Reads config.json and returns content as Python dictionary."""
    try:
        with open(filepath, "r") as f:
            devices = json.load(f)
        logging.info(f"config.json loaded successfully. "
                     f"Routers: {len(devices['Routers'])} | "
                     f"Switches: {len(devices['Switches'])}")
        return devices
    except FileNotFoundError:
        logging.error(f"config.json not found.")
        exit(1)
    except json.JSONDecodeError as e:
        logging.error(f"config.json is invalid JSON: {e}")
        exit(1)


# ─── Configure Routers ───────────────────────────────────────────────────────

def configure_routers(devices):
    """Applies initial configuration to all routers."""
    logging.info("=" * 60)
    logging.info("PHASE 1: Router Configuration")
    logging.info("=" * 60)

    for router in devices["Routers"]:
        logging.info(f"\nConfiguring {router['hostname']}...")
        cfg = NetworkConfigurator(router, mock=MOCK_MODE)

        if not cfg.connect():
            logging.error(f"Skipping {router['hostname']} - connection failed.")
            continue

        cfg.configure_hostname()

        for interface in router["interfaces"]:
            cfg.configure_interface(interface)

        for route in router["routes"]:
            cfg.configure_static_route(route)

        cfg.verify()
        cfg.disconnect()
        logging.info(f"{router['hostname']} [DONE] Configuration complete.")


# ─── Configure Switches ──────────────────────────────────────────────────────

def configure_switches(devices):
    """Applies initial configuration to all switches."""
    logging.info("=" * 60)
    logging.info("PHASE 2: Switch Configuration")
    logging.info("=" * 60)

    for switch in devices["Switches"]:
        logging.info(f"\nConfiguring {switch['hostname']}...")
        cfg = NetworkConfigurator(switch, mock=MOCK_MODE)

        if not cfg.connect():
            logging.error(f"Skipping {switch['hostname']} - connection failed.")
            continue

        cfg.configure_hostname()
        cfg.enable_ip_routing()

        for vlan in switch["vlans"]:
            cfg.configure_vlan(vlan)

        for svi in switch["SVIs"]:
            cfg.configure_svi(svi)

        cfg.configure_uplink(switch["uplink"])
        cfg.configure_default_route(switch["default_route"])

        # Configure DHCP pools (one per VLAN)
        for pool in switch["dhcp_pools"]:
            cfg.configure_dhcp(pool)

        cfg.verify()
        cfg.disconnect()
        logging.info(f"{switch['hostname']} [DONE] Configuration complete.")


# ─── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":

    logging.info("=" * 60)
    logging.info("TechLink Solutions - Network Automation System")
    logging.info(f"Mode: {'SIMULATION (MOCK)' if MOCK_MODE else 'REAL SSH'}")
    logging.info("=" * 60)

    # Step 1: Load devices
    devices = load_devices("config.json")

    # Step 2: Configure routers
    configure_routers(devices)

    # Step 3: Configure switches
    configure_switches(devices)

    # Step 4: Start monitoring
    logging.info("\n" + "=" * 60)
    logging.info("PHASE 3: Network Monitoring & Failover")
    logging.info("=" * 60)

    monitor = NetworkMonitor(
        devices,
        mock          = MOCK_MODE,
        interval      = MONITOR_INTERVAL,
        fail_after    = FAIL_AFTER,
        recover_after = RECOVER_AFTER
    )
    monitor.start()
