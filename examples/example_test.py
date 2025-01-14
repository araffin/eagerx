# EAGERx imports
from eagerx import Object, Bridge, Node, ResetNode, Converter, BaseConverter
from eagerx import initialize, log, process

# Environment imports
from eagerx.core.env import EagerxEnv
from eagerx.core.graph import Graph
from eagerx.wrappers import Flatten

# Implementation specific
import tests.test  # noqa # pylint: disable=unused-import

if __name__ == "__main__":
    initialize("eagerx_core", anonymous=True, log_level=log.DEBUG)

    # Process configuration (optional)
    node_p = process.NEW_PROCESS
    bridge_p = process.NEW_PROCESS
    rate = 7

    # todo: TODAY
    #  - Clean env.shutdown() without errors
    #  - Installation procedure
    #  - Effect of skipping first action on environment synchronization.
    #  - Parallel training (i.e. simultaneous experience selection with real & simulated robot)
    #  - Pause environment

    # Define nodes
    N3 = ResetNode.make("RealReset", "N3", rate=rate, process=node_p, inputs=["in_1", "in_2"], targets=["target_1"], states=[])
    N1 = Node.make("Process", "N1", rate=1.0, process=node_p)
    KF = Node.make("KalmanFilter", "KF", rate=rate, process=node_p, inputs=["in_1", "in_2"], outputs=["out_1", "out_2"])

    # Define object
    viper = Object.make("Viper", "obj", position=[1, 1, 1], actuators=["N8"], sensors=["N6"], states=["N9"])

    # Define converter (optional)
    RosString_RosUInt64 = Converter.make("RosString_RosUInt64", test_arg="test")
    RosImage_RosUInt64 = Converter.make("RosImage_RosUInt64", test_arg="test")

    # Define graph
    graph = Graph.create(nodes=[N3, KF], objects=[viper])
    graph.render(source=viper.sensors.N6, rate=1, converter=RosImage_RosUInt64, display=False)
    graph.render(source=viper.sensors.N6, rate=1, converter=RosImage_RosUInt64, display=False)
    graph.connect(source=viper.sensors.N6, observation="obs_1", delay=0.0)
    graph.connect(source=KF.outputs.out_1, observation="obs_3", delay=0.0)
    graph.connect(source=KF.outputs.out_1, observation="obs_4", delay=0.0)
    graph.connect(source=viper.sensors.N6, target=KF.inputs.in_1, delay=0.0)
    graph.connect(action="act_2", target=KF.inputs.in_2, skip=True)
    graph.connect(action="act_2", target=N3.feedthroughs.out_1, delay=0.0)
    graph.connect(source=viper.sensors.N6, target=N3.inputs.in_1)
    graph.connect(source=viper.states.N9, target=N3.targets.target_1)
    graph.connect(source=N3.outputs.out_1, target=viper.actuators.N8, delay=0.0, converter=RosString_RosUInt64)

    # Set & get parameters
    _ = graph.get(action="act_2", parameter="converter")
    graph.set(1, observation="obs_1", parameter="window")
    _ = graph.get(observation="obs_1", parameter="converter")
    _ = graph.get(N3.config, parameter="test_arg")
    _ = graph.get(viper)
    graph.set("Modified", entry=N3.config, parameter="test_arg")
    graph.set([1, 1, 1], entry=viper.config, parameter="position")

    # Replace output converter
    identity = BaseConverter.make("Identity")
    # Disconnects all connections (obs_1, KF, N3)
    graph.set({"converter": RosString_RosUInt64}, viper.sensors.N6)
    graph.set({"converter": identity}, viper.sensors.N6)
    graph.render(source=viper.sensors.N6, rate=1, converter=RosImage_RosUInt64)  # Reconnect
    graph.connect(source=viper.sensors.N6, observation="obs_1", delay=0.0)       # Reconnect
    graph.connect(source=viper.sensors.N6, target=KF.inputs.in_1, delay=0.0)     # Reconnect
    graph.connect(source=viper.sensors.N6, target=N3.inputs.in_1)                # Reconnect

    # Remove component. For action/observation use graph._remove_action/observation(...) instead.
    graph.remove_component(N3.inputs.in_2)

    # Rename action & observation
    graph.rename("act_1", action="act_2")
    graph.rename("obs_2", observation="obs_3")

    # Remove & add action (without action terminal removal)
    graph.disconnect(action="act_1", target=KF.inputs.in_2)
    graph.connect(action="act_1", target=KF.inputs.in_2, converter=None, delay=None, window=None, skip=True)

    # Remove & add observation (with observation terminal removal)
    graph.disconnect(source=viper.sensors.N6, observation="obs_1")
    graph.add_component(observation="obs_1")  # Add input terminal
    graph.connect(source=viper.sensors.N6, observation="obs_1", converter=None, delay=None, window=None)

    # Remove & add other input
    graph.disconnect(source=viper.sensors.N6, target=KF.inputs.in_1)
    graph.connect(source=viper.sensors.N6, target=KF.inputs.in_1)

    # Works with other sources as well, but then specify "source" instead of "action" as optional arg to connect(..) and disconnect(..).
    graph.connect(source=viper.sensors.N6, observation="obs_5", delay=0.0)  # todo: remove
    # NOTE: with the remove=False flag, we avoid removing terminal 'obs_1'
    graph.disconnect(source=viper.sensors.N6, observation="obs_1", remove=False)

    # GUI routine for making connections
    source = viper.sensors.N6
    target = ("env/observations", "inputs", "obs_1")
    # GUI: Identify if source/target is action/observation
    observation = target[2] if target[0] == "env/observations" else None
    action = source[2] if source()[0] == "env/actions" else None
    params = graph.get(observation="obs_1")  # Grab already defined parameters from input component
    if len(params) == 0:  # If observation, dict will be empty.
        converter = graph.get(source, parameter="space_converter")
        delay, window = 0, 0
    else:  # If not observation, these values will always be present
        converter, delay, window = params["converter"], params["delay"], params["window"]
    # GUI: open dialogue box where users can modify converter, delay, window etc... Use previous params to set initial values.
    # GUI: converter, delay, window = ConnectionOptionsDialogueBox(converter, delay, window)
    target = None if observation else target  # If we have an observation, it will be the target instead in .connect(..)
    source = None if action else source  # If we have an action, it will be the source instead in .connect(..)
    # GUI: use the modified params via the dialogue box to connect.
    graph.connect(
        source=source,
        target=target,
        action=action,
        observation=observation,
        converter=converter,
        delay=delay,
        window=window,
    )

    # TEST with KF having skipped all inputs at t=0
    graph.remove_component(KF.inputs.in_1)

    graph.gui()

    # Test save & load functionality
    graph.save("./test.graph")
    graph.load("./test.graph")

    # Define bridge
    bridge = Bridge.make("TestBridge", rate=20, sync=True, real_time_factor=0, process=bridge_p)

    # Initialize Environment
    env = EagerxEnv(
        name="rx",
        rate=rate,
        graph=graph,
        bridge=bridge,
        # reset_fn=lambda env: {
        #     "obj/N9": env.state_space.sample()["obj/N9"],
        #     "bridge/param_1": env.state_space.sample()["bridge/param_1"],
        # },
    )
    env = Flatten(env)

    # First reset
    obs = env.reset()
    env.render(mode="human")
    action = env.action_space.sample()
    for j in range(20000):
        print("\n[Episode %s]" % j)
        for i in range(5):
            obs, reward, done, info = env.step(action)
            # rgb = env.render(mode='rgb_array')
        obs = env.reset()
    print("\n[Finished]")

    # todo: THINGS TO KEEP IN MIND:
    #  - We repeat the observation_space for the set window length. If window = 0, it is not included in the observation_space.
    #  - If output converters are used on simnodes, you risk breaking the object's simulation graph (as some simnodes might expect an non-converted message).
    #  - The order in which you define env actions matters when including input converters. Namely, the first space_converter is chosen.
    #  - The exact moment of switching to a real reset cannot be predicted by any node, thus this introduces
    #  race-conditions in the timing of the switch that cannot be mitigated with a reactive scheme.
    #  - Currently, we assume that **all** nodes & objects are registered and initialized before the user calls reset.
    #  Hence, we cannot adaptively register new objects or controllers after some episodes.
    #  - If we have **kwargs in callback/reset signature, the node.py implementation supports adding inputs/states.
    #  - Only objects can have nonreactive inputs. In that case, the bridge is responsible for sending flag msgs (num_msgs_send).
    #  The bridges knows which inputs are nonreactive when the object is registered.
    #  - Nodes **must** at all times publish an output. Even, when a node did not received any new inputs and wishes to not publish.
    #  Perhaps, this constraint could be softened in the async setting, however the nodes that send "None", would then
    #  not be agnostic (as they would break in the case sync=True).
    #  - In the bridge definition of an object, there cannot be converters defined for the components related to the sensor and actuator.
    #  Reason for this is that if a converter would already be defined there, then it is not possible anymore to add another one in the agnostic graph.
