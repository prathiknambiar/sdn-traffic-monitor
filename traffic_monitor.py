#!/usr/bin/env python3
"""
SDN Traffic Monitoring and Statistics Collector
Ryu Controller - OpenFlow 1.3
"""
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, DEAD_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types
from ryu.lib import hub
import datetime
import os

STATS_INTERVAL = 10  # poll every 10 seconds
REPORT_FILE = os.path.expanduser("~/sdn-traffic-monitor/traffic_report.txt")

class TrafficMonitor(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mac_to_port = {}          # {dpid: {mac: port}}
        self.datapaths = {}            # {dpid: datapath}
        self.flow_stats = {}           # {dpid: [flow_stats]}
        self.port_stats = {}           # {dpid: [port_stats]}
        self.monitor_thread = hub.spawn(self._monitor_loop)
        self.report_lines = []

    # Switch handshake: install table-miss flow
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto  = datapath.ofproto
        parser   = datapath.ofproto_parser
        self.logger.info("Switch connected: dpid=%s", datapath.id)

        # Table-miss: send unmatched packets to controller
        match  = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self._add_flow(datapath, 0, match, actions)

    # Track datapaths (switches) coming and going
    @set_ev_cls(ofp_event.EventOFPStateChange,
                [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def state_change_handler(self, ev):
        datapath = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            self.datapaths[datapath.id] = datapath
            self.logger.info("Registered datapath: %s", datapath.id)
        elif ev.state == DEAD_DISPATCHER:
            self.datapaths.pop(datapath.id, None)
            self.logger.info("Unregistered datapath: %s", datapath.id)

    # Packet-in: learning switch logic + install flow rules
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg      = ev.msg
        datapath = msg.datapath
        ofproto  = datapath.ofproto
        parser   = datapath.ofproto_parser
        in_port  = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        dst = eth.dst
        src = eth.src
        dpid = datapath.id

        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][src] = in_port
        self.logger.debug("Learned %s → port %s on dpid %s", src, in_port, dpid)

        out_port = self.mac_to_port[dpid].get(dst, ofproto.OFPP_FLOOD)

        actions = [parser.OFPActionOutput(out_port)]

        # Install a flow rule if we know the destination
        if out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
            if msg.buffer_id != ofproto.OFP_NO_BUFFER:
                self._add_flow(datapath, 1, match, actions,
                               buffer_id=msg.buffer_id)
                return
            else:
                self._add_flow(datapath, 1, match, actions)

        data = msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
        out  = parser.OFPPacketOut(datapath=datapath,
                                   buffer_id=msg.buffer_id,
                                   in_port=in_port,
                                   actions=actions,
                                   data=data)
        datapath.send_msg(out)

    # Helper: install a flow rule
    def _add_flow(self, datapath, priority, match, actions,
                  buffer_id=None, idle_timeout=300, hard_timeout=0):
        ofproto = datapath.ofproto
        parser  = datapath.ofproto_parser
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        kwargs = dict(datapath=datapath, priority=priority,
                      match=match, instructions=inst,
                      idle_timeout=idle_timeout, hard_timeout=hard_timeout)
        if buffer_id and buffer_id != ofproto.OFP_NO_BUFFER:
            kwargs['buffer_id'] = buffer_id
        mod = parser.OFPFlowMod(**kwargs)
        datapath.send_msg(mod)

    # Monitoring loop: request stats every STATS_INTERVAL seconds
    def _monitor_loop(self):
        while True:
            for dp in list(self.datapaths.values()):
                self._request_flow_stats(dp)
                self._request_port_stats(dp)
            hub.sleep(STATS_INTERVAL)

    def _request_flow_stats(self, datapath):
        parser = datapath.ofproto_parser
        req = parser.OFPFlowStatsRequest(datapath)
        datapath.send_msg(req)

    def _request_port_stats(self, datapath):
        ofproto = datapath.ofproto
        parser  = datapath.ofproto_parser
        req = parser.OFPPortStatsRequest(datapath, 0, ofproto.OFPP_ANY)
        datapath.send_msg(req)

    # Handle flow stats reply
    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def flow_stats_reply_handler(self, ev):
        dpid = ev.msg.datapath.id
        self.flow_stats[dpid] = ev.msg.body
        self.logger.info("\n=== Flow Stats (dpid=%s) ===", dpid)
        for stat in sorted(ev.msg.body,
                           key=lambda s: (s.match.get('in_port', 0))):
            self.logger.info(
                "  in_port=%s eth_dst=%s | packets=%d bytes=%d | "
                "idle=%ds priority=%d",
                stat.match.get('in_port', '*'),
                stat.match.get('eth_dst', '*'),
                stat.packet_count,
                stat.byte_count,
                stat.idle_timeout,
                stat.priority)
        self._write_report()

    # Handle port stats reply
    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_reply_handler(self, ev):
        dpid = ev.msg.datapath.id
        self.port_stats[dpid] = ev.msg.body
        self.logger.info("\n=== Port Stats (dpid=%s) ===", dpid)
        for stat in ev.msg.body:
            self.logger.info(
                "  port=%s | rx_pkts=%d tx_pkts=%d "
                "rx_bytes=%d tx_bytes=%d rx_errors=%d tx_errors=%d",
                stat.port_no,
                stat.rx_packets, stat.tx_packets,
                stat.rx_bytes,   stat.tx_bytes,
                stat.rx_errors,  stat.tx_errors)

    # Generate simple text report
    def _write_report(self):
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = [f"\n{'='*60}",
                 f"  SDN Traffic Report — {ts}",
                 f"{'='*60}"]

        for dpid, flows in self.flow_stats.items():
            lines.append(f"\n[Switch dpid={dpid}] Flow Table:")
            lines.append(f"  {'in_port':<10} {'eth_dst':<20} {'packets':>10} {'bytes':>12}")
            lines.append(f"  {'-'*55}")
            for s in sorted(flows, key=lambda x: x.packet_count, reverse=True):
                lines.append(
                    f"  {str(s.match.get('in_port','*')):<10} "
                    f"{str(s.match.get('eth_dst','*')):<20} "
                    f"{s.packet_count:>10} {s.byte_count:>12}")

        for dpid, ports in self.port_stats.items():
            lines.append(f"\n[Switch dpid={dpid}] Port Statistics:")
            lines.append(f"  {'port':<6} {'rx_pkts':>10} {'tx_pkts':>10} {'rx_bytes':>12} {'tx_bytes':>12}")
            lines.append(f"  {'-'*55}")
            for s in ports:
                lines.append(
                    f"  {s.port_no:<6} {s.rx_packets:>10} {s.tx_packets:>10} "
                    f"{s.rx_bytes:>12} {s.tx_bytes:>12}")

        with open(REPORT_FILE, 'a') as f:
            f.write('\n'.join(lines) + '\n')
        self.logger.info("Report appended → %s", REPORT_FILE)
