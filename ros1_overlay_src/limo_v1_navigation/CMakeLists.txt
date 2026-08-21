cmake_minimum_required(VERSION 3.0.2)
project(limo_v1_navigation)

find_package(catkin REQUIRED COMPONENTS
  actionlib
  actionlib_msgs
  geometry_msgs
  nav_msgs
  move_base_msgs
  rosgraph
  rospy
  sensor_msgs
  std_msgs
  std_srvs
  tf2_msgs
  tf2_ros
)

catkin_python_setup()

catkin_package(
  CATKIN_DEPENDS actionlib actionlib_msgs geometry_msgs move_base_msgs nav_msgs rosgraph rospy sensor_msgs std_msgs std_srvs tf2_msgs tf2_ros
)

catkin_install_python(PROGRAMS
  scripts/audit_v1_overlay.py
  scripts/v1_acceptance_report.py
  scripts/v1_perception_only_field.py
  scripts/v1_cmd_guard.py
  scripts/v1_diagnostic_capture.py
  scripts/v1_localization_manager.py
  scripts/v1_navigation_gateway.py
  scripts/v1_runtime_preflight.py
  scripts/validate_v1_profile.py
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)

install(PROGRAMS scripts/v1_map_artifact_check.sh
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)

install(DIRECTORY config docs launch
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}
)
