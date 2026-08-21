cmake_minimum_required(VERSION 3.0.2)
project(limo_cleanup_ros1_base)

find_package(catkin REQUIRED COMPONENTS
  actionlib
  actionlib_msgs
  geometry_msgs
  move_base_msgs
  rospy
  sensor_msgs
  std_msgs
  tf2_ros
)

catkin_python_setup()

catkin_package(
  CATKIN_DEPENDS
    actionlib
    actionlib_msgs
    geometry_msgs
    move_base_msgs
    rospy
    sensor_msgs
    std_msgs
    tf2_ros
)

catkin_install_python(PROGRAMS
  scripts/fail_closed_cmd_vel_watchdog.py
  scripts/cleanup_sequence_guard.py
  scripts/fail_closed_navigation_adapter.py
  scripts/run_v2_bridged_navigation.py
  scripts/validate_v1_map_binding.py
  scripts/verify_v1_map_binding_runtime.py
  scripts/verify_ros1_base_bridge_topology.py
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)

install(DIRECTORY launch
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}
)

if(CATKIN_ENABLE_TESTING)
  catkin_add_nosetests(test/test_watchdog_policy.py)
  catkin_add_nosetests(test/test_topology_policy.py)
  catkin_add_nosetests(test/test_navigation_policy.py)
  catkin_add_nosetests(test/test_map_binding.py)
  catkin_add_nosetests(test/test_runner_barrier.py)
  catkin_add_nosetests(test/test_cleanup_sequence.py)
  catkin_add_nosetests(test/test_runtime_monitor_inputs.py)
endif()
