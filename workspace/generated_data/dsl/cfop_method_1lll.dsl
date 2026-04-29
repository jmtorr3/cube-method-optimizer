[METHOD: CFOP]

[STEP: cross]

init_empty_cube
add_edge UF
add_edge UB
add_edge UR
add_edge UL

[GROUP: F2L | order=in_order]

  [STEP: pair_fr]
  add_edge BR
  add_corner UBR
  [STEP: pair_fl]
  add_edge BL
  add_corner UBL
  [STEP: pair_bl]
  add_edge FL
  add_corner UFL
  [STEP: pair_br]
  add_edge FR
  add_corner UFR
[END GROUP]
[STEP: 1lll | cache_alg=true | free_layer=D]
add_corners_orientation
add_edges_orientation
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
