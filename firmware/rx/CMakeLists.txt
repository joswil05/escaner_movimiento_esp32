# Receptor (placa A): CSI del transmisor dedicado o del router -> PC en tramas binarias.
cmake_minimum_required(VERSION 3.16)
set(EXTRA_COMPONENT_DIRS ${CMAKE_CURRENT_LIST_DIR}/../components)
set(PROJECT_VER "rx-1.0.0")
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(csi_rx)
