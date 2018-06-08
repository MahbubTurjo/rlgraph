# Copyright 2018 The YARL-Project, All Rights Reserved.
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

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from yarl.components import Component
from yarl.spaces import Space


class Memory(Component):
    """
    Abstract memory component.
    """

    def __init__(self, capacity=1000, scope="memory", **kwargs):
        """
        Args:
            capacity (int): Maximum capacity of the memory.
        """
        super(Memory, self).__init__(scope=scope, **kwargs)

        # Variables (will be populated in create_variables).
        self.record_space = None
        self.record_registry = None
        self.capacity = capacity

        # Add default Sockets and insert GraphFunction.
        self.define_inputs("records")
        self.define_outputs("insert")

        self.add_graph_fn(inputs="records", outputs="insert", method=self._graph_fn_insert)

    def create_variables(self, input_spaces, action_space):
        # Store our record-space for convenience.
        self.record_space = input_spaces["records"]

        #  Create the main memory as a flattened OrderedDict from any arbitrarily nested Space.
        self.record_registry = self.get_variable(
            name="memory", trainable=False,
            from_space=self.record_space,
            flatten=True,
            add_batch_rank=self.capacity
        )

    def _graph_fn_insert(self, records):
        """
        Inserts one or more complex records.

        Args:
            records (FlattenedDataOp): FlattenedDataOp containing record data. Keys must match keys in record
                space.
        """
        raise NotImplementedError

    def _graph_fn_get_records(self, num_records):
        """
        Returns a number of records according to the retrieval strategy implemented by
        the memory.

        Args:
            num_records (int): Number of records to return.

        Returns:
            DataOpDict: The retrieved records.
        """
        raise NotImplementedError

    def _graph_fn_get_episodes(self, num_episodes):
        """
        Retrieves a given number of episodes.

        Args:
            num_episodes (int): Number of episodes to retrieve.

        Returns: The retrieved episodes.
        """
        pass

    def _graph_fn_clear(self):
        """
        Removes all entries from memory.
        """
        # Optional?
        pass

    def _graph_fn_update_records(self, indices, update):
        """
        Optionally updates memory records using information such as losses, e.g. to
        compute priorities.

        Args:
            indices (Union[ndarray,tf.Tensor]): The indices in the memory to update.
            update (any): Any information relevant to update records, e.g. losses of most recently read batch
                of records.
        """
        pass
