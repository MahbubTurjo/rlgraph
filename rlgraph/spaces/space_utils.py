# Copyright 2018 The RLgraph authors. All Rights Reserved.
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

from six.moves import xrange as range_
import numpy as np

from rlgraph.spaces import BoxSpace
from rlgraph.utils.util import RLGraphError, dtype, get_shape
from rlgraph.utils.ops import SingleDataOp
from rlgraph.spaces.bool_box import BoolBox
from rlgraph.spaces.int_box import IntBox
from rlgraph.spaces.float_box import FloatBox
from rlgraph.spaces.text_box import TextBox
from rlgraph.spaces.containers import Dict, Tuple


# TODO: replace completely by `Component.get_variable` (python-backend)
def get_list_registry(from_space, capacity=None, initializer=0, flatten=True, add_batch_rank=False):
    """
    Creates a list storage for a space by providing an ordered dict mapping space names
    to empty lists.

    Args:
        from_space: Space to create registry from.
        capacity (Optional[int]): Optional capacity to initalize list.
        initializer (Optional(any)): Optional initializer for list if capacity is not None.
        flatten (bool): Whether to produce a FlattenedDataOp with auto-keys.
        add_batch_rank (Optional[bool,int]): If from_space is given and is True, will add a 0th rank (None) to
            the created variable. If it is an int, will add that int instead of None.
            Default: False.
    Returns:
        dict: Container dict mapping spaces to empty lists.
    """
    if flatten:
        if capacity is not None:
            var = from_space.flatten(
                custom_scope_separator="-", scope_separator_at_start=False,
                mapping=lambda k, primitive: [initializer for _ in range_(capacity)]
            )
        else:
            var = from_space.flatten(
                custom_scope_separator="-", scope_separator_at_start=False,
                mapping=lambda k, primitive: []
            )
    else:
        if capacity is not None:
            var = [initializer for _ in range_(capacity)]
        else:
            var = []
    return var


def get_space_from_op(op):
    """
    Tries to re-create a Space object given some DataOp.
    This is useful for shape inference when passing a Socket's ops through a GraphFunction and
    auto-inferring the resulting shape/Space.

    Args:
        op (DataOp): The op to create a corresponding Space for.

    Returns:
        Space: The inferred Space object.
    """
    # a Dict
    if isinstance(op, dict):  # DataOpDict
        spec = dict()
        add_batch_rank = False
        add_time_rank = False
        for key, value in op.items():
            spec[key] = get_space_from_op(value)
            if spec[key].has_batch_rank:
                add_batch_rank = True
            if spec[key].has_time_rank:
                add_time_rank = True
        return Dict(spec, add_batch_rank=add_batch_rank, add_time_rank=add_time_rank)
    # a Tuple
    elif isinstance(op, tuple):  # DataOpTuple
        spec = list()
        add_batch_rank = False
        add_time_rank = False
        for i in op:
            spec.append(get_space_from_op(i))
            if spec[-1].has_batch_rank:
                add_batch_rank = True
            if spec[-1].has_time_rank:
                add_time_rank = True
        return Tuple(spec, add_batch_rank=add_batch_rank, add_time_rank=add_time_rank)
    # primitive Space -> infer from op dtype and shape
    else:
        # Simple constant value DataOp (python type or an np.ndarray).
        if isinstance(op, SingleDataOp) and op.constant_value is not None:
            value = op.constant_value
            if isinstance(value, np.ndarray):
                return BoxSpace.from_spec(spec=dtype(str(value.dtype), "np"), shape=value.shape)
        # Op itself is a single value, simple python type.
        elif isinstance(op, (bool, int, float)):
            return BoxSpace.from_spec(spec=type(op), shape=())
        # No Space: e.g. the tf.no_op, a distribution (anything that's not a tensor).
        elif hasattr(op, "dtype") is False or not hasattr(op, "get_shape"):
            return 0
        # Some tensor: can be converted into a BoxSpace.
        else:
            shape = get_shape(op)
            # Unknown shape (e.g. a cond op).
            if shape is None:
                return 0
            add_batch_rank = False
            add_time_rank = False
            # TODO: This is going to fail if time_major=True or we only have a time-rank (no batch rank)!
            # Detect automatically whether the first rank(s) are batch and/or time rank.
            if shape is not () and shape[0] is None:
                if len(shape) > 1 and shape[1] is None:
                    shape = shape[2:]
                    add_time_rank = True
                else:
                    shape = shape[1:]
                add_batch_rank = True

            base_dtype = op.dtype.base_dtype if hasattr(op.dtype, "base_dtype") else op.dtype
            base_dtype_str = str(base_dtype)

            # FloatBox
            if "float" in base_dtype_str:
                return FloatBox(shape=shape, add_batch_rank=add_batch_rank, add_time_rank=add_time_rank,
                                dtype=dtype(base_dtype, "np"))
            # IntBox
            elif "int" in base_dtype_str:
                return IntBox(shape=shape, add_batch_rank=add_batch_rank, add_time_rank=add_time_rank,
                              dtype=dtype(base_dtype, "np"))
            # a BoolBox
            elif "bool" in base_dtype_str:
                return BoolBox(shape=shape, add_batch_rank=add_batch_rank, add_time_rank=add_time_rank)
            # a TextBox
            elif "string" in base_dtype_str:
                return TextBox(shape=shape, add_batch_rank=add_batch_rank, add_time_rank=add_time_rank)

    raise RLGraphError("ERROR: Cannot derive Space from op '{}' (unknown type?)!".format(op))


