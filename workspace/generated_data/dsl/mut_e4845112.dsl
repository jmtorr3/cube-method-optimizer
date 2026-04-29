[METHOD: mut_e4845112]
[STEP: cross | cache_alg=false]
add_edge UF
add_edge UB
add_edge UR
add_edge UL
[GROUP: F2L | order=in_order]
[STEP: pair_fr | cache_alg=false]
add_edge BR
[STEP: pair_fl | cache_alg=false]
add_corner UBL
[STEP: pair_bl | cache_alg=false]
add_edge FL
add_corner UFL
add_edge LD
add_edge BL
[STEP: pair_br | cache_alg=false]
add_edge FR
add_corner UFR
[END GROUP]
[STEP: 1lll | cache_alg=true | free_layer=D]
add_corners_orientation
add_edges_orientation
add_edge FD
add_edge BD
add_edge RD
add_corner DFR
add_corner DBR
add_corner DBL
add_corner DFL
add_corner UBR
[END METHOD]