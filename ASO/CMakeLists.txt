#-----------------------------------------------------------------------------
set(MODULE_NAME ASO)

#-----------------------------------------------------------------------------
# ASO_Method/ and Resources/UI/ASO.ui belonged to the former local module: they
# drove the PRE/SEMI_ASO_CBCT and PRE/SEMI_ASO_IOS CLIs from inside Slicer, via
# a conda environment and a pytorch3d wheel. The module is now a thin client of
# the server's "ASO" tool and builds its panel from GET /tools, so neither is
# shipped any more. The files are left in the tree rather than deleted, the same
# way ALI_Method and SurgMovPred_CLI were -- see ARCHITECTURE.md.
#
# The tooth-chart images go with them: the tooth selection is a `multichoice`
# argument in the server's schema now, rendered as check boxes by formgen, so
# nothing loads these any more.
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
if (BUILD_TESTING)

  # Register the unittest subclass in the main script as a ctest.
  # Note that the test will also be available at runtime.
  slicer_add_python_unittest(SCRIPT ${MODULE_NAME}.py)

  # Additional build-time testing
  add_subdirectory(Testing)
endif ()