def sanity_check_space(
        space, allowed_types=None, non_allowed_types=None, must_have_batch_rank=None,
        must_have_time_rank=None, must_have_categories=None,
        rank=None, num_categories=None
):
    """
    Sanity checks a given Space for certain criteria and raises exceptions if they are not met.

    Args:
        space (Space): The Space object to check.
        allowed_types (Optional[List[type]]): A list of types that this Space must be an instance of.
        non_allowed_types (Optional[List[type]]): A list of type that this Space must not be an instance of.
        must_have_batch_rank (Optional[bool]): Whether the Space  must (True) or must not (False) have the
            `has_batch_rank` property set to True. None, if it doesn't matter.
        must_have_time_rank (Optional[bool]): Whether the Space  must (True) or must not (False) have the
            `has_time_rank` property set to True. None, if it doesn't matter.
        must_have_categories (Optional[bool]): For IntBoxes, whether the Space must (True) or must not (False) have
            global bounds with `num_categories` > 0. None, if it doesn't matter.
        rank (Optional[int,tuple]): An int or a tuple (min,max) range within which the Space's rank must lie.
            None if it doesn't matter.
        num_categories (Optional[int,tuple]): An int or a tuple (min,max) range within which the Space's
            `num_categories` rank must lie. Only valid for IntBoxes.
            None if it doesn't matter.

    Raises:
        RLGraphError: Various RLGraphErrors, if any of the conditions is not met.
    """
    # Check the types.
    if allowed_types is not None:
        if not isinstance(space, tuple(allowed_types)):
            raise RLGraphError("ERROR: Space ({}) is not an instance of {}!".format(space, allowed_types))

    if non_allowed_types is not None:
        if isinstance(space, tuple(non_allowed_types)):
            raise RLGraphError("ERROR: Space ({}) must not be an instance of {}!".format(space, non_allowed_types))

    if must_have_batch_rank is not None:
        if space.has_batch_rank != must_have_batch_rank:
            # Last chance: Check for rank >= 2, that would be ok as well.
            if must_have_batch_rank is True and len(space.get_shape(with_batch_rank=True)) >= 2:
                pass
            # Something is wrong.
            elif space.has_batch_rank is True:
                raise RLGraphError("ERROR: Space ({}) has a batch rank, but is not allowed to!".format(space))
            else:
                raise RLGraphError("ERROR: Space ({}) does not have a batch rank, but must have one!".format(space))

    if must_have_time_rank is not None:
        if space.has_time_rank != must_have_time_rank:
            # Last chance: Check for rank >= 3, that would be ok as well.
            if must_have_time_rank is True and len(space.get_shape(with_batch_rank=True, with_time_rank=True)) >= 2:
                pass
            # Something is wrong.
            elif space.has_time_rank is True:
                raise RLGraphError("ERROR: Space ({}) has a time rank, but is not allowed to!".format(space))
            else:
                raise RLGraphError("ERROR: Space ({}) does not have a time rank, but must have one!".format(space))

    if must_have_categories is not None:
        if not isinstance(space, IntBox):
            raise RLGraphError("ERROR: Space ({}) is not an IntBox. Only IntBox Spaces can have categories!".
                               format(space))
        elif space.global_bounds is False:
            raise RLGraphError("ERROR: Space ({}) must have categories (globally valid value bounds)!".format(space))

    if rank is not None:
        if isinstance(rank, int):
            if space.rank != rank:
                raise RLGraphError("ERROR: Space ({}) has rank {}, but must have rank {}!".
                                   format(space, space.rank, rank))
        elif not ((rank[0] or 0) <= space.rank <= (rank[1] or float("inf"))):
            raise RLGraphError("ERROR: Space ({}) has rank {}, but its rank must be between {} and "
                               "{}!".format(space, space.rank, rank[0], rank[1]))

    if num_categories is not None:
        if not isinstance(space, IntBox):
            raise RLGraphError("ERROR: Space ({}) is not an IntBox. Only IntBox Spaces can have "
                               "categories!".format(space))
        elif isinstance(num_categories, int):
            if space.num_categories != num_categories:
                raise RLGraphError("ERROR: Space ({}) has `num_categories` {}, but must have {}!".
                                   format(space, space.num_categories, num_categories))
        elif not ((num_categories[0] or 0) <= space.num_categories <= (num_categories[1] or float("inf"))):
            raise RLGraphError("ERROR: Space ({}) has `num_categories` {}, but this value must be between {} and "
                               "{}!".format(space, space.num_categories, num_categories[0], num_categories[1]))


def check_space_equivalence(space1, space2):
    """
    Compares the two input Spaces for equivalence and returns the more generic Space of the two.
    The more generic  Space  is the one that has the properties has_batch_rank and/or has _time_rank set (instead of
    hard values in these ranks).
    E.g.: FloatBox((64,)) is equivalent with FloatBox((), +batch-rank). The latter will be returned.

    NOTE: FloatBox((2,)) and FloatBox((3,)) are NOT equivalent.

    Args:
        space1 (Space): The 1st Space to compare.
        space2 (Space): The 2nd Space to compare.

    Returns:
        Union[Space,False]: False is the two spaces are not equivalent. The more generic Space of the two if they are
            equivalent.
    """
    # Spaces are the same: Return one of them.
    if space1 == space2:
        return space1
    # One has batch-rank, the other doesn't, but has one more rank.
    elif space1.has_batch_rank and not space2.has_batch_rank and space1.rank == space2.rank - 1:
        return space1
    elif space2.has_batch_rank and not space1.has_batch_rank and space2.rank == space1.rank - 1:
        return space2

    # TODO: time rank?

    return False