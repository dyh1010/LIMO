cmake_minimum_required(VERSION 3.0.2)
project(limo_cleanup_ros1_manipulation)

find_package(catkin REQUIRED COMPONENTS
  limo_cleanup_ros1_perception
  rospy
  std_msgs
)

catkin_python_setup()

catkin_package(
  CATKIN_DEPENDS limo_cleanup_ros1_perception rospy std_msgs
)

catkin_install_python(PROGRAMS
  scripts/fixed_bottle_pick_preview_node.py
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)

install(DIRECTORY config launch
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}
)

if(CATKIN_ENABLE_TESTING)
  catkin_add_nosetests(test/test_fixed_bottle_pick_core.py)
  catkin_add_nosetests(test/test_ros1_preview_source_contract.py)
endif()
