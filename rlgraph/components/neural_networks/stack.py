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

from rlgraph import get_backend
from rlgraph.utils.decorators import api
from rlgraph.components.component import Component
from rlgraph.utils.util import force_tuple, force_list

if get_backend() == "pytorch":
    import torch


class Stack(Component):
    """
    A component container stack that incorporates one or more sub-components some of whose API-methods
    (default: only `apply`) are automatically connected with each other (in the sequence the sub-Components are given
    in the c'tor), resulting in an API of the Stack.
    All sub-components' API-methods need to match in the number of input and output values. E.g. the third
    sub-component's api-metehod's number of return values has to match the forth sub-component's api-method's number of
    input parameters.
    """
    def __init__(self, *sub_components, **kwargs):
        """
        Args:
            sub_components (Union[Component,List[Component]]): The sub-components to add to the Stack and connect
                to each other.

        Keyword Args:
            api_methods (Set[Union[str,Tuple[str,str]]]): A set of names of API-methods to connect through the stack.
                Defaults to {"apply"}. All sub-Components must implement all API-methods in this set.
                Alternatively, a tuple can be used  (instead of a string), in which case the first tuple-item
                is used as the Stack's API-method name and the second item is the sub-Components' API-method name.
                E.g. api_methods={("stack_run", "run")}. This will create "stack_run" for the Stack, which will call
                - one by one - all the "run" methods of the sub-Components.

                Connecting always works by first calling the first sub-Component's API-method, then - with the
                result - calling the second sub-Component's API-method, etc..
                This is done for all API-methods in the given set.
        """
        # Network object for fast-path execution where we do not repeatedely call `call` between layers.
        self.stack_obj = None

        api_methods = kwargs.pop("api_methods", {"apply"})
        super(Stack, self).__init__(*sub_components, scope=kwargs.pop("scope", "stack"), **kwargs)

        self.num_allowed_inputs = None
        self.num_allowed_returns = None

        self._build_stack(api_methods)

    def _build_stack(self, api_methods):
        """
        For each api-method in set `api_methods`, automatically create this Stack's own API-method by connecting
        through all sub-Component's API-methods. This is skipped if this Stack already has a custom API-method
        by that name.

        Args:
            api_methods (Set[Union[str,Tuple[str,str]]]): See ctor kwargs.
        """
        # Loop through the API-method set.
        for api_method_spec in api_methods:

            function_to_use = None

            # API-method of sub-Components and this Stack should have different names.
            if isinstance(api_method_spec, tuple):
                # Custom method given, use that instead of creating one automatically.
                if callable(api_method_spec[1]):
                    stack_api_method_name = components_api_method_name = api_method_spec[0]
                    function_to_use = api_method_spec[1]
                else:
                    stack_api_method_name, components_api_method_name = api_method_spec[0], api_method_spec[1]
            # API-method of sub-Components and this Stack should have the same name.
            else:
                stack_api_method_name = components_api_method_name = api_method_spec

            # API-method for this Stack does not exist yet -> Automatically create it.
            if not hasattr(self, stack_api_method_name):

                # Custom API-method is given (w/o decorator) -> Call the decorator directly here to register it.
                if function_to_use is not None:
                    api(api_method=function_to_use, component=self, name=stack_api_method_name)

                # No API-method given -> Create auto-API-method and set it up through decorator.
                else:
                    @api(name=stack_api_method_name, component=self)
                    def method(self_, *args, **kwargs):
                        if get_backend() == "pytorch" and self.execution_mode == "define_by_run":
                            # Avoid jumping back between layers and calls at runtime.
                            return self.fast_path_exec(args)  # TODO: what about the **kwargs?
                        else:
                            args_ = args
                            kwargs_ = kwargs
                            for i, sub_component in enumerate(self_.sub_components.values()):  # type: Component
                                # TODO: python-Components: For now, we call each preprocessor's graph_fn
                                #  directly (assuming that inputs are not ContainerSpaces).
                                if self_.backend == "python" or get_backend() == "python":
                                    graph_fn = getattr(sub_component, "_graph_fn_" + components_api_method_name)
                                    if sub_component.api_methods[components_api_method_name].add_auto_key_as_first_param:
                                        results = graph_fn("", *args_)  # TODO: kwargs??
                                    else:
                                        results = graph_fn(*args_)
                                elif get_backend() == "pytorch":
                                    # Do NOT convert to tuple, has to be in unpacked again immediately.n
                                    results = getattr(sub_component, components_api_method_name)(*force_list(args_))
                                else:  #if get_backend() == "tf":
                                    results = getattr(sub_component, components_api_method_name)(*args_, **kwargs_)

                                # Recycle args_, kwargs_ for reuse in next sub-Component's API-method call.
                                if isinstance(results, dict):
                                    args_ = ()
                                    kwargs_ = results
                                else:
                                    args_ = force_tuple(results)
                                    kwargs_ = {}

                            return kwargs_ if args_ == () else args_

        # Build fast-path execution method for pytorch / eager.
        if get_backend() == "pytorch":
            def fast_path_exec(*inputs):
                inputs = inputs[0]
                forward_inputs = []
                for v in inputs:
                    if v is not None:
                        if isinstance(v, tuple):
                            # Unitary tuples
                            forward_inputs.append(v[0])
                        else:
                            forward_inputs.append(v)
                result = self.stack_obj.forward(*forward_inputs)
                # Problem: Not everything in the neural network stack is a true layer.
                for c in self.non_layer_components:
                    result = getattr(c, "apply")(*force_list(result))
                return result
            self.fast_path_exec = fast_path_exec

    def _post_define_by_run_build(self):
        # Layer objects only exist after build - define torch neural network.
        layer_objects = []
        self.non_layer_components = []
        for component in self.sub_components.values():
            if hasattr(component, "layer"):
                # Store Layer object itself.
                layer_objects.append(component.layer)

                # Append activation fn if needed.
                if component.activation_fn is not None:
                    layer_objects.append(component.activation_fn)
            else:
                self.non_layer_components.append(component)
        self.stack_obj = torch.nn.Sequential(*layer_objects)

    @classmethod
    def from_spec(cls, spec=None, **kwargs):
        if isinstance(spec, dict):
            kwargs["_args"] = list(spec.pop("layers", []))
        elif isinstance(spec, (tuple, list)):
            kwargs["_args"] = spec
            spec = None
        return super(Stack, cls).from_spec(spec, **kwargs)
