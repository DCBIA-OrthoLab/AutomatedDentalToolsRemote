#-----------------------------------------------------------------------------
# test_client.py only imports ServerToolsCoreLib.client (requests + stdlib, no
# slicer/qt), so it is registered as a plain Python3 ctest rather than through
# slicer_add_python_unittest — no need to pay for a full Slicer interpreter
# launch to test an HTTP client. See ARCHITECTURE.md, "Debatable decisions".
find_package(Python3 COMPONENTS Interpreter REQUIRED)

add_test(
  NAME ServerToolsCore_test_client
  COMMAND ${Python3_EXECUTABLE} -m unittest test_client
  WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
  )
