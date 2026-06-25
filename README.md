# TechLink Solutions — Multi-Branch Network Automation

A network design and Python automation project for a fictional multi-branch company (TechLink Solutions) with sites in Cairo (HQ), Alexandria, and Giza.

The project covers full network design including IP addressing, VLAN segmentation, inter-VLAN routing via SVIs, redundant WAN links, and static routing. A Python automation system handles initial device configuration via SSH using Netmiko, continuous WAN link monitoring, and automatic failover and failback without manual intervention.

## Files

| File | Description |
|---|---|
| `main.py` | Entry point — orchestrates configuration and monitoring |
| `configure.py` | NetworkConfigurator class — pushes initial config to all devices |
| `monitor.py` | NetworkMonitor class — monitors links, triggers failover/failback |
| `config.json` | Device data — IPs, interfaces, routes, VLANs, DHCP pools |
| `day0_configs/` | Manual bootstrap configs for all 6 devices |
| `docs/` | Network design document and topology diagram |
| `sample_output/` | Sample log showing configuration and failover events |

## How to Run

```bash
pip install netmiko
python main.py
```

Set `MOCK_MODE = True` in `main.py` for simulation. Set to `False` for real SSH connections.
