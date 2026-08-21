cmake_minimum_required(VERSION 3.5)
project(limo_cleanup_dabai_sensor)

find_package(ament_cmake REQUIRED)

install(
  DIRECTORY launch
  DESTINATION share/${PROJECT_NAME}
)

if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)
  ament_add_pytest_test(
    test_dabai_sensor_only_source_contract
    test/test_dabai_sensor_only_source_contract.py
  )
endif()

ament_package()
