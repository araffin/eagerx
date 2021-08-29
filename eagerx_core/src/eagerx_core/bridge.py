import rospy
from std_msgs.msg import UInt64, String

# Rx imports
from eagerx_core.node import RxNode
from eagerx_core.utils.utils import get_attribute_from_module, launch_node, wait_for_node_initialization, get_param_with_blocking
import eagerx_core

# Memory usage
from functools import partial
from threading import current_thread, Condition
import os, psutil


class BridgeNode(object):
    def __init__(self, name, message_broker):
        self.name = name
        self.ns = '/'.join(name.split('/')[:2])
        self.mb = message_broker
        self.params = get_param_with_blocking(self.name)
        # self.params = rospy.get_param(self.name)

        # Initialize any simulator here, that can be used in each node
        # todo: Make a ThreadSafe simulator object
        self.simulator = None

        # Initialized nodes
        self.is_initialized = dict()

        # Memory usage
        self.py = psutil.Process(os.getpid())

    def register_object(self, obj_params):
        # Initialize nodes
        sp_nodes = dict()
        launch_nodes = dict()
        subs = []
        for node_params in obj_params:
            name = node_params['name']
            launch_file = node_params['launch_file']
            launch_locally = node_params['launch_locally']
            single_process = node_params['single_process']
            assert single_process, 'Only single_process simulation nodes are supported.'

            # Flag to check if node is initialized
            self.is_initialized[name] = False

            # Block env until all nodes are initialized
            def initialized(msg, name):
                self.is_initialized[name] = True
            sub = rospy.Subscriber(self.ns + '/' + name + '/initialized', UInt64, partial(initialized, name=name))
            subs.append(sub)

            # Initialize node (with reference to simulator)
            if single_process:  # Initialize inside this process
                sp_nodes[self.ns + '/' + name] = RxNode(name=self.ns + '/' + name, message_broker=self.mb,
                                                              scheduler=None, simulator=self.simulator)
            else:  # Not yet supported, because we cannot pass a reference to the simulator here.
                if launch_locally and launch_file:  # Launch node as separate process
                    launch_nodes[self.ns + '/' + name] = launch_node(launch_file, args=['node_name:=' + name, 'name:=' + self.ns])
                    launch_nodes[self.ns + '/' + name].start()

        [node.node_initialized() for name, node in sp_nodes.items()]
        return sp_nodes, launch_nodes

    def pre_reset(self, ticks):
        rospy.loginfo('[%s][%s][%s] %s: %s' % (os.getpid(), current_thread().name, self.name, 'PRE-RESET', ticks))
        return None

    def post_reset(self):
        rospy.loginfo('[%s][%s][%s] %s: %s' % (os.getpid(), current_thread().name, self.name, 'POST-RESET', '***NO INPUT***'))
        return None

    def callback(self, topics_in):
        # todo: implement how to step the environment
        ...
        return None


class RxBridge(object):
    def __init__(self, name, message_broker, scheduler=None):
        self.name = name
        self.ns = '/'.join(name.split('/')[:2])
        self.mb = message_broker
        self.initialized = False

        # Prepare input & output topics
        dt, topics_in, topics_out, self.bridge = self._prepare_io_topics(self.name)

        # Initialize reactive pipeline
        rx_objects = eagerx_core.init_bridge(self.ns, dt, self.bridge.callback, self.bridge.pre_reset,
                                             self.bridge.post_reset, self.bridge.register_object,
                                             topics_in, topics_out, self.mb, node_name=self.name, scheduler=scheduler)
        self.mb.add_rx_objects(node_name=name, node=self, **rx_objects)
        self.mb.connect_io()

        # Initialize object registry
        # todo: make reactive
        self.cond_reg = Condition()
        # self.is_initialized = dict()
        # self._sp_nodes = dict()
        # self._launch_nodes = dict()
        # self._register_sub = rospy.Subscriber(self.ns + '/register', String, self._register_handler)

        # Prepare closing routine
        rospy.on_shutdown(self._close)

    def node_initialized(self):
        with self.cond_reg:
            # Wait for all nodes to be initialized
            # [node.node_initialized() for name, node in self._sp_nodes.items()]
            wait_for_node_initialization(self.bridge.is_initialized)

            # Notify env that node is initialized
            if not self.initialized:
                init_pub = rospy.Publisher(self.name + '/initialized', UInt64, queue_size=0, latch=True)
                init_pub.publish(UInt64(data=1))
                rospy.loginfo('Node "%s" initialized.' % self.name)
                self.initialized = True

    def _prepare_io_topics(self, name):
        params = rospy.get_param(name)
        rate = params['rate']
        dt = 1 / rate

        # Get node
        node_cls = get_attribute_from_module(params['module'], params['node_type'])
        node = node_cls(name, self.mb)

        # Prepare input topics
        for i in params['topics_in']:
            i['msg_type'] = get_attribute_from_module(i['msg_module'], i['msg_type'])
            i['converter'] = get_attribute_from_module(i['converter_module'], i['converter'])

        # Prepare output topics
        for i in params['topics_out']:
            i['msg_type'] = get_attribute_from_module(i['msg_module'], i['msg_type'])
            i['converter'] = get_attribute_from_module(i['converter_module'], i['converter'])

        return dt, params['topics_in'], tuple(params['topics_out']), node

    def _close(self):
        return True

    # def _register_handler(self, msg):
    #     with self.cond_reg:
    #         node_params = self.bridge.register_object(msg)
    #
    #         # If node_params is None, object_params cannot be loaded.
    #         if node_params is None:
    #             rospy.logwarn('Parameters for object registry request (%s) not found on parameter server. Timeout: object (%s) not registered.' % (msg.data, msg.data))
    #             return
    #
    #         # Upload parameters to ROS param server
    #         for params in node_params:
    #             name = params['name']
    #
    #             # Flag to check if node is initialized
    #             self.is_initialized[name] = False
    #
    #             # Add topics_out as topics_in of stepper
    #             for i in params['topics_out']:
    #                 name = i['name']
    #                 if name in self._topics_in_name:
    #                     raise ValueError('Cannot add topic_out "%s" multiple times as input to stepper.' % name)
    #                 else:
    #                     self._topics_in_name.add(name)
    #                     i['repeat'] = 'empty'
    #                     i['is_reactive'] = True
    #                     # todo: move rx code to _init__.py?
    #                     i['msg'] = Subject()
    #                     i['reset'] = Subject()
    #                     self.topics_in.append(i)
    #
    #         # Initialize nodes
    #         subs = []
    #         for params in node_params:
    #             name = params['name']
    #             launch_file = params['launch_file']
    #             launch_locally = params['launch_locally']
    #             single_process = params['single_process']
    #
    #             # Block env until all nodes are initialized
    #             def initialized(msg, name):
    #                 self.is_initialized[name] = True
    #             sub = rospy.Subscriber(self.ns + '/' + name + '/initialized', UInt64, partial(initialized, name=name))
    #             subs.append(sub)
    #
    #             # Initialize node
    #             if single_process:  # Initialize inside this process
    #                 self._sp_nodes[self.ns + '/' + name] = RxNode(name=self.ns + '/' + name, message_broker=self.mb, scheduler=None)
    #             else:
    #                 if launch_locally and launch_file:  # Launch node as separate process
    #                     self._launch_nodes[self.ns + '/' + name] = launch_node(launch_file, args=['node_name:=' + name,
    #                                                                                               'name:=' + self.ns])
    #                     self._launch_nodes[self.ns + '/' + name].start()
    #
    #         [node.node_initialized() for name, node in self._sp_nodes.items()]


