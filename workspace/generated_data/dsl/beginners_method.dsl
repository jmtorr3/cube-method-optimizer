[METHOD: BEGINNERS| rotation=x2]

[STEP: cross]

init_empty_cube
add_edge UF
add_edge UB
add_edge UR
add_edge UL

[GROUP: CORNERS | order=in_order]
  [STEP: corner_fr]
  add_corner UFR
  [STEP: corner_fl]
  add_corner UFL
  [STEP: corner_bl]
  add_corner UBL
  [STEP: corner_br]
  add_corner UBR
[END GROUP]

[GROUP: EDGES | order=in_order]
  [STEP: edge_fr]
  add_edge FR
  [STEP: edge_fl]
  add_edge FL
  [STEP: edge_bl]
  add_edge BL
  [STEP: edge_br]
  add_edge BR
[END GROUP]

[STEP: EO]
add_edges_orientation
[STEP: CO]
add_corners_orientation
[REMOVE: add_corners_orientation]
[STEP: CP]
add_corners
[REMOVE: add_edges_orientation]
[STEP: ep]
add_edges
[END METHOD]
scramble D R L F2 D' L' F B L' D2 R2 L2 D' L2 F2 R2 F2 D R2 U
solve
