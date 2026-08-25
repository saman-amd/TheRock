# Copyright Advanced Micro Devices, Inc.
# SPDX-License-Identifier: MIT

# Adds a test for shared libraries under a common path.
# PATH: Common path (relative to CMAKE_CURRENT_BINARY_DIR if not absolute)
# LIB_NAMES: Library names to validate (Linux)
# DLL_NAMES: Library names to validate (Windows)
# DEP_DIRS: Extra directories to search for dependent libraries (Windows)
function(therock_test_validate_shared_lib)
  cmake_parse_arguments(
    PARSE_ARGV 0 ARG
    ""
    "PATH"
    "LIB_NAMES;DLL_NAMES;DEP_DIRS"
  )

  # Skip shared-library dlopen validation for sanitizer builds.
  if(NOT "${THEROCK_SANITIZER}" STREQUAL "")
    return()
  endif()

  if(WIN32)
    set(_lib_names ${ARG_DLL_NAMES})
  else()
    set(_lib_names ${ARG_LIB_NAMES})
  endif()

  if(NOT _lib_names)
    return()
  endif()

  if(NOT IS_ABSOLUTE ARG_PATH)
    cmake_path(ABSOLUTE_PATH ARG_PATH BASE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}")
  endif()

  # Windows has no RPATH, so dependent DLLs must be located explicitly.
  set(_dep_dir_args)
  if(WIN32)
    foreach(dep_dir ${ARG_DEP_DIRS})
      list(APPEND _dep_dir_args "--dep-dir" "${dep_dir}")
    endforeach()
  endif()

  foreach(lib_name ${_lib_names})
    add_test(
      NAME therock-validate-shared-lib-${lib_name}
      COMMAND
        "${Python3_EXECUTABLE}" "${THEROCK_SOURCE_DIR}/build_tools/validate_shared_library.py"
          "${ARG_PATH}/${lib_name}" ${_dep_dir_args}
    )
  endforeach()
endfunction()
