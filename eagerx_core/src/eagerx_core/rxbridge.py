#!/usr/bin/env python3

import rospy
from std_msgs.msg import UInt64

# Rx imports
import eagerx_core.rxmessage_broker
import eagerx_core.rxoperators
import eagerx_core.rxpipelines
from eagerx_core.utils.utils import get_attribute_from_module, initialize_converter, get_ROS_log_level, get_param_with_blocking
from eagerx_core.utils.node_utils import wait_for_node_initialization
from eagerx_core.baseconverter import IdentityConverter
from eagerx_core.constants import log_levels_ROS

# Other imports
from threading import Condition


class RxBridge(object):
    def __init__(self, name, message_broker):
        self.name = name
        self.ns = '/'.join(name.split('/')[:2])
        self.mb = message_broker
        self.initialized = False

        # Prepare input & output topics
        dt, inputs, outputs, node_names, target_addresses, self.bridge = self._prepare_io_topics(self.name)

        # Initialize reactive pipeline
        rx_objects = eagerx_core.rxpipelines.init_bridge(self.ns, dt, self.bridge, inputs, outputs, node_names, target_addresses, self.mb)
        self.mb.add_rx_objects(node_name=name, node=self, **rx_objects)
        self.mb.add_rx_objects(node_name=name + '/dynamically_registered', node=self)
        self.mb.connect_io()
        self.cond_reg = Condition()

        # Prepare closing routine
        rospy.on_shutdown(self._close)

    def node_initialized(self):
        with self.cond_reg:
            # Wait for all nodes to be initialized
            wait_for_node_initialization(self.bridge.is_initialized)

            # Notify env that node is initialized
            if not self.initialized:
                init_pub = rospy.Publisher(self.name + '/initialized', UInt64, queue_size=0, latch=True)
                init_pub.publish(UInt64(data=1))
                rospy.loginfo('Node "%s" initialized.' % self.name)
                self.initialized = True

    def _prepare_io_topics(self, name):
        params = get_param_with_blocking(name)
        node_names = params['node_names']
        target_addresses = params['target_addresses']
        rate = params['rate']
        dt = 1 / rate

        # Get node
        node_cls = get_attribute_from_module(params['module'], params['node_type'])
        node = node_cls(ns=self.ns, message_broker=self.mb, **params)

        # Prepare input topics
        for i in params['inputs']:
            i['msg_type'] = get_attribute_from_module(i['msg_module'], i['msg_type'])
            if 'converter' in i and isinstance(i['converter'], dict):
                i['converter'] = initialize_converter(i['converter'])
            elif 'converter' not in i:
                i['converter'] = IdentityConverter()

        # Prepare output topics
        for i in params['outputs']:
            i['msg_type'] = get_attribute_from_module(i['msg_module'], i['msg_type'])
            if 'converter' in i and isinstance(i['converter'], dict):
                i['converter'] = initialize_converter(i['converter'])
            elif 'converter' not in i:
                i['converter'] = IdentityConverter()

        return dt, params['inputs'], tuple(params['outputs']), node_names, target_addresses, node

    def _close(self):
        return True


if __name__ == '__main__':

    log_level = get_ROS_log_level(rospy.get_name())

    rospy.init_node('rxbridge', log_level=log_levels_ROS[log_level])

    message_broker = eagerx_core.rxmessage_broker.RxMessageBroker(owner=rospy.get_name())

    pnode = RxBridge(name=rospy.get_name(), message_broker=message_broker)

    message_broker.connect_io()

    pnode.node_initialized()

    rospy.spin()

