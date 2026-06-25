"""
configure.py
------------
Contains the NetworkConfigurator class.
Responsible for connecting to a network device and pushing initial configuration.

Supports two modes:
- MOCK mode (mock=True):  simulates SSH connection and command execution locally
- REAL mode (mock=False): connects to actual devices via SSH using Netmiko

In mock mode, no real connection is made. Commands are logged as if sent to a real device.
This satisfies the assignment requirement of "mock devices allowed".
"""

# ─── Imports ────────────────────────────────────────────────────────────────

import logging
import time

try:
    from netmiko import ConnectHandler
    from netmiko.exceptions import NetmikoTimeoutException, NetmikoAuthenticationException
    NETMIKO_AVAILABLE = True
except ImportError:
    # If netmiko is not installed, mock mode is the only option
    NETMIKO_AVAILABLE = False
    logging.warning("Netmiko not installed. Running in MOCK mode only.")


# ─── Simulated IOS Output ────────────────────────────────────────────────────
# These are realistic Cisco IOS responses used in mock mode
# to make the log output look like real device responses.

MOCK_SHOW_IP_INT_BRIEF = """
Interface              IP-Address      OK? Method Status                Protocol
GigabitEthernet0/0    {g00}           YES manual up                    up
GigabitEthernet0/1    {g01}           YES manual up                    up
GigabitEthernet0/2    {g02}           YES manual up                    up
GigabitEthernet0/3    unassigned      YES unset  administratively down down
Vlan1                  unassigned      YES unset  administratively down down
"""

MOCK_CONFIG_RESPONSE = """
Enter configuration commands, one per line.  End with CNTL/Z.
{hostname}(config)#{last_command}
{hostname}(config)#end
{hostname}#
"""


# ─── NetworkConfigurator Class ───────────────────────────────────────────────

