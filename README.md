# SDN Traffic Monitoring and Statistics Collector

## Problem Statement
An SDN-based traffic monitoring system using Mininet and Ryu (OpenFlow 1.3) that collects and displays flow and port statistics from a software-defined network. The controller implements a learning switch with periodic stats polling, generating traffic reports every 10 seconds.

## Topology
Star topology: 1 Open vSwitch (s1) connected to 4 hosts (h1-h4) with 10 Mbps links.

```
h1
|
h2--s1--h3
|
h4
```
## Setup

### Requirements
- Ubuntu 22.04 (VMware)
- Mininet
- Ryu SDN Controller
- Open vSwitch
- iperf3

### Installation
```bash
# Install Mininet
git clone https://github.com/mininet/mininet.git
cd mininet && sudo util/install.sh -n

# Install Ryu in virtualenv
python3 -m venv ~/ryu-env
source ~/ryu-env/bin/activate
pip install eventlet==0.30.2 ryu
```

## Execution

### Terminal 1 — Start Ryu Controller
```bash
source ~/ryu-env/bin/activate
cd ~/sdn-traffic-monitor
ryu-manager --observe-links --ofp-tcp-listen-port 6653 traffic_monitor.py
```

### Terminal 2 — Start Mininet Topology
```bash
sudo python3 topology.py
```

## Controller Logic
- Handles `packet_in` events to learn MAC-to-port mappings
- Installs OpenFlow 1.3 flow rules (match on in_port + eth_dst, action output)
- Table-miss rule sends unmatched packets to controller (priority 0)
- Polls flow and port stats every 10 seconds via OFPFlowStatsRequest and OFPPortStatsRequest
- Appends formatted report to `traffic_report.txt`

## Test Scenarios

### Scenario 1 — Normal Traffic

```
h1 iperf3 -s &
h2 iperf3 -c 10.0.0.1 -t 10

```

Result: ~9.9 Mbits/sec throughput, low byte counts per flow

### Scenario 2 — High Traffic (Multi-flow)

```
h1 iperf3 -s &
h2 iperf3 -c 10.0.0.1 -t 20 &
h3 iperf3 -c 10.0.0.1 -t 20 &
h4 iperf3 -c 10.0.0.1 -t 20 &
```

Result: Port byte counts jump to ~12MB, showing traffic aggregation at h1

## Expected Output
- Controller logs flow/port stats every 10 seconds
- `traffic_report.txt` updated periodically with packet/byte counts per flow and port
- `ovs-ofctl -O OpenFlow13 dump-flows s1` shows installed flow rules

## Proof of Execution
See screenshots below in `/screenshots` folder:
1. `pingall.png` — 0% packet loss (12/12)
2. `dump_flows.png` — OpenFlow rules installed by controller
3. `scenario1_iperf.png` — Normal traffic ~9.9 Mbits/sec
4. `scenario2_flowstats.png` — High traffic, 12MB+ byte counts
5. `report.png` — Periodic traffic report output

## References
- Mininet: http://mininet.org
- Ryu SDN Framework: https://ryu-sdn.org
- OpenFlow 1.3 Spec: https://opennetworking.org/wp-content/uploads/2014/10/openflow-spec-v1.3.0.pdf
- Jim Kurose & Keith Ross, Computer Networks: A Top-Down Approach
