#!/usr/bin/env python3
from mininet.net import Mininet
from mininet.node import RemoteController
from mininet.topo import Topo
from mininet.log import setLogLevel
from mininet.cli import CLI
from mininet.link import TCLink

class StarTopo(Topo):
    """
    Star topology: 1 switch, 4 hosts
        h1
        |
    h2--s1--h3
        |
        h4
    """
    def build(self):
        s1 = self.addSwitch('s1')
        for i in range(1, 5):
            h = self.addHost(f'h{i}',
                             ip=f'10.0.0.{i}/24',
                             mac=f'00:00:00:00:00:0{i}')
            self.addLink(h, s1, cls=TCLink, bw=10)  # 10 Mbps links

def run():
    setLogLevel('info')
    topo = StarTopo()
    net = Mininet(topo=topo,
                  controller=RemoteController('c0', ip='127.0.0.1', port=6653),
                  link=TCLink,
                  autoSetMacs=True)
    net.start()

    # Static ARP entries to avoid ARP flooding issues
    hosts = net.hosts
    for h in hosts:
        for other in hosts:
            if h != other:
                h.cmd(f'arp -s {other.IP()} {other.MAC()}')

    print("\n*** Hosts:")
    for h in net.hosts:
        print(f"  {h.name}: {h.IP()}")
    print("\n*** Running initial pingall...")
    net.pingAll()
    CLI(net)
    net.stop()

if __name__ == '__main__':
    run()

