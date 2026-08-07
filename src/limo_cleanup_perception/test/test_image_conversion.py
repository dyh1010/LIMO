import unittest

import numpy as np

from limo_cleanup_perception.image_conversion import (
    image_message_to_numpy,
)


class FakeImage:

    def __init__(
            self, width, height, encoding, data, step,
            is_bigendian=False):
        self.width = width
        self.height = height
        self.encoding = encoding
        self.data = data
        self.step = step
        self.is_bigendian = is_bigendian


class ImageConversionTest(unittest.TestCase):

    def test_bgr8_is_preserved(self):
        source = np.array([[[10, 20, 30], [40, 50, 60]]], dtype=np.uint8)
        message = FakeImage(2, 1, 'bgr8', source.tobytes(), 6)
        converted = image_message_to_numpy(message, color=True)
        np.testing.assert_array_equal(source, converted)

    def test_rgb8_is_converted_to_bgr(self):
        source = np.array([[[30, 20, 10]]], dtype=np.uint8)
        message = FakeImage(1, 1, 'rgb8', source.tobytes(), 3)
        converted = image_message_to_numpy(message, color=True)
        np.testing.assert_array_equal(
            np.array([[[10, 20, 30]]], dtype=np.uint8), converted)

    def test_16uc1_depth_ignores_row_padding(self):
        rows = np.array(
            [[1000, 2000, 9999], [3000, 4000, 9999]],
            dtype=np.uint16)
        message = FakeImage(2, 2, '16UC1', rows.tobytes(), 6)
        converted = image_message_to_numpy(message)
        np.testing.assert_array_equal(
            np.array([[1000, 2000], [3000, 4000]], dtype=np.uint16),
            converted,
        )

    def test_unsupported_encoding_raises(self):
        message = FakeImage(1, 1, 'yuv422', bytes(2), 2)
        with self.assertRaises(ValueError):
            image_message_to_numpy(message, color=True)


if __name__ == '__main__':
    unittest.main()
