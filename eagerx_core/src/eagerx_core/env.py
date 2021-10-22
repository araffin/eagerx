# ROS packages required
import rospy
import rosparam
from rosgraph.masterapi import Error
from std_msgs.msg import UInt64, String

# EAGERX
from eagerx_core.params import RxNodeParams, RxObjectParams
from eagerx_core.utils.utils import merge_dicts
from eagerx_core.utils.node_utils import initialize_nodes, wait_for_node_initialization
from eagerx_core.node import RxNode
from eagerx_core.rxenv import RxEnvironment
from eagerx_core import RxMessageBroker

# OTHER IMPORTS
import gym
from typing import List, Dict
import multiprocessing


class Env(object):
    @staticmethod
    def define_actions(new=True):
        actions = dict(default=dict(inputs={}, outputs={}, output_converters={}), inputs={}, outputs={})

        # Add step as input
        if new:
            actions['node_type'] = 'eagerx_core.node/ActionsNode'
            actions['default']['single_process'] = True
            actions['default']['launch_locally'] = True
            actions['default']['name'] = 'env/actions'
            actions['default']['package_name'] = 'n/a'
            actions['default']['config_name'] = 'n/a'

            # Add step as input
            cname = 'step'
            address = 'step'
            actions['default']['inputs'][cname] = address
            actions['inputs'][cname] = {'msg_type': 'std_msgs.msg/UInt64', 'repeat': 'all'}

            # Add observations/set as input
            cname = 'observations_set'
            address = 'env/observations/set'
            actions['default']['inputs'][cname] = address
            actions['inputs'][cname] = {'msg_type': 'std_msgs.msg/UInt64', 'repeat': 'all'}
        return actions

    @staticmethod
    def define_observations(new=True):
        observations = dict(default=dict(inputs={}, input_converters={}, outputs={}), inputs={}, outputs={})

        # Add step as input
        if new:
            observations['node_type'] = 'eagerx_core.node/ObservationsNode'
            observations['default']['single_process'] = True
            observations['default']['launch_locally'] = True
            observations['default']['name'] = 'env/observations'
            observations['default']['package_name'] = 'n/a'
            observations['default']['config_name'] = 'n/a'

            # Add 'observations/set' as output
            cname = 'observations_set'
            address = 'env/observations/set'
            observations['default']['outputs'][cname] = address
            observations['outputs'][cname] = {'msg_type': 'std_msgs.msg/UInt64'}
        return observations

    @staticmethod
    def define_states(new=True):
        states = dict(default=dict(states={}, state_converters={}), states={})

        if new:
            states['node_type'] = 'eagerx_core.rxenv/EnvironmentNode'
            states['default']['single_process'] = True
            states['default']['launch_locally'] = True
            states['default']['name'] = 'env/supervisor'
            states['default']['package_name'] = 'n/a'
            states['default']['config_name'] = 'n/a'
        return states

    def __init__(self, name: str, rate: int,
                 observations: Dict,
                 actions: Dict,
                 states: Dict,
                 bridge: RxNodeParams,
                 nodes: List[RxNodeParams]) -> None:
        self.name = name
        self.ns = '/' + name
        self.rate = rate
        self.initialized = False
        self._bridge_name = bridge.name
        self._is_initialized = dict()
        self._launch_nodes = dict()
        self._sp_nodes = dict()
        self._event = multiprocessing.Event()

        # Initialize environment
        self.act_node, self.obs_node, self.env_node, self.rx_nodes, self.mb = self._init_env(actions, observations, states)

        # Initialize bridge
        initialize_nodes(bridge, self.ns, self.name, self.mb, self._is_initialized, self._sp_nodes, self._launch_nodes)
        wait_for_node_initialization(self._is_initialized)  # Proceed after bridge is initialized

        # Initialize nodes
        initialize_nodes(nodes, self.ns, self.name, self.mb, self._is_initialized, self._sp_nodes, self._launch_nodes)

        # Initialize ROS topics
        # self.register_pub = rospy.Publisher(self.ns + '/register', String, queue_size=0)
        # self._step_pub = {'step':  rospy.Publisher(self.ns + '/step', UInt64, queue_size=0, latch=True),
        #                   'reset': rospy.Publisher(self.ns + '/step/reset', UInt64, queue_size=0, latch=True),
        #                   'counter': 0}
        # self._reset_pub = rospy.Publisher(self.ns + '/start_reset', UInt64, queue_size=0, latch=True)
        # self._start_pub = rospy.Publisher(self.ns + '/bridge/tick', UInt64, queue_size=0)
        # self._reset_sub = rospy.Subscriber(self.ns + '/end_reset', UInt64, self.__end_reset_handler)
        # rospy.sleep(0.1)  # todo: needed, else publisher might not yet be initialized

        # Initialize state topics
        # self._resettable_states = dict()
        # self._sim_sub = rospy.Subscriber(self.ns + '/resettable/sim', String, self._register_states)
        # self._real_sub = rospy.Subscriber(self.ns + '/resettable/real', String, self._register_states)

    @property
    def observation_space(self):
        observation_space = dict()
        for name, buffer in self.obs_node.observation_buffer.items():
            observation_space[name] = buffer['converter'].get_space()
        return gym.spaces.Dict(spaces=observation_space)

    @property
    def action_space(self):
        action_space = dict()
        for name, buffer in self.act_node.action_buffer.items():
            action_space[name] = buffer['converter'].get_space()
        return gym.spaces.Dict(spaces=action_space)

    @property
    def state_space(self):
        state_space = dict()
        for name, buffer in self.env_node.state_buffer.items():
            state_space[name] = buffer['converter'].get_space()
        return gym.spaces.Dict(spaces=state_space)

    def _set_action(self, action):
        # Set actions in buffer
        for name, buffer in self.act_node.action_buffer.items():
            assert name in action, 'Action "%s" not specified. Must specify all actions in action_space.' % name
            buffer['msg'] = action[name]

    def _set_state(self, state):
        # Set states in buffer
        for name, msg in state.items():
            assert name in self.env_node.state_buffer, 'Cannot set unknown state "%s".' % name
            self.env_node.state_buffer[name]['msg'] = msg

    def _get_observation(self):
        # Get observations from buffer
        observation = dict()
        for name, buffer in self.obs_node.observation_buffer.items():
            observation[name] = buffer['msg']
        return observation

    def _step(self):
        self.env_node.step()
        return self._get_observation()

    def _init_env(self, actions: Dict, observations: Dict, states: Dict):
        # Check that env has at least one input.
        assert len(observations['default']['inputs']) > 0, 'Environment "%s" must have at least one input (i.e. input).' % self.name
        assert len(actions['default']['outputs']) > 0, 'Environment "%s" must have at least one action (i.e. output).' % self.name

        # Check that all action/observation addresses are unique
        addresses_obs = [address for cname, address in observations['default']['inputs'].items()]
        addresses_act = [address for cname, address in actions['default']['outputs'].items()]
        addresses_ste = [address for cname, address in states['default']['states'].items()]
        len(set(addresses_obs)) == len(addresses_obs), 'Duplicate observations found: %s. Make sure to only have unique observations' % (set([x for x in addresses_obs if addresses_obs.count(x) > 1]))
        len(set(addresses_act)) == len(addresses_act), 'Duplicate actions found: %s. Make sure to only have unique actions.' % (set([x for x in addresses_act if addresses_act.count(x) > 1]))
        len(set(addresses_ste)) == len(addresses_ste), 'Duplicate states found: %s. Make sure to only have unique states.' % (set([x for x in addresses_act if addresses_act.count(x) > 1]))

        # Delete pre-existing parameters
        try:
            rosparam.delete_param('/%s' % self.name)
            rospy.loginfo('Pre-existing parameters under namespace "/%s" deleted.' % self.name)
        except Error:
            pass

        # Initialize message broker
        mb = RxMessageBroker(owner='%s/%s' % (self.ns, 'env'))

        # Upload rate of '/step' to rosparam server
        step_params = dict(step={'rate': self.rate})
        rosparam.upload_params(self.ns, step_params)

        # Create observation node
        obs_name = observations['default']['name']
        obs_params = merge_dicts(dict(), [dict(default={'rate': self.rate}), observations])
        obs_params = RxNodeParams(obs_name, obs_params)
        obs_params = obs_params.get_params(ns=self.ns)
        rosparam.upload_params(self.ns, obs_params)
        rx_obs = RxNode(name='%s/%s' % (self.ns, obs_name), message_broker=mb, scheduler=None)
        rx_obs.node_initialized()

        # Create action node
        act_name = actions['default']['name']
        act_params = merge_dicts(dict(), [dict(default={'rate': self.rate}), actions])
        act_params = RxNodeParams(act_name, act_params)
        act_params = act_params.get_params(ns=self.ns)
        rosparam.upload_params(self.ns, act_params)
        rx_act = RxNode(name='%s/%s' % (self.ns, act_name), message_broker=mb, scheduler=None)
        rx_act.node_initialized()

        # Create env node
        ste_name = states['default']['name']
        ste_params = merge_dicts(dict(), [dict(default={'rate': self.rate}), states])
        ste_params = RxNodeParams(ste_name, ste_params)
        ste_params = ste_params.get_params(ns=self.ns)
        rosparam.upload_params(self.ns, ste_params)
        rx_env = RxEnvironment(name='%s/%s' % (self.ns, ste_name), message_broker=mb, scheduler=None)
        rx_env.node_initialized()

        # Store nodes into object
        rx_nodes = {'actions': rx_act, 'observations': rx_obs, 'env': rx_env}
        return rx_act.node, rx_obs.node, rx_env.node, rx_nodes, mb

    def _initialize(self):
        assert not self.initialized, 'Environment already initialized. Cannot re-initialize pipelines. '

        # Wait for nodes to be initialized
        [node.node_initialized() for name, node in self._sp_nodes.items()]
        wait_for_node_initialization(self._is_initialized)

        # Initialize single process communication
        self.mb.connect_io(print_status=True)
        rospy.loginfo('Nodes initialized.')

        # Perform first reset
        # todo: perhaps states are sometimes not registered yet, so that it blocks here?
        _ = self._reset()

        # Nodes initialized
        self.initialized = True
        rospy.loginfo("Pipelines initialized.")

    def _reset(self):
        self.env_node.reset()
        return self._get_observation()

    def register_object(self, object: RxObjectParams):
        # todo: There might be timing issues... Currently solved with condition.
        # Look-up via <env_name>/<obj_name>/nodes/<component_type>/<component>: /rx/obj/nodes/sensors/pos_sensors
        self.env_node.register_object(object, self._bridge_name)

    def reset(self):
        # Initialize environment
        if not self.initialized:
            self._initialize()

            # todo: remove this sleep & connect
            rospy.sleep(1.0)
            self.mb.connect_io()
            self.mb.print_io_status()

        # Set desired reset states
        # self._set_state(self.state_space.sample())
        self._set_state({'N8': UInt64()})

        # Perform reset
        observation = self._reset()
        return observation

    def step(self, action):
        # Check that nodes were previously initialized.
        assert self.initialized, 'Not yet initialized. Call .initialize_node_pipelines() before calling .step().'

        # Set actions in buffer
        self._set_action(action)

        # Send actions and wait for observations
        observation = self._step()
        reward = None
        is_done = False
        info = {}
        return observation, reward, is_done, info

    def close(self):
        for name in self._launch_nodes:
            self._launch_nodes[name].shutdown()
        try:
            rosparam.delete_param('/')
            rospy.loginfo('Pre-existing parameters under namespace "/" deleted.')
        except:
            pass