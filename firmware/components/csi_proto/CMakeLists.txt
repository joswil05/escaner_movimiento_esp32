# C puro, sin dependencias de IDF: también se compila en la PC para los tests.
idf_component_register(SRCS "csi_proto.c"
                       INCLUDE_DIRS "include")
