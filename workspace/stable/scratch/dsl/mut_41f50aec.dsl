[METHOD: mut_41f50aec]
[STEP: eo_line | cache_alg=false]
add_edge UF
add_edge UB
add_edges_orientation
[GROUP: F2L | order=best]
[STEP: block_fr | cache_alg=false]
add_edge UR
add_edge RU
add_corner UBL
[STEP: block_fl | cache_alg=false]
add_edge UL
add_edge BL
add_corner UBR
[STEP: block_bl | cache_alg=false]
add_edge FL
add_edge UL
add_corner UFL
[STEP: block_br | cache_alg=false]
add_edge FR
add_edge UR
add_corner UFR
[END GROUP]
[REMOVE: set_gen RULD]
[STEP: zbll | cache_alg=true | free_layer=D]
add_corners_orientation
add_edge FD
add_edge BD
add_edge LD
add_edge RD
add_corner DFR
add_corner DBR
add_corner DBL
add_corner DFL
[END METHOD]