from eagerx_core.params import RxBridgeParams
from eagerx_core.rxgraph import RxGraph
from eagerx_core.rxenv import EAGERxEnv
from typing import Dict, Tuple, Callable
import numpy as np
import gym


class EAGERxGym(EAGERxEnv):
    def __init__(self, name: str, rate: float, graph: RxGraph, bridge: RxBridgeParams,
                 reward_fn: Callable = lambda prev_obs, obs, action, steps: obs['reward'][0],
                 is_done_fn: Callable = lambda obs, action, steps: obs['done'][0]) -> None:
        super().__init__(name=name, rate=rate, graph=graph, bridge=bridge, reward_fn=reward_fn, is_done_fn=is_done_fn)
        # Flatten action spaces
        self._reduced_action_space = super(EAGERxGym, self).action_space
        self._flattened_action_space, self._actions_all_discrete = get_flattened_space(self._reduced_action_space)

        # Flatten & reduce observation spaces (remove 'reward' & 'done')
        obs_space = dict(super(EAGERxGym, self).observation_space)
        obs_space.pop('reward', None)
        obs_space.pop('done', None)
        self._reduced_obs_space = gym.spaces.Dict(obs_space)
        self._flattened_obs_space, self._obs_all_discrete = get_flattened_space(self._reduced_obs_space)
        assert not self._obs_all_discrete, 'Only continuous observations are currently supported.'

    @property
    def observation_space(self):
        return self._flattened_obs_space

    @property
    def action_space(self):
        return self._flattened_action_space

    def unflatten_action(self, action):
        # Unflatten action
        if not isinstance(action, np.ndarray):  # Discrete space
            action = np.array([action])
        return gym.spaces.unflatten(self._reduced_action_space, action)

    def flatten_observation(self, obs):
        if not self._obs_all_discrete:
            return gym.spaces.flatten(self._reduced_obs_space, obs)
        else:
            raise ValueError('Only continuous observations are currently supported.')

    def step(self, action: np.ndarray) -> Tuple[np.ndarray, float, bool, Dict]:
        action = self.unflatten_action(action)

        # Apply action
        obs, reward, is_done, info = super(EAGERxGym, self).step(action)

        # Remove 'reward' and 'done' from observation
        obs.pop('reward', None)
        obs.pop('done', None)

        # Flatten observation
        obs = self.flatten_observation(obs)
        return obs, reward, is_done, info

    def reset(self):
        obs = super(EAGERxGym, self).reset()
        obs = self.flatten_observation(obs)
        return obs


def get_flattened_space(spaces):
    if not isinstance(spaces, dict):
        spaces = dict(spaces)
    # Check if all discrete or mixed (with continuous)
    all_discrete = True
    for key, space in spaces.items():
        if isinstance(space, gym.spaces.Box) and not (space.dtype == 'int64' and space.shape == (1,)):
            all_discrete = False
        elif isinstance(space, gym.spaces.MultiDiscrete):
            raise ValueError('MultiDiscrete space not supported.')
    # If all discrete & multiple discrete, initialize MultiDiscrete, else just discrete
    if all_discrete and len(spaces) > 1:
        multi = []
        for key, space in spaces.items():
            multi.append(space.high[0] + 1)
        flattened_space = gym.spaces.MultiDiscrete(multi)
    elif all_discrete and len(spaces) == 1:
        key = list(spaces)[0]
        flattened_space = gym.spaces.Discrete(spaces[key].high[0] + 1)
    else:
        for key, space in spaces.items():
            if isinstance(space, gym.spaces.Box) and space.dtype == 'int64' and space.shape == (1,):
                spaces[key] = gym.spaces.Box(low=space.low.astype('float32'),
                                             high=space.high.astype('float32') + 0.9999, dtype='float32')
        flattened_space = gym.spaces.flatten_space(gym.spaces.Dict(spaces))
    return flattened_space, all_discrete