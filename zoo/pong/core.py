import gym
import numpy as np
import tensorflow as tf
import tensorflow_probability as tfp


class PongEnvWrapper(gym.Wrapper):
    def __init__(self):
        super().__init__(gym.make("Pong-v0"))
        self.observation_space = gym.spaces.Box(low=0, high=1, shape=(80, 80, 4), dtype=np.int8)
        self.state = np.zeros(self.observation_space.shape, dtype=np.int8)

    def step(self, action):
        observation, reward, done, info = super().step(action)
        self.state = np.dstack((self.state, self._preprocess(observation)))[:, :, 1:]
        return self.state, reward, done, info

    def reset(self, **kwargs):
        observation = super().reset(**kwargs)
        self.state = np.zeros(self.observation_space.shape, dtype=np.int8)
        self.state = np.dstack((self.state, self._preprocess(observation)))[:, :, 1:]
        return self.state

    @staticmethod
    def _preprocess(observation):
        observation = observation[34:194]
        observation = observation[::2, ::2, 0]
        observation[observation == 144] = 0
        observation[observation != 0] = 1
        return observation.astype(np.int8)


class PolicyNetwork(tf.keras.Model):
    def __init__(self, input_shape, output_dim):
        super().__init__()
        self.conv1 = tf.keras.layers.Conv2D(filters=8, kernel_size=(5, 5), activation="relu", input_shape=input_shape)
        self.pool1 = tf.keras.layers.MaxPooling2D(pool_size=(2, 2))
        self.conv2 = tf.keras.layers.Conv2D(filters=16, kernel_size=(3, 3), activation="relu")
        self.pool2 = tf.keras.layers.MaxPooling2D(pool_size=(2, 2))
        self.flatten = tf.keras.layers.Flatten()
        self.dense1 = tf.keras.layers.Dense(units=128, activation="relu")
        self.dense2 = tf.keras.layers.Dense(units=output_dim, activation="linear")

    def get_config(self):
        super().get_config()

    def call(self, observations, **kwargs):
        x = self.conv1(tf.cast(observations, tf.float32))
        x = self.pool1(x)
        x = self.conv2(x)
        x = self.pool2(x)
        x = self.flatten(x)
        x = self.dense1(x)
        x = self.dense2(x)
        return x

    def distribution(self, observations):
        logits = self.call(observations)
        return tfp.distributions.Categorical(logits=logits)

    def sample(self, observations):
        return self.distribution(observations).sample()

    def log_prob(self, observations, actions):
        return self.distribution(observations).log_prob(actions)


class ValueFunctionNetwork(tf.keras.Model):
    def __init__(self, input_shape):
        super().__init__()
        self.conv1 = tf.keras.layers.Conv2D(filters=8, kernel_size=(5, 5), activation="relu", input_shape=input_shape)
        self.pool1 = tf.keras.layers.MaxPooling2D(pool_size=(2, 2))
        self.conv2 = tf.keras.layers.Conv2D(filters=16, kernel_size=(3, 3), activation="relu")
        self.pool2 = tf.keras.layers.MaxPooling2D(pool_size=(2, 2))
        self.flatten = tf.keras.layers.Flatten()
        self.dense1 = tf.keras.layers.Dense(units=128, activation="relu")
        self.dense2 = tf.keras.layers.Dense(units=1, activation="linear")

    def get_config(self):
        super().get_config()

    def call(self, observations, **kwargs):
        x = self.conv1(tf.cast(observations, tf.float32))
        x = self.pool1(x)
        x = self.conv2(x)
        x = self.pool2(x)
        x = self.flatten(x)
        x = self.dense1(x)
        x = self.dense2(x)
        return x

    def compute(self, observations):
        return self.call(observations)
