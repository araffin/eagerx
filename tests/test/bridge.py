# OTHER IMPORTS
from typing import Optional, List
from math import isclose

# ROS IMPORTS
import rospy
from std_msgs.msg import UInt64

# EAGERx IMPORTS
from eagerx.core.constants import process, ERROR
from eagerx.core.entities import Bridge, SpaceConverter
import eagerx.core.register as register
from eagerx.utils.utils import Msg


class TestBridgeNode(Bridge):
    def initialize(self, num_substeps: int, nonreactive_address: str):
        # Initialize any simulator here, that is passed as reference to each simnode
        self.simulator = None

        # If real_time bridge, assert that real_time_factor == 1 & sync=False.

        # Initialize nonreactive input (Only required for this test bridge implementation
        self.nonreactive_pub = rospy.Publisher(self.ns + nonreactive_address, UInt64, queue_size=0, latch=True)

    @staticmethod
    @register.spec("TestBridge", Bridge)
    def spec(
        spec,
        rate,
        process: Optional[int] = process.NEW_PROCESS,
        sync: Optional[bool] = True,
        real_time_factor: Optional[float] = 0,
        simulate_delays: Optional[bool] = True,
        log_level: Optional[int] = ERROR,
        states: Optional[List[str]] = None,
    ):
        """TestBridge spec"""
        # Performs all the steps to fill-in the params with registered info about all functions.
        TestBridgeNode.initialize_spec(spec)

        # Modify default bridge params
        spec.config.rate = rate
        spec.config.process = process
        spec.config.sync = sync
        spec.config.real_time_factor = real_time_factor
        spec.config.simulate_delays = simulate_delays
        spec.config.log_level = log_level
        spec.config.color = "magenta"
        spec.config.states = states if states else ["param_1"]

        # Add custom params
        spec.config.num_substeps = 10
        spec.config.nonreactive_address = "/nonreactive_input_topic"  # Only required to test nonreactive inputs

        # Add state: "param_1"
        spec.states.param_1.space_converter = SpaceConverter.make("Space_RosUInt64", low=[0], high=[100], dtype="uint64")

    @register.bridge_config(req_arg=None, xacro="$(find some_package)/urdf/object.urdf.xacro")
    def add_object(self, config, bridge_config, node_params, state_params):
        # add object to simulator (we have a ref to the simulator with self.simulator)
        rospy.loginfo(f'Adding object "{config["name"]}" of type "{config["entity_id"]}" to the simulator.')

    def pre_reset(self, param_1: Optional[UInt64] = None):
        return "PRE RESET RETURN VALUE"

    @register.states(param_1=UInt64)
    def reset(self, param_1: Optional[UInt64] = None):
        # Publish nonreactive input (this is only required for simulation setup)
        self.nonreactive_pub.publish(UInt64(data=0))
        return "POST RESET RETURN VALUE"

    @register.outputs(tick=UInt64)
    def callback(self, t_n: float):
        # Publish nonreactive input
        self.nonreactive_pub.publish(UInt64(data=self.num_ticks))

        # Verify that # of ticks equals internal counter
        node_tick = t_n * self.rate
        if not isclose(self.num_ticks, node_tick):
            rospy.logerr(
                f"[{self.name}][callback]: ticks not equal (self.num_ticks={self.num_ticks}, node_tick={round(node_tick)})."
            )
