import collections
from abc import ABC, abstractmethod

import numpy as np
import scipy.signal
import tensorflow as tf

from rl.utils import RingBuffer

ReplayField = collections.namedtuple(
    'ReplayField',
    ['name', 'dtype', 'shape'],
    defaults=[np.float32, ()]
)


class ReplayBuffer(ABC):
    def __init__(self, buffer_size, store_fields, compute_fields, gamma=1.0, lambda_=1.0):
        self.buffer_size = buffer_size
        self.store_fields = store_fields
        self.compute_fields = compute_fields
        self.gamma = gamma
        self.lambda_ = lambda_

        self.compute_config = {
            'advantage': {
                'func': self._compute_advantage,
                'dependencies': {'done', 'reward', 'value', 'value_next'}
            },
            'reward_to_go': {
                'func': self._compute_reward_to_go,
                'dependencies': {'done', 'reward'}
            },
            'episode_return': {
                'func': self._compute_episode_return,
                'dependencies': {'done', 'reward'}
            },
            'episode_length': {
                'func': self._compute_episode_length,
                'dependencies': {'done'}
            },
        }
        store_field_names = {f.name for f in self.store_fields}
        for f in self.compute_fields:
            dependencies = self.compute_config[f.name]['dependencies']
            if not dependencies.issubset(store_field_names):
                raise ValueError(f'Compute field {f.name} requires store fields {dependencies}')

        self.buffers = {f.name: RingBuffer(self.buffer_size, f.shape, f.dtype)
                        for f in self.store_fields + self.compute_fields}
        self.current_size, self.compute_head = 0, 0

    @abstractmethod
    def as_dataset(self, *args, **kwargs):
        self._compute()

    def purge(self):
        for buffer in self.buffers.values():
            buffer.purge()
        self.current_size, self.compute_head = 0, 0

    def store_transition(self, transition):
        for f in self.store_fields:
            self.buffers[f.name].append(transition[f.name])
        for f in self.compute_fields:
            self.buffers[f.name].append(np.zeros(f.shape))
        if self.current_size == self.buffer_size:
            self.compute_head = max(self.compute_head - 1, 0)
        self.current_size = min(self.current_size + 1, self.buffer_size)

    def _compute(self):
        if self.compute_head == self.current_size:
            return

        indices = np.arange(self.compute_head, self.current_size)
        tail_indices = 1 + indices[self.buffers['done'][self.compute_head:]]
        # If the last index is not done, add it to the tail_indices
        if self.buffers['done'][-1] is False:
            tail_indices = np.concatenate((tail_indices, [self.current_size]))

        for compute_tail in tail_indices:
            for f in self.compute_fields:
                self.compute_config[f.name]['func'](self.compute_head, compute_tail)
            # If the last index is not done, do not move the compute_head
            if compute_tail < self.current_size or self.buffers['done'][-1]:
                self.compute_head = compute_tail

    def _compute_advantage(self, head, tail):
        rewards = self.buffers['reward'][head:tail]
        values = self.buffers['value'][head:tail]
        value_nexts = self.buffers['value_next'][head:tail]
        deltas = rewards + self.gamma * value_nexts - values
        self.buffers['advantage'][head:tail] = self._discounted_cumsum(deltas, self.gamma * self.lambda_)

    def _compute_reward_to_go(self, head, tail):
        rewards = self.buffers['reward'][head:tail]
        self.buffers['reward_to_go'][head:tail] = self._discounted_cumsum(rewards, self.gamma)

    def _compute_episode_return(self, head, tail):
        episode_return = np.sum(self.buffers['reward'][head:tail])
        self.buffers['episode_return'][head:tail] = episode_return

    def _compute_episode_length(self, head, tail):
        self.buffers['episode_length'][head:tail] = tail - head + 1

    @staticmethod
    def _discounted_cumsum(values, discount):
        """
        Example:
        values = [1,2,3], discount = 0.9
        returns = [1 * 0.9^0 + 2 * 0.9^1 + 3 * 0.9^3,
                   2 * 0.9^0 + 3 * 0.9^1,
                   3 * 0.9^0]
        """
        return scipy.signal.lfilter([1], [1, float(-discount)], values[::-1], axis=0)[::-1]


class OnePassReplayBuffer(ReplayBuffer):
    def as_dataset(self, batch_size=32):
        def data_generator():
            for i in np.random.default_rng().choice(self.current_size, size=self.current_size, replace=False):
                yield {f.name: self.buffers[f.name][i.item()]
                       for f in self.store_fields + self.compute_fields}

        super().as_dataset()
        dataset = tf.data.Dataset.from_generator(
            data_generator,
            output_types={f.name: tf.as_dtype(f.dtype) for f in self.store_fields + self.compute_fields},
            output_shapes={f.name: f.shape for f in self.store_fields + self.compute_fields}
        )
        dataset = dataset.batch(batch_size)
        dataset = dataset.prefetch(tf.data.AUTOTUNE)
        return dataset


class UniformReplayBuffer(ReplayBuffer):
    def as_dataset(self, batch_size=32):
        def data_generator():
            i = np.random.randint(self.current_size)
            yield {k: buf[i] for k, buf in self.buffers.items()}

        super().as_dataset()
        dataset = tf.data.Dataset.from_generator(
            data_generator,
            output_types={f.name: tf.as_dtype(f.dtype) for f in self.store_fields + self.compute_fields},
            output_shapes={f.name: f.shape for f in self.store_fields + self.compute_fields}
        )
        dataset = dataset.repeat(-1)
        dataset = dataset.batch(batch_size)
        dataset = dataset.prefetch(tf.data.AUTOTUNE)
        return dataset
