# C99 puro, sin dependencias de IDF: también se compila en la PC para compararlo con Python.
idf_component_register(SRCS "csi_dsp.c"
                       INCLUDE_DIRS "include")
target_link_libraries(${COMPONENT_LIB} PRIVATE m)
