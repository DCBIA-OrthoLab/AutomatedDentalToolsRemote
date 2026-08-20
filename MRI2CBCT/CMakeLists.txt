#-----------------------------------------------------------------------------
set(MODULE_NAME MRI2CBCT)

#-----------------------------------------------------------------------------
# MRI2CBCT_utils/ belonged to the former local module: it drove the six
# MRI2CBCT_CLI modules from inside Slicer, downloaded the nnUNet condyle model
# into Documents, and carried 488 lines of interactive manual approximation.
# The module is now a thin client of the server's "MRI2CBCT" tool and builds
# its panel from GET /tools, so neither it nor the .ui is shipped any more. The
# files are left in the tree rather than deleted, the same way ALI_Method was -
# see ARCHITECTURE.md.
set(MODULE_PYTHON_SCRIPTS
  ${MODULE_NAME}.py
  )

set(MODULE_PYTHON_RESOURCES
  Resources/Icons/${MODULE_NAME}.png
  )

#-----------------------------------------------------------------------------
slicerMacroBuildScriptedModule(
  NAME ${MODULE_NAME}
  SCRIPTS ${MODULE_PYTHON_SCRIPTS}
  RESOURCES ${MODULE_PYTHON_RESOURCES}
  WITH_GENERIC_TESTS
  )

#-----------------------------------------------------------------------------
if(BUILD_TESTING)

  # Register the unittest subclass in the main script as a ctest.
  # Note that the test will also be available at runtime.
  slicer_add_python_unittest(SCRIPT ${MODULE_NAME}.py)

  # Additional build-time testing
  add_subdirectory(Testing)
endif()
