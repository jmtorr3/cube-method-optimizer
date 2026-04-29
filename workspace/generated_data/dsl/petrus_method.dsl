[METHOD: PETRUS]

[STEP: 2x2x2]

init_empty_cube
add_edge UF
add_edge UL
add_edge FL
add_corner UFL

[STEP: 2x2x3]
add_edge UB
add_edge LB
add_corner UBL

[STEP: EO]
add_edges_orientation

[GROUP: F2L | order=best_1]
  [STEP: block_fr]
  add_edge BR
  add_corner UBR
  add_edge UR
  [STEP: block_br]
  add_edge FR
  add_corner UFR
  add_edge UR
[END GROUP]
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
