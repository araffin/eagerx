import yaml
from tabulate import tabulate
from copy import deepcopy
import matplotlib.pyplot as plt
import networkx as nx
from typing import List, Union, Dict, Tuple, Optional, Any
from yaml import dump
yaml.Dumper.ignore_aliases = lambda *args: True  # todo: check if needed.
import rospy
from eagerx_core.params import RxNodeParams, RxObjectParams, add_default_args
from eagerx_core.utils.utils import get_opposite_msg_cls, get_module_type_string, get_cls_from_string
from eagerx_core.utils.network_utils import reset_graph, episode_graph, plot_graph, color_nodes, color_edges, is_stale
from eagerx_core.baseconverter import BaseConverter


class RxGraph:
    def __init__(self, state: Dict):
        self._state = state

    @classmethod
    def create(cls, nodes: Optional[List[RxNodeParams]] = None, objects: Optional[List[RxObjectParams]] = None):
        if nodes is None:
            nodes = []
        if objects is None:
            objects = []
        if isinstance(nodes, RxNodeParams):
            nodes = [nodes]
        if isinstance(objects, RxObjectParams):
            objects = [objects]

        # Add action & observation node to list
        actions = RxNodeParams.create(name='env/actions', package_name='eagerx_core', config_name='actions', rate=1.0)
        observations = RxNodeParams.create(name='env/observations', package_name='eagerx_core', config_name='observations', rate=1.0)
        nodes += [actions, observations]

        # Create a state
        state = dict(nodes=dict(), connects=list())
        cls._add(state, nodes)
        cls._add(state, objects)
        return cls(state)

    def add(self, entities: Union[Union[RxNodeParams, RxObjectParams], List[Union[RxNodeParams, RxObjectParams]]]):
        self._add(self._state, entities)

    @staticmethod
    def _add(state: Dict, entities: Union[Union[RxNodeParams, RxObjectParams], List[Union[RxNodeParams, RxObjectParams]]]):
        if not isinstance(entities, list):
            entities = [entities]

        for entity in entities:
            name = entity.name
            assert name not in state['nodes'], 'There is already a node or object registered in this graph with name "%s".' % name

            # Add node to state
            params = entity.params
            package_name = params['default']['package_name']
            config_name = params['default']['config_name']
            if isinstance(entity, RxNodeParams):
                params_default = RxNodeParams.create(name, package_name, config_name, rate=1).params
            else:
                params_default = RxObjectParams.create(name, package_name, config_name).params
            state['nodes'][name] = dict()
            state['nodes'][name]['params'] = deepcopy(params)
            state['nodes'][name]['default'] = params_default

    def remove(self, names: Union[str, List[str]]):
        """
        First removes all associated connects from self._state.
        Then, removes node/object from self._state.
        Also removes observation entries if they are disconnected.
        Also removes action entries if they are disconnect and the last connection.
        """
        if not isinstance(names, list):
            names = [names]
        for name in names:
            self._exist(self._state, name)
            for source, target in deepcopy(self._state['connects']):
                if name in [source[0], target[0]]:
                    if source[0] == 'env/actions':
                        action = source[2]
                        source = None
                    else:
                        action = None
                        source = source
                    if target[0] == 'env/observations':
                        observation = target[2]
                        target = None
                    else:
                        observation = None
                        target = target
                    self.disconnect(source, target, action, observation)
            self._state['nodes'].pop(name)

    def _remove(self, names: Union[str, List[str]]):
        """
        First removes all associated connects from self._state.
        Then, removes node/object from self._state.
        **DOES NOT** remove observation entries if they are disconnected.
        **DOES NOT** remove action entries if they are disconnect and the last connection.
        """
        if not isinstance(names, list):
            names = [names]
        for name in names:
            self._exist(self._state, name)
            for source, target in deepcopy(self._state['connects']):
                if name in [source[0], target[0]]:
                    if source[0] == 'env/actions':
                        action = source[2]
                        source = None
                    else:
                        action = None
                        source = source
                    if target[0] == 'env/observations':
                        observation = target[2]
                        target = None
                    else:
                        observation = None
                        target = target
                    self._disconnect(source, target, action, observation)
            self._state['nodes'].pop(name)

    def add_component(self, name: Optional[str] = None, component: Optional[str] = None, cname: Optional[str] = None, action: Optional[str] = None, observation: Optional[str] = None):
        # assert only action, only observation, only name, component, cname
        self._correct_signature(name, component, cname, action, observation)
        if (name is not None) and (component is not None) and (cname is not None):  # component parameter
            self._add_component(name, component, cname)
        if action:
            self._add_action(action)
        if observation:
            self._add_observation(observation)

    def _add_component(self, name: str, component: str, cname: str):
        """
        adds a component entry to the selection list.
        For feedthroughs, it will remove the corresponding output from the selection list.
        """
        # For feedthroughs, add the corresponding output instead
        component = 'outputs' if component == 'feedthroughs' else component

        # Check that cname exists
        self._exist(self._state, name, component=component, cname=cname)

        # Add cname to selection list if it is not already selected
        params = self._state['nodes'][name]['params']
        assert cname not in params['default'][component], '"%s" already selected in "%s" under %s.' % (cname, name, component)
        params['default'][component].append(cname)

    def _add_action(self, action: str):
        """
        Adds disconnected action entry to 'env/actions' node in self._state.
        """
        assert action != 'set', 'Cannot define an action with the reserved name "set".'
        params_action = self._state['nodes']['env/actions']['params']
        if action not in params_action['outputs']:  # Action already registered
            params_action['outputs'][action] = dict()
            self._add_component('env/actions', 'outputs', action)

    def _add_observation(self, observation: str):
        """
        Adds disconnected observation entry to 'env/observations' node in self._state.
        """
        assert observation != 'actions_set', 'Cannot define an observations with the reserved name "actions_set".'
        params_obs = self._state['nodes']['env/observations']['params']
        if observation in params_obs['inputs']:
            assert len(params_obs['inputs'][observation]) == 0, 'Observation "%s" already exists and is connected.' % observation
        else:
            params_obs['inputs'][observation] = dict()
            self._add_component('env/observations', 'inputs', observation)

    def remove_component(self, name: Optional[str] = None, component: Optional[str] = None, cname: Optional[str] = None, action: Optional[str] = None, observation: Optional[str] = None):
        # assert only action, only observation, only name, component, cname
        if (name is not None) and (component is not None) and (cname is not None):  # component parameter
            assert action is None, 'If {name, component, cname} are specified, action argument cannot be specified.'
            assert observation is None, 'If {name, component, cname} are specified, observation argument cannot be specified.'
            self._remove_component(name, component, cname)
        if action:
            assert observation is None, 'If action is specified, observation must be None.'
            assert (name is None) and (component is None) and (cname is None), 'If action is specified, arguments {name, component, cname} cannot be specified.'
            self._remove_action(action)
        if observation:
            assert action is None, 'If observation is specified, action must be None.'
            assert (name is None) and (component is None) and (cname is None), 'If action is specified, arguments {name, component, cname} cannot be specified.'
            self._remove_observation(observation)

    def _remove_component(self, name: str, component: str, cname: str):
        """
        Removes a component entry from the selection list. It will first disconnect all connections in connect.
        For feedthroughs, it will remove the corresponding output from the selection list.
        """
        # For feedthroughs, remove the corresponding output instead
        component = 'outputs' if component == 'feedthroughs' else component
        self._is_selected(self._state, name, component, cname)

        # Disconnect component entry
        self._disconnect_component(name, component, cname)

        # Remove cname from selection list
        params = self._state['nodes'][name]['params']
        params['default'][component].remove(cname)

    def _remove_action(self, action: str):
        """
        Method to remove an action. Can only remove existing and disconnected actions.
        """
        params_action = self._state['nodes']['env/actions']['params']
        source = ['env/actions', 'outputs', action]
        connect_exists = False
        for idx, c in enumerate(self._state['connects']):
            if source == c[0]:
                connect_exists = True
                target = c[1]
                break
        assert not connect_exists, 'Action entry "%s" cannot be removed, because it is not disconnected. Connection with target %s still exists.' % (action, target)
        assert action in params_action['outputs'], 'Action "%s" cannot be removed, because it does not exist.' % action

        self._remove_component('env/actions', 'outputs', action)
        params_action['outputs'].pop(action)

    def _remove_observation(self, observation: str):
        """
        Method to remove an observation. Can only remove existing and disconnected observations.
        """
        params_obs = self._state['nodes']['env/observations']['params']
        target = ['env/observations', 'inputs', observation]
        connect_exists = False
        for idx, c in enumerate(self._state['connects']):
            if target == c[1]:
                connect_exists = True
                source = c[0]
                break
        assert not connect_exists, 'Observation entry "%s" cannot be removed, because it is not disconnected. Connection with source %s still exists.' % (observation, source)
        assert observation in params_obs['inputs'], 'Observation "%s" cannot be removed, because it does not exist.' % observation

        self._remove_component('env/observations', 'inputs', observation)
        params_obs['inputs'].pop(observation)

    def connect(self,
                source: Optional[Tuple[str, str, str]] = None,
                target: Optional[Tuple[str, str, str]] = None,
                action: str = None, observation: str = None,
                converter: Optional[Dict] = None,
                window: Optional[int] = None,
                delay: Optional[float] = None):
        assert not source or not action, 'You cannot specify a source if you wish to connect action "%s", as the action will act as the source.' % action
        assert not target or not observation, 'You cannot specify a target if you wish to connect observation "%s", as the observation will act as the target.' % observation
        assert not (observation and action), 'You cannot connect an action directly to an observation.'

        if isinstance(converter, BaseConverter):
            converter = converter.get_yaml_definition()

        if action:  # source = action
            try:
                self.add_component(action=action)
            except AssertionError:
                pass
            self._connect_action(action, target, converter=converter)
            source = ('env/actions', 'outputs', action)
        elif observation:  # target = observation
            try:
                self.add_component(observation=observation)
            except AssertionError:
                pass
            converter = self._connect_observation(source, observation, converter=converter)
            target = ('env/observations', 'inputs', observation)
        self._connect(source, target, converter, window, delay)

    def _connect(self,
                source: Optional[Tuple[str, str, str]] = None,
                target: Optional[Tuple[str, str, str]] = None,
                converter: Optional[Dict] = None,
                window: Optional[int] = None,
                delay: Optional[float] = None):
        """
        Method to connect a source to a target. For actions/observations, first a (new) disconnected entry must be created,
        after which an additional call to connect_action/observation is required before calling this method.
        For more info, see self.connect.
        """
        if isinstance(converter, BaseConverter):
            converter = converter.get_yaml_definition()

        if isinstance(source, tuple):
            source = list(source)
        if isinstance(target, tuple):
            target = list(target)

        # Perform checks on source
        source_name, source_comp, source_cname = source
        self._is_selected(self._state, source_name, source_comp, source_cname)

        # Perform checks on target
        target_name, target_comp, target_cname = target
        target_params = self._state['nodes'][target_name]['params']
        if target_comp == 'feedthroughs':
            assert window is None or window > 0, 'Feedthroughs must have a window > 0, else no action can be fed through.'
            self._is_selected(self._state, target_name, 'outputs', target_cname)
        else:
            self._is_selected(self._state, target_name, target_comp, target_cname)

        # Add properties to target params
        if converter is not None:
            target_params[target_comp][target_cname]['converter'] = converter
        if window is not None:
            target_params[target_comp][target_cname]['window'] = window
        if delay is not None:
            target_params[target_comp][target_cname]['delay'] = delay

        # Add connection
        connect = [source, target]
        RxGraph.check_msg_type(source, target, self._state)
        self._state['connects'].append(connect)

    def _connect_action(self, action, target, converter=None):
        """
        Method to connect a (previously added) action, that *precedes* self._connect(source, target).
        """
        params_action = self._state['nodes']['env/actions']['params']
        assert action in params_action['outputs'], 'Action "%s" must be added, before you can connect it.' % action
        name, component, cname = target
        if component == 'feedthroughs': component = 'outputs'
        params_target = self._state['nodes'][name]['params']

        assert 'space_converter' in params_target[component][cname], '"%s" does not have a space_converter defined under %s in the .yaml of object "%s".' % (cname, component, name)

        # Infer source properties (converter & msg_type) from target
        space_converter = params_target[component][cname]['space_converter']
        msg_type_C = get_cls_from_string(params_target[component][cname]['msg_type'])
        if converter:  # Overwrite msg_type_B if input converter specified
            msg_type_B = get_opposite_msg_cls(msg_type_C, converter)
        else:
            msg_type_B = msg_type_C

        # Set properties in node params of 'env/actions'
        if len(params_action['outputs'][action]) > 0:  # Action already registered
            space_converter_state = params_action['outputs'][action]['converter']
            msg_type_B_state = get_opposite_msg_cls(params_action['outputs'][action]['msg_type'], space_converter_state)
            assert msg_type_B == msg_type_B_state, 'Conflicting %s for action "%s" that is already used in another connection. Occurs with connection %s' % ('msg_types', action, tuple([name, component, cname]))
            if not space_converter == space_converter_state:
                rospy.logwarn('Conflicting %s for action "%s". Not using the space_converter of %s[%s][%s]' % ('space_converters', action, name, component, cname))
            msg_type_A = get_opposite_msg_cls(msg_type_B_state, space_converter_state)
        else:
            # Verify that converter is not modifying the msg_type (i.e. it is a processor).
            assert msg_type_B == msg_type_C, 'Cannot have a converter that maps to a different msg_type as the converted msg_type will not be compatible with the space_converter specified in the .yaml.'
            msg_type_A = get_opposite_msg_cls(msg_type_B, space_converter)
            params_action['outputs'][action]['msg_type'] = get_module_type_string(msg_type_A)
            params_action['outputs'][action]['converter'] = space_converter
            add_default_args(params_action['outputs'][action], component='outputs')

    def _connect_observation(self, source, observation, converter):
        """
        Method to connect a (previously added & disconnected) observation, that *precedes* self._connect(source, target).
        """
        params_obs = self._state['nodes']['env/observations']['params']
        assert observation in params_obs['inputs'], 'Observation "%s" must be added, before you can connect it.' % observation
        name, component, cname = source
        params_source = self._state['nodes'][name]['params']

        assert converter is not None or 'space_converter' in params_source[component][cname], '"%s" does not have a space_converter defined under %s in the .yaml of "%s". Either specify it there, or add an input converter that acts as a space_converter to this connection.' % (cname, component, name)

        # Infer target properties (converter & msg_type) from source
        msg_type_A = get_cls_from_string(params_source[component][cname]['msg_type'])
        output_converter = params_source[component][cname]['converter']
        msg_type_B = get_opposite_msg_cls(msg_type_A, output_converter)
        if converter is None:
            converter = params_source[component][cname]['space_converter']
        msg_type_C = get_opposite_msg_cls(msg_type_B, converter)

        # Set properties in node params of 'env/observations'
        assert len(params_obs['inputs'][observation]) == 0, 'Observation "%s" already connected.' % observation
        params_obs['inputs'][observation]['msg_type'] = get_module_type_string(msg_type_C)
        add_default_args(params_obs['inputs'][observation], component='inputs')
        return converter

    def disconnect(self,
                   source: Optional[Tuple[str, str, str]] = None,
                   target: Optional[Tuple[str, str, str]] = None,
                   action: str = None, observation: str = None,
                   remove: bool = True):
        """
        Disconnects a source from a target. The target is reset in self._state to its disconnected state.
        If remove=True, remove observations and actions in the following cases:
        In case of an observation, the complete entry is always removed.
        In case of an action, it is removed if the action is not connected to any other target.
        """
        self._disconnect(source, target, action, observation)
        if remove:
            if action:
                connect_exists = False
                source = ['env/actions', 'outputs', action]
                for idx, c in enumerate(self._state['connects']):
                    if source == c[0]:
                        connect_exists = True
                        break
                if not connect_exists:
                    self.remove_component(action=action)
            if observation:
                self.remove_component(observation=observation)

    def _disconnect(self,
                   source: Optional[Tuple[str, str, str]] = None,
                   target: Optional[Tuple[str, str, str]] = None,
                   action: str = None, observation: str = None, ):
        """
        Disconnects a source from a target. The target is reset in self._state to its disconnected state.
        """
        assert not source or not action, 'You cannot specify a source if you wish to disconnect action "%s", as the action will act as the source.' % action
        assert not target or not observation, 'You cannot specify a target if you wish to disconnect observation "%s", as the observation will act as the target.' % observation
        assert not (observation and action), 'You cannot disconnect an action from an observation, as such a connection cannot exist.'
        if isinstance(source, tuple):
            source = list(source)
        if isinstance(target, tuple):
            target = list(target)

        # Create source & target entries
        if action:
            source = ['env/actions', 'outputs', action]
        if observation:
            target = ['env/observations', 'inputs', observation]

        # Check if connection exists
        self._is_selected(self._state, *source)
        self._is_selected(self._state, *target)

        # Check if connection exists
        connect_exists = False
        idx_connect = None
        for idx, c in enumerate(self._state['connects']):
            if source == c[0] and target == c[1]:
                connect_exists = True
                idx_connect = idx
                break
        assert connect_exists, 'The connection with source=%s and target=%s cannot be removed, because it does not exist.' % (source, target)

        # Pop the connection from the state
        self._state['connects'].pop(idx_connect)

        # Reset source params to disconnected state
        if action:
            self._disconnect_action(action)
        else:
            # Nothing to do here (for now)
            source_name, source_comp, source_cname = source
            source_params = self._state['nodes'][source_name]['params']

        # Reset target params to disconnected state (reset to go back to default yaml), i.e. reset window/delay/converter.
        if observation:
            self._disconnect_observation(observation)
        else:
            target_name, target_comp, target_cname = target
            target_params = self._state['nodes'][target_name]['params']
            target_params[target_comp][target_cname] = self._state['nodes'][target_name]['default'][target_comp][target_cname]

    def _disconnect_component(self, name: str, component: str, cname: str):
        """
        Disconnects all associated connects from self._state.
        **DOES NOT** remove observation entries if they are disconnected.
        **DOES NOT** remove action entries if they are disconnect and the last connection.
        """
        for source, target in deepcopy(self._state['connects']):
            self._is_selected(self._state, *source)
            self._is_selected(self._state, *target)
            source_name, source_comp, source_cname = source
            target_name, target_comp, target_cname = target
            if source_name == 'env/actions':
                action = source_cname
                source = None
            else:
                action = None
                source = source
            if target_name == 'env/observations':
                observation = target_cname
                target = None
            else:
                observation = None
                target = target
            if name == source_name and component == source_comp and cname == source_cname:
                self._disconnect(source, target, action, observation)
            elif name == target_name and component == target_comp and cname == target_cname:
                self._disconnect(source, target, action, observation)

    def _disconnect_action(self, action: str):
        """
        Returns the action entry back to its disconnected state.
        That is, remove space_converter if it is not connected to any other targets.
        """
        params_action = self._state['nodes']['env/actions']['params']
        assert action in params_action['outputs'], 'Cannot disconnect action "%s", as it does not exist.' % action
        source = ['env/actions', 'outputs', action]
        connect_exists = False
        for idx, c in enumerate(self._state['connects']):
            if source == c[0]:
                connect_exists = True
                break
        if not connect_exists:
            params_action['outputs'][action] = dict()

    def _disconnect_observation(self, observation: str):
        """
        Returns the observation entry back to its disconnected state (i.e. empty dict).
        """
        params_obs = self._state['nodes']['env/observations']['params']
        assert observation in params_obs[
            'inputs'], 'Cannot disconnect observation "%s", as it does not exist.' % observation
        params_obs['inputs'][observation] = dict()

    def rename(self, old, new, name: Optional[str] = None, component: Optional[str] = None):
        if (name is not None) and (component is not None):  # component renaming
            self._rename_component(name, component, old_cname=old, new_cname=new)
        elif (name is None) and (component is None):  # node/object renaming
            self._rename_entity(old_name=old, new_name=new)
        else:
            raise ValueError('Either the arguments {name, component} are None, or they must both be specified.')

    def _rename_component(self, name: str, component: str, old_cname: str, new_cname: str):
        """
        Renames the component name (cname) of an entity (node/object) in _state['nodes'] and self._state[connects].
        We cannot change names for node/object components, because their python implementation could depend on it.
        Does not work for feedthroughs.
        """
        self._exist(self._state, name, component=component, cname=old_cname)
        default = self._state['nodes'][name]['default']
        params = self._state['nodes'][name]['params']

        # For now, we only support changing action/observation cnames
        assert name in ['env/observations', 'env/actions'], 'Cannot change "%s" of "%s". Only name changes to observations and actions are supported.' % (old_cname, name)
        assert new_cname not in params[component], '"%s" already defined in "%s" under %s.' % (new_cname, name, component)

        # Rename cname in params
        # Does not work for outputs with feedthroughs. Then, both outputs and feedthroughs cnames must be changed.
        for d in (params, default):
            if component in d and old_cname in d[component]:
                assert new_cname not in d[component], '"%s" already defined in "%s" under %s.' % (new_cname, name, component)
                d[component][new_cname] = d[component].pop(old_cname)
            if component in d['default'] and old_cname in d['default'][component]:
                assert new_cname not in d['default'][component], '"%s" already defined in "%s" under %s.' % (new_cname, name, component)
                d['default'][component].remove(old_cname)
                d['default'][component].append(new_cname)

        # Rename cname in all connects
        for source, target in self._state['connects']:
            source_name, source_comp, source_cname = source
            target_name, target_comp, target_cname = target

            if source_comp == component and source_cname == old_cname:
                source[2] = new_cname
            if target_comp == component and target_cname == old_cname:
                target[2] = new_cname

    def _rename_entity(self, old_name: str, new_name: str):
        """
        Renames the entity (node/object) in _state['nodes'] and self._state[connects]
        """
        self._exist(self._state, old_name)
        assert old_name not in ['env/observations', 'env/actions', 'env/render'], 'Node name "%s" is fixed and cannot be changed.' % old_name
        assert new_name not in self._state['nodes'], 'There is already a node or object registered in this graph with name "%s".' % new_name

        # Rename entity in params
        self._state['nodes'][new_name] = self._state['nodes'].pop(old_name)
        self._state['nodes'][new_name]['default']['default']['name'] = new_name
        self._state['nodes'][new_name]['params']['default']['name'] = new_name

        # Rename in all connects
        for source, target in self._state['connects']:
            source_name, source_comp, source_cname = source
            target_name, target_comp, target_cname = target

            if source_name == old_name:
                source[0] = new_name
            if target_name == old_name:
                target[0] = new_name

    def set_parameter(self, parameter: str, value: Any, name: Optional[str] = None, component: Optional[str] = None, cname: Optional[str] = None, action: Optional[str] = None, observation: Optional[str] = None):
        """
        A wrapper to set a single parameter. See set_parameters for more info.
        """
        return self.set_parameters({parameter: value}, name=name, component=component, cname=cname, action=action, observation=observation)

    def set_parameters(self, mapping: Dict[str, Any], name: Optional[str] = None, component: Optional[str] = None, cname: Optional[str] = None, action: Optional[str] = None, observation: Optional[str] = None):
        """
        Sets parameters in self._state, based on the node/object name. If a component and cname are specified, the
        parameter will be set there. Else, the parameter is set under the "default" key.
        For objects, parameters are set under their agnostic definitions of the components (so not bridge specific).
        If a converter is added, we check if the msg_type changes with the new converter. If so, the component is
        disconnected. See _set_converter for more info.
        """
        self._correct_signature(name, component, cname, action, observation)
        if action:
            name = 'env/actions'
            component = 'outputs'
            cname = action
        if observation:
            name = 'env/observations'
            component = 'inputs'
            cname = observation
        self._exist(self._state, name, component=component, cname=cname)

        if (component is not None) and (cname is not None):  # component parameter
            for parameter, value in mapping.items():
                self._exist(self._state, name, component=component, cname=cname, parameter=parameter)
                if parameter == 'converter':
                    if isinstance(value, BaseConverter):
                        value = value.get_yaml_definition()
                    self._set_converter(name, component, cname, value)
                else:
                    self._state['nodes'][name]['params'][component][cname][parameter] = value
        else:  # Default parameter
            for parameter, value in mapping.items():
                self._exist(self._state, name, component=component, cname=cname, parameter=parameter)
                assert parameter not in ['sensors', 'actuators', 'targets', 'states', 'inputs', 'outputs'], 'You cannot modify component parameters with this function. Use _add/remove_component(..) instead.'
                assert parameter not in ['config_name', 'package_name'], 'Cannot change the config_name or package_name parameter.'
                assert parameter not in ['name'], 'You cannot rename with this function. Use rename_(name) instead.'
                default = self._state['nodes'][name]['params']['default']
                default[parameter] = value

    def _set_converter(self, name: str, component: str, cname: str, converter: Dict):
        """
        Replaces the converter specified for a node's/object's I/O.
        **DOES NOT** remove observation entries if they are disconnected.
        **DOES NOT** remove action entries if they are disconnect and the last connection.
        """
        self._exist(self._state, name, component=component, cname=cname, parameter='converter')
        params = self._state['nodes'][name]['params']

        # Check if converted msg_type of old converter is equal to the msg_type of newly specified converter
        msg_type = get_cls_from_string(params[component][cname]['msg_type'])
        converter_old = params[component][cname]['converter']
        msg_type_ros_old = get_opposite_msg_cls(msg_type, converter_old)
        msg_type_ros_new = get_opposite_msg_cls(msg_type, converter)
        if not msg_type_ros_new == msg_type_ros_old:
            self._disconnect_component(name, component, cname)

        # Replace converter
        params[component][cname]['converter'] = converter

    def get_parameter(self, parameter: str, name: Optional[str] = None, component: Optional[str] = None, cname: Optional[str] = None, action: Optional[str] = None, observation: Optional[str] = None, default=None):
        """
        Get node/object parameters. If component and cname are specified, get the parameter of them instead.
        If default was specified, get default parameter instead. Else, raise an error.
        """
        self._correct_signature(name, component, cname, action, observation)
        if action:
            name = 'env/actions'
            component = 'outputs'
            cname = action
        if observation:
            name = 'env/observations'
            component = 'inputs'
            cname = observation
        try:
            self._exist(self._state, name, component, cname, parameter=parameter)
            if (component is not None) and (cname is not None):  # component parameter
                return self._state['nodes'][name]['params'][component][cname][parameter]
            else:  # default parameter
                return self._state['nodes'][name]['params']['default'][parameter]
        except AssertionError:
            if default:
                return default
            else:
                raise

    def get_parameters(self, name: Optional[str] = None, component: Optional[str] = None, cname: Optional[str] = None, action: Optional[str] = None, observation: Optional[str] = None):
        """
        Get all node/object parameters. If component and cname are specified, get the parameters of them instead.
        """
        self._correct_signature(name, component, cname, action, observation)
        if action:
            name = 'env/actions'
            component = 'outputs'
            cname = action
        if observation:
            name = 'env/observations'
            component = 'inputs'
            cname = observation
        self._exist(self._state, name, component, cname)
        if (component is not None) and (cname is not None):  # component parameter
            return self._state['nodes'][name]['params'][component][cname]
        else:  # default parameter
            return self._state['nodes'][name]['params']['default']

    def _reset_converter(self, name: str, component: str, cname: str):
        """
        Replaces the converter specified for a node's/object's I/O defined in self._state[name]['default'].
        **DOES NOT** remove observation entries if they are disconnected.
        **DOES NOT** remove action entries if they are disconnect and the last connection.
        """
        default = self._state['nodes'][name]['default']
        self._exist(self._state, name, component=component, cname=cname, parameter='converter', check_default=True)

        # Grab converter from the default params
        converter_default = default[component][cname]['converter']

        # Replace the converter with the default converter
        self._set_converter(name, component, cname, converter_default)

    def register_graph(self):
        """
        Set the addresses in all incoming components.
        Validate the graph.
        Create params that can be uploaded to the ROS param server.
        """
        # Check if valid graph.
        assert self.is_valid(plot=False), 'Graph not valid.'

        # Add addresses based on connections
        state = deepcopy(self._state)
        for source, target in state['connects']:
            source_name, source_comp, source_cname = source
            target_name, target_comp, target_cname = target
            address = '%s/%s/%s' % (source_name, source_comp, source_cname)
            state['nodes'][target_name]['params'][target_comp][target_cname]['address'] = address

        # Initialize param objects
        nodes = []
        objects = []
        render = None
        actions = None
        observations = None
        for name, entry in state['nodes'].items():
            params = entry['params']
            if 'node_type' in params:
                if name == 'env/actions':
                    actions = RxNodeParams(name, params)
                elif name == 'env/observations':
                    observations = RxNodeParams(name, params)
                elif name == 'env/render':
                    render = RxNodeParams(name, params)
                else:
                    nodes.append(RxNodeParams(name, params))
            else:
                objects.append(RxObjectParams(name, params))

        assert actions, 'No action node defined in the graph.'
        assert observations, 'No observation node defined in the graph.'
        return nodes, objects, actions, observations, render

    def render(self, source: Tuple[str, str, str], rate: float, converter: Optional[Dict] = None, window: Optional[int] = None, delay: Optional[float] = None,
               package_name='eagerx_core', config_name='render', **kwargs):
        # Delete old render node from self._state['nodes'] if it exists
        if 'env/render' in self._state['nodes']:
            self.remove('env/render')

        # Add (new) render node to self._state['node']
        render = RxNodeParams.create('env/render', package_name, config_name, rate=rate, **kwargs)
        self.add(render)

        # Create connection
        target = ('env/render', 'inputs', 'image')
        self.connect(source=source, target=target, converter=converter, window=window, delay=delay)

    def save(self, path: str):
        with open(path, 'w') as outfile:
            yaml.dump(self._state, outfile, default_flow_style=False)
        pass

    def load(self, path: str):
        with open(path, "r") as stream:
            try:
                self._state = yaml.safe_load(stream)
                # self._state = yaml.load(path)
            except yaml.YAMLError as exc:
                print(exc)

    def update(self, entities: Optional[List[str]]=None):
        # todo: updates the default params to the yaml as specified in the config.
        # todo: update actual params with additional default args & new I/O & name changes & new bridge implementations
        # todo: if None, update all entities
        assert False, 'Not implemented'

    def gui(self):
        # todo: JELLE opens gui with state and outputs state
        assert False, 'Not implemented'
        self._state = RxGui(deepcopy(self._state))

    @staticmethod
    def _exist(state: Dict, name: str, component: Optional[str] = None, cname: Optional[str] = None, parameter: Optional[str] = None, check_default: Optional[bool] = False):
        """
        Check if provided entry exists.
        """
        # Check that node/object exists
        assert name in state['nodes'], 'There is no node or object registered in this graph with name "%s".' % name

        # See if we must check both default and current params.
        if check_default:
            check_params = (state['nodes'][name]['params'], state['nodes'][name]['default'])
        else:
            check_params = (state['nodes'][name]['params'],)

        # Check params
        for params in check_params:
            default = params['default']

            # Check that components and specific entry (cname) exists
            assert component is None or component in params, 'Component "%s" not present in "%s". Check config "%s.yaml" of "%s" in package "%s".' % (component, name, default['config_name'], default['name'], default['package_name'])
            if component is None:
                assert cname is None, 'Cannot check if "%s" exists, because no component was specified.' % cname
            assert cname is None or cname in params[component], '"%s" not defined in "%s" under %s. Check config "%s.yaml" of "%s" in package "%s".' % (cname, name, component, default['config_name'], default['name'], default['package_name'])

            # check that parameter exists
            if parameter is not None:
                if (component is not None) and (cname is not None):  # component parameter
                    assert parameter in params[component][cname], 'Cannot set parameter "%s". Parameter does not exist in "%s" under %s. Check config "%s.yaml" of "%s" in package "%s".' % (parameter, cname, component, default['config_name'], default['name'], default['package_name'])
                else:
                    assert parameter in default, 'Cannot set parameter "%s". Parameter does not exist under "default". Check config "%s.yaml" of "%s" in package "%s".' % (parameter, default['config_name'], default['name'], default['package_name'])

    @staticmethod
    def _is_selected(state: Dict, name: str, component: str, cname: str):
        """
        Check if provided entry was selected in params.
        """
        RxGraph._exist(state, name, component, cname)
        params = state['nodes'][name]['params']
        component = 'outputs' if component == 'feedthroughs' else component
        assert cname in params['default'][component], '"%s" not selected in "%s" under "default" in %s. ' % (cname, name, component)

    @staticmethod
    def _correct_signature(name: Optional[str] = None, component: Optional[str] = None, cname: Optional[str] = None, action: Optional[str] = None, observation: Optional[str] = None):
        # assert only action, only observation, or only name, component, cname
        if (name is not None) and (component is not None) and (cname is not None):  # component parameter
            assert action is None, 'If {name, component, cname} are specified, action argument cannot be specified.'
            assert observation is None, 'If {name, component, cname} are specified, observation argument cannot be specified.'
        if name is not None:  # entity parameter
            assert action is None, 'If {name, component, cname} are specified, action argument cannot be specified.'
            assert observation is None, 'If {name, component, cname} are specified, observation argument cannot be specified.'
        if component is not None:  # entity parameter
            assert name is not None, 'Either both or None of component "%s" and name "%s" must be specified.' % (component, name)
            assert action is None, 'If {name, component, cname} are specified, action argument cannot be specified.'
            assert observation is None, 'If {name, component, cname} are specified, observation argument cannot be specified.'
        if cname is not None:  # entity parameter
            assert name is not None, 'Either both or None of component "%s" and name "%s" must be specified.' % (component, name)
            assert component is not None, 'If cname "%s" is specified, also component "%s" and name "%s" must be specified.' % (cname, component, name)
            assert action is None, 'If {name, component, cname} are specified, action argument cannot be specified.'
            assert observation is None, 'If {name, component, cname} are specified, observation argument cannot be specified.'
        if action:
            assert observation is None, 'If action is specified, observation must be None.'
            assert (name is None) and (component is None) and (cname is None), 'If action is specified, arguments {name, component, cname} cannot be specified.'
        if observation:
            assert action is None, 'If observation is specified, action must be None.'
            assert (name is None) and (component is None) and (cname is None), 'If action is specified, arguments {name, component, cname} cannot be specified.'

    def is_valid(self, plot=True):
        return self._is_valid(self._state, plot=plot)

    @staticmethod
    def _is_valid(state, plot=True):
        state = deepcopy(state)
        RxGraph.check_msg_types_are_consistent(state)
        RxGraph.check_inputs_have_address(state)
        RxGraph.check_graph_is_acyclic(state, plot=plot)
        RxGraph.check_exists_compatible_bridge(state)
        return True

    @staticmethod
    def check_msg_type(source, target, state):
        source_name, source_comp, source_cname = source
        source_params = state['nodes'][source_name]['params']
        target_name, target_comp, target_cname = target
        target_params = state['nodes'][target_name]['params']

        # Convert the source msg_type to target msg_type with converters:
        # msg_type_source --> output_converter --> msg_type_ROS --> input_converter --> msg_type_target
        msg_type_out = get_cls_from_string(source_params[source_comp][source_cname]['msg_type'])
        converter_out = source_params[source_comp][source_cname]['converter']
        msg_type_ros = get_opposite_msg_cls(msg_type_out, converter_out)
        converter_in = target_params[target_comp][target_cname]['converter']
        msg_type_in = get_opposite_msg_cls(msg_type_ros, converter_in)

        # Verify that this msg_type_in is the same as the msg_type specified in the target
        if target_comp == 'feedthroughs':
            msg_type_in_target = get_cls_from_string(target_params['outputs'][target_cname]['msg_type'])
        else:
            msg_type_in_target = get_cls_from_string(target_params[target_comp][target_cname]['msg_type'])

        msg_type_str = '\n\nConversion of msg_type from source="%s/%s/%s" ---> target="%s/%s/%s":\n\n' % tuple(
            source + target)
        msg_type_str += '>> msg_type_source:  %s (as specified in source)\n         ||\n         \/\n' % msg_type_out
        msg_type_str += '>> output_converter: %s \n         ||\n         \/\n' % converter_out
        msg_type_str += '>> msg_type_ROS:     %s \n         ||\n         \/\n' % msg_type_ros
        msg_type_str += '>> input_converter:  %s \n         ||\n         \/\n' % converter_in
        msg_type_str += '>> msg_type_target:  %s (inferred from converters)\n         /\ \n         || (These must be equal, but they are not!!)\n         \/\n' % msg_type_in
        msg_type_str += '>> msg_type_target:  %s (as specified in target)\n' % msg_type_in_target
        assert msg_type_in == msg_type_in_target, msg_type_str

    @staticmethod
    def check_msg_types_are_consistent(state):
        for source, target in state['connects']:
            RxGraph.check_msg_type(source, target, state)
        return True

    @staticmethod
    def check_inputs_have_address(state):
        state = deepcopy(state)
        for source, target in state['connects']:
            source_name, source_comp, source_cname = source
            target_name, target_comp, target_cname = target
            address = '%s/%s/%s' % (source_name, source_comp, source_cname)
            state['nodes'][target_name]['params'][target_comp][target_cname]['address'] = address

        for name, entry in state['nodes'].items():
            params = entry['params']
            if 'node_type' in params:
                for component in params['default']:
                    if component not in ['inputs', 'outputs', 'targets', 'feedthroughs', 'states']:
                        continue
                    for cname in params['default'][component]:
                        assert cname in params[component], '"%s" was selected in %s of "%s", but has no implementation.' % (cname, component, name)
                        if component not in ['inputs', 'targets', 'feedthroughs']: continue
                        assert 'address' in params[component][cname], '"%s" was selected in %s of "%s", but no address was specified. Either deselect it, or connect it.' % (cname, component, name)
            else:
                for component in params['default']:
                    if component not in ['sensors', 'actuators', 'states']:
                        continue
                    for cname in params['default'][component]:
                        assert cname in params[component], '"%s" was selected in %s of "%s", but has no (agnostic) implementation.' % (cname, component, name)
                        if component not in ['actuators']: continue
                        assert 'address' in params[component][cname], '"%s" was selected in %s of "%s", but no address was specified. Either deselect it, or connect it.' % (cname, component, name)
        return True

    @staticmethod
    def check_graph_is_acyclic(state, plot=True):
        # Add nodes
        G = nx.MultiDiGraph()
        for node, params in state['nodes'].items():
            default = params['params']['default']
            if 'node_type' not in state['nodes'][node]['params']:  # Object
                if 'sensors' in default and len(default['sensors']) > 0:
                    G.add_node('%s/sensors' % node, remain_active=False, always_active=True, is_stale=False)
                if 'actuators' in default and len(default['actuators']) > 0:
                    G.add_node('%s/actuators' % node, remain_active=True, always_active=False, is_stale=False)
            else:  # node
                G.add_node(node, remain_active=False, always_active=False, is_stale=False)

        # Add edges
        target_comps = ['inputs', 'actuators', 'feedthroughs']
        source_comps = ['outputs', 'sensors']
        G.add_edge('env/observations', 'env/actions', key='%s/%s' % ('inputs', 'observations_set'),
                   feedthrough=False, style='solid', color='black', alpha=1.0, is_stale=False, start_with_msg=False,
                   source=('env/observations', 'outputs', 'set'), target=('env/actions', 'inputs', 'observations_set'))
        for source, target in state['connects']:
            source_name, source_comp, source_cname = source
            target_name, target_comp, target_cname = target
            if source_comp in source_comps and target_comp in target_comps:
                edge = []
                for name, comp in zip((source_name, target_name), (source_comp, target_comp)):
                    if 'node_type' in state['nodes'][name]['params']:
                        node_name = name
                    else:
                        node_name = '%s/%s' % (name, comp)
                    edge.append(node_name)

                # Determine stale nodes in real_reset routine via feedthrough edges
                if target_comp == 'feedthroughs':
                    feedthrough = True
                else:
                    feedthrough = False

                # Determine edges that do not break DAG property (i.e. edges that start with an initial message)
                start_with_msg = state['nodes'][source_name]['params'][source_comp][source_cname]['start_with_msg']
                key = '%s/%s' % (target_comp, target_cname)
                color = 'green' if start_with_msg else 'black'
                style = 'dotted' if start_with_msg else 'solid'

                # Add edge
                G.add_edge(edge[0], edge[1], key=key, color=color, feedthrough=feedthrough, style=style, alpha=1.0,
                           is_stale=False, start_with_msg=start_with_msg, source=source, target=target)

        # Color nodes based on in/out going edges
        not_active = is_stale(G)
        color_nodes(G)
        color_edges(G)

        # Remap action & observation labels to more readable form
        label_mapping = {'env/observations': 'observations', 'env/actions': 'actions', 'env/render': 'render'}
        G = nx.relabel_nodes(G, label_mapping)

        # Check if graph is acyclic (excluding 'start_with_msg' edges)
        H, cycles = episode_graph(G)
        is_dag = nx.is_directed_acyclic_graph(H)

        # Plot graphs
        if plot:
            fig_env, ax_env = plt.subplots(nrows=1, ncols=1)
            ax_env.set_title('Communication graph (episode)')
            _, _, _, pos = plot_graph(G, k=2, ax=ax_env)
            plt.show()

        # Assert if graph is a directed-acyclical graph (DAG)
        cycle_strs = ['Algebraic loops detected: ']
        for idx, connect in enumerate(cycles):
            connect.append(connect[0])
            s = ' Loop %s: ' % idx
            n = '\n' + ''.join([' ']*len(s)) + '...-->'
            s = '\n\n' + s + '...-->'
            for idx in range(len(connect)-1):
                tmp, target = connect[idx]
                source, tmp2 = connect[idx+1]
                source_name, source_comp, source_cname = source
                target_name, target_comp, target_cname = target
                assert source_name == target_name, 'Source and target not equal: %s, %s' % (source, target)
                connect_name = '%s/%s/%s][%s/%s/%s' % tuple(list(source) + list(target))
                node_name = ('Node: ' + source_name).center(len(connect_name), ' ')
                s += '[%s]-->' % connect_name
                n += '[%s]-->' % node_name
            s += '...'
            n += '...'
            cycle_strs.append(s)
            cycle_strs.append(n)
            connect.pop(-1)
        assert is_dag, ''.join(cycle_strs)
        assert len(not_active) == 0, 'Stale episode graph detected. Nodes "%s" will be stale, while they must be active (i.e. connected) in order for the graph to resolve (i.e. not deadlock).' % not_active

        # Create a shallow copy graph that excludes feedthrough edges
        F = reset_graph(G)
        not_active = is_stale(F)
        color_nodes(F)
        color_edges(F)

        # Plot graphs
        if plot:
            fig_reset, ax_reset = plt.subplots(nrows=1, ncols=1)
            ax_reset.set_title('Communication graph (reset)')
            _, _, _, pos = plot_graph(F, pos=pos, ax=ax_reset)
            plt.show()

        # Assert if reset graph is not stale
        has_real_reset = len([e for e, ft in nx.get_edge_attributes(G, 'feedthrough').items() if ft]) > 0
        assert len(not_active) == 0 or not has_real_reset, 'Stale reset graph detected. Nodes "%s" will be stale, while they must be active (i.e. connected) in order for the graph to resolve (i.e. not deadlock).' % not_active
        return True

    @staticmethod
    def check_exists_compatible_bridge(state):
        # Bridges are headers
        bridges = []
        objects = []
        for node, params in state['nodes'].items():
            default = params['params']['default']
            # todo: only check bridge if it concerns one of the selected components
            if 'node_type' not in state['nodes'][node]['params']:  # Object
                params = state['nodes'][node]['params']
                package = '%s/%s' % (params['default']['package_name'], params['default']['config_name'])
                obj_name = params['default']['name']
                entry = [obj_name, package]

                # Add all (unknown) bridges to the list
                for key, value in params.items():
                    if key in ['default', 'sensors', 'actuators', 'states']: continue
                    if key not in bridges:
                        bridges.append(key)

                # See what bridges support all object components
                for b in bridges:
                    if b in params:
                        for component in ['sensors', 'actuators', 'states']:
                            if component in default:
                                for cname in default[component]:
                                    if component in params[b] and cname in params[b][component]:
                                        e_str = 'x'  # Component entry is supported
                                    else:
                                        e_str = ' '  # Component entry is not supported
                                        break  # Break if entry in component is not supported
                            else:
                                raise KeyError('No components in %s' % default)
                    else:  # Bridge name not even mentioned in object config
                        e_str = ' '
                    entry.append(e_str)
                objects.append(entry)

        # Fill up incompatible bridges that were added after object entries
        for entry in objects:
            for b in bridges[len(entry)-2:]:
                entry.append(' ')

        # Get compatible bridges
        compatible = []
        for idx, b in enumerate(bridges):
            idx = idx + 2
            for entry in objects:
                c = [True if entry[idx] == 'x' else False for entry in objects]
            if len(c) == len(objects):
                compatible.append(b)

        # Objects are entries
        headers = ['\nname', '\nobject']
        for b in bridges:
            headers.append(b.replace('/', '/\n'))

        # Assert if there are compatible bridges
        tabulate_str = tabulate(objects, headers=headers, tablefmt="fancy_grid", colalign=["center"]*len(headers))
        assert len(compatible), 'No compatible bridges for the selected objects. Ensure that all components, selected in each object, is supported by a common bridge.\n%s' % tabulate_str
        return True
