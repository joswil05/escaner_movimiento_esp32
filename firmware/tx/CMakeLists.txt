# Transmisor dedicado (placa B): beacons ESP-NOW a tasa fija + actualización OTA por WiFi.
cmake_minimum_required(VERSION 3.16)
set(EXTRA_COMPONENT_DIRS ${CMAKE_CURRENT_LIST_DIR}/../components)
set(PROJECT_VER "tx-1.0.0")
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(csi_tx)
