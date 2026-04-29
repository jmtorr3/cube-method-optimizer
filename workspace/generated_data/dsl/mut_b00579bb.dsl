[METHOD: mut_b00579bb | rotation=x2]
[STEP: fb | cache_alg=false]
add_edge UR
add_edge FR
add_edge BL
add_corner UFR
add_edges_orientation
[GROUP: sb | order=in_order]
[STEP: block_fl | cache_alg=false]
add_edge UL
add_corner UBL
add_edge BR
[STEP: block_bl | cache_alg=false]
add_edge FL
add_edge UL
add_corner UFL
add_corner UBR
[END GROUP]
[REMOVE: set_gen lLD]
[STEP: cmll | cache_alg=true | free_layer=D]
add_corners
[STEP: eo | cache_alg=false]
set_gen MD
add_edges_orientation
[REMOVE: add_edges_orientation]
[STEP: L6E | cache_alg=false]
add_edges
[END METHOD]