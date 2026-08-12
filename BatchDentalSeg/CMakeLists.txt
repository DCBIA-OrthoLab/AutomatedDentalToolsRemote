#-----------------------------------------------------------------------------
set(MODULE_NAME BatchDentalSeg)

#-----------------------------------------------------------------------------
# This module replaces the local BATCHDENTALSEG one, which ran nnUNet inside
# Slicer's own interpreter. That folder is left in the tree but is no longer
# added from the root CMakeLists.txt -- the same treatment ALI_Method and
# SurgMovPred_CLI got. See ARCHITECTURE.md.
#
# BatchDentalSegLib/ holds only the Slicer-free half of the panel (reading the
# run report, naming and colouring segments), listed here as extra SCRIPTS the
# way BATCHDENTALSEGLib was: slicerMacroBuildScriptedModule registers exactly
# one module (NAME) and copies the rest alongside it.
set(MODULE_PYTHON_SCRIPTS
  ${MODULE_NAME}.py
  BatchDentalSegLib/__init__.py
  BatchDentalSegLib/results.py
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

  add_subdirectory(Testing)

endif ()
