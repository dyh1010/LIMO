"""Convert common ROS Image encodings to NumPy without cv_bridge."""

import sys

COLOR_ENCODINGS = {
    'bgr8': ('uint8', 3, 'bgr'),
    'rgb8': ('uint8', 3, 'rgb'),
    'bgra8': ('uint8', 4, 'bgra'),
    'rgba8': ('uint8', 4, 'rgba'),
    'mono8': ('uint8', 1, 'mono'),
}
DEPTH_ENCODINGS = {
    '16UC1': 'uint16',
    'mono16': 'uint16',
    '32FC1': 'float32',
}


def image_message_to_numpy(message, color=False):
    """Convert one sensor_msgs/Image-like object to a compact array."""
    import numpy as np

    encoding = str(message.encoding)
    if color:
        if encoding not in COLOR_ENCODINGS:
            raise ValueError(f'unsupported color encoding: {encoding}')
        dtype, channels, order = COLOR_ENCODINGS[encoding]
        image = _reshape_message(message, dtype, channels)
        if order == 'rgb':
            return image[:, :, ::-1].copy()
        if order == 'rgba':
            return image[:, :, [2, 1, 0]].copy()
        if order == 'bgra':
            return image[:, :, :3].copy()
        if order == 'mono':
            return np.repeat(image[:, :, None], 3, axis=2)
        return image

    if encoding not in DEPTH_ENCODINGS:
        raise ValueError(f'unsupported depth encoding: {encoding}')
    return _reshape_message(message, DEPTH_ENCODINGS[encoding], 1)


def _reshape_message(message, dtype, channels):
    import numpy as np

    dtype = np.dtype(dtype)
    row_elements = int(message.step) // dtype.itemsize
    expected_elements = int(message.height) * row_elements
    values = np.frombuffer(message.data, dtype=dtype, count=expected_elements)
    values = values.reshape(int(message.height), row_elements)
    used_elements = int(message.width) * channels
    if row_elements < used_elements:
        raise ValueError('image step is smaller than encoded row width')
    values = values[:, :used_elements]
    message_big_endian = bool(message.is_bigendian)
    system_big_endian = sys.byteorder == 'big'
    if dtype.itemsize > 1 and message_big_endian != system_big_endian:
        values = values.byteswap()
    if channels == 1:
        return values.reshape(int(message.height), int(message.width)).copy()
    return values.reshape(
        int(message.height), int(message.width), channels).copy()
