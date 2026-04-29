[METHOD: ZZ | rotation=x2]

[STEP: eo_line]

init_empty_cube
add_edge UF
add_edge UB
add_edges_orientation

[GROUP: F2L | order=best]

  set_gen RULD

  [STEP: block_fr]
  add_edge UR
  add_edge BR
  add_corner UBR
  [STEP: block_fl]
  add_edge UL
  add_edge BL
  add_corner UBL
  [STEP: block_bl]
  add_edge FL
  add_edge UL
  add_corner UFL
  [STEP: block_br]
  add_edge FR
  add_edge UR
  add_corner UFR
[END GROUP]
[REMOVE: set_gen RULD]
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
scramble F R U2 D2 F' R F' U B U' B2 D L2 U' F2 R2 L2 D' R2 F2
solve
