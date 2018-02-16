
$fa = 1;
$fs = 0.5;

use <../0-tools/advanced_cube.scad>;
use <../0-tools/fillets_and_chamfers.scad>;

eps = 0.05;
eps2 = 2 * eps;
eps_z = [0, 0, -eps];
eps2_z = [0, 0, eps2];
tol = 0.3;

hotend = [17+4, 18.2, 16];

outside = hotend + [5, 6, 2];
nozzle_cutout = hotend - [4+2, 2, 1];

difference() {
    translate([-3, -1, 0]) centered_cube(outside, "y");
    translate([2+eps, 0, 2+6+eps]) centered_cube(hotend, "y");

    translate([4+2+1, 0, -eps]) centered_cube(nozzle_cutout, "y");

    translate([14, 0, 12]) rotate([90, 0, 0]) cylinder(d=2.7, h=20);

    translate([14, hotend.y/2-1.5, 2+6]) cylinder(d=5, h=20);

    translate([-0.5, 20, 4]) rotate([90, 0, 0]) cylinder(d=2.7, h=40);
    translate([-0.5, 20, 4+(4*2.54)]) rotate([90, 0, 0]) cylinder(d=2.7, h=40);
}