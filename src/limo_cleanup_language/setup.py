from setuptools import find_packages, setup

package_name = 'limo_cleanup_language'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='dyh',
    maintainer_email='dyh@todo.todo',
    description='Natural-language command normalization for the LIMO cleanup robot.',
    license='Apache-2.0',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'language_node = limo_cleanup_language.language_node:main',
            'list_models = limo_cleanup_language.list_models:main',
        ],
    },
)
