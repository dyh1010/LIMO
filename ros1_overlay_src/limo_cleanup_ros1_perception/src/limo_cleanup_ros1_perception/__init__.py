"""ROS1 Noetic perception package with no import-time side effects.

Runtime entrypoints import their exact implementation modules explicitly.
Keeping package import inert also lets the host provenance gate load the exact
model-binding closure without ambient import-path expansion.
"""

__all__ = ()
