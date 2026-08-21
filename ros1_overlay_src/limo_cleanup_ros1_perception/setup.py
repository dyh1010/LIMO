#!/usr/bin/env python3

from setuptools import setup

try:
    from catkin_pkg.python_setup import generate_distutils_setup
except ImportError:
    package_args = {
        'name': 'limo_cleanup_ros1_perception',
        'version': '0.1.0',
        'packages': ['limo_cleanup_ros1_perception'],
        'package_dir': {'': 'src'},
    }
else:
    package_args = generate_distutils_setup(
        packages=['limo_cleanup_ros1_perception'],
        package_dir={'': 'src'},
    )

package_args['python_requires'] = '>=3.8'
package_args['install_requires'] = [
    'numpy==1.23.4',
    'torch==2.1.0a0+41361538.nv23.06',
    'ultralytics==8.3.21',
]
package_args['zip_safe'] = False
setup(**package_args)
