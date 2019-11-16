import torch.nn as nn
import torch.optim as optim
import torch
from collections import namedtuple
import numpy as np
import gym
from torch.utils.tensorboard import SummaryWriter
import os
import time

HIDDEN_SIZE = 128
BATCH_SIZE = 100
PERCENTILE = 70
GAMMA = 0.9

MODEL_PATH = r'C:\github_code\rl\model'


class Net(nn.Module):
    def __init__(self, obs_size, hidden_size, n_actions):
        super(Net, self).__init__()
        self.net = nn.Sequential(
            nn.Linear(obs_size, hidden_size),
            nn.ReLU(),
            nn.Linear(hidden_size, n_actions)
        )

    def forward(self, x):
        return self.net(x)

Episode = namedtuple('Episode', field_names=['reward', 'steps'])
EpisodeStep = namedtuple('EpisodeStep', field_names=['observation', 'action'])

def iterate_batches(env, net, batch_size):
    batch = []
    episode_reward = 0.0
    episode_steps = []
    obs = env.reset()
    sm = nn.Softmax(dim=1)

    while True:
        obs_v = torch.FloatTensor([obs])
        act_probs_v = sm(net(obs_v))
        act_probs = act_probs_v.data.numpy()[0]
        action = np.random.choice(len(act_probs), p=act_probs)
        next_obs, reward, is_done, _ = env.step(action)
        episode_reward += reward
        episode_steps.append(EpisodeStep(observation=obs, action=action))

        if is_done:
            batch.append(Episode(reward=episode_reward, steps=episode_steps))
            episode_reward = 0.0
            episode_steps = []
            next_obs = env.reset()
            if len(batch) == batch_size:
                yield batch
                batch = []

        obs = next_obs

def filter_batch(batch, percentile):
    # tweaked version discounts rewards
    disc_rewards = list(map(lambda s: s.reward * (GAMMA ** len(s.steps)), batch))
    reward_bound = np.percentile(disc_rewards, percentile)

    train_obs = []
    train_act = []
    elite_batch = []
    for example, discounted_reward in zip(batch, disc_rewards):
        if discounted_reward > reward_bound:
            train_obs.extend(map(lambda step: step.observation,
                             example.steps))
            train_act.extend(map(lambda step: step.action, example.steps))
            elite_batch.append(example)

    return elite_batch, train_obs, train_act, reward_bound


class DiscreteOneHotWrapper(gym.ObservationWrapper):
    def __init__(self, env):
        super(DiscreteOneHotWrapper, self).__init__(env)
        assert isinstance(env.observation_space, gym.spaces.Discrete)
        self.observation_space = gym.spaces.Box(0.0, 1.0, (env.observation_space.n, ), dtype=np.float32)

    def observation(self, observation):
        res = np.copy(self.observation_space.low)
        res[observation] = 1.0
        return res


def save_model(net, name):
    # save model
    path = os.path.join(MODEL_PATH, '{}.model'.format(name))
    torch.save(net.state_dict(), path)


if __name__ == '__main__':
    env = gym.make('FrozenLake-v0')
#    env = gym.wrappers.Monitor(env, directory='mon', force=True)
    env = DiscreteOneHotWrapper(env)
    obs_size = env.observation_space.shape[0]
    n_actions = env.action_space.n

    net = Net(obs_size, HIDDEN_SIZE, n_actions)
    objective = nn.CrossEntropyLoss()
    optimizer = optim.Adam(params=net.parameters(), lr=0.001)
    writer = SummaryWriter()

    full_batch = []
    t1 = time.time()
    for iter_no, batch in enumerate(iterate_batches(env, net, BATCH_SIZE)):
        reward_mean = float(np.mean(list(map(lambda s: s.reward, batch))))
        full_batch, obs, acts, reward_bound = filter_batch(full_batch + batch, PERCENTILE)
        if not full_batch:
            continue
        obs_v = torch.FloatTensor(obs)
        acts_v = torch.LongTensor(acts)
        full_batch = full_batch[-500:]

        optimizer.zero_grad()
        action_scores_v = net(obs_v)
        loss_v = objective(action_scores_v, acts_v)
        loss_v.backward()
        optimizer.step()

        t2 = time.time()
        runtime = t2 - t1
        t1 = t2

        print('%d: loss=%.3f, reward_mean=%.3f, reward_bound=%.3f, time=%.2f' %
              (iter_no, loss_v.item(), reward_mean, reward_bound, runtime))
        writer.add_scalar('loss', loss_v.item(), iter_no)
        writer.add_scalar('reward_bound', reward_bound, iter_no)
        writer.add_scalar('reward_mean', reward_mean, iter_no)

        if iter_no % 100 == 0:
            save_model(net, iter_no)

        if reward_mean > 0.5:
            print('solved')
            save_model(net, '{}_final'.format(iter_no))

            break

    writer.close()