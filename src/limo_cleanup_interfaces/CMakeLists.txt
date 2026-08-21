cmake_minimum_required(VERSION 3.8)
project(limo_cleanup_interfaces)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# find dependencies
find_package(ament_cmake REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(rosidl_default_generators REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/CleanupTask.msg"
  "msg/CleanupStatus.msg"
  "msg/ObjectDetection.msg"
  "msg/PerceptionTarget.msg"
  "msg/PerceptionFrame.msg"
  "msg/ArmState.msg"
  "msg/GripperState.msg"
  "action/ExecuteCleanup.action"
  "action/ControlGripper.action"
  "action/ExecuteArmMotion.action"
  "action/ExecuteGripperMotion.action"
  "srv/StopArm.srv"
  "srv/AcknowledgeArmFault.srv"
  "srv/StopGripper.srv"
  "srv/AcknowledgeGripperFault.srv"
  DEPENDENCIES builtin_interfaces geometry_msgs
)

ament_export_dependencies(rosidl_default_runtime)
# uncomment the following section in order to fill in
# further dependencies manually.
# find_package(<dependency> REQUIRED)

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  # the following line skips the linter which checks for copyrights
  # comment the line when a copyright and license is added to all source files
  set(ament_cmake_copyright_FOUND TRUE)
  # the following line skips cpplint (only works in a git repo)
  # comment the line when this package is in a git repo and when
  # a copyright and license is added to all source files
  set(ament_cmake_cpplint_FOUND TRUE)
  ament_lint_auto_find_test_dependencies()
endif()

ament_package()
