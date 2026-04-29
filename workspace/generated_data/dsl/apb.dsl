[METHOD: APB| rotation=x2| symmetry=U| symmetry_depth=1]

[STEP: fb]

init_empty_cube
add_edge UL
add_edge FL
add_edge BL
add_corner UFL
add_corner UBL
add_edges_orientation

[STEP: 2x2x3]
add_edge UF
add_edge UB

[STEP: EOPair]
add_corner UFR
add_edge FR
add_edges_orientation

[STEP: LXS | cache_alg=true | free_layer=D]
add_edge BR
add_edge UR
add_corner UBR

[REMOVE: add_edges_orientation]
[STEP: co | cache_alg=true | free_layer=D]
add_corners_orientation

[STEP: pll | cache_alg=true | free_layer=D]
add_edge FD
add_edge BD
add_edge LD
add_edge RD
add_corner DFR
add_corner DBR
add_corner DBL
add_corner DFL

[END METHOD]
scramble D R L F2 D' L' F B L' D2 R2 L2 D' L2 F2 R2 F2 D R2 U
solve
