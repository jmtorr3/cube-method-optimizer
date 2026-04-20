[METHOD: mut_d33deab5]
[STEP: 2x2x2 | cache_alg=false]
add_edge UF
add_edge UL
add_edge FL
add_corner UFL
[STEP: 2x2x3 | cache_alg=false]
add_edge UB
add_edge LB
add_corner UBL
add_edge BD
[STEP: EO | cache_alg=false]
add_edges_orientation
[GROUP: F2L | order=best_1]
[STEP: block_fr | cache_alg=false]
add_edge BR
add_corner UBR
add_edge UR
[STEP: block_br | cache_alg=false]
add_edge FR
add_corner UFR
add_edge UR
[END GROUP]
[STEP: co | cache_alg=true | free_layer=D]
add_corners_orientation
[STEP: pll | cache_alg=true | free_layer=D]
add_edge FD
add_edge LD
add_edge RD
add_corner DFR
add_corner DBR
add_corner DBL
add_corner DFL
[END METHOD]