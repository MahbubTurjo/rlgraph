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

from __future__ import absolute_import, division, print_function

import os
import unittest

import cv2
import numpy as np

from rlgraph.components.layers import GrayScale, ReShape, Multiply, Divide, Clip, ImageBinary, ImageResize, ImageCrop, \
    MovingStandardize
from rlgraph.environments import OpenAIGymEnv
from rlgraph.spaces import *
from rlgraph.tests import ComponentTest, recursive_assert_almost_equal
from rlgraph.utils import SMALL_NUMBER


class TestPreprocessLayers(unittest.TestCase):

    def test_multiply(self):
        multiply = Multiply(factor=2.0)
        test = ComponentTest(component=multiply, input_spaces=dict(inputs=FloatBox(
            shape=(2, 1), add_batch_rank=True)
        ))

        test.test("reset")
        # Batch=2
        input_ = np.array([[[1.0], [2.0]], [[3.0], [4.0]]])
        expected = np.array([[[2.0], [4.0]], [[6.0], [8.0]]])
        test.test(("call", input_), expected_outputs=expected)

    def test_divide(self):
        divide = Divide(divisor=10.0)
        test = ComponentTest(component=divide, input_spaces=dict(inputs=FloatBox(shape=(1, 2),
                                                                                               add_batch_rank=False)))

        test.test("reset")

        input_ = np.array([[10.0, 100.0]])
        expected = np.array([[1.0, 10.0]])
        test.test(("call", input_), expected_outputs=expected)

    def test_clip(self):
        clip = Clip(min=0.0, max=1.0)
        # Grayscale image of 2x2 size.
        test = ComponentTest(
            component=clip,
            input_spaces=dict(inputs=FloatBox(shape=(2, 2), add_batch_rank=True))
        )

        test.test("reset")
        # Batch=3
        input_images = np.array([
            [[125.6, 10.3], [-45, 5.234]],
            [[-10.0, 1.0004], [0.0, -0.0003]],
            [[0.0005, 0.00000009], [90.0, 10000901.347]]
        ])
        expected = np.array([
            [[1.0, 1.0], [0.0, 1.0]],
            [[0.0, 1.0], [0.0, 0.0]],
            [[0.0005, 0.00000009], [1.0, 1.0]]
        ])
        test.test(("call", input_images), expected_outputs=expected)

    def test_grayscale_with_uint8_image(self):
        # last rank is always the color rank (its dim must match len(grayscale-weights))
        space = IntBox(256, shape=(1, 1, 3), dtype="uint8", add_batch_rank=True)

        for backend in (None, "python"):
            grayscale = GrayScale(weights=(0.333, 0.333, 0.333), keep_rank=False, backend=backend)
            test = ComponentTest(component=grayscale, input_spaces=dict(inputs=space))

            # Run the test (batch of 3 images).
            input_ = space.sample(size=3)
            expected = np.sum(input_, axis=-1, keepdims=False)
            expected = (expected / 3).astype(input_.dtype)
            test.test("reset")
            print(test.test(("call", input_), expected_outputs=expected, decimals=0))

    def test_split_inputs_on_grayscale(self):
        # last rank is always the color rank (its dim must match len(grayscale-weights))
        space = Dict.from_spec(dict(
            a=Tuple(FloatBox(shape=(1, 1, 2)), FloatBox(shape=(1, 2, 2))),
            b=FloatBox(shape=(2, 2, 2, 2)),
            c=dict(type=float, shape=(2,))  # single scalar pixel
        ))
        grayscale = GrayScale(weights=(0.5, 0.5), keep_rank=False)

        test = ComponentTest(component=grayscale, input_spaces=dict(inputs=space))

        # Run the test.
        input_ = dict(
            a=(
                np.array([[[3.0, 5.0]]]), np.array([[[3.0, 5.0], [1.0, 5.0]]])
            ),
            b=np.array([[[[2.0, 4.0], [2.0, 4.0]],
                         [[2.0, 4.0], [2.0, 4.0]]],
                        [[[2.0, 4.0], [2.0, 4.0]],
                         [[2.0, 4.0], [2.0, 4.0]]]]
                       ),
            c=np.array([0.6, 0.8])
        )
        expected = dict(
            a=(
                np.array([[4.0]]), np.array([[4.0, 3.0]])
            ),
            b=np.array([[[3.0, 3.0], [3.0, 3.0]], [[3.0, 3.0], [3.0, 3.0]]]),
            c=0.7
        )
        test.test("reset")
        test.test(("call", input_), expected_outputs=expected)

    def test_split_graph_on_reshape_flatten(self):
        space = Dict.from_spec(
            dict(
                a=Tuple(FloatBox(shape=(1, 1, 2)), FloatBox(shape=(1, 2, 2))),
                b=FloatBox(shape=(2, 2, 3)),
                c=dict(type=float, shape=(2,)),
                d=IntBox(3)
            ),
            add_batch_rank=True
        )
        flatten = ReShape(flatten=True, flatten_categories={"d": 3})

        test = ComponentTest(component=flatten, input_spaces=dict(inputs=space))

        input_ = dict(
            a=(
                np.array([[[[3.0, 5.0]]], [[[1.0, 5.2]]]]), np.array([[[[3.1, 3.2], [3.3, 3.4]]],
                                                                      [[[3.5, 3.6], [3.7, 3.8]]]])
            ),
            b=np.array([[[[0.01, 0.02, 0.03], [0.04, 0.05, 0.06]], [[0.07, 0.08, 0.09], [0.10, 0.11, 0.12]]],
                        [[[0.13, 0.14, 0.15], [0.16, 0.17, 0.18]], [[0.19, 0.20, 0.21], [0.22, 0.23, 0.24]]]]),
            c=np.array([[0.1, 0.2], [0.3, 0.4]]),
            d=np.array([2, 0])
        )
        expected = dict(
            a=(
                np.array([[3.0, 5.0], [1.0, 5.2]], dtype=np.float32), np.array([[3.1, 3.2, 3.3, 3.4], [3.5, 3.6, 3.7, 3.8]], dtype=np.float32)
            ),
            b=np.array([[0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10, 0.11, 0.12],
                        [0.13, 0.14, 0.15, 0.16, 0.17, 0.18, 0.19, 0.20, 0.21, 0.22, 0.23, 0.24]]
            ),
            c=np.array([[0.1, 0.2], [0.3, 0.4]], dtype=np.float32),
            d=np.array([[0.0, 0.0, 1.0], [1.0, 0.0, 0.0]])  # category (one-hot) flatten
        )
        test.test("reset")
        test.test(("call", input_), expected_outputs=expected)

    def test_image_resize(self):
        image_resize = ImageResize(width=4, height=4, interpolation="bilinear")
        # Some image of 16x16x3 size.
        test = ComponentTest(
            component=image_resize, input_spaces=dict(inputs=FloatBox(shape=(16, 16, 3), add_batch_rank=False))
        )

        test.test("reset")

        input_image = cv2.imread(os.path.join(os.path.dirname(__file__), "images/16x16x3_image.bmp"))
        expected = cv2.imread(os.path.join(os.path.dirname(__file__), "images/4x4x3_image_resized.bmp"))
        assert expected is not None

        test.test(("call", input_image), expected_outputs=expected)

    def test_image_crop(self):
        for backend in (None, "python"):
            image_crop = ImageCrop(x=7, y=1, width=8, height=12, backend=backend)

            # Some image of 16x16x3 size.
            test = ComponentTest(component=image_crop, input_spaces=dict(
                inputs=FloatBox(shape=(16, 16, 3), add_batch_rank=False)
            ))

            test.test("reset")

            input_image = cv2.imread(os.path.join(os.path.dirname(__file__), "images/16x16x3_image.bmp"))
            expected = cv2.imread(os.path.join(os.path.dirname(__file__), "images/8x12x3_image_cropped.bmp"))
            assert expected is not None

            test.test(("call", input_image), expected_outputs=expected)
            test.terminate()

    def test_black_and_white(self):
        binary = ImageBinary()
        # Color image of 2x2x3 size.
        test = ComponentTest(component=binary, input_spaces=dict(inputs=FloatBox(shape=(2, 2, 3), add_batch_rank=True)))

        test.test("reset")
        # Batch=2
        input_images = np.array([
            [[[0, 1, 0], [10, 9, 5]], [[0, 0, 0], [0, 0, 1]]],
            [[[255, 255, 255], [0, 0, 0]], [[0, 0, 0], [255, 43, 0]]]
        ])
        expected = np.array([
            [[1, 1], [0, 1]],
            [[1, 0], [0, 1]]
        ])
        test.test(("call", input_images), expected_outputs=expected)

    def test_moving_standardize(self):
        env = OpenAIGymEnv("Pong-v0")
        space = env.state_space

        for backend in (None, "python"):
            moving_standardize = MovingStandardize(backend=backend)
            test = ComponentTest(component=moving_standardize, input_spaces=dict(inputs=space))

            samples = [space.sample() for _ in range(100)]
            out = None
            for sample in samples:
                out = test.test(("call", sample))

            # Assert shape remains intact.
            expected_shape = (1, ) + space.shape
            self.assertEqual(expected_shape, moving_standardize.mean_est.shape)
            # Assert mean estimate.
            expected_mean = np.mean(samples, axis=0)
            recursive_assert_almost_equal(test.get_variable_values("mean-est"), expected_mean)

            expected_variance = np.var(samples, ddof=1, axis=0)
            variance_estimate = test.get_variable_values("std-sum-est") / \
                                (test.get_variable_values("sample-count") - 1.0)
            recursive_assert_almost_equal(expected_shape, variance_estimate.shape)
            recursive_assert_almost_equal(variance_estimate, expected_variance)

            std = np.sqrt(variance_estimate) + SMALL_NUMBER

            # Final output.
            expected_out = (samples[-1] - test.get_variable_values("mean-est")) / std
            recursive_assert_almost_equal(out, expected_out)
