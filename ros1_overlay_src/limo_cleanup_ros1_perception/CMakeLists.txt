cmake_minimum_required(VERSION 3.0.2)
project(limo_cleanup_ros1_perception)

find_package(catkin REQUIRED COMPONENTS
  cv_bridge
  geometry_msgs
  message_filters
  message_generation
  rosbag
  rospy
  sensor_msgs
  std_msgs
  tf2_msgs
  tf2_ros
)

catkin_python_setup()

add_message_files(
  FILES
  ObjectDetection.msg
  PerceptionFrame.msg
  PerceptionTarget.msg
)

generate_messages(
  DEPENDENCIES
  geometry_msgs
)

catkin_package(
  CATKIN_DEPENDS
    cv_bridge
    geometry_msgs
    message_filters
    message_runtime
    rosbag
    rospy
    sensor_msgs
    std_msgs
    tf2_msgs
    tf2_ros
)

catkin_install_python(
  PROGRAMS
    scripts/dual_model_detector.py
    scripts/perception_frame_adapter.py
    scripts/perception_frame_collector.py
    scripts/perception_readiness.py
    scripts/rosbag1_rgbd_indexer.py
    scripts/typed_raw_binding.py
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)

install(
  FILES
    config/capability_matrix.json
    config/dabai_ros1_formal_four_scene_six_topics_v1.json
    config/dabai_ros1_raw_rgbd_six_topics_v1.json
    config/jyu2c_intrinsics_640x480.json
    config/model_bindings.json
    config/read_only_output_contract.json
    config/ros1_noetic_field_install_contract.json
    config/source_core_binding_v2.json
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}/config
)

install(
  FILES
    fixtures/dabai_camera_query_allowlist.json
    fixtures/orchestration_typed_frames.json
    fixtures/perception_field_intake.schema.json
    fixtures/perception_field_intake_template.json
    fixtures/perception_readiness_bundle_template.json
    fixtures/perception_readiness_missing_bundle.json
    fixtures/perception_readiness_negative_cases.json
    fixtures/rgbd_expected_topics.json
    fixtures/ros1_dabai_runtime_contract.json
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}/fixtures
)

install(
  FILES
    launch/perception_v2_formal_capture.launch
    launch/perception_v2_readonly.launch
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}/launch
)

install(
  FILES
    msg/ObjectDetection.msg
    msg/PerceptionFrame.msg
    msg/PerceptionTarget.msg
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}/msg
)

if(CATKIN_ENABLE_TESTING)
  catkin_add_nosetests(test/test_rosbag1_isolated_probe.py)
  catkin_add_nosetests(test/test_rosbag1_rgbd_indexer.py)
  catkin_add_nosetests(test/test_runtime_install_contract.py)
  catkin_add_nosetests(test/test_ros1_adapter_pure_fake.py)
  catkin_add_nosetests(test/test_jyu2c_intrinsics_contract.py)
endif()
