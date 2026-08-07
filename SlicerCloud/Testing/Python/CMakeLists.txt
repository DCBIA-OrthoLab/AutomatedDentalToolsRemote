#-----------------------------------------------------------------------------
# test_deploy.py imports SlicerCloudLib.deploy only, which pulls in neither
# slicer nor qt (it is subprocess plus the standard library). It is therefore a
# plain Python3 ctest rather than a slicer_add_python_unittest — no need to pay
# for a full Slicer interpreter launch. Same rationale as
# ServerToolsCore/Testing/Python, see ARCHITECTURE.md, "Debatable decisions".
find_package(Python3 COMPONENTS Interpreter REQUIRED)

add_test(
  NAME SlicerCloud_test_deploy
  COMMAND ${Python3_EXECUTABLE} -m unittest test_deploy
  WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
  )
