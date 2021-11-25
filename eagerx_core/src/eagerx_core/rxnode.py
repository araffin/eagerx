#!/usr/bin/env python3

# ROS imports
import rospy
from std_msgs.msg import UInt64

# Rx imports
from eagerx_core.constants import log_levels_ROS
import eagerx_core.rxmessage_broker
import eagerx_core.rxpipelines
from eagerx_core.utils.utils import get_attribute_from_module, initialize_converter, get_ROS_log_level, get_param_with_blocking
from eagerx_core.baseconverter import IdentityConverter


class RxNode(object):
    def __init__(self, name, message_broker):
        self.name = name
        self.ns = '/'.join(name.split('/')[:2])
        self.mb = message_broker
        self.initialized = False

        # Prepare input & output topics
        dt, inputs, outputs, feedthroughs, states, targets, self.node = self._prepare_io_topics(self.name)

        # Initialize reactive pipeline
        rx_objects = eagerx_core.rxpipelines.init_node(self.ns, dt, self.node, inputs, outputs, feedthrough=feedthroughs,
                                                       state_inputs=states, targets=targets)
        self.mb.add_rx_objects(node_name=name, node=self, **rx_objects)

    def node_initialized(self):
        # Notify env that node is initialized
        init_pub = rospy.Publisher(self.name + '/initialized', UInt64, queue_size=0, latch=True)
        init_pub.publish(UInt64())

        if not self.initialized:
            rospy.loginfo('Node "%s" initialized.' % self.name)
        self.initialized = True

    def _prepare_io_topics(self, name):
        params = get_param_with_blocking(name)
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

        # Prepare state topics
        for i in params['states']:
            i['msg_type'] = get_attribute_from_module(i['msg_module'], i['msg_type'])
            if 'converter' in i and isinstance(i['converter'], dict):
                i['converter'] = initialize_converter(i['converter'])
            elif 'converter' not in i:
                i['converter'] = IdentityConverter()

        # Prepare target topics
        for i in params['targets']:
            i['msg_type'] = get_attribute_from_module(i['msg_module'], i['msg_type'])
            if 'converter' in i and isinstance(i['converter'], dict):
                i['converter'] = initialize_converter(i['converter'])
            elif 'converter' not in i:
                i['converter'] = IdentityConverter()

        # Prepare feedthrough topics
        for i in params['feedthroughs']:
            i['msg_type'] = get_attribute_from_module(i['msg_module'], i['msg_type'])
            if 'converter' in i and isinstance(i['converter'], dict):
                i['converter'] = initialize_converter(i['converter'])
            elif 'converter' not in i:
                i['converter'] = IdentityConverter()

        return dt, tuple(params['inputs']), tuple(params['outputs']), tuple(params['feedthroughs']), tuple(
            params['states']), tuple(params['targets']), node


if __name__ == '__main__':

    log_level = get_ROS_log_level(rospy.get_name())

    rospy.init_node('rxnode', log_level=log_levels_ROS[log_level])

    message_broker = eagerx_core.rxmessage_broker.RxMessageBroker(owner=rospy.get_name())

    pnode = RxNode(name=rospy.get_name(), message_broker=message_broker)

    message_broker.connect_io()

    pnode.node_initialized()

    rospy.spin()


###########################################################################
# Specific implementations ################################################
###########################################################################

