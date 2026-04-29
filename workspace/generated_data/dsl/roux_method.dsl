[METHOD: Roux| rotation=x2]

[STEP: fb]

init_empty_cube
add_edge UR
add_edge FR
add_edge BR
add_corner UFR
add_corner UBR
add_edges_orientation

[GROUP: sb | order=in_order]
  set_gen lLD
  [STEP: block_fl]
  add_edge UL
  add_edge BL
  add_corner UBL
  [STEP: block_bl]
  add_edge FL
  add_edge UL
  add_corner UFL
[END GROUP]
[REMOVE: set_gen lLD]
[STEP: cmll | cache_alg=true | free_layer=D]
add_corners
[STEP: eo]
set_gen MD
add_edges_orientation
[REMOVE: add_edges_orientation]
[STEP: L6E]
add_edges
[END METHOD]
scramble D R L F2 D' L' F B L' D2 R2 L2 D' L2 F2 R2 F2 D R2 U
solve