class NetworkConfigurator:
    """
    Handles SSH connection and configuration for a single network device.

    Parameters:
        device (dict): One device entry from devices.json
        mock   (bool): If True, simulate connection. If False, use real SSH.
    """

    def __init__(self, device, mock=True):
        self.device     = device
        self.mock       = mock
        self.connection = None
        logging.info(f"[{'MOCK' if mock else 'REAL'}] Initialized configurator for: {device['hostname']}")


    def connect(self):
        """
        Opens SSH connection to the device.
        In mock mode: simulates connection with a small delay.
        In real mode: uses Netmiko ConnectHandler.
        """
        hostname = self.device["hostname"]

        if self.mock:
            # Simulate SSH handshake delay
            logging.info(f"[MOCK] Initiating SSH connection to {hostname} at {self.device['mngmt_ip']}...")
            time.sleep(0.5)  # simulates TCP handshake + SSH negotiation time
            logging.info(f"[MOCK] SSH connection established to {hostname}.")
            logging.info(f"[MOCK] {hostname}> enable")
            logging.info(f"[MOCK] {hostname}#")
            self.connection = "MOCK_CONNECTION"  # placeholder so other methods know we're connected
            return True

        # ── Real mode ────────────────────────────────────────────────────
        if not NETMIKO_AVAILABLE:
            logging.error("Netmiko not installed. Cannot use real mode.")
            return False

        device_params = {
            "device_type": self.device["device_type"],
            "host":        self.device["mngmt_ip"],
            "username":    self.device["username"],
            "password":    self.device["password"],
            "timeout":     10
        }

        try:
            self.connection = ConnectHandler(**device_params)
            logging.info(f"[REAL] SSH connection established to {hostname}.")
            return True

        except NetmikoTimeoutException:
            logging.error(f"[REAL] [{hostname}] Connection TIMEOUT - device unreachable at {self.device['mngmt_ip']}")
            return False

        except NetmikoAuthenticationException:
            logging.error(f"[REAL] [{hostname}] Authentication FAILED - check username/password")
            return False

        except Exception as e:
            logging.error(f"[REAL] [{hostname}] Unexpected connection error: {e}")
            return False


    def _send_config(self, commands):
        """
        PRIVATE helper — sends configuration commands to the device.
        In mock mode: logs each command with a small delay.
        In real mode: uses Netmiko send_config_set().
        """
        hostname = self.device["hostname"]

        if self.connection is None:
            logging.error(f"[{hostname}] Cannot send config - no active connection.")
            return None

        if self.mock:
            # Simulate entering config mode
            logging.info(f"[MOCK] {hostname}# configure terminal")
            logging.info(f"[MOCK] {hostname}(config)#")
            output_lines = []

            for command in commands:
                time.sleep(0.1)  # simulates command execution time
                logging.info(f"[MOCK] {hostname}(config)# {command}")
                output_lines.append(f"{hostname}(config)# {command}")

            logging.info(f"[MOCK] {hostname}(config)# end")
            logging.info(f"[MOCK] {hostname}#")
            return "\n".join(output_lines)

        # ── Real mode ────────────────────────────────────────────────────
        output = self.connection.send_config_set(commands)
        return output


    def configure_hostname(self):
        """Sets the device hostname."""
        hostname = self.device["hostname"]
        commands = [f"hostname {hostname}"]
        output   = self._send_config(commands)
        logging.info(f"[{hostname}] Hostname configured.")
        return output


    def configure_interface(self, interface):
        """
        Configures a single interface with IP, description, and activates it.
        Skips interfaces with no IP (shouldn't happen in our JSON but safe to check).
        """
        hostname = self.device["hostname"]
        name     = interface["name"]
        ip       = interface["ip"]
        mask     = interface["mask"]
        role     = interface["role"]

        commands = [
            f"interface {name}",
            f"description {role}",
            f"ip address {ip} {mask}",
            "no shutdown"
        ]

        output = self._send_config(commands)
        logging.info(f"[{hostname}] Interface {name} ({role}) configured → IP: {ip}/{mask}")
        return output


    def configure_static_route(self, route):
        """
        Configures PRIMARY static route only (next_hop[0]).
        Backup route (next_hop[1]) is pushed by monitor.py during failover.
        """
        hostname    = self.device["hostname"]
        destination = route["destination"]
        mask        = route["mask"]
        primary_hop = route["next_hop"][0]

        commands = [f"ip route {destination} {mask} {primary_hop}"]
        output   = self._send_config(commands)
        logging.info(f"[{hostname}] Primary route: {destination}/{mask} via {primary_hop}")
        return output


    def configure_vlan(self, vlan):
        """Creates a VLAN entry on the switch VLAN database."""
        hostname  = self.device["hostname"]
        vlan_id   = vlan["id"]
        vlan_name = vlan["name"]

        commands = [
            f"vlan {vlan_id}",
            f"name {vlan_name}"
        ]

        output = self._send_config(commands)
        logging.info(f"[{hostname}] VLAN {vlan_id} ({vlan_name}) created.")
        return output


    def configure_svi(self, svi):
        """
        Configures Switch Virtual Interface (SVI).
        This is the Layer 3 gateway IP for each VLAN.
        PCs use this IP as their default gateway.
        """
        hostname = self.device["hostname"]
        vlan_id  = svi["vlan"]
        ip       = svi["ip"]
        mask     = svi["mask"]

        commands = [
            f"interface vlan {vlan_id}",
            f"ip address {ip} {mask}",
            "no shutdown"
        ]

        output = self._send_config(commands)
        logging.info(f"[{hostname}] SVI VLAN {vlan_id} configured → IP: {ip}")
        return output


    def configure_uplink(self, uplink):
        """
        Configures the switch uplink port toward the router as a routed port.
        'no switchport' converts it from Layer 2 to Layer 3 mode.
        """
        hostname = self.device["hostname"]
        name     = uplink["name"]
        ip       = uplink["ip"]
        mask     = uplink["mask"]

        commands = [
            f"interface {name}",
            "no switchport",
            f"ip address {ip} {mask}",
            "no shutdown"
        ]

        output = self._send_config(commands)
        logging.info(f"[{hostname}] Uplink {name} configured as routed port → IP: {ip}")
        return output


    def configure_default_route(self, gateway_ip):
        """
        Configures default route on switch.
        All unknown traffic is forwarded to the router.
        """
        hostname = self.device["hostname"]
        commands = [f"ip route 0.0.0.0 0.0.0.0 {gateway_ip}"]
        output   = self._send_config(commands)
        logging.info(f"[{hostname}] Default route configured → via {gateway_ip}")
        return output


    def configure_dhcp(self, pool):
        """
        Configures a DHCP pool on the L3 switch for a specific VLAN.
        Called once per VLAN per switch.

        Parameters:
            pool (dict): One dhcp_pools entry from config.json.
                         Keys: pool_name, network, mask, gateway, dns,
                               excluded_start, excluded_end

        IOS commands equivalent:
            ip dhcp excluded-address 10.1.10.1 10.1.10.10
            ip dhcp pool HQ_VLAN10_Management
             network 10.1.10.0 255.255.255.0
             default-router 10.1.10.1
             dns-server 8.8.8.8

        The excluded-address command reserves a range of IPs that DHCP
        will never assign — used to protect gateway and device IPs.
        DHCP assigns from the first non-excluded address (.11 in this case).
        """
        hostname       = self.device["hostname"]
        pool_name      = pool["pool_name"]
        network        = pool["network"]
        mask           = pool["mask"]
        gateway        = pool["gateway"]
        dns            = pool["dns"]
        excluded_start = pool["excluded_start"]
        excluded_end   = pool["excluded_end"]

        commands = [
            # Reserve gateway and device IPs from DHCP assignment
            f"ip dhcp excluded-address {excluded_start} {excluded_end}",
            # Create the DHCP pool
            f"ip dhcp pool {pool_name}",
            f" network {network} {mask}",      # subnet to assign from
            f" default-router {gateway}",       # gateway PCs will receive
            f" dns-server {dns}",               # DNS server PCs will receive
            f" lease 7"                         # IP lease duration in days
        ]

        output = self._send_config(commands)
        logging.info(f"[{hostname}] DHCP pool {pool_name} configured "
                     f"| Network: {network}/{mask} "
                     f"| Gateway: {gateway} "
                     f"| Excluded: {excluded_start}-{excluded_end}")
        return output


    def enable_ip_routing(self):
        """
        Enables IP routing on L3 switch.
        Required for inter-VLAN routing via SVIs.
        Without this command, the switch won't route between VLANs
        even if SVIs are configured.
        """
        hostname = self.device["hostname"]
        commands = ["ip routing"]
        output   = self._send_config(commands)
        logging.info(f"[{hostname}] IP routing enabled.")
        return output


    def verify(self):
        """
        Runs 'show ip interface brief' and logs the output.
        In mock mode: returns a realistic simulated IOS table.
        In real mode: returns actual device output.
        """
        hostname = self.device["hostname"]

        if self.connection is None:
            logging.error(f"[{hostname}] Cannot verify - no active connection.")
            return None

        if self.mock:
            # Build a realistic looking interface table from our JSON data
            time.sleep(0.3)  # simulates command execution
            lines = [
                f"\n[MOCK] {hostname}# show ip interface brief",
                f"Interface              IP-Address      OK? Method Status      Protocol"
            ]
            for iface in self.device.get("interfaces", []):
                lines.append(
                    f"GigabitEthernet{iface['name'][1:]}    "
                    f"{iface['ip']:<15} YES manual up          up"
                )
            # Add SVIs if this is a switch
            for svi in self.device.get("SVIs", []):
                lines.append(
                    f"Vlan{svi['vlan']}                  "
                    f"{svi['ip']:<15} YES manual up          up"
                )
            output = "\n".join(lines)
            logging.info(output)
            return output

        # ── Real mode ────────────────────────────────────────────────────
        output = self.connection.send_command("show ip interface brief")
        logging.info(f"[{hostname}] Verification:\n{output}")
        return output


    def disconnect(self):
        """Closes the SSH connection cleanly."""
        hostname = self.device["hostname"]
        if self.connection:
            if not self.mock:
                self.connection.disconnect()
            time.sleep(0.2)  # simulates graceful session teardown
            logging.info(f"[{'MOCK' if self.mock else 'REAL'}] SSH session closed for {hostname}.")
            self.connection = None
