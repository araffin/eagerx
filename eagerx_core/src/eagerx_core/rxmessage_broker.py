# IMPORT ROS
import rospy
from std_msgs.msg import UInt64

# IMPORT OTHER
from termcolor import cprint
import logging
import types
from functools import wraps
from threading import Condition

# IMPORT EAGERX
from eagerx_core.constants import DEBUG
from eagerx_core.rxoperators import from_topic


def thread_safe_wrapper(func, condition):
    @wraps(func)
    def wrapped(*args, **kwargs):
        with condition:
            return func(*args, **kwargs)
    return wrapped


class RxMessageBroker(object):
    def __init__(self, owner):
        self.owner = owner

        # Determine log_level
        self.effective_log_level = logging.getLogger('rosout').getEffectiveLevel()

        # Ensure that we are not reading and writing at the same time.
        self.cond = Condition()

        # Structured as outputs[address][node_name] = {rx=Subject, node_name=node_name, source=RxOutput(...), etc..}
        self.rx_connectable = dict()

        # Structured as node_io[node_name][type][address] = {rx=Subject, disposable=rx_disposable, etc..}
        self.node_io = dict()
        self.disconnected = dict()
        self.connected_ros = dict()
        self.connected_rx = dict()

    # Every method is wrapped in a 'with Condition' block in order to be threadsafe
    def __getattribute__(self, name):
        attr = super(RxMessageBroker, self).__getattribute__(name)
        if isinstance(attr, types.MethodType):
            attr = thread_safe_wrapper(attr, self.cond)
        return attr

    def add_rx_objects(self, node_name, node=None, inputs=tuple(), outputs=tuple(), feedthrough=tuple(),
                       state_inputs=tuple(), state_outputs=tuple(), targets=tuple(), node_inputs=tuple(), node_outputs=tuple(),
                       reactive_proxy=tuple()):
        # todo: connect all outputs
        # Only add outputs that we would like to link with rx (i.e., skipping ROS (de)serialization)
        for i in outputs:
            if i['address'] == '/rx/bridge/outputs/tick': continue
            assert i['address'] not in self.rx_connectable, 'Non-unique output (%s). All output names must be unique.' % i['address']
            self.rx_connectable[i['address']] = dict(rx=i['msg'], source=i, node_name=node_name, rate=i['rate'])

        # Register all I/O of node
        if node_name not in self.node_io:
            assert node is not None, 'No reference to Node "%s" was provided, during the first attempt to register it.'
            # Prepare io dictionaries
            self.node_io[node_name] = dict(node=node, inputs={}, outputs={}, feedthrough={}, state_inputs={}, state_outputs={}, targets={}, node_inputs={}, node_outputs={}, reactive_proxy={})
            self.disconnected[node_name] = dict(inputs={}, feedthrough={}, state_inputs={}, targets={}, node_inputs={})
            self.connected_ros[node_name] = dict(inputs={}, feedthrough={}, state_inputs={}, targets={}, node_inputs={})
            self.connected_rx[node_name] = dict(inputs={}, feedthrough={}, state_inputs={}, targets={}, node_inputs={})
        n = dict(inputs={}, outputs={}, feedthrough={}, state_inputs={}, state_outputs={}, targets={}, node_inputs={}, node_outputs={}, reactive_proxy={})
        for i in inputs:
            address = i['address']
            assert address not in self.node_io[node_name]['inputs'], 'Cannot re-register the same address (%s) twice as "%s".' % (address, 'inputs')
            n['inputs'][address] = {'rx': i['msg'], 'disposable': None, 'source': i, 'msg_type': i['msg_type'], 'converter': i['converter'], 'repeat': i['repeat'], 'status': 'disconnected'}
            n['inputs'][address + '/reset'] = {'rx': i['reset'], 'disposable': None, 'source': i, 'msg_type': UInt64, 'status': 'disconnected'}
        for i in outputs:
            address = i['address']
            assert address not in self.node_io[node_name]['outputs'], 'Cannot re-register the same address (%s) twice as "%s".' % (address, 'outputs')
            n['outputs'][address] = {'rx': i['msg'], 'disposable': None, 'source': i, 'msg_type': i['msg_type'], 'rate': i['rate'], 'converter': i['converter'], 'status': ''}
            n['outputs'][address + '/reset'] = {'rx': i['reset'], 'disposable': None, 'source': i, 'msg_type': UInt64, 'status': ''}

            # Create publisher
            i['msg_pub'] = rospy.Publisher(i['address'], i['msg_type'], queue_size=0, latch=True)
            i['msg'].subscribe(on_next=i['msg_pub'].publish)
            i['reset_pub'] = rospy.Publisher(i['address'] + '/reset', i['msg_type'], queue_size=0, latch=True)
            i['reset'].subscribe(on_next=i['reset_pub'].publish)
        for i in feedthrough:
            address = i['address']
            assert address not in self.node_io[node_name]['feedthrough'], 'Cannot re-register the same address (%s) twice as "%s".' % (address, 'feedthrough')
            n['feedthrough'][address] = {'rx': i['msg'], 'disposable': None, 'source': i, 'msg_type': i['msg_type'], 'converter': i['converter'], 'repeat': i['repeat'], 'status': 'disconnected'}
            n['feedthrough'][address + '/reset'] = {'rx': i['reset'], 'disposable': None, 'source': i, 'msg_type': UInt64, 'status': 'disconnected'}
        for i in state_outputs:
            address = i['address']
            assert address not in self.node_io[node_name]['state_outputs'], 'Cannot re-register the same address (%s) twice as "%s".' % (address, 'state_outputs')
            n['state_outputs'][address] = {'rx': i['msg'], 'disposable': None, 'source': i, 'msg_type': i['msg_type'], 'status': ''}
            if 'converter' in i:
                n['state_outputs'][address]['converter'] = i['converter']

            # Create publisher
            i['msg_pub'] = rospy.Publisher(i['address'], i['msg_type'], queue_size=0, latch=True)
            i['msg'].subscribe(on_next=i['msg_pub'].publish)
        for i in state_inputs:
            address = i['address']
            if 'msg' in i:  # Only true if sim state node (i.e. **not** for bridge done flags)
                assert address + '/set' not in self.node_io[node_name]['state_inputs'], 'Cannot re-register the same address (%s) twice as "%s".' % (address + '/set', 'state_inputs')
                n['state_inputs'][address + '/set'] = {'rx': i['msg'], 'disposable': None, 'source': i, 'msg_type': i['msg_type'], 'converter': i['converter'], 'status': 'disconnected'}
            if address + '/done' not in n['state_outputs'].keys():  # Only true if **not** a real reset node (i.e., sim state & bridge done flag)
                assert address + '/done' not in self.node_io[node_name]['state_inputs'], 'Cannot re-register the same address (%s) twice as "%s".' % (address + '/done', 'state_inputs')
                n['state_inputs'][address + '/done'] = {'rx': i['done'], 'disposable': None, 'source': i, 'msg_type': UInt64, 'status': 'disconnected'}
        for i in targets:
            address = i['address']
            assert address not in self.node_io[node_name]['targets'], 'Cannot re-register the same address (%s) twice as "%s".' % (address, 'targets')
            n['targets'][address + '/set'] = {'rx': i['msg'], 'disposable': None, 'source': i, 'msg_type': i['msg_type'], 'converter': i['converter'], 'status': 'disconnected'}
        for i in node_inputs:
            address = i['address']
            assert address not in self.node_io[node_name]['node_inputs'], 'Cannot re-register the same address (%s) twice as "%s".' % (address, 'node_inputs')
            n['node_inputs'][address] = {'rx': i['msg'], 'disposable': None, 'source': i, 'msg_type': i['msg_type'], 'status': 'disconnected'}
        for i in node_outputs:
            address = i['address']
            assert address not in self.node_io[node_name]['node_outputs'], 'Cannot re-register the same address (%s) twice as "%s".' % (address, 'node_outputs')
            n['node_outputs'][address] = {'rx': i['msg'], 'disposable': None, 'source': i, 'msg_type': i['msg_type'], 'status': ''}

            # Create publisher: (latched: register, node_reset, start_reset, reset, real_reset)
            i['msg_pub'] = rospy.Publisher(i['address'], i['msg_type'], queue_size=0, latch=True)
            i['msg'].subscribe(on_next=i['msg_pub'].publish)
        for i in reactive_proxy:
            address = i['address']
            assert address not in self.node_io[node_name]['reactive_proxy'], 'Cannot re-register the same address (%s) twice as "%s".' % (address, 'reactive_proxy')
            n['reactive_proxy'][address + '/reset'] = {'rx': i['reset'], 'disposable': None, 'source': i,  'msg_type': UInt64, 'rate': i['rate'], 'status': ''}

            # Create publisher
            i['reset_pub'] = rospy.Publisher(i['address'] + '/reset', UInt64, queue_size=0, latch=True)
            i['reset'].subscribe(on_next=i['reset_pub'].publish)

        # Add new addresses to already registered I/Os
        for key in n.keys():
            self.node_io[node_name][key].update(n[key])

        # Add new addresses to disconnected
        for key in ('inputs', 'feedthrough', 'state_inputs', 'targets', 'node_inputs'):
            self.disconnected[node_name][key] = n[key].copy()

    def print_io_status(self, node_names=None):
        # Only print status for specific node
        if node_names is None:
            node_names = self.node_io.keys()
        else:
            if not isinstance(node_names, list):
                node_names = list(node_names)

        # Print status
        for node_name in node_names:
            cprint(('OWNER "%s"' % self.owner).ljust(15, ' ') + ('| OVERVIEW NODE "%s" ' % node_name).ljust(180, " "), attrs=['bold', 'underline'])
            for key in ('inputs', 'feedthrough', 'state_inputs', 'targets', 'node_inputs', 'outputs', 'state_outputs', 'node_outputs', 'reactive_proxy'):
                if len(self.node_io[node_name][key]) == 0:
                    continue
                for address in self.node_io[node_name][key].keys():
                    color = None
                    if key in ('outputs', 'node_outputs', 'state_outputs', 'reactive_proxy'):
                        color = 'cyan'
                    else:
                        if address in self.disconnected[node_name][key]:
                            color = 'red'
                        if address in self.connected_rx[node_name][key]:
                            assert color is None, 'Duplicate connection status for address (%s).' % address
                            color = 'green'
                        if address in self.connected_ros[node_name][key]:
                            assert color is None, 'Duplicate connection status for address (%s).' % address
                            color = 'blue'
                    status = self.node_io[node_name][key][address]['status']

                    # Print status
                    entry = self.node_io[node_name][key][address]
                    key_str = ('%s' % key).ljust(15, ' ')
                    address_str = ('| %s ' % address).ljust(50, ' ')
                    msg_type_str = ('| %s ' % entry['msg_type'].__name__).ljust(10, ' ')
                    if 'converter' in entry:
                        converter_str = ('| %s ' % entry['converter'].__class__.__name__).ljust(23, ' ')
                    else:
                        converter_str = ('| %s ' % '').ljust(23, ' ')
                    if 'repeat' in entry:
                        repeat_str = ('| %s ' % entry['repeat']).ljust(8, ' ')
                    else:
                        repeat_str = ('| %s ' % '').ljust(8, ' ')
                    if 'rate' in entry:
                        rate_str = '|' + ('%s' % entry['rate']).center(3, ' ')
                    else:
                        rate_str = '|' + ''.center(3, ' ')
                    status_str = ('| %s' % status).ljust(60, ' ')

                    log_msg = key_str + rate_str + address_str + msg_type_str + converter_str + repeat_str + status_str
                    cprint(log_msg, color)
            print(' '.center(140, " "))

    def connect_io(self, print_status=True):
        # If log_level is not high enough, overwrite print_status
        if self.effective_log_level > DEBUG:
            print_status = False

        for node_name, node in self.disconnected.items():
            # Skip if no disconnected addresses
            num_disconnected = 0
            for key, addresses in node.items():
                num_disconnected += len(addresses)
            if num_disconnected == 0:
                continue

            # Else, initialize connection

            print_status and cprint(('OWNER "%s"' % self.owner).ljust(15, ' ') + ('| CONNECTING NODE "%s" ' % node_name).ljust(180, " "), attrs=['bold', 'underline'])
            for key, addresses in node.items():
                for address in list(addresses.keys()):
                    entry = addresses[address]
                    assert address not in self.connected_rx[node_name][key], 'Address (%s) of this node (%s) already connected via rx.' % (address, node_name)
                    assert address not in self.connected_ros[node_name][key], 'Address (%s) of this node (%s) already connected via ROS.' % (address, node_name)
                    if address in self.rx_connectable.keys():
                        color = 'green'
                        status = 'Rx'.ljust(4, ' ')
                        entry['rate'] = self.rx_connectable[address]['rate']
                        rate_str = '|' + ('%s' % entry['rate']).center(3, ' ')
                        node_str = ('| %s' % self.rx_connectable[address]['node_name']).ljust(40, ' ')
                        msg_type_str = ('| %s' % self.rx_connectable[address]['source']['msg_type'].__name__).ljust(12, ' ')
                        converter_str = ('| %s' % self.rx_connectable[address]['source']['converter'].__class__.__name__).ljust(12, ' ')
                        status += node_str + msg_type_str + converter_str
                        self.connected_rx[node_name][key][address] = entry
                        O = self.rx_connectable[address]['rx']
                    else:
                        color = 'blue'
                        status = 'ROS |'.ljust(5, ' ')
                        rate_str = '|' + ''.center(3, ' ')
                        msg_type = entry['msg_type']
                        self.connected_ros[node_name][key][address] = entry
                        O = from_topic(msg_type, address, node_name=node_name)

                    # Subscribe and change status
                    entry['disposable'] = O.subscribe(entry['rx'])
                    entry['status'] = status

                    # Print status
                    key_str = ('%s' % key).ljust(15, ' ')
                    address_str = ('| %s ' % address).ljust(50, ' ')
                    msg_type_str = ('| %s ' % entry['msg_type'].__name__).ljust(10, ' ')
                    status_str = ('| Connected via %s' % status).ljust(60, ' ')

                    if 'converter' in entry:
                        converter_str = ('| %s ' % entry['converter'].__class__.__name__).ljust(23, ' ')
                    else:
                        converter_str = ('| %s ' % '').ljust(23, ' ')
                    if 'repeat' in entry:
                        repeat_str = ('| %s ' % entry['repeat']).ljust(8, ' ')
                    else:
                        repeat_str = ('| %s ' % '').ljust(8, ' ')

                    log_msg = key_str + rate_str + address_str + msg_type_str + converter_str + repeat_str + status_str
                    print_status and cprint(log_msg, color)

                    # Remove address from disconnected
                    addresses.pop(address)

            print_status and print(''.center(140, " "))
