"""
monitor.py
----------
Contains the NetworkMonitor class.
Monitors WAN link health and handles automatic failover and failback.

Supports two modes:
- MOCK mode: simulates ping results, triggers automatic failure after FAIL_AFTER seconds
- REAL mode: uses real system ping via subprocess

Mock mode automatically:
1. Runs normally for FAIL_AFTER seconds (all pings succeed)
2. Simulates wan1_primary link failure (ping starts failing)
3. Triggers failover automatically
4. After RECOVER_AFTER seconds, simulates link recovery
5. Triggers failback automatically
This gives a complete realistic demonstration without any manual intervention.
"""

# ─── Imports ────────────────────────────────────────────────────────────────

import logging
import time
import subprocess
import platform

try:
    from netmiko import ConnectHandler
    from netmiko.exceptions import NetmikoTimeoutException, NetmikoAuthenticationException
    NETMIKO_AVAILABLE = True
except ImportError:
    NETMIKO_AVAILABLE = False


# ─── NetworkMonitor Class ────────────────────────────────────────────────────

class NetworkMonitor:
    """
    Monitors WAN link health for all routers.
    Handles automatic failover and failback.

    Parameters:
        devices       (dict): Full content of devices.json
        mock          (bool): If True, simulate ping and SSH
        interval      (int):  Seconds between monitoring cycles
        fail_after    (int):  Seconds before simulating link failure (mock only)
        recover_after (int):  Seconds after failure before simulating recovery (mock only)
    """

    def __init__(self, devices, mock=True, interval=10, fail_after=30, recover_after=30):
        self.routers       = devices["Routers"]
        self.mock          = mock
        self.interval      = interval
        self.fail_after    = fail_after    # seconds until mock failure is triggered
        self.recover_after = recover_after # seconds until mock recovery is triggered
        self.start_time    = None          # set when monitoring starts
        self.failed_links  = set()         # tracks which links are currently simulated as down

        # Initialize state — all routes start on primary
        self.state = {}
        for router in self.routers:
            self.state[router["hostname"]] = {}
            for route in router["routes"]:
                self.state[router["hostname"]][route["destination"]] = "primary"

        logging.info(f"NetworkMonitor initialized in {'MOCK' if mock else 'REAL'} mode.")
        logging.info(f"Monitoring interval: {interval}s | "
                     f"Mock failure after: {fail_after}s | "
                     f"Mock recovery after: {fail_after + recover_after}s")


    def _mock_ping(self, ip, role):
        """
        Simulates ping result based on elapsed time.

        Timeline:
        0 ────────── fail_after ────────── fail_after+recover_after ──────────
        [  all up  ] [  wan1_primary DOWN  ] [  all up again (recovered)  ]

        Only wan1_primary links are simulated as failing.
        All other links always return True (up).
        """
        elapsed = time.time() - self.start_time

        # Only simulate failure for wan1_primary links
        if "wan1_primary" in role or "wan1" in role:
            if self.fail_after < elapsed < (self.fail_after + self.recover_after):
                # We are in the failure window
                if ip not in self.failed_links:
                    self.failed_links.add(ip)
                    logging.warning(f"[MOCK] Simulating link failure on {ip} ({role})")
                return False  # ping fails
            else:
                # Outside failure window — link is up
                if ip in self.failed_links:
                    self.failed_links.discard(ip)
                    logging.info(f"[MOCK] Link {ip} ({role}) has recovered.")
                return True   # ping succeeds

        # All other links always up
        return True


    def _ping(self, ip, role=""):
        """
        Pings an IP address and returns True/False.
        In mock mode: uses _mock_ping() based on elapsed time.
        In real mode: runs actual system ping via subprocess.
        """
        if self.mock:
            time.sleep(0.2)  # simulates ping round-trip time
            return self._mock_ping(ip, role)

        # ── Real mode ────────────────────────────────────────────────────
        os_type = platform.system()
        if os_type == "Windows":
            command = ["ping", "-n", "1", "-w", "1000", ip]
        else:
            command = ["ping", "-c", "1", "-W", "1", ip]

        result = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return result.returncode == 0


    def _connect_to_router(self, router):
        """
        Opens SSH connection to a router for route updates.
        In mock mode: returns a placeholder string.
        In real mode: uses Netmiko ConnectHandler.
        """
        hostname = router["hostname"]

        if self.mock:
            time.sleep(0.5)  # simulates SSH connection time
            logging.info(f"[MOCK] SSH connection established to {hostname} for route update.")
            return "MOCK_CONNECTION"

        if not NETMIKO_AVAILABLE:
            logging.error("Netmiko not installed.")
            return None

        device_params = {
            "device_type": router["device_type"],
            "host":        router["mngmt_ip"],
            "username":    router["username"],
            "password":    router["password"],
            "timeout":     10
        }

        try:
            connection = ConnectHandler(**device_params)
            logging.info(f"[REAL] SSH connection established to {hostname}.")
            return connection
        except NetmikoTimeoutException:
            logging.error(f"[{hostname}] Connection TIMEOUT during route update.")
            return None
        except NetmikoAuthenticationException:
            logging.error(f"[{hostname}] Authentication FAILED during route update.")
            return None
        except Exception as e:
            logging.error(f"[{hostname}] Unexpected error: {e}")
            return None


    def _send_route_commands(self, connection, router, commands):
        """
        Sends route update commands to the router.
        In mock mode: logs each command with delay.
        In real mode: uses Netmiko send_config_set().
        """
        hostname = router["hostname"]

        if self.mock:
            logging.info(f"[MOCK] {hostname}# configure terminal")
            for command in commands:
                time.sleep(0.1)
                logging.info(f"[MOCK] {hostname}(config)# {command}")
            logging.info(f"[MOCK] {hostname}(config)# end")
            return "[MOCK] Route update applied successfully."

        return connection.send_config_set(commands)


    def _push_backup_route(self, router, route):
        """
        FAILOVER: Removes primary route and pushes backup route.
        Called when primary link is detected as down.
        """
        hostname    = router["hostname"]
        destination = route["destination"]
        mask        = route["mask"]
        primary_hop = route["next_hop"][0]
        backup_hop  = route["next_hop"][1]

        logging.warning(f"[{hostname}] *** FAILOVER INITIATED ***")
        logging.warning(f"[{hostname}] Destination: {destination}/{mask}")
        logging.warning(f"[{hostname}] Removing primary route via {primary_hop}")
        logging.warning(f"[{hostname}] Adding backup route via {backup_hop}")

        connection = self._connect_to_router(router)
        if connection is None:
            return

        try:
            commands = [
                f"no ip route {destination} {mask} {primary_hop}",
                f"ip route {destination} {mask} {backup_hop}"
            ]
            output = self._send_route_commands(connection, router, commands)
            logging.warning(f"[{hostname}] *** FAILOVER COMPLETE *** Traffic rerouted via {backup_hop}")

        except Exception as e:
            logging.error(f"[{hostname}] Failover failed: {e}")

        finally:
            if not self.mock and connection:
                connection.disconnect()
            elif self.mock:
                time.sleep(0.2)
                logging.info(f"[MOCK] SSH session closed after failover.")


    def _restore_primary_route(self, router, route):
        """
        FAILBACK: Removes backup route and restores primary route.
        Called when primary link recovers.
        """
        hostname    = router["hostname"]
        destination = route["destination"]
        mask        = route["mask"]
        primary_hop = route["next_hop"][0]
        backup_hop  = route["next_hop"][1]

        logging.info(f"[{hostname}] *** FAILBACK INITIATED ***")
        logging.info(f"[{hostname}] Destination: {destination}/{mask}")
        logging.info(f"[{hostname}] Removing backup route via {backup_hop}")
        logging.info(f"[{hostname}] Restoring primary route via {primary_hop}")

        connection = self._connect_to_router(router)
        if connection is None:
            return

        try:
            commands = [
                f"no ip route {destination} {mask} {backup_hop}",
                f"ip route {destination} {mask} {primary_hop}"
            ]
            output = self._send_route_commands(connection, router, commands)
            logging.info(f"[{hostname}] *** FAILBACK COMPLETE *** Traffic restored via {primary_hop}")

        except Exception as e:
            logging.error(f"[{hostname}] Failback failed: {e}")

        finally:
            if not self.mock and connection:
                connection.disconnect()
            elif self.mock:
                time.sleep(0.2)
                logging.info(f"[MOCK] SSH session closed after failback.")


    def _check_router(self, router):
        """
        Checks all primary WAN links for one router.
        Triggers failover or failback based on ping result and current state.

        Decision table:
        | Ping  | State   | Action   |
        |-------|---------|----------|
        | Pass  | primary | nothing  |
        | Pass  | backup  | failback |
        | Fail  | primary | failover |
        | Fail  | backup  | nothing  |
        """
        hostname = router["hostname"]

        for interface in router["interfaces"]:
            # Only check primary WAN interfaces
            if "primary" not in interface["role"]:
                continue
            # Skip LAN trunk (no peer IP)
            if interface["pair"] is None:
                continue

            peer_ip = interface["pair"]
            role    = interface["role"]

            # Find the route this interface serves
            # Match by checking if peer_ip is next_hop[0] of any route
            matching_route = None
            for route in router["routes"]:
                if route["next_hop"][0] == peer_ip:
                    matching_route = route
                    break

            if matching_route is None:
                continue

            destination   = matching_route["destination"]
            current_state = self.state[hostname][destination]

            # ── Ping the peer IP ──────────────────────────────────────────
            logging.info(f"[{hostname}] Pinging {peer_ip} ({role})...")
            ping_ok = self._ping(peer_ip, role)

            # ── Decision logic ────────────────────────────────────────────
            if ping_ok and current_state == "primary":
                logging.info(f"[{hostname}] Link {role} UP | Route to {destination}: PRIMARY active.")

            elif ping_ok and current_state == "backup":
                logging.info(f"[{hostname}] Link {role} RECOVERED | Initiating FAILBACK...")
                self._restore_primary_route(router, matching_route)
                self.state[hostname][destination] = "primary"

            elif not ping_ok and current_state == "primary":
                logging.warning(f"[{hostname}] Link {role} DOWN | Initiating FAILOVER...")
                self._push_backup_route(router, matching_route)
                self.state[hostname][destination] = "backup"

            elif not ping_ok and current_state == "backup":
                logging.warning(f"[{hostname}] Link {role} still DOWN | Backup route already active.")


    def start(self):
        """
        Starts the monitoring loop.
        Runs continuously until user presses Ctrl+C.
        """
        self.start_time = time.time()

        logging.info("=" * 60)
        logging.info("Network monitoring STARTED. Press Ctrl+C to stop.")
        if self.mock:
            logging.info(f"[MOCK] Link failure will be simulated at t={self.fail_after}s")
            logging.info(f"[MOCK] Link recovery will be simulated at t={self.fail_after + self.recover_after}s")
        logging.info("=" * 60)

        cycle = 1
        try:
            while True:
                elapsed = int(time.time() - self.start_time)
                logging.info(f"\n--- Monitoring Cycle #{cycle} | Elapsed: {elapsed}s ---")

                for router in self.routers:
                    self._check_router(router)

                logging.info(f"--- Cycle #{cycle} complete. Next check in {self.interval}s ---")
                cycle += 1
                time.sleep(self.interval)

        except KeyboardInterrupt:
            logging.info("\nMonitoring stopped by user (Ctrl+C).")
            logging.info("=" * 60)
