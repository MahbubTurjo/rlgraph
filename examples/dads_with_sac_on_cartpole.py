# Copyright 2018/2019 The RLgraph authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================

"""
Example script for training a DADS algorithm on an OpenAI gym environment using the DADSWorker and
any Agent.
Config must contain "agent_spec" and optionally a "environment_spec". Alternatively, the environment
spec can be the --env command line flag (the openAI gym ID). Env given on command line will overwrite
the spec given in the config file.

Usage:
python dads_with_sac_on_cartpole.py [--config configs/dads_with_sac_on_cartpole.json] (--env [openAI gym ID])?
"""

import json
import os
import sys

import numpy as np
from absl import flags

from rlgraph.environments import OpenAIGymEnv
from rlgraph.execution import DADSWorker

FLAGS = flags.FLAGS

flags.DEFINE_string('config', './configs/dads_with_sac_on_cartpole.json', 'DADSWorker config file.')
flags.DEFINE_string('env', None, 'gym environment ID.')
flags.DEFINE_bool('render', False, 'Whether to render the Env.')


def main(argv):
    try:
        FLAGS(argv)
    except flags.Error as e:
        print('%s\\nUsage: %s ARGS\\n%s' % (e, sys.argv[0], FLAGS))

    worker_config_path = os.path.join(os.getcwd(), FLAGS.config)
    with open(worker_config_path, 'rt') as fp:
        worker_config = json.load(fp)

    env_spec = FLAGS.env or worker_config.get("environment_spec", {
        "type": "openai",
        "gym_env": FLAGS.env
    })
    env = OpenAIGymEnv.from_spec(env_spec)

    episode_returns = []

    def episode_finished_callback(episode_return, duration, timesteps):
        episode_returns.append(episode_return)
        if len(episode_returns) % 10 == 0:
            print("Episode {} finished: reward={:.2f}, average reward={:.2f}.".format(
                len(episode_returns), episode_return, np.mean(episode_returns[-10:])
            ))

    worker = DADSWorker(
        agent_spec=worker_config.get("agent_spec"),
        env_spec=lambda: env,
        skill_dynamics_model_spec=worker_config.get("skill_dynamics_model_spec"),
        render=FLAGS.render, worker_executes_preprocessing=False,
        episode_finish_callback=episode_finished_callback
    )
    print("Starting workload, this will take some time for the agents to build.")

    # Use exploration is true for training, false for evaluation.
    worker.execute_timesteps(10000, use_exploration=True)

    print("Mean reward: {:.2f} / over the last 10 episodes: {:.2f}".format(
        np.mean(episode_returns), np.mean(episode_returns[-10:])
    ))


if __name__ == '__main__':
    main(sys.argv)
