[METHOD: CFOP| rotation=x2]

[STEP: cross]

init_empty_cube
add_edge UF
add_edge UB
add_edge UR
add_edge UL

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

[STEP: oll]
add_edge FD
add_edge BD
add_edge LD
add_edge RD
[STEP: pll]
add_corner DFR
add_corner DBR
add_corner DBL
add_corner DFL
[END METHOD]
scramble D R L F2 D' L' F B L' D2 R2 L2 D' L2 F2 R2 F2 D R2 U
solve

